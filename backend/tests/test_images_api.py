import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage

from app.api import images
from app.api.dependencies import require_workspace
from app.main import create_app
from app.services import image_files


@pytest.fixture
def image_api(monkeypatch, tmp_path):
    application = create_app(frontend_dir=tmp_path / "frontend")
    application.dependency_overrides[require_workspace] = lambda: "ws_test"
    folder = tmp_path / "data" / "images"
    folder.mkdir(parents=True)

    path = folder / "sample.jpg"
    PillowImage.new("RGB", (8, 8), "blue").save(path)

    record = SimpleNamespace(
        id="img_test",
        creator="Test Photographer",
        source_url="https://example.com/photo",
        license_url="https://example.com/license",
        file_path="data/images/sample.jpg",
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
    )

    session = MagicMock()
    session.get.side_effect = (
        lambda model, key:
        record if key == ("ws_test", "img_test") else None
    )

    session_context = MagicMock()
    session_context.__enter__.return_value = session

    monkeypatch.setattr(
        images, "SessionLocal", lambda: session_context
    )
    monkeypatch.setattr(image_files, "PROJECT_ROOT", tmp_path)

    with TestClient(application) as client:
        yield client, record, path, session


def test_registered_image_is_served(image_api):
    client, _, path, _ = image_api

    response = client.get(
        "/images/img_test/file",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_different_workspace_cannot_read_image(image_api):
    client, _, _, session = image_api
    client.app.dependency_overrides[require_workspace] = lambda: "ws_other"

    response = client.get(
        "/images/img_test/file",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 404
    session.get.assert_called_once_with(
        images.Image, ("ws_other", "img_test")
    )


def test_unknown_image_returns_404(image_api):
    client, _, _, _ = image_api

    response = client.get(
        "/images/unknown/file",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 404


def test_missing_authentication_returns_401(image_api):
    client, _, _, session = image_api
    del client.app.dependency_overrides[require_workspace]

    response = client.get("/images/img_test/file")

    assert response.status_code == 401
    session.get.assert_not_called()


def test_forged_tenant_header_does_not_change_workspace(image_api):
    client, _, _, session = image_api

    response = client.get(
        "/images/img_test/file",
        headers={"X-Tenant-ID": "ws_someone_else"},
    )

    assert response.status_code == 200
    session.get.assert_called_once_with(
        images.Image, ("ws_test", "img_test")
    )


@pytest.mark.parametrize(
    "problem", ["missing", "checksum", "outside_corpus"]
)
def test_invalid_registered_file_is_not_served(image_api, problem):
    client, record, path, _ = image_api

    if problem == "missing":
        path.unlink()
    elif problem == "checksum":
        path.write_bytes(b"Changed file contents")
    else:
        outside = path.parents[2] / "outside.jpg"
        outside.write_bytes(path.read_bytes())
        record.file_path = "outside.jpg"

    response = client.get(
        "/images/img_test/file",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Image file unavailable"}


def test_image_attribution_is_returned(image_api):
    client, _, _, _ = image_api

    response = client.get(
        "/images/img_test/attribution",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "image_id": "img_test",
        "creator": "Test Photographer",
        "source_url": "https://example.com/photo",
        "license_url": "https://example.com/license",
    }


def test_attribution_is_workspace_scoped(image_api):
    client, _, _, session = image_api
    client.app.dependency_overrides[require_workspace] = lambda: "ws_other"

    response = client.get(
        "/images/img_test/attribution",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}
    session.get.assert_called_once_with(
        images.Image, ("ws_other", "img_test")
    )


def test_unknown_attribution_returns_404(image_api):
    client, _, _, _ = image_api

    response = client.get(
        "/images/unknown/attribution",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("tenant", [None, "demo"])
def test_attribution_requires_authentication(image_api, tenant):
    client, _, _, session = image_api
    del client.app.dependency_overrides[require_workspace]
    headers = {} if tenant is None else {"X-Tenant-ID": tenant}

    response = client.get(
        "/images/img_test/attribution",
        headers=headers,
    )

    assert response.status_code == 401
    session.get.assert_not_called()
