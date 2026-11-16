"""End-to-end API tests: real FastAPI app, offline (demo mode, or live mode with mocked HTTP)."""

from collections.abc import Iterator

import pytest
import respx
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.schemas import MAX_MESSAGE_LENGTH
from tests.conftest import FAKE_CREDENTIALS
from tests.helpers import PLATFORM_NAMES, VALID_MESSAGE, mock_all, message_of_length


def _client(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    with TestClient(main_module.app) as test_client:  # `with` runs the lifespan (startup)
        yield test_client


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """DEMO mode, no credentials."""
    yield from _client(monkeypatch, Settings(_env_file=None, posting_mode="demo"))


@pytest.fixture
def live_client(monkeypatch: pytest.MonkeyPatch, router: respx.MockRouter) -> Iterator[TestClient]:
    """LIVE mode with fake credentials; every HTTP call is answered by respx."""
    live = Settings(
        _env_file=None, posting_mode="live", platform_timeout_seconds=0.5,
        public_check_delay_seconds=0, **FAKE_CREDENTIALS,
    )
    yield from _client(monkeypatch, live)


def post(client: TestClient, message: str):
    return client.post("/posting", json={"message": message})


# --------------------------------------------------------------------------- #
# Basics
# --------------------------------------------------------------------------- #
def test_health_check_reports_demo_mode(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "mode": "demo"}


def test_health_check_reports_live_mode(live_client: TestClient) -> None:
    assert live_client.get("/health").json() == {"status": "ok", "mode": "live"}


def test_swagger_docs_and_openapi_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/posting" in schema["paths"]
    # Only "message" is required: no platform selection in the request body.
    assert list(schema["components"]["schemas"]["PostRequest"]["properties"]) == ["message"]


# --------------------------------------------------------------------------- #
# Demo mode (works with no credentials and no network)
# --------------------------------------------------------------------------- #
def test_demo_mode_returns_five_simulated_results(client: TestClient) -> None:
    response = post(client, VALID_MESSAGE)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["mode"] == "demo"
    assert "DEMO MODE" in body["notice"]
    assert body["cta_url"] == "https://example.com"
    assert body["summary"] == {"total": 5, "succeeded": 0, "simulated": 5, "failed": 0}
    assert [r["platform"] for r in body["results"]] == PLATFORM_NAMES

    for result in body["results"]:
        assert result["status"] == "simulated"
        assert result["posted_url"] is None
        assert result["public_access"] is False
        assert result["date"] is None and result["time"] is None
        assert result["error"] is None
        assert "SIMULATED" in result["note"]


def test_demo_mode_makes_no_network_calls(client: TestClient, router: respx.MockRouter) -> None:
    assert post(client, VALID_MESSAGE).status_code == 200
    assert len(router.calls) == 0


def test_request_with_extra_platform_field_is_ignored(client: TestClient) -> None:
    response = client.post("/posting", json={"message": VALID_MESSAGE, "platforms": ["bluesky"]})

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 5


# --------------------------------------------------------------------------- #
# Live mode (HTTP mocked)
# --------------------------------------------------------------------------- #
def test_live_mode_success(live_client: TestClient, router: respx.MockRouter) -> None:
    mock_all(router)

    body = post(live_client, VALID_MESSAGE).json()

    assert body["success"] is True and body["mode"] == "live"
    assert body["summary"] == {"total": 5, "succeeded": 5, "simulated": 0, "failed": 0}
    for result in body["results"]:
        assert result["status"] == "success"
        assert result["posted_url"].startswith("https://")
        assert result["public_access"] is True
        assert len(result["date"]) == 10 and len(result["time"]) == 8  # YYYY-MM-DD / HH:MM:SS


def test_live_mode_one_platform_fails_others_succeed(live_client: TestClient, router: respx.MockRouter) -> None:
    mock_all(router, devto="auth")

    body = post(live_client, VALID_MESSAGE).json()

    assert body["success"] is True
    assert body["summary"] == {"total": 5, "succeeded": 4, "simulated": 0, "failed": 1}
    devto = next(r for r in body["results"] if r["platform"] == "DEV.to")
    assert devto["status"] == "failed"
    assert devto["error"] == "Authentication failed: Invalid credentials"
    assert devto["posted_url"] is None and devto["public_access"] is False


def test_live_mode_all_fail_is_unsuccessful_but_still_http_200(live_client: TestClient, router: respx.MockRouter) -> None:
    mock_all(router, bluesky="auth", mastodon="auth", devto="auth", hashnode="auth", wordpress="auth")

    response = post(live_client, VALID_MESSAGE)

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["summary"]["failed"] == 5


def test_live_mode_slow_platform_is_stopped_by_asyncio_timeout(
    live_client: TestClient, router: respx.MockRouter
) -> None:
    import asyncio

    mock_all(router)

    async def hang(request):  # noqa: ANN001
        await asyncio.sleep(30)

    router.post("https://dev.to/api/articles").mock(side_effect=hang)

    body = post(live_client, VALID_MESSAGE).json()

    devto = next(r for r in body["results"] if r["platform"] == "DEV.to")
    assert devto["status"] == "failed"
    assert devto["error"] == "DEV.to did not respond within 0.5 seconds"
    assert body["summary"]["succeeded"] == 4


# --------------------------------------------------------------------------- #
# Scenario 4: invalid input
# --------------------------------------------------------------------------- #
def test_message_of_exactly_200_characters_is_accepted(client: TestClient) -> None:
    assert post(client, message_of_length(MAX_MESSAGE_LENGTH)).status_code == 200


@pytest.mark.parametrize(
    ("message", "expected_message"),
    [
        (message_of_length(MAX_MESSAGE_LENGTH + 1), "Message must not exceed 200 characters (received 201)"),
        ("", "Message must not be empty"),
        ("    ", "Message must not be empty"),
        ("Visit https://example.com and https://example.org", "exactly one URL, but 2 were found"),
        ("https://example.com again https://example.com", "exactly one URL, but 2 were found"),
        ("No link in this message", "none was found"),
        ("Download ftp://example.com/file", "not allowed"),
        ("Visit www.example.com", "must start with http"),
        ("Visit http://localhost:8000", "localhost"),
        ("Visit https://example", "invalid host name"),
        ("Visit https://user:pass@example.com", "credentials"),
    ],
)
def test_invalid_messages_return_422(client: TestClient, message: str, expected_message: str) -> None:
    response = post(client, message)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "Validation failed"
    assert body["details"][0]["field"] == "message"
    assert expected_message in body["details"][0]["message"]


def test_missing_message_field(client: TestClient) -> None:
    response = client.post("/posting", json={})

    assert response.status_code == 422
    assert response.json()["details"] == [{"field": "message", "message": "Field required"}]


def test_non_string_message(client: TestClient) -> None:
    response = client.post("/posting", json={"message": 12345})

    assert response.status_code == 422
    assert "valid string" in response.json()["details"][0]["message"]


def test_malformed_json_body(client: TestClient) -> None:
    response = client.post("/posting", content="{not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.json()["details"] == [{"field": "body", "message": "Request body must be valid JSON"}]


def test_validation_failure_never_calls_any_platform(live_client: TestClient, router: respx.MockRouter) -> None:
    body = post(live_client, "no url here").json()

    assert "results" not in body
    assert body["success"] is False
    assert len(router.calls) == 0
