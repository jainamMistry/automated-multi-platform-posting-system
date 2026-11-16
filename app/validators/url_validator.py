"""URL extraction and validation for the call-to-action (CTA) link.

Rules
-----
* The message must contain exactly one URL.
* The URL must use ``http`` or ``https`` and carry an explicit scheme.
* It must have a real public host name (``localhost``, private IPs, single
  label hosts such as ``http://example`` and malformed names are rejected).
* No embedded credentials (``user:pass@host``), valid port, max 2048 chars.
"""

import ipaddress
import re
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}

# Anything that looks like "scheme://something" or starts with "www." counts as
# a URL candidate, so `ftp://x.com` and `www.example.com` are reported as
# invalid instead of being silently ignored.
_CANDIDATE_RE = re.compile(r"(?:\b[a-zA-Z][a-zA-Z0-9+.\-]*://|\bwww\.)[^\s<>\"']+")
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$")

_TRAILING_PUNCTUATION = ".,;:!?"
_CLOSING_PAIRS = {")": "(", "]": "[", "}": "{"}


class URLValidationError(ValueError):
    """Raised when the message has no URL, several URLs, or an invalid URL."""


def _strip_trailing_punctuation(url: str) -> str:
    """Remove punctuation that belongs to the sentence, not to the URL."""
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCTUATION:
            url = url[:-1]
        elif last in _CLOSING_PAIRS and url.count(last) > url.count(_CLOSING_PAIRS[last]):
            url = url[:-1]  # unbalanced ")" -> e.g. "(see https://example.com)"
        else:
            break
    return url


def extract_urls(text: str) -> list[str]:
    """Return every URL-like token found in ``text`` (in order of appearance)."""
    return [_strip_trailing_punctuation(match) for match in _CANDIDATE_RE.findall(text)]


def _validate_host(host: str) -> None:
    if host == "localhost" or host.endswith(".localhost"):
        raise URLValidationError("URL host must be public (localhost is not allowed)")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise URLValidationError("URL host must be public (private or reserved IP addresses are not allowed)")
        return

    try:
        ascii_host = host.encode("idna").decode("ascii")  # supports unicode domains
    except UnicodeError:
        raise URLValidationError(f"URL has an invalid host name: {host!r}") from None

    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or len(labels) < 2:
        raise URLValidationError(f"URL has an invalid host name: {host!r} (expected something like example.com)")
    if not all(_LABEL_RE.match(label) for label in labels):
        raise URLValidationError(f"URL has an invalid host name: {host!r}")
    if not _TLD_RE.match(labels[-1]):
        raise URLValidationError(f"URL has an invalid top-level domain: {labels[-1]!r}")


def validate_url(url: str) -> str:
    """Validate one URL and return it unchanged, or raise ``URLValidationError``."""
    if len(url) > MAX_URL_LENGTH:
        raise URLValidationError(f"URL must not exceed {MAX_URL_LENGTH} characters")

    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for a bad / out-of-range port
    except ValueError:
        raise URLValidationError(f"URL is malformed: {url!r}") from None

    if not parts.scheme:
        raise URLValidationError(f"URL must start with http:// or https:// (got {url!r})")
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise URLValidationError(f"URL scheme {parts.scheme!r} is not allowed; use http or https")
    if not parts.hostname:
        raise URLValidationError(f"URL has no host name: {url!r}")
    if parts.username is not None or parts.password is not None:
        raise URLValidationError("URL must not contain credentials (user:password@host)")
    if port == 0:
        raise URLValidationError("URL has an invalid port")

    _validate_host(parts.hostname.lower())
    return url


def extract_single_url(message: str) -> str:
    """Return the one valid CTA URL in ``message``.

    Raises ``URLValidationError`` if the message has no URL, more than one URL
    (the same URL repeated counts as more than one), or an invalid URL.
    """
    urls = extract_urls(message)
    if not urls:
        raise URLValidationError("Message must contain exactly one URL starting with http:// or https://, but none was found")
    if len(urls) > 1:
        raise URLValidationError(f"Message must contain exactly one URL, but {len(urls)} were found")
    return validate_url(urls[0])
