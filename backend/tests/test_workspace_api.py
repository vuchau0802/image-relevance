from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import create_app
from app.services.auth import AuthenticatedUser, require_user


@pytest.fixture
def workspace_api(monkeypatch, tmp_path):
    application = create_app(frontend_dir=tmp_path)
    identity = AuthenticatedUser(
        issuer="https://test-instance.clerk.accounts.dev",
        user_id="user_first",
        session_id="sess_first",
    )

    application.dependency_overrides[require_user] = lambda: identity

    repository = Mock(return_value="ws_first")
    monkeypatch.setattr(
        auth_api, "get_or_create_workspace", repository
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            identity=identity,
            repository=repository,
        )


def test_workspace_uses_verified_account(workspace_api):
    ctx = workspace_api

    response = ctx.client.post("/api/workspace")

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws_first"}
    ctx.repository.assert_called_once_with(
        auth_issuer=ctx.identity.issuer,
        auth_user_id="user_first",
    )


def test_forged_tenant_header_cannot_select_workspace(workspace_api):
    ctx = workspace_api

    response = ctx.client.post(
        "/api/workspace",
        headers={"X-Tenant-ID": "another-users-workspace"},
    )

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws_first"}
    ctx.repository.assert_called_once_with(
        auth_issuer=ctx.identity.issuer,
        auth_user_id="user_first",
    )


def test_missing_authentication_does_not_create_workspace(workspace_api):
    ctx = workspace_api
    del ctx.app.dependency_overrides[require_user]

    response = ctx.client.post("/api/workspace")

    assert response.status_code == 401
    ctx.repository.assert_not_called()


def test_account_switch_uses_new_verified_owner(workspace_api):
    ctx = workspace_api

    first = ctx.client.post("/api/workspace")
    assert first.json() == {"workspace_id": "ws_first"}

    second_identity = AuthenticatedUser(
        issuer=ctx.identity.issuer,
        user_id="user_second",
        session_id="sess_second",
    )
    ctx.app.dependency_overrides[require_user] = (
        lambda: second_identity
    )
    ctx.repository.return_value = "ws_second"

    second = ctx.client.post("/api/workspace")

    assert second.status_code == 200
    assert second.json() == {"workspace_id": "ws_second"}
    ctx.repository.assert_called_with(
        auth_issuer=second_identity.issuer,
        auth_user_id="user_second",
    )