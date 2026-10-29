from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import posts
from app.api.dependencies import require_workspace
from app.main import create_app
from app.repositories.posts import PostBusyError, PostNotFoundError


@pytest.fixture(params=["", "/api"])
def deletion_api(request, monkeypatch, tmp_path):
    deletion = Mock()
    monkeypatch.setattr(posts, "delete_post", deletion)

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            prefix=request.param,
            path=f"{request.param}/posts/post_test",
            deletion=deletion,
        )


def test_successful_deletion_returns_empty_204(deletion_api):
    ctx = deletion_api

    response = ctx.client.delete(ctx.path)

    assert response.status_code == 204
    assert response.content == b""
    ctx.deletion.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="post_test",
    )


def test_missing_or_unowned_post_returns_404(deletion_api):
    ctx = deletion_api
    ctx.deletion.side_effect = PostNotFoundError()

    response = ctx.client.delete(ctx.path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}


def test_active_preparation_returns_409(deletion_api):
    ctx = deletion_api
    message = (
        "Post preparation is queued or processing. "
        "Wait for it to finish before deleting."
    )
    ctx.deletion.side_effect = PostBusyError(message)

    response = ctx.client.delete(ctx.path)

    assert response.status_code == 409
    assert response.json() == {"detail": message}


def test_deletion_requires_sign_in(deletion_api):
    ctx = deletion_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.delete(
        ctx.path,
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 401
    ctx.deletion.assert_not_called()


def test_caller_cannot_override_workspace(deletion_api):
    ctx = deletion_api

    response = ctx.client.delete(
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        params={"tenant_id": "ws_other"},
    )

    assert response.status_code == 204
    ctx.deletion.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="post_test",
    )


def test_overlong_post_id_is_rejected(deletion_api):
    ctx = deletion_api

    response = ctx.client.delete(
        f"{ctx.prefix}/posts/{'x' * 51}"
    )

    assert response.status_code == 422
    ctx.deletion.assert_not_called()