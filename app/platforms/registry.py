"""Platform registry: the single place that knows which platforms exist."""

from collections.abc import Iterable

import httpx

from app.config import Settings
from app.platforms.base import BasePlatform
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.hashnode import HashnodePlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.wordpress import WordPressPlatform


class PlatformRegistry:
    def __init__(self, platforms: Iterable[BasePlatform] = ()) -> None:
        self._platforms: dict[str, BasePlatform] = {}
        for platform in platforms:
            self.register(platform)

    def register(self, platform: BasePlatform) -> None:
        if platform.key in self._platforms:
            raise ValueError(f"Platform {platform.key!r} is already registered")
        self._platforms[platform.key] = platform

    def get(self, key: str) -> BasePlatform:
        try:
            return self._platforms[key]
        except KeyError:
            raise KeyError(f"Unknown platform {key!r}. Registered: {', '.join(self._platforms)}") from None

    def all(self) -> list[BasePlatform]:
        """All platforms, in registration order."""
        return list(self._platforms.values())

    def __len__(self) -> int:
        return len(self._platforms)


def build_default_registry(client: httpx.AsyncClient, settings: Settings) -> PlatformRegistry:
    """Create the registry with all five integrations sharing one HTTP client."""
    return PlatformRegistry(
        [
            BlueskyPlatform(client, settings),
            MastodonPlatform(client, settings),
            DevToPlatform(client, settings),
            HashnodePlatform(client, settings),
            WordPressPlatform(client, settings),
        ]
    )
