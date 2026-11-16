"""DEV.to integration (Forem API v1 ``POST /api/articles``).

Authentication: ``api-key`` header. DEV.to answers 201 with the article
(``id``, ``url``, ``published_at`` ...), 401 for a bad key, 422 for a rejected
article and 429 when the article-creation rate limit is exceeded.
"""

from app.exceptions import InvalidResponseError
from app.platforms.base import BasePlatform, PostedContent, make_title, parse_datetime

FOREM_ACCEPT = "application/vnd.forem.api-v1+json"


class DevToPlatform(BasePlatform):
    name = "DEV.to"
    key = "devto"

    BASE_URL = "https://dev.to"

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        s = self._settings
        self._require(devto_api_key=s.devto_api_key)

        data = self._json(
            await self._request(
                "POST",
                f"{self.BASE_URL}/api/articles",
                headers={"api-key": s.devto_api_key, "Accept": FOREM_ACCEPT},
                json={
                    "article": {
                        "title": make_title(message, cta_url),
                        "body_markdown": message,
                        "published": True,
                    }
                },
            )
        )
        article_id, url = data.get("id"), data.get("url")
        if not article_id or not url:
            raise InvalidResponseError("DEV.to response did not contain the article id and url")

        # Anonymous check: only published articles are returned by the public endpoint.
        public = await self._poll_public(
            f"{self.BASE_URL}/api/articles/{article_id}", headers={"Accept": FOREM_ACCEPT}
        )
        return PostedContent(
            external_id=str(article_id),
            posted_url=str(url),
            public_access=public is not None,
            published_at=parse_datetime(data.get("published_at") or data.get("created_at")),
        )
