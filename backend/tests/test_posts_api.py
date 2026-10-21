from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import posts
from app.api.dependencies import require_workspace
from app.main import create_app
from app.schemas.post import PostListResponse, PostSummary


@pytest.fixture
def posts_api(monkeypatch, tmp_path):
    application = create_app(frontend_dir=tmp_path)

    # Explicitly simulate authenticated workspace resolution for these tests.
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_test"
    )

    listing = Mock(return_value=PostListResponse(
        items=[],
        next_offset=None,
    ))
    monkeypatch.setattr(posts, "list_posts", listing)

    with TestClient(application) as client:
        yield client, listing, application


def test_posts_use_verified_workspace(posts_api):
    client, listing, _ = posts_api

    listing.return_value = PostListResponse(
        items=[
            PostSummary(
                id="post_test",
                title="A test post",
                required_subject="red fox",
            )
        ],
        next_offset=3,
    )

    response = client.get("/posts?offset=2&limit=1")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{
            "id": "post_test",
            "title": "A test post",
            "required_subject": "red fox",
        }],
        "next_offset": 3,
    }
    listing.assert_called_once_with(
        tenant_id="ws_test", offset=2, limit=1
    )


def test_forged_header_cannot_change_workspace(posts_api):
    client, listing, _ = posts_api

    response = client.get(
        "/posts",
        headers={"X-Tenant-ID": "another-workspace"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "next_offset": None,
    }
    listing.assert_called_once_with(
        tenant_id="ws_test", offset=0, limit=50
    )


@pytest.mark.parametrize("tenant", [None, "demo"])
def test_authentication_is_required(posts_api, tenant):
    client, listing, application = posts_api
    del application.dependency_overrides[require_workspace]

    headers = {} if tenant is None else {"X-Tenant-ID": tenant}
    response = client.get("/posts", headers=headers)

    assert response.status_code == 401
    listing.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        "offset=-1",
        "limit=0",
        "limit=101",
        "offset=invalid",
    ],
)
def test_invalid_pagination_is_rejected(posts_api, query):
    client, listing, _ = posts_api

    response = client.get(f"/posts?{query}")

    assert response.status_code == 422
    listing.assert_not_called()