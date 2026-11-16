"""Shared fixtures. Everything here is offline and deterministic."""

import socket
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.config import Settings

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test tries to open a non-local network connection.

    Loopback is allowed because asyncio / TestClient use it internally.
    """
    original_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object, *args: object, **kwargs: object):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in _LOOPBACK:
            raise RuntimeError(f"External network access is blocked in tests (tried to connect to {host})")
        return original_connect(self, address, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


FAKE_CREDENTIALS = {
    "bluesky_handle": "tester.bsky.social",
    "bluesky_app_password": "abcd-efgh-ijkl-mnop",
    "mastodon_instance": "https://mastodon.test",
    "mastodon_access_token": "fake-mastodon-token",
    "devto_api_key": "fake-devto-key",
    "hashnode_api_key": "fake-hashnode-token",
    "hashnode_publication_id": "64f000000000000000000001",
    "wordpress_url": "https://blog.test",
    "wordpress_username": "editor",
    "wordpress_app_password": "abcd EFGH 1234 ijkl MNOP 5678",
}


@pytest.fixture
def settings() -> Settings:
    """LIVE-mode settings with FAKE credentials; ignores any local .env file."""
    return Settings(_env_file=None, posting_mode="live", public_check_delay_seconds=0, **FAKE_CREDENTIALS)


@pytest.fixture
def demo_settings() -> Settings:
    """DEMO-mode settings with no credentials at all."""
    return Settings(_env_file=None, posting_mode="demo")


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 11, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    """respx router that intercepts every HTTPX request made in the test."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def http_client(router: respx.MockRouter) -> AsyncIterator[httpx.AsyncClient]:
    """A normal HTTPX client; respx (``router``) answers its requests."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        yield client
