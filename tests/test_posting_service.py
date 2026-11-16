"""PostingService: modes, concurrency, failure isolation, timeouts, success rules (all offline)."""

import asyncio
from datetime import date, datetime, time

import httpx
import pytest
import respx

from app.config import Settings
from app.platforms.base import BasePlatform, PostedContent
from app.platforms.registry import PlatformRegistry, build_default_registry
from app.schemas import PostStatus
from app.services.posting_service import PostingService
from tests.helpers import PLATFORM_KEYS, PLATFORM_NAMES, VALID_MESSAGE, VALID_URL, mock_all


@pytest.fixture
def service(http_client: httpx.AsyncClient, settings: Settings, fixed_now: datetime) -> PostingService:
    registry = build_default_registry(http_client, settings)
    return PostingService(registry, mode="live", timeout_seconds=2.0, clock=lambda: fixed_now)


# --------------------------------------------------------------------------- #
# Demo mode: simulated, no credentials, no network at all
# --------------------------------------------------------------------------- #
async def test_demo_mode_simulates_all_five_platforms_without_any_http_call(
    router: respx.MockRouter, http_client: httpx.AsyncClient, demo_settings: Settings
) -> None:
    registry = build_default_registry(http_client, demo_settings)
    service = PostingService(registry, mode="demo")

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert len(router.calls) == 0  # no external API call
    assert response.success is True
    assert response.mode == "demo"
    assert "DEMO MODE" in response.notice
    assert (response.summary.total, response.summary.simulated, response.summary.succeeded) == (5, 5, 0)
    assert [r.platform for r in response.results] == PLATFORM_NAMES
    for result in response.results:
        assert result.status is PostStatus.SIMULATED
        assert result.posted_url is None
        assert result.public_access is False
        assert result.date is None and result.time is None
        assert result.error is None
        assert "SIMULATED" in result.note


# --------------------------------------------------------------------------- #
# Live mode: success
# --------------------------------------------------------------------------- #
async def test_live_all_platforms_succeed(router: respx.MockRouter, service: PostingService) -> None:
    mock_all(router)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.success is True
    assert response.mode == "live"
    assert (response.summary.total, response.summary.succeeded, response.summary.failed) == (5, 5, 0)
    assert [r.platform for r in response.results] == PLATFORM_NAMES
    for result in response.results:
        assert result.status is PostStatus.SUCCESS
        assert result.posted_url.startswith("https://")
        assert result.public_access is True
        assert result.error is None
        assert result.date == date(2026, 11, 15)
        assert result.time is not None


async def test_live_uses_the_publication_time_reported_by_the_platform(
    router: respx.MockRouter, service: PostingService
) -> None:
    mock_all(router)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)
    by_name = {r.platform: r for r in response.results}

    assert by_name["Mastodon"].time == time(10, 30, 1)
    assert by_name["DEV.to"].time == time(10, 30, 2)
    assert by_name["Hashnode"].time == time(10, 30, 3)
    assert by_name["WordPress"].time == time(10, 30, 4)
    assert by_name["Bluesky"].time == time(10, 30, 5)  # indexedAt from the public AppView


async def test_live_post_not_publicly_reachable_is_reported_honestly(
    router: respx.MockRouter, settings: Settings, service: PostingService
) -> None:
    mock_all(router)
    router.get("https://blog.test/2026/11/15/check-out-our-latest-business-platform/").respond(404)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)
    wordpress = next(r for r in response.results if r.platform == "WordPress")

    assert wordpress.status is PostStatus.SUCCESS  # it was published ...
    assert wordpress.public_access is False  # ... but public access is NOT verified
    assert "could not be verified" in wordpress.note


# --------------------------------------------------------------------------- #
# Live mode: individual failures never stop the others
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("failing_key", PLATFORM_KEYS)
@pytest.mark.parametrize("outcome", ["auth", "timeout", "rate_limit", "server_error", "network", "bad_request"])
async def test_one_platform_fails_others_succeed(
    failing_key: str, outcome: str, router: respx.MockRouter, service: PostingService
) -> None:
    mock_all(router, **{failing_key: outcome})

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.success is True
    assert (response.summary.succeeded, response.summary.failed) == (4, 1)
    for key, result in zip(PLATFORM_KEYS, response.results):
        if key == failing_key:
            assert result.status is PostStatus.FAILED
            assert result.posted_url is None
            assert result.public_access is False
            assert result.date is None and result.time is None
            assert result.error
        else:
            assert result.status is PostStatus.SUCCESS


async def test_error_categories_per_platform(router: respx.MockRouter, service: PostingService) -> None:
    mock_all(router, bluesky="rate_limit", mastodon="server_error", devto="network", hashnode="auth", wordpress="timeout")

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.success is False
    assert [r.error_type for r in response.results] == [
        "rate_limit_error",
        "api_error",
        "connection_error",
        "authentication_error",
        "timeout_error",
    ]
    assert "retry after 30" in response.results[0].error


