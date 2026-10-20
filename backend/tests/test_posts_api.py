from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import posts
from app.main import app
from app.schemas.post import PostListResponse, PostSummary


@pytest.fixture
def posts_api(monkeypatch):
    listing = Mock(return_value=PostListResponse(
        items=[],
        next_offset=None,
    ))
    monkeypatch.setattr(posts, "list_posts", listing)

    with TestClient(app) as client:
        yield client, listing


def test_posts_and_pagination_are_returned(posts_api):
    client, listing = posts_api
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

    response = client.get(
        "/posts?offset=2&limit=1",
        headers={"X-Tenant-ID": "demo"},
    )

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
        tenant_id="demo", offset=2, limit=1
    )


def test_empty_list_uses_requested_tenant(posts_api):
    client, listing = posts_api

    response = client.get(
        "/posts",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "next_offset": None,
    }
    listing.assert_called_once_with(
        tenant_id="different-tenant", offset=0, limit=50
    )


@pytest.mark.parametrize("tenant", [None, "   "])
def test_nonblank_tenant_is_required(posts_api, tenant):
    client, listing = posts_api
    headers = {} if tenant is None else {"X-Tenant-ID": tenant}

    response = client.get("/posts", headers=headers)

    assert response.status_code == 422
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
    client, listing = posts_api

    response = client.get(
        f"/posts?{query}",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 422
    listing.assert_not_called()