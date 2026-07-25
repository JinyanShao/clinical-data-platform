from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from clinical_data_platform.models import User
from clinical_data_platform.session import get_session

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: UUID | None
    username: str
    role: str


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> Principal:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")

    token = credentials.credentials
    bootstrap_key = os.getenv("ADMIN_API_KEY")
    if not bootstrap_key and os.getenv("ENVIRONMENT", "development") != "production":
        bootstrap_key = "dev-admin-token"
    if bootstrap_key and secrets.compare_digest(token, bootstrap_key):
        return Principal(None, "bootstrap-admin", "admin")

    user = session.scalar(sa.select(User).where(User.api_key_hash == hash_api_key(token)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return Principal(user.id, user.username, user.role)


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(get_current_user)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return principal

    return dependency
