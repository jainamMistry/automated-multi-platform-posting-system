"""Base platform interface.

Every integration subclasses ``BasePlatform`` and implements ``publish()``
(live mode). The base class owns the shared HTTP plumbing: sending requests
and turning timeouts, connection problems and error status codes into the
exceptions from ``app.exceptions``. Platform classes therefore only contain
what is specific to their API (endpoint, payload, how to read the response).
"""

import asyncio
import html
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.exceptions import (
    AuthenticationError,
    ConfigurationError,
    InvalidResponseError,
    PlatformAPIError,
    PlatformConnectionError,
    PlatformTimeoutError,
    RateLimitError,
)

USER_AGENT = "automated-posting/2.0 (+https://github.com/)"


@dataclass(frozen=True)
class PostedContent:
    """What a platform returns after a confirmed publication."""

    external_id: str
    posted_url: str
    public_access: bool
    published_at: datetime | None = None  # as reported by the platform, if it says


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp from an API response (UTC assumed when naive)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def make_title(message: str, cta_url: str, max_length: int = 80) -> str:
    """A title for blog-style platforms: the message without its URL, shortened."""
    text = re.sub(r"\s+", " ", message.replace(cta_url, " ")).strip(" -–—:|")
    if not text:
        return f"Update from {urlsplit(cta_url).hostname}"
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def html_body(message: str, cta_url: str) -> str:
    """Message as safe HTML with the CTA URL turned into a link."""
    escaped = html.escape(message)
    link = html.escape(cta_url)
    return "<p>" + escaped.replace(link, f'<a href="{link}">{link}</a>') + "</p>"


class BasePlatform(ABC):
    #: Human readable name used in API responses, e.g. "Bluesky".
    name: ClassVar[str]
    #: Lowercase identifier used by the registry.
    key: ClassVar[str]

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        # The HTTP client is injected so tests can swap the transport (respx).
        self._client = client
        self._settings = settings

    @abstractmethod
    async def publish(self, message: str, cta_url: str) -> PostedContent:
        """Really publish ``message`` through the official API (live mode).

        Must raise a ``PlatformError`` subclass on failure.
        """

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    def _require(self, **values: str) -> None:
        """Raise ``ConfigurationError`` listing every empty setting."""
        missing = [env.upper() for env, value in values.items() if not value.strip()]
        if missing:
            raise ConfigurationError(
                f"{self.name} is not configured: set {', '.join(missing)} in the environment / .env file"
            )

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send an HTTP request and raise a ``PlatformError`` on any failure."""
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:  # must come before TransportError
            raise PlatformTimeoutError(f"{self.name} API request timed out") from exc
        except httpx.TransportError as exc:
            raise PlatformConnectionError(f"Could not connect to {self.name} API: {exc}") from exc

        self._raise_for_error(response)
        return response

    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        status = response.status_code
        detail = self._error_detail(response)

        if status in (401, 403):
            raise AuthenticationError(f"Authentication failed: {detail}", status_code=status)
        if status == 429:
            retry_after = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset")
            hint = f" (retry after {retry_after})" if retry_after else ""
            raise RateLimitError(f"Rate limit exceeded{hint}: {detail}", status_code=status)
        if status >= 500:
            raise PlatformAPIError(f"{self.name} server error ({status}): {detail}", status_code=status)
        raise PlatformAPIError(f"{self.name} rejected the request ({status}): {detail}", status_code=status)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Pull a readable message out of the platform-specific error body."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:200] or response.reason_phrase

        if isinstance(body, dict):
            for key in ("message", "error_description", "error", "detail"):
                value = body.get(key)
                if isinstance(value, str) and value:
                    return value
        return response.reason_phrase

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        """Parse a JSON object body or raise ``InvalidResponseError``."""
        try:
            data = response.json()
        except ValueError:
            raise InvalidResponseError(f"{self.name} returned a response that is not valid JSON") from None
        if not isinstance(data, dict):
            raise InvalidResponseError(f"{self.name} returned an unexpected JSON structure")
        return data

    async def _poll_public(
        self,
        url: str,
        accept: Callable[[httpx.Response], bool] = lambda r: r.status_code == 200,
        **kwargs: Any,
    ) -> httpx.Response | None:
        """Fetch ``url`` anonymously (no credentials) to verify public access.

        Retries a few times because a brand-new post may take a moment to appear.
        Never raises: ``None`` simply means "not verified as public".
        """
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        attempts = max(1, self._settings.public_check_attempts)
        for attempt in range(attempts):
            try:
                response = await self._client.get(url, follow_redirects=True, headers=headers, **kwargs)
                if accept(response):
                    return response
            except (httpx.HTTPError, ValueError):
                pass
            if attempt < attempts - 1:
                await asyncio.sleep(self._settings.public_check_delay_seconds)
        return None
