"""Message validation (PostRequest schema): empty, length, URL rules."""

import pytest
from pydantic import ValidationError

from app.schemas import MAX_MESSAGE_LENGTH, PostRequest
from tests.helpers import VALID_MESSAGE, VALID_URL, message_of_length


def test_valid_message_is_accepted() -> None:
    request = PostRequest(message=VALID_MESSAGE)
    assert request.message == VALID_MESSAGE
    assert request.cta_url == VALID_URL


def test_surrounding_whitespace_is_trimmed() -> None:
    request = PostRequest(message=f"   Hello {VALID_URL}  \n")
    assert request.message == f"Hello {VALID_URL}"


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_empty_message_is_rejected(message: str) -> None:
    with pytest.raises(ValidationError, match="Message must not be empty"):
        PostRequest(message=message)


def test_message_of_exactly_200_characters_is_accepted() -> None:
    message = message_of_length(MAX_MESSAGE_LENGTH)
    assert len(PostRequest(message=message).message) == 200


def test_message_of_201_characters_is_rejected() -> None:
    with pytest.raises(ValidationError, match=r"must not exceed 200 characters \(received 201\)"):
        PostRequest(message=message_of_length(MAX_MESSAGE_LENGTH + 1))


def test_length_is_checked_after_trimming_whitespace() -> None:
    padded = message_of_length(MAX_MESSAGE_LENGTH) + " " * 50
    assert len(PostRequest(message=padded).message) == 200


def test_message_without_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="none was found"):
        PostRequest(message="Great offer, but I forgot the link")


def test_message_with_multiple_urls_is_rejected() -> None:
    with pytest.raises(ValidationError, match="but 2 were found"):
        PostRequest(message="Visit https://example.com and https://example.org")


def test_message_with_invalid_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid host name"):
        PostRequest(message="Visit https://not_a_domain")


def test_non_string_message_is_rejected() -> None:
    with pytest.raises(ValidationError, match="valid string"):
        PostRequest(message=12345)  # type: ignore[arg-type]


def test_missing_message_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        PostRequest()  # type: ignore[call-arg]


def test_url_only_message_is_valid() -> None:
    assert PostRequest(message=VALID_URL).cta_url == VALID_URL
