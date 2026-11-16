"""Mastodon integration (REST API ``POST /api/v1/statuses``).

Needs an access token with the ``write:statuses`` scope.
"""

from app.exceptions import InvalidResponseError
from app.platforms.base import BasePlatform, PostedContent, parse_datetime


def normalise_base_url(value: str) -> str:
    """``mastodon.social`` / ``https://mastodon.social/`` -> ``https://mastodon.social``."""
    value = value.strip().rstrip("/")
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


class MastodonPlatform(BasePlatform):
    name = "Mastodon"
    key = "mastodon"

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        s = self._settings
        self._require(mastodon_instance=s.mastodon_instance, mastodon_access_token=s.mastodon_access_token)
        base = normalise_base_url(s.mastodon_instance)

        data = self._json(
            await self._request(
                "POST",
                f"{base}/api/v1/statuses",
                headers=self._bearer(s.mastodon_access_token),
                json={"status": message, "visibility": "public"},
            )
        )
        status_id, url = data.get("id"), data.get("url")
        if not status_id or not url:
            raise InvalidResponseError("Mastodon response did not contain the status id and url")

        # Anonymous check: public statuses can be read without a token.
        public = await self._poll_public(
            f"{base}/api/v1/statuses/{status_id}",
            accept=lambda r: r.status_code == 200 and r.json().get("visibility") == "public",
        )
        return PostedContent(
            external_id=str(status_id),
            posted_url=str(url),
            public_access=public is not None,
            published_at=parse_datetime(data.get("created_at")),
        )
