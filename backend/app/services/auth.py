from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKError,
    PyJWKSetError,
)
from pydantic import BaseModel

from app.config import get_settings


bearer = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    issuer: str
    user_id: str
    session_id: str


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="A valid sign-in session is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=4)
def get_jwks_client(issuer: str) -> jwt.PyJWKClient:
    # The URL comes from server configuration, never from token headers.
    return jwt.PyJWKClient(
        f"{issuer}/.well-known/jwks.json",
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
    )


def verify_session_token(token: str) -> AuthenticatedUser:
    settings = get_settings()
    issuer = settings.clerk_issuer
    authorized_parties = settings.clerk_authorized_parties

    if not issuer or not authorized_parties:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured",
        )

    issuer = issuer.rstrip("/")

    try:
        parsed = urlsplit(issuer)
        valid_issuer = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid_issuer = False

    if not valid_issuer:
        raise HTTPException(
            status_code=503,
            detail="Authentication configuration is invalid",
        )

    if not token or len(token) > 16384:
        raise unauthorized()

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if (
            header.get("alg") != "RS256"
            or not isinstance(kid, str)
            or not kid.strip()
            or len(kid) > 200
        ):
            raise unauthorized()

        key = get_jwks_client(issuer).get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=5,
            options={
                "require": [
                    "iss", "sub", "sid", "exp", "iat", "nbf", "azp",
                ],
                # Default Clerk session tokens use issuer + azp.
                # Custom audience-based tokens are not supported here.
                "verify_aud": False,
            },
        )
    except PyJWKClientConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
        ) from None
    except (
        InvalidTokenError,
        PyJWKClientError,
        PyJWKError,
        PyJWKSetError,
    ):
        raise unauthorized() from None

    user_id = claims.get("sub")
    session_id = claims.get("sid")
    authorized_party = claims.get("azp")

    if (
        not isinstance(user_id, str)
        or not user_id.startswith("user_")
        or not isinstance(session_id, str)
        or not session_id.startswith("sess_")
        or not isinstance(authorized_party, str)
        or authorized_party not in authorized_parties
    ):
        raise unauthorized()

    # Pending sessions must finish required sign-in tasks first.
    if claims.get("sts") not in (None, "active"):
        raise unauthorized()

    return AuthenticatedUser(
        issuer=issuer,
        user_id=user_id,
        session_id=session_id,
    )


def require_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer),
    ],
) -> AuthenticatedUser:
    if credentials is None:
        raise unauthorized()

    return verify_session_token(credentials.credentials)