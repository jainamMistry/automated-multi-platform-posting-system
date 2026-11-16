"""Per-platform request shapes, response handling and edge cases (HTTP mocked with respx)."""

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.exceptions import (
    AuthenticationError,
    ConfigurationError,
    InvalidResponseError,
    PlatformAPIError,
    PlatformConnectionError,
    PlatformTimeoutError,
    RateLimitError,
)
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.hashnode import HashnodePlatform
from app.platforms.mastodon import MastodonPlatform, normalise_base_url
from app.platforms.wordpress import WordPressPlatform
from tests import helpers as h
from tests.helpers import VALID_MESSAGE, VALID_URL


def body_of(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


# --------------------------------------------------------------------------- #
# Bluesky
# --------------------------------------------------------------------------- #
async def test_bluesky_flow(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "bluesky")

    result = await BlueskyPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.external_id == h.BSKY_URI
    assert result.posted_url == h.BSKY_URL
    assert result.public_access is True

    login = router.calls[0].request
    assert json.loads(login.content) == {"identifier": "tester.bsky.social", "password": "abcd-efgh-ijkl-mnop"}

    create = router.calls[1].request
    assert create.headers["authorization"] == "Bearer jwt"
    payload = json.loads(create.content)
    assert payload["repo"] == h.BSKY_DID
    assert payload["collection"] == "app.bsky.feed.post"
    record = payload["record"]
    assert record["$type"] == "app.bsky.feed.post" and record["text"] == VALID_MESSAGE
    facet = record["facets"][0]
    start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
    assert VALID_MESSAGE.encode()[start:end] == VALID_URL.encode()
    assert facet["features"] == [{"$type": "app.bsky.richtext.facet#link", "uri": VALID_URL}]


async def test_bluesky_facet_uses_utf8_byte_offsets(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    h.mock_success(router, "bluesky")
    message = f"Café ünïcode 🚀 {VALID_URL}"

    await BlueskyPlatform(http_client, settings).publish(message, VALID_URL)

    facet = json.loads(router.calls[1].request.content)["record"]["facets"][0]
    assert message.encode()[facet["index"]["byteStart"] : facet["index"]["byteEnd"]] == VALID_URL.encode()
    assert facet["index"]["byteStart"] > len(message.split(VALID_URL)[0])  # bytes > characters


async def test_bluesky_bad_app_password(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    router.post(f"{h.BSKY_PDS}/xrpc/com.atproto.server.createSession").respond(
        401, json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"}
    )

    with pytest.raises(AuthenticationError, match="Authentication failed: Invalid identifier or password"):
        await BlueskyPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


async def test_bluesky_post_stays_successful_when_public_check_fails(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    h.mock_success(router, "bluesky")
    router.get(f"{h.BSKY_PUBLIC}/xrpc/app.bsky.feed.getPosts").respond(200, json={"posts": []})

    result = await BlueskyPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.public_access is False
    assert result.posted_url == h.BSKY_URL


async def test_bluesky_invalid_record_response(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    h.mock_success(router, "bluesky")
    router.post(f"{h.BSKY_PDS}/xrpc/com.atproto.repo.createRecord").respond(200, json={"cid": "x"})

    with pytest.raises(InvalidResponseError, match="valid post URI"):
        await BlueskyPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


# --------------------------------------------------------------------------- #
# Mastodon
# --------------------------------------------------------------------------- #
async def test_mastodon_flow(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "mastodon")

    result = await MastodonPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.posted_url == h.MASTODON_URL and result.public_access is True
    request = router.calls[0].request
    assert request.headers["authorization"] == "Bearer fake-mastodon-token"
    assert json.loads(request.content) == {"status": VALID_MESSAGE, "visibility": "public"}
    assert "authorization" not in router.calls[1].request.headers  # public check is anonymous


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("mastodon.social", "https://mastodon.social"), ("https://mastodon.social/", "https://mastodon.social"),
     (" http://localhost:3000 ", "http://localhost:3000")],
)
def test_mastodon_instance_normalisation(raw: str, expected: str) -> None:
    assert normalise_base_url(raw) == expected


async def test_mastodon_non_public_status_is_not_reported_public(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    h.mock_success(router, "mastodon")
    router.get(f"{h.MASTODON}/api/v1/statuses/111222333444555666").respond(404, json={"error": "Record not found"})

    assert (await MastodonPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)).public_access is False


# --------------------------------------------------------------------------- #
# DEV.to
# --------------------------------------------------------------------------- #
async def test_devto_flow(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "devto")

    result = await DevToPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.posted_url == h.DEVTO_URL and result.external_id == "424242" and result.public_access is True
    request = router.calls[0].request
    assert request.headers["api-key"] == "fake-devto-key"
    assert request.headers["accept"] == "application/vnd.forem.api-v1+json"
    article = json.loads(request.content)["article"]
    assert article["published"] is True
    assert article["body_markdown"] == VALID_MESSAGE
    assert article["title"] and VALID_URL not in article["title"]


async def test_devto_validation_error_422(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    router.post("https://dev.to/api/articles").respond(422, json={"error": "Title can't be blank", "status": 422})

    with pytest.raises(PlatformAPIError, match=r"rejected the request \(422\): Title can't be blank"):
        await DevToPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


# --------------------------------------------------------------------------- #
# Hashnode
# --------------------------------------------------------------------------- #
async def test_hashnode_flow(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "hashnode")

    result = await HashnodePlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.posted_url == h.HASHNODE_URL and result.public_access is True
    request = router.calls[0].request
    assert request.headers["authorization"] == "fake-hashnode-token"  # raw PAT, no "Bearer"
    payload = json.loads(request.content)
    assert "publishPost(input: $input)" in payload["query"]
    assert payload["variables"]["input"]["publicationId"] == "64f000000000000000000001"
    assert payload["variables"]["input"]["contentMarkdown"] == VALID_MESSAGE
    assert payload["variables"]["input"]["title"]


@pytest.mark.parametrize(
    ("error", "exception"),
    [
        ({"message": "You must be logged in", "extensions": {"code": "UNAUTHENTICATED"}}, AuthenticationError),
        ({"message": "Too many requests, slow down"}, RateLimitError),
        ({"message": "Publication not found", "extensions": {"code": "NOT_FOUND"}}, PlatformAPIError),
    ],
)
async def test_hashnode_graphql_errors_in_http_200(
    error: dict, exception: type, router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    router.post("https://gql.hashnode.com").respond(200, json={"errors": [error], "data": None})

    with pytest.raises(exception, match=error["message"]):
        await HashnodePlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


async def test_hashnode_missing_post_in_response(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    router.post("https://gql.hashnode.com").respond(200, json={"data": {"publishPost": {"post": None}}})

    with pytest.raises(InvalidResponseError):
        await HashnodePlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


# --------------------------------------------------------------------------- #
# WordPress
# --------------------------------------------------------------------------- #
async def test_wordpress_flow(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "wordpress")

    result = await WordPressPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)

    assert result.posted_url == h.WORDPRESS_LINK and result.public_access is True
    request = router.calls[0].request
    assert request.headers["authorization"].startswith("Basic ")
    payload = json.loads(request.content)
    assert payload["status"] == "publish"
    assert f'<a href="{VALID_URL}">{VALID_URL}</a>' in payload["content"]


async def test_wordpress_html_is_escaped(router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings) -> None:
    h.mock_success(router, "wordpress")

    await WordPressPlatform(http_client, settings).publish(f"<script>alert(1)</script> {VALID_URL}", VALID_URL)

    assert "<script>" not in json.loads(router.calls[0].request.content)["content"]


async def test_wordpress_draft_status_is_not_reported_as_published(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    router.post("https://blog.test/wp-json/wp/v2/posts").respond(
        201, json={"id": 1, "link": "https://blog.test/?p=1", "status": "pending"}
    )

    with pytest.raises(InvalidResponseError, match="not 'publish'"):
        await WordPressPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


async def test_wordpress_application_password_rejected(
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    router.post("https://blog.test/wp-json/wp/v2/posts").respond(
        401, json={"code": "incorrect_password", "message": "The provided password is an invalid application password."}
    )

    with pytest.raises(AuthenticationError, match="invalid application password"):
        await WordPressPlatform(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


# --------------------------------------------------------------------------- #
# Shared error handling and configuration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("platform_cls", "key"),
    [(BlueskyPlatform, "bluesky"), (MastodonPlatform, "mastodon"), (DevToPlatform, "devto"),
     (HashnodePlatform, "hashnode"), (WordPressPlatform, "wordpress")],
)
@pytest.mark.parametrize(
    ("outcome", "exception"),
    [
        ("auth", AuthenticationError),
        ("forbidden", AuthenticationError),
        ("rate_limit", RateLimitError),
        ("server_error", PlatformAPIError),
        ("bad_request", PlatformAPIError),
        ("timeout", PlatformTimeoutError),
        ("network", PlatformConnectionError),
    ],
)
async def test_http_errors_map_to_exceptions(
    platform_cls: type, key: str, outcome: str, exception: type,
    router: respx.MockRouter, http_client: httpx.AsyncClient, settings: Settings,
) -> None:
    h.mock_failure(router, key, outcome)

    with pytest.raises(exception):
        await platform_cls(http_client, settings).publish(VALID_MESSAGE, VALID_URL)


@pytest.mark.parametrize(
    ("platform_cls", "expected"),
    [
        (BlueskyPlatform, "BLUESKY_HANDLE, BLUESKY_APP_PASSWORD"),
        (MastodonPlatform, "MASTODON_INSTANCE, MASTODON_ACCESS_TOKEN"),
        (DevToPlatform, "DEVTO_API_KEY"),
        (HashnodePlatform, "HASHNODE_API_KEY, HASHNODE_PUBLICATION_ID"),
        (WordPressPlatform, "WORDPRESS_URL, WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD"),
    ],
)
async def test_missing_credentials_raise_configuration_error_without_http_call(
    platform_cls: type, expected: str, router: respx.MockRouter, http_client: httpx.AsyncClient
) -> None:
    empty = Settings(_env_file=None, posting_mode="live")

    with pytest.raises(ConfigurationError, match=expected):
        await platform_cls(http_client, empty).publish(VALID_MESSAGE, VALID_URL)
    assert len(router.calls) == 0


def test_make_title_strips_url_and_truncates() -> None:
    from app.platforms.base import make_title

    assert make_title(f"Hello world {VALID_URL}", VALID_URL) == "Hello world"
    assert make_title(VALID_URL, VALID_URL) == "Update from example.com"
    assert len(make_title("word " * 60 + VALID_URL, VALID_URL)) <= 80
