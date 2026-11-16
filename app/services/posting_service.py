"""Posting service: runs every platform concurrently and isolates failures."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from app.exceptions import PlatformError
from app.platforms.base import BasePlatform
from app.platforms.registry import PlatformRegistry
from app.schemas import DEMO_NOTICE, LIVE_NOTICE, PlatformResult, PostingResponse, PostingSummary, PostStatus

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PostingService:
    def __init__(
        self,
        registry: PlatformRegistry,
        mode: str = "demo",
        timeout_seconds: float = 5.0,
        clock: Callable[[], datetime] = utc_now,  # injectable for predictable tests
    ) -> None:
        if mode not in ("demo", "live"):
            raise ValueError(f"mode must be 'demo' or 'live', got {mode!r}")
        self._registry = registry
        self._mode = mode
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    @property
    def mode(self) -> str:
        return self._mode

    async def post_to_all(self, message: str, cta_url: str) -> PostingResponse:
        platforms = self._registry.all()
        logger.info("Posting to %d platforms in %s mode", len(platforms), self._mode.upper())

        # All platforms start at the same time. _post_to_platform never raises,
        # and return_exceptions=True is a second safety net, so one platform
        # can never prevent the others from finishing.
        outcomes = await asyncio.gather(
            *(self._post_to_platform(platform, message, cta_url) for platform in platforms),
            return_exceptions=True,
        )

        results: list[PlatformResult] = []
        for platform, outcome in zip(platforms, outcomes):
            if isinstance(outcome, BaseException):  # pragma: no cover - defensive
                outcome = PlatformResult.failed(
                    platform.name, error=f"Unexpected error: {outcome}", error_type="unexpected_error"
                )
            results.append(outcome)

        succeeded = sum(result.status is PostStatus.SUCCESS for result in results)
        simulated = sum(result.status is PostStatus.SIMULATED for result in results)
        failed = len(results) - succeeded - simulated
        return PostingResponse(
            # demo: at least one platform simulated; live: at least one confirmed publication
            success=(succeeded + simulated) > 0,
            mode=self._mode,
            notice=DEMO_NOTICE if self._mode == "demo" else LIVE_NOTICE,
            cta_url=cta_url,
            summary=PostingSummary(total=len(results), succeeded=succeeded, simulated=simulated, failed=failed),
            results=results,
        )

    async def _post_to_platform(self, platform: BasePlatform, message: str, cta_url: str) -> PlatformResult:
        """Post to one platform and always return a result (never raise)."""
        if self._mode == "demo":
            # Demo mode never touches the platform class's API code: no credentials, no network.
            logger.info("[DEMO] %s: simulated (nothing published)", platform.name)
            return PlatformResult.simulated(platform.name)

        try:
            content = await asyncio.wait_for(platform.publish(message, cta_url), timeout=self._timeout_seconds)
            note = None if content.public_access else "Published, but the post could not be verified as publicly accessible yet."
            result = PlatformResult.succeeded(
                platform.name,
                posted_url=content.posted_url,
                public_access=content.public_access,
                external_id=content.external_id,
                posted_at=content.published_at or self._clock(),
                note=note,
            )
        except TimeoutError:
            result = PlatformResult.failed(
                platform.name,
                error=f"{platform.name} did not respond within {self._timeout_seconds:g} seconds",
                error_type="timeout_error",
            )
        except PlatformError as exc:
            result = PlatformResult.failed(platform.name, error=str(exc), error_type=exc.error_type)
        except Exception as exc:  # a bug in one integration must not affect the others
            logger.exception("Unexpected error while posting to %s", platform.name)
            result = PlatformResult.failed(
                platform.name, error=f"Unexpected error: {exc}", error_type="unexpected_error"
            )

        if result.status is PostStatus.SUCCESS:
            logger.info("[LIVE] %s: published posted_url=%s public=%s", platform.name, result.posted_url, result.public_access)
        else:
            logger.warning("[LIVE] %s: failed (%s) %s", platform.name, result.error_type, result.error)
        return result
