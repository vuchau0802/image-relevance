from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import CurrentWorkspace
from app.services.auth import AuthenticatedUser, require_user


@pytest.fixture
def workspace_dependency_api(monkeypatch):
    application = FastAPI()

    @application.get("/probe")
    def probe(workspace_id: CurrentWorkspace):
        return {"workspace_id": workspace_id}

    identity = AuthenticatedUser(
        issuer="https://test-instance.clerk.accounts.dev",
        user_id="user_first",
        session_id="sess_first",
    )
    application.dependency_overrides[require_user] = lambda: identity

    repository = Mock(return_value="ws_first")
    monkeypatch.setattr(
        dependencies,
        "get_or_create_workspace",
        repository,
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            identity=identity,
            repository=repository,
        )


def test_workspace_resolves_from_verified_identity(
    workspace_dependency_api,
):
    ctx = workspace_dependency_api

    response = ctx.client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws_first"}
    ctx.repository.assert_called_once_with(
        auth_issuer=ctx.identity.issuer,
        auth_user_id=ctx.identity.user_id,
    )


def test_client_cannot_select_another_workspace(
    workspace_dependency_api,
):
    ctx = workspace_dependency_api

    response = ctx.client.get(
        "/probe?workspace_id=ws_other&tenant_id=demo",
        headers={"X-Tenant-ID": "ws_other"},
    )

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws_first"}
    ctx.repository.assert_called_once_with(
        auth_issuer=ctx.identity.issuer,
        auth_user_id=ctx.identity.user_id,
    )


def test_missing_authentication_stops_workspace_resolution(
    workspace_dependency_api,
):
    ctx = workspace_dependency_api
    del ctx.app.dependency_overrides[require_user]

    response = ctx.client.get(
        "/probe",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    ctx.repository.assert_not_called()


def test_changed_account_resolves_its_own_workspace(
    workspace_dependency_api,
):
    ctx = workspace_dependency_api

    first = ctx.client.get("/probe")
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

    second = ctx.client.get("/probe")

    assert second.status_code == 200
    assert second.json() == {"workspace_id": "ws_second"}
    ctx.repository.assert_called_with(
        auth_issuer=second_identity.issuer,
        auth_user_id="user_second",
    )