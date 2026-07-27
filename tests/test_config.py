from __future__ import annotations

import pytest
from clinical_data_platform.config import (
    DEMO_ADMIN_TOKEN,
    ConfigurationError,
    Settings,
    resolve_source_namespace,
    study_source_namespace,
)


def _settings(**overrides) -> Settings:
    base = dict(
        environment="production",
        admin_api_key=None,
        enable_demo_admin_token=False,
        database_url="postgresql+psycopg://user:pw@db/app",
        database_url_was_explicit=True,
        redis_url="redis://redis:6379/0",
    )
    base.update(overrides)
    return Settings(**base)


def test_unconfigured_production_grants_no_bootstrap_token() -> None:
    """The core fail-open regression: absent config must mean no admin token."""
    settings = _settings()
    settings.validate()
    assert settings.bootstrap_admin_token is None


def test_demo_token_is_refused_outside_development() -> None:
    settings = _settings(enable_demo_admin_token=True)
    with pytest.raises(ConfigurationError, match="ENABLE_DEMO_ADMIN_TOKEN"):
        settings.validate()


def test_demo_token_requires_explicit_opt_in_even_in_development() -> None:
    assert _settings(environment="development").bootstrap_admin_token is None


def test_demo_token_available_when_explicitly_enabled_in_development() -> None:
    settings = _settings(environment="development", enable_demo_admin_token=True)
    settings.validate()
    assert settings.bootstrap_admin_token == DEMO_ADMIN_TOKEN


def test_operator_supplied_key_wins_over_demo_token() -> None:
    settings = _settings(
        environment="development", enable_demo_admin_token=True, admin_api_key="real-secret"
    )
    settings.validate()
    assert settings.bootstrap_admin_token == "real-secret"


def test_published_demo_token_rejected_as_admin_key_outside_development() -> None:
    settings = _settings(admin_api_key=DEMO_ADMIN_TOKEN)
    with pytest.raises(ConfigurationError, match="published demo token"):
        settings.validate()


def test_missing_database_url_is_fatal_outside_development() -> None:
    settings = _settings(database_url_was_explicit=False, database_url="sqlite:///local.db")
    with pytest.raises(ConfigurationError, match="DATABASE_URL is required"):
        settings.validate()


def test_missing_database_url_is_tolerated_in_development() -> None:
    _settings(
        environment="development", database_url_was_explicit=False, database_url="sqlite:///local.db"
    ).validate()


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="ENVIRONMENT must be one of"):
        _settings(environment="staging-2").validate()


def test_blank_admin_key_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="ADMIN_API_KEY is set but empty"):
        _settings(admin_api_key="   ").validate()


def test_namespace_defaults_isolate_by_study() -> None:
    assert resolve_source_namespace(None, "study-a") == study_source_namespace("study-a")
    assert resolve_source_namespace(None, "study-a") != resolve_source_namespace(None, "study-b")


def test_explicit_namespace_overrides_study_derivation() -> None:
    assert resolve_source_namespace("urn:hospital:mrn", "study-a") == "urn:hospital:mrn"
    assert resolve_source_namespace("  urn:hospital:mrn  ", None) == "urn:hospital:mrn"


def test_namespace_falls_back_to_default_without_study() -> None:
    assert resolve_source_namespace(None, None) == "urn:cdp:default"
    assert resolve_source_namespace("", None) == "urn:cdp:default"
