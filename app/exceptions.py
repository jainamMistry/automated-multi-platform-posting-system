"""Exceptions raised by platform integrations.

Platform classes translate low-level HTTPX errors and HTTP status codes into
these exceptions, so the posting service only deals with one error vocabulary.
"""


class PlatformError(Exception):
    """Base class for every platform failure."""

    error_type = "platform_error"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigurationError(PlatformError):
    """Required credentials / settings for the platform are missing (live mode)."""

    error_type = "configuration_error"


class AuthenticationError(PlatformError):
    """Credentials missing, expired or rejected (HTTP 401 / 403)."""

    error_type = "authentication_error"


class RateLimitError(PlatformError):
    """The platform asked us to slow down (HTTP 429)."""

    error_type = "rate_limit_error"


class PlatformTimeoutError(PlatformError):
    """The platform did not answer in time."""

    error_type = "timeout_error"


class PlatformConnectionError(PlatformError):
    """The platform could not be reached (DNS, TCP, TLS ...)."""

    error_type = "connection_error"


class PlatformAPIError(PlatformError):
    """The platform rejected the request or had an internal error (4xx / 5xx)."""

    error_type = "api_error"


class InvalidResponseError(PlatformError):
    """The platform answered successfully but the body was not what we expect."""

    error_type = "invalid_response"
