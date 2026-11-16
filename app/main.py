"""Application entry point.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.platforms.registry import build_default_registry
from app.schemas import ErrorDetail, ValidationErrorResponse
from app.services.posting_service import PostingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s - %(message)s")
logger = logging.getLogger(__name__)
# HTTPX logs full request URLs at INFO; keep them out of the logs (they may contain identifiers).
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared HTTP client and the posting service once at startup."""
    settings = get_settings()
    # One shared client. In demo mode it is never used to call any API.
    client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    registry = build_default_registry(client, settings)
    app.state.posting_service = PostingService(
        registry, mode=settings.posting_mode, timeout_seconds=settings.platform_timeout_seconds
    )
    logger.info("Started in %s mode", settings.posting_mode.upper())
    try:
        yield
    finally:
        await client.aclose()


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn Pydantic errors into a compact, readable 422 response."""
    details: list[ErrorDetail] = []
    for error in exc.errors():
        if error["type"] == "json_invalid":
            field, message = "body", "Request body must be valid JSON"
        else:
            field = ".".join(str(part) for part in error["loc"][1:]) or "body"
            message = error["msg"].removeprefix("Value error, ")
        details.append(ErrorDetail(field=field, message=message))

    body = ValidationErrorResponse(details=details)
    return JSONResponse(status_code=422, content=body.model_dump())


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Posts one short message with a CTA link to **Bluesky, Mastodon, DEV.to, Hashnode and WordPress**.\n\n"
            "**Demo mode (`POSTING_MODE=demo`, default):** nothing is published and no credentials are needed; "
            "every platform returns `simulated`.\n\n"
            "**Live mode (`POSTING_MODE=live`):** real posts are created through each platform's official API."
        ),
        version="2.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app


app = create_app()
