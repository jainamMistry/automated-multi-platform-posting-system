"""Helpers shared by the tests: sample data and respx route builders (all offline)."""

import httpx
import respx

VALID_URL = "https://example.com"
VALID_MESSAGE = f"Check out our latest business platform and grow your online visibility. {VALID_URL}"

PLATFORM_KEYS = ["bluesky", "mastodon", "devto", "hashnode", "wordpress"]
PLATFORM_NAMES = ["Bluesky", "Mastodon", "DEV.to", "Hashnode", "WordPress"]


def message_of_length(length: int, url: str = VALID_URL) -> str:
    """A valid message (text + one URL) with exactly ``length`` characters."""
    filler = "a" * (length - len(url) - 1)
    message = f"{filler} {url}"
    assert len(message) == length
    return message


# --------------------------------------------------------------------------- #
# Fake API responses (shapes follow the official API documentation)
# --------------------------------------------------------------------------- #
BSKY_DID = "did:plc:abc123xyz"
BSKY_URI = f"at://{BSKY_DID}/app.bsky.feed.post/3kabcdefghij2"
BSKY_PDS = "https://bsky.social"
BSKY_PUBLIC = "https://public.api.bsky.app"
BSKY_URL = "https://bsky.app/profile/tester.bsky.social/post/3kabcdefghij2"

MASTODON = "https://mastodon.test"
MASTODON_URL = "https://mastodon.test/@tester/111222333444555666"

DEVTO_URL = "https://dev.to/tester/check-out-our-latest-business-platform-1a2b"
HASHNODE_URL = "https://tester.hashnode.dev/check-out-our-latest-business-platform"
WORDPRESS_LINK = "https://blog.test/2026/11/15/check-out-our-latest-business-platform/"


def mock_success(router: respx.MockRouter, key: str) -> None:
    """Register a complete, successful API conversation for one platform."""
    if key == "bluesky":
        router.post(f"{BSKY_PDS}/xrpc/com.atproto.server.createSession").respond(
            200, json={"accessJwt": "jwt", "did": BSKY_DID, "handle": "tester.bsky.social"}
        )
        router.post(f"{BSKY_PDS}/xrpc/com.atproto.repo.createRecord").respond(
            200, json={"uri": BSKY_URI, "cid": "bafyreiabc"}
        )
        router.get(f"{BSKY_PUBLIC}/xrpc/app.bsky.feed.getPosts").respond(
            200, json={"posts": [{"uri": BSKY_URI, "indexedAt": "2026-11-15T10:30:05.000Z"}]}
        )
    elif key == "mastodon":
        router.post(f"{MASTODON}/api/v1/statuses").respond(
            200,
            json={"id": "111222333444555666", "url": MASTODON_URL, "visibility": "public",
                  "created_at": "2026-11-15T10:30:01.000Z"},
        )
        router.get(f"{MASTODON}/api/v1/statuses/111222333444555666").respond(
            200, json={"id": "111222333444555666", "visibility": "public"}
        )
    elif key == "devto":
        router.post("https://dev.to/api/articles").respond(
            201, json={"id": 424242, "url": DEVTO_URL, "published": True, "published_at": "2026-11-15T10:30:02Z"}
        )
        router.get("https://dev.to/api/articles/424242").respond(200, json={"id": 424242})
    elif key == "hashnode":
        router.post("https://gql.hashnode.com").respond(
            200,
            json={"data": {"publishPost": {"post": {
                "id": "6500000000000000000000aa", "slug": "check-out", "url": HASHNODE_URL,
                "publishedAt": "2026-11-15T10:30:03.000Z"}}}},
        )
        router.get(HASHNODE_URL).respond(200, text="<html>post</html>")
    elif key == "wordpress":
        router.post("https://blog.test/wp-json/wp/v2/posts").respond(
            201, json={"id": 77, "link": WORDPRESS_LINK, "status": "publish", "date_gmt": "2026-11-15T10:30:04"}
        )
        router.get(WORDPRESS_LINK).respond(200, text="<html>post</html>")
    else:
        raise ValueError(key)


def _failure_route(router: respx.MockRouter, key: str) -> respx.Route:
    """The route that carries the *publishing* call (Bluesky: the login call)."""
    return {
        "bluesky": lambda: router.post(f"{BSKY_PDS}/xrpc/com.atproto.server.createSession"),
        "mastodon": lambda: router.post(f"{MASTODON}/api/v1/statuses"),
        "devto": lambda: router.post("https://dev.to/api/articles"),
        "hashnode": lambda: router.post("https://gql.hashnode.com"),
        "wordpress": lambda: router.post("https://blog.test/wp-json/wp/v2/posts"),
    }[key]()


_ERRORS = {
    "auth": (401, "Invalid credentials"),
    "forbidden": (403, "Forbidden"),
    "rate_limit": (429, "Too many requests"),
    "server_error": (500, "Internal platform error"),
    "bad_request": (422, "Validation failed"),
}


def mock_failure(router: respx.MockRouter, key: str, outcome: str) -> respx.Route:
    """Register a failing response. outcome: auth, forbidden, rate_limit, server_error, bad_request, timeout, network."""
    route = _failure_route(router, key)
    if outcome == "timeout":
        route.mock(side_effect=httpx.ReadTimeout("simulated timeout"))
    elif outcome == "network":
        route.mock(side_effect=httpx.ConnectError("simulated connection refused"))
    else:
        status, message = _ERRORS[outcome]
        headers = {"retry-after": "30"} if status == 429 else {}
        route.respond(status, json={"message": message, "error": "Err"}, headers=headers)
    return route


def mock_platform(router: respx.MockRouter, key: str, outcome: str = "success") -> None:
    if outcome == "success":
        mock_success(router, key)
    else:
        mock_failure(router, key, outcome)


def mock_all(router: respx.MockRouter, **outcomes: str) -> None:
    for key in PLATFORM_KEYS:
        mock_platform(router, key, outcomes.get(key, "success"))
