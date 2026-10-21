import time
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

from app.main import create_app
from app.services import auth


@pytest.fixture(scope="module")
def signing_keys():
    return (
        rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        ),
        rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        ),
    )


@pytest.fixture
def auth_api(monkeypatch, tmp_path, signing_keys):
    private_key, other_key = signing_keys

    settings = SimpleNamespace(
        clerk_issuer="https://test-instance.clerk.accounts.dev",
        clerk_authorized_parties=["http://127.0.0.1:8000"],
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(
        key=private_key.public_key()
    )
    monkeypatch.setattr(
        auth, "get_jwks_client", Mock(return_value=jwks)
    )

    def claims():
        now = int(time.time())
        return {
            "iss": settings.clerk_issuer,
            "sub": "user_test",
            "sid": "sess_test",
            "iat": now - 5,
            "nbf": now - 5,
            "exp": now + 60,
            "azp": "http://127.0.0.1:8000",
        }

    def sign(payload, key=None):
        return jwt.encode(
            payload,
            private_key if key is None else key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    with TestClient(create_app(frontend_dir=tmp_path)) as client:
        yield SimpleNamespace(
            client=client,
            settings=settings,
            jwks=jwks,
            claims=claims,
            sign=sign,
            other_key=other_key,
        )


def request_me(ctx, token):
    return ctx.client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_valid_signed_session_returns_user(auth_api):
    response = request_me(auth_api, auth_api.sign(auth_api.claims()))

    assert response.status_code == 200
    assert response.json() == {"user_id": "user_test"}


def test_missing_token_returns_401_without_key_lookup(auth_api):
    response = auth_api.client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    auth_api.jwks.get_signing_key_from_jwt.assert_not_called()


def test_malformed_token_returns_generic_401(auth_api):
    response = request_me(auth_api, "invalid-token")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "A valid sign-in session is required"
    }
    auth_api.jwks.get_signing_key_from_jwt.assert_not_called()


def test_wrong_signature_is_rejected(auth_api):
    token = auth_api.sign(
        auth_api.claims(),
        key=auth_api.other_key,
    )

    assert request_me(auth_api, token).status_code == 401


@pytest.mark.parametrize(
    "problem",
    [
        "expired",
        "not_yet_valid",
        "future_issued",
        "wrong_issuer",
        "wrong_origin",
        "pending_session",
        "missing_expiration",
    ],
)
def test_invalid_session_claims_are_rejected(auth_api, problem):
    claims = auth_api.claims()
    now = int(time.time())

    if problem == "expired":
        claims["exp"] = now - 60
    elif problem == "not_yet_valid":
        claims["nbf"] = now + 60
    elif problem == "future_issued":
        claims["iat"] = now + 60
    elif problem == "wrong_issuer":
        claims["iss"] = "https://another-instance.clerk.accounts.dev"
    elif problem == "wrong_origin":
        claims["azp"] = "https://untrusted.example"
    elif problem == "pending_session":
        claims["sts"] = "pending"
    else:
        del claims["exp"]

    response = request_me(auth_api, auth_api.sign(claims))

    assert response.status_code == 401
    assert response.json() == {
        "detail": "A valid sign-in session is required"
    }


def test_other_algorithm_is_rejected_before_key_lookup(auth_api):
    token = jwt.encode(
        auth_api.claims(),
        "synthetic-test-secret-with-at-least-32-characters",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )

    assert request_me(auth_api, token).status_code == 401
    auth_api.jwks.get_signing_key_from_jwt.assert_not_called()


def test_key_service_outage_returns_503(auth_api):
    auth_api.jwks.get_signing_key_from_jwt.side_effect = (
        PyJWKClientConnectionError("Synthetic connection failure")
    )

    response = request_me(auth_api, auth_api.sign(auth_api.claims()))

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication service temporarily unavailable"
    }


def test_unconfigured_authentication_fails_closed(auth_api):
    token = auth_api.sign(auth_api.claims())
    auth_api.settings.clerk_issuer = None

    response = request_me(auth_api, token)

    assert response.status_code == 503
    auth_api.jwks.get_signing_key_from_jwt.assert_not_called()