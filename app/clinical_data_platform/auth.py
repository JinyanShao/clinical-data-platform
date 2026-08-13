from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
import sqlalchemy as sa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from clinical_data_platform.config import settings
from clinical_data_platform.models import User
from clinical_data_platform.session import get_session, set_rls_context

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: UUID | None
    username: str
    role: str


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=300)


def _oidc_principal(token: str, session: Session) -> Principal:
    issuer = settings.oidc_issuer_url
    audience = settings.oidc_audience
    if not issuer or not audience:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC is not configured")
    jwks_url = settings.oidc_jwks_url or f"{issuer}/protocol/openid-connect/certs"
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token") from exc

    subject = claims["sub"]
    username = str(claims.get("preferred_username") or claims.get("email") or subject)
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    application_roles = [role for role in roles if role in {"admin", "researcher", "auditor"}]
    if len(application_roles) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access token must contain exactly one clinical platform realm role",
        )
    role = application_roles[0]
    user = session.scalar(sa.select(User).where(User.oidc_subject == subject))
    if user is None:
        user = User(username=username, oidc_subject=subject, role=role, api_key_hash=hash_api_key(secrets.token_urlsafe(32)))
        session.add(user)
        session.flush()
    else:
        # Keycloak remains the source of truth for role assignment. Do not use
        # username as identity because it is a mutable display claim.
        user.username = username
        user.role = role
        session.flush()
    return Principal(user.id, user.username, user.role)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> Principal:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")

    token = credentials.credentials

    if settings.auth_mode == "oidc":
        principal = _oidc_principal(token, session)
        set_rls_context(session, principal.id, principal.role)
        return principal

    # Bootstrap admin access exists only when an operator has configured it.
    # There is deliberately no fallback token: missing configuration means no
    # bootstrap admin, not a well-known one.
    bootstrap_token = settings.bootstrap_admin_token
    if bootstrap_token and secrets.compare_digest(token, bootstrap_token):
        principal = Principal(None, "bootstrap-admin", "admin")
        set_rls_context(session, principal.id, principal.role)
        return principal

    user = session.scalar(sa.select(User).where(User.api_key_hash == hash_api_key(token)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    principal = Principal(user.id, user.username, user.role)
    set_rls_context(session, principal.id, principal.role)
    return principal


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(get_current_user)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return principal

    return dependency