async def test_authentication_error_is_reported_clearly(router: respx.MockRouter, service: PostingService) -> None:
    mock_all(router, mastodon="auth")

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)
    mastodon = next(r for r in response.results if r.platform == "Mastodon")

    assert mastodon.status is PostStatus.FAILED
    assert mastodon.error == "Authentication failed: Invalid credentials"
    assert mastodon.error_type == "authentication_error"


@pytest.mark.parametrize("outcome", ["auth", "rate_limit", "server_error", "timeout", "network"])
async def test_all_platforms_fail_means_overall_failure(
    outcome: str, router: respx.MockRouter, service: PostingService
) -> None:
    mock_all(router, **dict.fromkeys(PLATFORM_KEYS, outcome))

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.success is False
    assert (response.summary.total, response.summary.succeeded, response.summary.failed) == (5, 0, 5)
    assert all(r.status is PostStatus.FAILED and r.error for r in response.results)


async def test_live_mode_without_credentials_fails_every_platform_meaningfully(
    router: respx.MockRouter, http_client: httpx.AsyncClient
) -> None:
    empty = Settings(_env_file=None, posting_mode="live")
    service = PostingService(build_default_registry(http_client, empty), mode="live", timeout_seconds=2.0)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.success is False
    assert len(router.calls) == 0  # nothing is sent without credentials
    assert all(r.error_type == "configuration_error" for r in response.results)
    assert "BLUESKY_HANDLE" in response.results[0].error
    assert "DEVTO_API_KEY" in response.results[2].error


# --------------------------------------------------------------------------- #
# Concurrency, asyncio timeout, exception isolation (with fake platforms)
# --------------------------------------------------------------------------- #
class FakePlatform(BasePlatform):
    """Tiny platform whose behaviour is a coroutine function given by the test."""

    def __init__(self, key: str, behaviour) -> None:  # noqa: ANN001 - test helper
        self.key = key
        self.name = key.title()
        self._behaviour = behaviour

    async def publish(self, message: str, cta_url: str) -> PostedContent:
        await self._behaviour()
        return PostedContent(external_id=f"{self.key}-1", posted_url=f"https://{self.key}.example/1", public_access=True)


async def ok() -> None:
    return None


async def test_platforms_run_concurrently() -> None:
    # Every fake waits at a barrier that only opens once ALL 5 run at the same time.
    # Sequential execution would never open it and would hit the timeout.
    barrier = asyncio.Barrier(5)
    platforms = [FakePlatform(f"p{i}", barrier.wait) for i in range(5)]
    service = PostingService(PlatformRegistry(platforms), mode="live", timeout_seconds=2.0)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)

    assert response.summary.succeeded == 5


async def test_slow_platform_is_cut_off_by_asyncio_timeout() -> None:
    async def hang() -> None:
        await asyncio.sleep(30)

    registry = PlatformRegistry([FakePlatform("fast", ok), FakePlatform("slow", hang), FakePlatform("also_fast", ok)])
    service = PostingService(registry, mode="live", timeout_seconds=0.1)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)
    by_name = {r.platform: r for r in response.results}

    assert by_name["Slow"].status is PostStatus.FAILED
    assert by_name["Slow"].error == "Slow did not respond within 0.1 seconds"
    assert by_name["Slow"].error_type == "timeout_error"
    assert by_name["Fast"].status is PostStatus.SUCCESS
    assert by_name["Also_Fast"].status is PostStatus.SUCCESS


async def test_unexpected_exception_in_one_platform_does_not_break_others() -> None:
    async def boom() -> None:
        raise RuntimeError("bug in integration")

    registry = PlatformRegistry([FakePlatform("a", ok), FakePlatform("broken", boom), FakePlatform("b", ok)])
    service = PostingService(registry, mode="live", timeout_seconds=1.0)

    response = await service.post_to_all(VALID_MESSAGE, VALID_URL)
    by_name = {r.platform: r for r in response.results}

    assert response.success is True
    assert by_name["Broken"].error == "Unexpected error: bug in integration"
    assert by_name["Broken"].error_type == "unexpected_error"
    assert by_name["A"].status is PostStatus.SUCCESS and by_name["B"].status is PostStatus.SUCCESS


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode must be"):
        PostingService(PlatformRegistry(), mode="production")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_default_registry_contains_the_five_platforms(http_client: httpx.AsyncClient, settings: Settings) -> None:
    registry = build_default_registry(http_client, settings)

    assert len(registry) == 5
    assert [p.key for p in registry.all()] == PLATFORM_KEYS
    assert registry.get("devto").name == "DEV.to"


def test_registry_rejects_duplicates_and_unknown_keys() -> None:
    registry = PlatformRegistry([FakePlatform("one", ok)])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakePlatform("one", ok))
    with pytest.raises(KeyError, match="Unknown platform"):
        registry.get("myspace")
