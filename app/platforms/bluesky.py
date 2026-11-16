"""Bluesky integration (AT Protocol XRPC).

1. ``POST {pds}/xrpc/com.atproto.server.createSession``  (handle + App Password)
2. ``POST {pds}/xrpc/com.atproto.repo.createRecord``      (collection ``app.bsky.feed.post``)
3. ``GET  {public_api}/xrpc/app.bsky.feed.getPosts``      (anonymous check that the post is public)
"""

from datetime import datetime, timezone

from app.exceptions import InvalidResponseError
from app.platforms.base import BasePlatform, PostedContent, parse_datetime


class BlueskyPlatform(BasePlatform):
    name = "Bluesky"
    key = "bluesky"

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        s = self._settings
        self._require(bluesky_handle=s.bluesky_handle, bluesky_app_password=s.bluesky_app_password)
        pds = s.bluesky_pds_url.rstrip("/")

        # 1. Authenticate with handle + App Password.
        session = self._json(
            await self._request(
                "POST",
                f"{pds}/xrpc/com.atproto.server.createSession",
                json={"identifier": s.bluesky_handle.strip().lstrip("@"), "password": s.bluesky_app_password},
            )
        )
        access_jwt, did = session.get("accessJwt"), session.get("did")
        if not access_jwt or not did:
            raise InvalidResponseError("Bluesky createSession response did not contain accessJwt and did")
        handle = session.get("handle") or did

        # 2. Create the post record. A link facet makes the CTA URL clickable;
        #    facet indexes are UTF-8 BYTE offsets, not character offsets.
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        record: dict = {"$type": "app.bsky.feed.post", "text": message, "createdAt": created_at}
        text_bytes = message.encode("utf-8")
        url_bytes = cta_url.encode("utf-8")
        start = text_bytes.find(url_bytes)
        if start >= 0:
            record["facets"] = [
                {
                    "index": {"byteStart": start, "byteEnd": start + len(url_bytes)},
                    "features": [{"$type": "app.bsky.richtext.facet#link", "uri": cta_url}],
                }
            ]
        created = self._json(
            await self._request(
                "POST",
                f"{pds}/xrpc/com.atproto.repo.createRecord",
                headers=self._bearer(access_jwt),
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            )
        )
        uri = created.get("uri")
        if not isinstance(uri, str) or not uri.startswith("at://") or "/app.bsky.feed.post/" not in uri:
            raise InvalidResponseError("Bluesky createRecord response did not contain a valid post URI")

        rkey = uri.rsplit("/", 1)[-1]
        posted_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        # 3. Anonymous check through the public AppView.
        public = await self._poll_public(
            f"{s.bluesky_public_api_url.rstrip('/')}/xrpc/app.bsky.feed.getPosts",
            accept=lambda r: r.status_code == 200 and bool(r.json().get("posts")),
            params={"uris": uri},
        )
        indexed_at = None
        if public is not None:
            indexed_at = parse_datetime(public.json()["posts"][0].get("indexedAt"))

        return PostedContent(
            external_id=uri,
            posted_url=posted_url,
            public_access=public is not None,
            published_at=indexed_at or parse_datetime(created_at),
        )
