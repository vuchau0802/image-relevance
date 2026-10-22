from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import posts
from app.api.dependencies import require_workspace
from app.main import create_app
from app.schemas.post import PostInput


@pytest.fixture
def creation_api(monkeypatch, tmp_path):
    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    def fake_create(tenant_id, payload):
        return PostInput(
            id="post_server_generated",
            **payload.model_dump(),
        )

    repository = Mock(side_effect=fake_create)
    monkeypatch.setattr(posts, "create_post", repository)

    payload = {
        "title": "  My first post  ",
        "content": "  A post about urban red foxes.  ",
        "required_subject": "  red fox  ",
    }

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            repository=repository,
            payload=payload,
        )


def test_valid_post_uses_authenticated_workspace(creation_api):
    ctx = creation_api

    response = ctx.client.post("/api/posts", json=ctx.payload)

    assert response.status_code == 201
    assert response.json() == {
        "id": "post_server_generated",
        "title": "My first post",
        "content": "A post about urban red foxes.",
        "required_subject": "red fox",
    }

    ctx.repository.assert_called_once()
    arguments = ctx.repository.call_args.kwargs

    assert arguments["tenant_id"] == "ws_owner"
    assert arguments["payload"].model_dump() == {
        "title": "My first post",
        "content": "A post about urban red foxes.",
        "required_subject": "red fox",
    }


def test_forged_header_cannot_change_post_owner(creation_api):
    ctx = creation_api

    response = ctx.client.post(
        "/api/posts",
        json=ctx.payload,
        headers={"X-Tenant-ID": "ws_someone_else"},
    )

    assert response.status_code == 201
    ctx.repository.assert_called_once()
    assert (
        ctx.repository.call_args.kwargs["tenant_id"]
        == "ws_owner"
    )


@pytest.mark.parametrize("tenant", [None, "demo"])
def test_post_creation_requires_authentication(creation_api, tenant):
    ctx = creation_api
    del ctx.app.dependency_overrides[require_workspace]

    headers = {} if tenant is None else {"X-Tenant-ID": tenant}
    response = ctx.client.post(
        "/api/posts",
        json=ctx.payload,
        headers=headers,
    )

    assert response.status_code == 401
    ctx.repository.assert_not_called()


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"title": "   "},
        {"content": ""},
        {"required_subject": "   "},
        {"title": "x" * 301},
        {"content": "x" * 10001},
        {"required_subject": "x" * 201},
        {"tenant_id": "ws_someone_else"},
        {"auth_user_id": "user_someone_else"},
        {"id": "client_chosen_id"},
    ],
    ids=[
        "blank-title",
        "blank-content",
        "blank-subject",
        "long-title",
        "long-content",
        "long-subject",
        "client-workspace",
        "client-owner",
        "client-post-id",
    ],
)
def test_invalid_post_is_rejected(creation_api, invalid_fields):
    ctx = creation_api
    payload = {**ctx.payload, **invalid_fields}

    response = ctx.client.post("/api/posts", json=payload)

    assert response.status_code == 422
    ctx.repository.assert_not_called()