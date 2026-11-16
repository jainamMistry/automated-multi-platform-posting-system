"""Hashnode integration (GraphQL API, ``publishPost`` mutation).

* Endpoint: ``https://gql.hashnode.com``
* Authentication: Personal Access Token sent as the raw ``Authorization`` header
  (no ``Bearer`` prefix).
* GraphQL reports many failures with HTTP 200 and an ``errors`` array, so the
  body is always inspected.
"""

from typing import Any


from app.exceptions import AuthenticationError, InvalidResponseError, PlatformAPIError, RateLimitError
from app.platforms.base import BasePlatform, PostedContent, make_title, parse_datetime

PUBLISH_POST_MUTATION = """
mutation PublishPost($input: PublishPostInput!) {
  publishPost(input: $input) {
    post {
      id
      slug
      url
      publishedAt
    }
  }
}
"""

_AUTH_CODES = {"UNAUTHENTICATED", "UNAUTHORIZED", "FORBIDDEN"}


class HashnodePlatform(BasePlatform):
    name = "Hashnode"
    key = "hashnode"

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        s = self._settings
        self._require(hashnode_api_key=s.hashnode_api_key, hashnode_publication_id=s.hashnode_publication_id)

        response = await self._request(
            "POST",
            s.hashnode_graphql_url,
            headers={"Authorization": s.hashnode_api_key, "Content-Type": "application/json"},
            json={
                "query": PUBLISH_POST_MUTATION,
                "variables": {
                    "input": {
                        "title": make_title(message, cta_url),
                        "contentMarkdown": message,
                        "publicationId": s.hashnode_publication_id,
                    }
                },
            },
        )
        body = self._json(response)
        self._raise_for_graphql_errors(body)

        post = ((body.get("data") or {}).get("publishPost") or {}).get("post") or {}
        post_id, url = post.get("id"), post.get("url")
        if not post_id or not url:
            raise InvalidResponseError("Hashnode response did not contain the published post id and url")

        public = await self._poll_public(str(url))
        return PostedContent(
            external_id=str(post_id),
            posted_url=str(url),
            public_access=public is not None,
            published_at=parse_datetime(post.get("publishedAt")),
        )

    def _raise_for_graphql_errors(self, body: dict[str, Any]) -> None:
        errors = body.get("errors")
        if not errors:
            return
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        message = str(first.get("message") or "unknown GraphQL error")
        code = str((first.get("extensions") or {}).get("code") or "").upper()
        lowered = message.lower()
        if code in _AUTH_CODES or "authenticat" in lowered or "unauthor" in lowered:
            raise AuthenticationError(f"Authentication failed: {message}", status_code=200)
        if "rate limit" in lowered or "too many requests" in lowered or code == "RATE_LIMITED":
            raise RateLimitError(f"Rate limit exceeded: {message}", status_code=200)
        raise PlatformAPIError(f"Hashnode rejected the request: {message}", status_code=200)
