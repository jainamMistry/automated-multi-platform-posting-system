"""Request and response schemas."""

import datetime as dt
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.validators.url_validator import extract_single_url

MAX_MESSAGE_LENGTH = 200

DEMO_NOTICE = (
    "DEMO MODE: nothing was published to any platform. No external API was called, "
    "no credentials were used and no post URLs exist. Set POSTING_MODE=live to publish for real."
)
LIVE_NOTICE = "LIVE MODE: results reflect real calls to the official platform APIs."

SIMULATED_NOTE = "SIMULATED: not published; no external API call was made."


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #
class PostRequest(BaseModel):
    message: str = Field(
        ...,
        description=(
            f"Message to post: 1-{MAX_MESSAGE_LENGTH} characters and exactly one "
            "http(s) CTA URL."
        ),
        examples=["Check out our latest business platform and grow your online visibility. https://example.com"],
        json_schema_extra={"minLength": 1, "maxLength": MAX_MESSAGE_LENGTH},
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be empty")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Message must not exceed {MAX_MESSAGE_LENGTH} characters (received {len(value)})"
            )
        extract_single_url(value)  # raises URLValidationError (a ValueError)
        return value

    @property
    def cta_url(self) -> str:
        """The single, validated CTA URL contained in the message."""
        return extract_single_url(self.message)


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #
class PostStatus(str, Enum):
    SIMULATED = "simulated"  # demo mode only: nothing was published
    SUCCESS = "success"  # live mode only: publication confirmed by the platform API
    FAILED = "failed"


class PlatformResult(BaseModel):
    platform: str = Field(description="Platform name")
    status: PostStatus
    posted_url: str | None = Field(None, description="Real URL of the published post (always null in demo mode)")
    public_access: bool = Field(
        description="True only when the post was fetched anonymously after publishing (always false in demo mode)"
    )
    date: dt.date | None = Field(None, description="Publication date (UTC); null unless really published")
    time: dt.time | None = Field(None, description="Publication time (UTC); null unless really published")
    error: str | None = Field(None, description="Error details when status is 'failed'")
    error_type: str | None = Field(None, description="Machine-readable error category")
    external_id: str | None = Field(None, description="Platform-specific post id / URI (live mode)")
    note: str | None = Field(None, description="Extra information, e.g. the SIMULATED label in demo mode")

    @classmethod
    def simulated(cls, platform: str) -> "PlatformResult":
        return cls(
            platform=platform,
            status=PostStatus.SIMULATED,
            posted_url=None,
            public_access=False,
            note=SIMULATED_NOTE,
        )

    @classmethod
    def succeeded(
        cls,
        platform: str,
        *,
        posted_url: str,
        public_access: bool,
        external_id: str,
        posted_at: dt.datetime,
        note: str | None = None,
    ) -> "PlatformResult":
        return cls(
            platform=platform,
            status=PostStatus.SUCCESS,
            posted_url=posted_url,
            public_access=public_access,
            date=posted_at.date(),
            time=posted_at.time().replace(microsecond=0),
            external_id=external_id,
            note=note,
        )

    @classmethod
    def failed(cls, platform: str, *, error: str, error_type: str) -> "PlatformResult":
        return cls(
            platform=platform,
            status=PostStatus.FAILED,
            public_access=False,
            error=error,
            error_type=error_type,
        )


class PostingSummary(BaseModel):
    total: int
    succeeded: int = Field(description="Confirmed live publications")
    simulated: int = Field(description="Platforms simulated in demo mode")
    failed: int


class PostingResponse(BaseModel):
    success: bool = Field(
        description="Demo mode: true when the platforms were simulated. "
        "Live mode: true when at least one platform confirmed publication."
    )
    mode: Literal["demo", "live"]
    notice: str
    cta_url: str = Field(description="The CTA URL extracted from the message")
    summary: PostingSummary
    results: list[PlatformResult]


class ErrorDetail(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    success: bool = False
    error: str = "Validation failed"
    details: list[ErrorDetail]
