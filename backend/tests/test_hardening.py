import hashlib

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import ValidationError

from app.schemas.image import ImageMetadata
from app.services import image_files
from app.services.retries import is_retryable


def valid_metadata():
    return dict(subject="red fox", category="animal", attributes=["orange fur"], caption="A fox outdoors", confidence=0.9)


@pytest.mark.parametrize("changes", [
    {"attributes": []}, {"attributes": [""]}, {"attributes": ["   "]},
    {"attributes": ["x"] * 21}, {"attributes": ["x" * 201]},
    {"subject": "x" * 201}, {"caption": "x" * 2001},
])
def test_metadata_rejects_empty_or_unbounded_output(changes):
    with pytest.raises(ValidationError):
        ImageMetadata(**(valid_metadata() | changes))


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_installed_sdk_wrapped_transport_error_is_retryable_without_hidden_retry(error_type):
    requests = []

    def fail(request):
        requests.append(request)
        raise error_type("test transport failure", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as transport:
        with genai.Client(
            api_key="unused-test-key",
            http_options=types.HttpOptions(
                httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=0),
            ),
        ) as client:
            with pytest.raises(Exception) as caught:
                client.interactions.create(
                    model="gemini-3.5-flash-lite",
                    input=[{"type": "text", "text": "test"}],
                )
    assert len(requests) == 1
    assert is_retryable(caught.value)


def test_permanent_status_takes_precedence_over_transport_cause():
    error = Exception("permanent request error")
    error.status_code = 400
    error.__cause__ = httpx.ConnectError("earlier failure")
    assert not is_retryable(error)


def test_retry_detection_handles_cyclic_causes():
    error = Exception("cycle")
    error.__cause__ = error
    assert not is_retryable(error)


def test_registered_image_verification_rejects_escape_and_changed_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(image_files, "PROJECT_ROOT", tmp_path)
    corpus = tmp_path / "data" / "images"
    corpus.mkdir(parents=True)
    image = corpus / "image.jpg"
    image.write_bytes(b"original")
    digest = hashlib.sha256(b"original").hexdigest()
    assert image_files.verify_registered_image("data/images/image.jpg", digest) == image
    with pytest.raises(ValueError, match="outside"):
        image_files.verify_registered_image("../outside.jpg", digest)
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        image_files.verify_registered_image("data/images/image.jpg", digest)
