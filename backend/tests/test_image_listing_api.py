from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import images
from app.api.dependencies import require_workspace
from app.main import create_app
from app.schemas.image import ImageListItem, ImageListResponse


@pytest.fixture(params=["", "/api"])
def listing_api(request, monkeypatch, tmp_path):
    listing = Mock(return_value=ImageListResponse(
        items=[
            ImageListItem(
                image_id="img_test",
                status="completed",
                creator="Example creator",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ],
        next_offset=None,
    ))
    monkeypatch.setattr(images, "list_images", listing)

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            path=f"{request.param}/images",
            listing=listing,
        )


def test_returns_images_and_forwards_pagination(listing_api):
    ctx = listing_api

    response = ctx.client.get(
        ctx.path,
        params={"offset": 4, "limit": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["next_offset"] is None
    assert body["items"][0]["image_id"] == "img_test"
    assert body["items"][0]["embedding_ready"] is False
    assert body["items"][0]["failed_analysis_job_id"] is None
    assert set(body["items"][0]) == {
        "image_id", "status", "creator", "created_at", "embedding_ready",
        "failed_analysis_job_id",
    }
    ctx.listing.assert_called_once_with(
        tenant_id="ws_owner",
        offset=4,
        limit=2,
    )


def test_empty_workspace_returns_empty_page(listing_api):
    ctx = listing_api
    ctx.listing.return_value = ImageListResponse(
        items=[], next_offset=None
    )

    response = ctx.client.get(ctx.path)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "next_offset": None,
    }


def test_listing_requires_sign_in(listing_api):
    ctx = listing_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.get(
        ctx.path,
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 401
    ctx.listing.assert_not_called()


def test_caller_cannot_override_workspace(listing_api):
    ctx = listing_api

    response = ctx.client.get(
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        params={"tenant_id": "ws_other"},
    )

    assert response.status_code == 200
    ctx.listing.assert_called_once_with(
        tenant_id="ws_owner",
        offset=0,
        limit=50,
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"offset": -1},
        {"limit": 101},
    ],
)
def test_invalid_pagination_returns_422(listing_api, parameters):
    ctx = listing_api

    response = ctx.client.get(ctx.path, params=parameters)

    assert response.status_code == 422
    ctx.listing.assert_not_called()