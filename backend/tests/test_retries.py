from unittest.mock import Mock
import httpx
import pytest

from app.services.retries import is_retryable
from app.schemas.image import ImageMetadata
from app.services.retries import run_with_retries


class FakeAPIError(Exception):
    def __init__(self, status_code):
        super().__init__("Simulated API error")
        self.status_code = status_code


def test_temporary_failure_then_success():
    operation = Mock(
        side_effect=[FakeAPIError(503), "success"]
    )

    result = run_with_retries(operation, base_delay=0)

    assert result == "success"
    assert operation.call_count == 2


def test_stops_after_three_attempts():
    operation = Mock(side_effect=FakeAPIError(503))

    with pytest.raises(FakeAPIError):
        run_with_retries(operation, base_delay=0)

    assert operation.call_count == 3


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_permanent_errors_are_not_retried(status_code):
    operation = Mock(side_effect=FakeAPIError(status_code))

    with pytest.raises(FakeAPIError):
        run_with_retries(operation, base_delay=0)

    assert operation.call_count == 1


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectError, httpx.ReadTimeout],
)
def test_sdk_connection_errors_are_retryable(error_type):
    request = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/",
    )

    error = error_type("Simulated transport failure", request=request)

    assert is_retryable(error)

def test_invalid_model_output_then_valid_output():
    responses = iter([
        '{"subject": "red fox"}',
        """
        {
            "subject": "red fox",
            "category": "animal",
            "attributes": ["orange fur"],
            "caption": "A red fox",
            "confidence": 0.94
        }
        """,
    ])

    operation = Mock(
        side_effect=lambda: ImageMetadata.model_validate_json(
            next(responses)
        )
    )

    result = run_with_retries(operation, base_delay=0)

    assert result.subject == "red fox"
    assert operation.call_count == 2
