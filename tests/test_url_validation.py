"""URL extraction and validation."""

import pytest

from app.validators.url_validator import (
    URLValidationError,
    extract_single_url,
    extract_urls,
    validate_url,
)


# --------------------------------------------------------------------------- #
# validate_url
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com",
        "https://www.example.com/path?query=1&b=2#fragment",
        "https://sub.domain.example.co.in/a/b/c",
        "https://example.com:8443/secure",
        "https://münchen.de/start",  # unicode domain
        "https://xn--mnchen-3ya.de",  # punycode domain
        "https://8.8.8.8/landing",  # public IP address
        "https://example.com/wiki/Python_(language)",
    ],
)
def test_valid_urls_are_accepted(url: str) -> None:
    assert validate_url(url) == url


@pytest.mark.parametrize(
    ("url", "expected_error"),
    [
        ("ftp://example.com/file", "not allowed"),
        ("www.example.com", "must start with http"),
        ("https://localhost:3000", "localhost"),
        ("http://127.0.0.1/admin", "public"),
        ("http://192.168.1.10/router", "public"),
        ("http://10.0.0.5", "public"),
        ("https://example", "invalid host name"),  # no top-level domain
        ("https://example.c", "top-level domain"),
        ("https://example.123", "top-level domain"),
        ("http://999.999.999.999", "top-level domain"),
        ("https://-bad.example.com", "invalid host name"),
        ("https://exa_mple.com", "invalid host name"),
        ("https://example..com", "invalid host name"),
        ("https://.example.com", "invalid host name"),
        ("https://user:pass@example.com", "credentials"),
        ("https://example.com:99999", "malformed"),
        ("https://example.com:0", "port"),
        ("https://", "no host"),
        ("https://example.com/" + "a" * 2050, "2048"),
    ],
)
def test_invalid_urls_are_rejected(url: str, expected_error: str) -> None:
    with pytest.raises(URLValidationError, match=expected_error):
        validate_url(url)


# --------------------------------------------------------------------------- #
# extract_urls
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Visit https://example.com today", ["https://example.com"]),
        ("Visit https://example.com.", ["https://example.com"]),  # sentence dot
        ("Wow! https://example.com!!!", ["https://example.com"]),
        ("(see https://example.com)", ["https://example.com"]),  # unbalanced ")"
        ("Read https://en.wikipedia.org/wiki/Python_(language) now", ["https://en.wikipedia.org/wiki/Python_(language)"]),
        ("Go to https://a.com, then https://b.com", ["https://a.com", "https://b.com"]),
        ("No links here, just text and an email me@example.com", []),
        ("Bare domain example.com is not a link", []),
        ("Try www.example.com", ["www.example.com"]),  # reported so it can be rejected
        ("Get ftp://files.example.com/a.zip", ["ftp://files.example.com/a.zip"]),
    ],
)
def test_extract_urls(text: str, expected: list[str]) -> None:
    assert extract_urls(text) == expected


# --------------------------------------------------------------------------- #
# extract_single_url (exactly one URL)
# --------------------------------------------------------------------------- #
def test_single_url_is_returned() -> None:
    assert extract_single_url("Grow your reach https://example.com/offer?id=7.") == "https://example.com/offer?id=7"


def test_message_with_only_a_url_is_accepted() -> None:
    assert extract_single_url("https://example.com") == "https://example.com"


def test_no_url_is_rejected() -> None:
    with pytest.raises(URLValidationError, match="none was found"):
        extract_single_url("There is no link in this message")


def test_multiple_urls_are_rejected() -> None:
    with pytest.raises(URLValidationError, match="but 2 were found"):
        extract_single_url("Visit https://example.com or https://example.org")


def test_same_url_twice_counts_as_two() -> None:
    with pytest.raises(URLValidationError, match="but 2 were found"):
        extract_single_url("https://example.com and again https://example.com")


def test_single_but_invalid_url_is_rejected() -> None:
    with pytest.raises(URLValidationError, match="not allowed"):
        extract_single_url("Download ftp://example.com/file")
