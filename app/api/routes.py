"""API routes."""

from fastapi import APIRouter, Depends

from app.dependencies import get_posting_service
from app.schemas import PostingResponse, PostRequest, ValidationErrorResponse
from app.services.posting_service import PostingService

router = APIRouter()


@router.post(
    "/posting",
    response_model=PostingResponse,
    summary="Post a message to Bluesky, Mastodon, DEV.to, Hashnode and WordPress",
    description=(
        "Validates the message (1-200 characters, exactly one valid http(s) URL) and posts it "
        "**concurrently** to all five platforms. No platform selection is needed.\n\n"
        "* **`POSTING_MODE=demo`** (default): nothing is published. Every platform returns status "
        "`simulated`, `posted_url: null` and `public_access: false`. No credentials are needed.\n"
        "* **`POSTING_MODE=live`**: real posts are created through the official APIs. `success` "
        "status means publication was confirmed by the platform; failures are reported per platform.\n\n"
        "One platform failing never stops the others. The response is HTTP 200 whenever the request "
        "was valid; `success` is true when at least one platform succeeded (live) or was simulated (demo)."
    ),
    responses={422: {"model": ValidationErrorResponse, "description": "Invalid message"}},
)
async def create_posting(
    payload: PostRequest,
    service: PostingService = Depends(get_posting_service),
) -> PostingResponse:
    return await service.post_to_all(payload.message, payload.cta_url)


@router.get("/health", summary="Health check", tags=["system"])
async def health(service: PostingService = Depends(get_posting_service)) -> dict[str, str]:
    return {"status": "ok", "mode": service.mode}
