from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import jwt
import pytest
from clinical_data_platform import auth
from clinical_data_platform.config import settings
from clinical_data_platform.db import Base
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _token(private_key, *, roles: list[str]) -> str:
    return jwt.encode(
        {
            "sub": "keycloak-user-123",
            "preferred_username": "alice",
            "iss": "https://keycloak.example/realms/clinical",
            "aud": "clinical-data-platform-api",
            "iat": 1_700_000_000,
            "exp": 2_000_000_000,
            "realm_access": {"roles": roles},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_oidc_jwks_validation_provisions_a_stable_subject(session: Session, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "settings",
        replace(
            settings,
            auth_mode="oidc",
            oidc_issuer_url="https://keycloak.example/realms/clinical",
            oidc_audience="clinical-data-platform-api",
            oidc_jwks_url="https://jwks.example",
        ),
    )
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())),
    )

    principal = auth._oidc_principal(_token(private_key, roles=["researcher"]), session)

    assert principal.username == "alice"
    assert principal.role == "researcher"
    assert principal.id is not None


def test_oidc_rejects_tokens_without_exactly_one_application_role(session: Session, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "settings",
        replace(
            settings,
            auth_mode="oidc",
            oidc_issuer_url="https://keycloak.example/realms/clinical",
            oidc_audience="clinical-data-platform-api",
            oidc_jwks_url="https://jwks.example",
        ),
    )
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())),
    )

    with pytest.raises(HTTPException, match="exactly one"):
        auth._oidc_principal(_token(private_key, roles=["admin", "researcher"]), session)
