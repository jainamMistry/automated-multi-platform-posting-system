"""WordPress integration (REST API ``POST /wp-json/wp/v2/posts``).

Authentication: HTTP Basic with the WordPress username and an *Application
Password* (Users -> Profile -> Application Passwords). This works on
self-hosted WordPress (and sites that expose Application Passwords); the
site should be served over HTTPS. WordPress.com sites use OAuth instead.
"""

import httpx

from app.exceptions import InvalidResponseError
from app.platforms.base import BasePlatform, PostedContent, html_body, make_title, parse_datetime


class WordPressPlatform(BasePlatform):
    name = "WordPress"
    key = "wordpress"

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        s = self._settings
        self._require(
            wordpress_url=s.wordpress_url,
            wordpress_username=s.wordpress_username,
            wordpress_app_password=s.wordpress_app_password,
        )
        base = s.wordpress_url.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"

        data = self._json(
            await self._request(
                "POST",
                f"{base}/wp-json/wp/v2/posts",
                auth=httpx.BasicAuth(s.wordpress_username, s.wordpress_app_password),
                json={
                    "title": make_title(message, cta_url),
                    "content": html_body(message, cta_url),
                    "status": "publish",
                },
            )
        )
        post_id, link = data.get("id"), data.get("link")
        if not post_id or not link:
            raise InvalidResponseError("WordPress response did not contain the post id and link")
        if data.get("status") != "publish":
            raise InvalidResponseError(
                f"WordPress created the post but its status is {data.get('status')!r}, not 'publish' "
                "(the account may lack the publish_posts capability)"
            )

        public = await self._poll_public(str(link))
        return PostedContent(
            external_id=str(post_id),
            posted_url=str(link),
            public_access=public is not None,
            published_at=parse_datetime(data.get("date_gmt")) or parse_datetime(data.get("date")),
        )
