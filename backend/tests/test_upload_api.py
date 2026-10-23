from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import images, upload_limits
from app.api.dependencies import require_workspace
from app.main import create_app
from app.schemas.upload import ImageUploadResponse
from app.services.upload_validation import InvalidImageUploadError


@pytest.fixture(params=["", "/api"])
def upload_api(request, monkeypatch, tmp_path):
    service = Mock(
        return_value=ImageUploadResponse(
            image_id="img_test",
            status="pending",
        )
    )
    monkeypatch.setattr(images, "create_uploaded_image", service)

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_" + "a" * 32
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            path=f"{request.param}/images",
            service=service,
            tenant="ws_" + "a" * 32,
        )


def test_upload_passes_file_and_creator_to_service(upload_api):
    ctx = upload_api

    response = ctx.client.post(
        ctx.path,
        data={"creator": "  Example creator  "},
        files={"file": ("photo.jpg", b"test-image", "image/jpeg")},
    )

    assert response.status_code == 201
    assert response.json() == {
        "image_id": "img_test",
        "status": "pending",
    }
    ctx.service.assert_called_once_with(
        tenant_id=ctx.tenant,
        data=b"test-image",
        creator="Example creator",
    )


def test_upload_requires_sign_in(upload_api):
    ctx = upload_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "demo"},
        data={"creator": "Example creator"},
        files={"file": ("photo.jpg", b"test-image", "image/jpeg")},
    )

    assert response.status_code == 401
    ctx.service.assert_not_called()


@pytest.mark.parametrize("creator", ["", "   ", "x" * 201])
def test_invalid_creator_is_rejected(upload_api, creator):
    ctx = upload_api

    response = ctx.client.post(
        ctx.path,
        data={"creator": creator},
        files={"file": ("photo.jpg", b"test-image", "image/jpeg")},
    )

    assert response.status_code == 422
    ctx.service.assert_not_called()


def test_invalid_image_returns_validation_error(upload_api):
    ctx = upload_api
    ctx.service.side_effect = InvalidImageUploadError(
        "Upload a valid, readable JPEG image."
    )

    response = ctx.client.post(
        ctx.path,
        data={"creator": "Example creator"},
        files={"file": ("photo.jpg", b"invalid", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Upload a valid, readable JPEG image."
    }


def test_file_byte_limit_is_enforced(upload_api, monkeypatch):
    ctx = upload_api
    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 4)

    response = ctx.client.post(
        ctx.path,
        data={"creator": "Example creator"},
        files={"file": ("photo.jpg", b"12345", "image/jpeg")},
    )

    assert response.status_code == 413
    ctx.service.assert_not_called()


def test_declared_request_size_is_rejected(upload_api, monkeypatch):
    ctx = upload_api
    monkeypatch.setattr(
        upload_limits, "MAX_UPLOAD_REQUEST_BYTES", 128
    )

    response = ctx.client.post(
        ctx.path,
        content=b"",
        headers={"Content-Length": "129"},
    )

    assert response.status_code == 413
    ctx.service.assert_not_called()


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_actual_stream_size_is_checked(
    upload_api, monkeypatch, declared_length
):
    ctx = upload_api
    monkeypatch.setattr(
        upload_limits, "MAX_UPLOAD_REQUEST_BYTES", 512
    )

    body = (
        b"--upload-test\r\n"
        b'Content-Disposition: form-data; name="creator"\r\n'
        b"\r\nExample creator\r\n"
        b"--upload-test\r\n"
        b'Content-Disposition: form-data; name="file"; '
        b'filename="photo.jpg"\r\n'
        b"Content-Type: image/jpeg\r\n\r\n"
        + b"x" * 600
        + b"\r\n--upload-test--\r\n"
    )
    headers = {
        "Content-Type": "multipart/form-data; boundary=upload-test"
    }
    if declared_length is not None:
        headers["Content-Length"] = declared_length

    response = ctx.client.post(
        ctx.path,
        content=iter([body[:100], body[100:]]),
        headers=headers,
    )

    assert response.status_code == 413
    ctx.service.assert_not_called()


def test_client_cannot_override_workspace(upload_api):
    ctx = upload_api

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        data={
            "creator": "Example creator",
            "tenant_id": "ws_other",
        },
        files={"file": ("photo.jpg", b"test-image", "image/jpeg")},
    )

    assert response.status_code == 201
    assert ctx.service.call_args.kwargs["tenant_id"] == ctx.tenant