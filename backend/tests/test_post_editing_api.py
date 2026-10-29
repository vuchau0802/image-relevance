from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import posts
from app.api.dependencies import require_workspace
from app.main import create_app
from app.repositories.posts import PostNotFoundError
from app.schemas.post import PostInput, PostUpdate


def payload():
    return {
        "title": "Forest article",
        "content": "A walk through a green forest.",
        "required_subject": "forest",
    }


@pytest.fixture(params=["", "/api"])
def editing_api(request, monkeypatch, tmp_path):
    stored = PostInput(id="post_test", **payload())
    reader = Mock(return_value=stored)
    writer = Mock(
        side_effect=lambda **kwargs: PostInput(
            id=kwargs["post_id"],
            **kwargs["payload"].model_dump(),
        )
    )

    monkeypatch.setattr(posts, "get_post", reader)
    monkeypatch.setattr(posts, "update_post", writer)

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            path=f"{request.param}/posts/post_test",
            reader=reader,
            writer=writer,
            stored=stored,
        )


def test_reads_owned_post(editing_api):
    ctx = editing_api

    response = ctx.client.get(ctx.path)

    assert response.status_code == 200
    assert response.json() == ctx.stored.model_dump()
    ctx.reader.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="post_test",
    )


def test_updates_post_with_validated_fields(editing_api):
    ctx = editing_api
    submitted = {
        field: f"  {value}  "
        for field, value in payload().items()
    }

    response = ctx.client.put(ctx.path, json=submitted)

    assert response.status_code == 200
    assert response.json() == {
        "id": "post_test",
        **payload(),
    }
    ctx.writer.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="post_test",
        payload=PostUpdate(**payload()),
    )


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_missing_or_unowned_post_returns_404(editing_api, method):
    ctx = editing_api
    ctx.reader.side_effect = PostNotFoundError()
    ctx.writer.side_effect = PostNotFoundError()

    response = ctx.client.request(
        method,
        ctx.path,
        **({"json": payload()} if method == "PUT" else {}),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_editing_requires_sign_in(editing_api, method):
    ctx = editing_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.request(
        method,
        ctx.path,
        headers={"X-Tenant-ID": "demo"},
        **({"json": payload()} if method == "PUT" else {}),
    )

    assert response.status_code == 401
    ctx.reader.assert_not_called()
    ctx.writer.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_caller_cannot_override_workspace(editing_api, method):
    ctx = editing_api

    response = ctx.client.request(
        method,
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        params={"tenant_id": "ws_other"},
        **({"json": payload()} if method == "PUT" else {}),
    )

    assert response.status_code == 200
    target = ctx.writer if method == "PUT" else ctx.reader
    assert target.call_args.kwargs["tenant_id"] == "ws_owner"


@pytest.mark.parametrize(
    "case",
    [
        "blank-title",
        "blank-content",
        "blank-subject",
        "missing-content",
        "supplied-id",
        "supplied-tenant",
    ],
)
def test_invalid_update_is_rejected(editing_api, case):
    ctx = editing_api
    submitted = payload()

    if case == "blank-title":
        submitted["title"] = "   "
    elif case == "blank-content":
        submitted["content"] = "   "
    elif case == "blank-subject":
        submitted["required_subject"] = "   "
    elif case == "missing-content":
        submitted.pop("content")
    elif case == "supplied-id":
        submitted["id"] = "replacement-id"
    else:
        submitted["tenant_id"] = "ws_other"

    response = ctx.client.put(ctx.path, json=submitted)

    assert response.status_code == 422
    ctx.writer.assert_not_called()