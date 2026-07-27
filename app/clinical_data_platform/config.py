"""Centralised configuration with fail-closed validation.

Every setting that affects security or data durability is resolved here once,
at import time, and validated before the application is allowed to serve
traffic. The guiding rule is that a *missing* configuration value must never
silently produce a permissive or throwaway deployment:

- ``ENVIRONMENT`` defaults to ``production`` so that forgetting to set it
  yields the strictest behaviour rather than the loosest.
- The built-in demo admin token only exists when it is explicitly switched on
  and is refused outright in production.
- ``DATABASE_URL`` is mandatory outside development, so a misconfigured
  deployment fails at startup instead of quietly running on a local SQLite
  file that ``/ready`` would happily report as healthy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEVELOPMENT = "development"
STAGING = "staging"
PRODUCTION = "production"
VALID_ENVIRONMENTS = (DEVELOPMENT, STAGING, PRODUCTION)

#: Only ever usable when ``ENABLE_DEMO_ADMIN_TOKEN`` is explicitly true and the
#: environment is ``development``. Never a fallback.
DEMO_ADMIN_TOKEN = "demo-admin-token"

DEVELOPMENT_DATABASE_URL = "sqlite:///clinical_data_platform.db"

#: Namespace used when a caller supplies no issuing system and the import is
#: not bound to a ResearchStudy. See ``docs/domain-model.md``.
DEFAULT_SOURCE_NAMESPACE = "urn:cdp:default"

#: Prefix for namespaces derived from the ResearchStudy an import is bound to.
STUDY_SOURCE_NAMESPACE_PREFIX = "urn:cdp:study:"


class ConfigurationError(RuntimeError):
    """Raised when the process is not safe to start with the given settings."""


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str
    admin_api_key: str | None
    enable_demo_admin_token: bool
    database_url: str
    database_url_was_explicit: bool
    redis_url: str

    @property
    def is_development(self) -> bool:
        return self.environment == DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.environment == PRODUCTION

    @property
    def bootstrap_admin_token(self) -> str | None:
        """The single token that grants bootstrap admin access, if any.

        ``ADMIN_API_KEY`` is an explicit operator-provided secret and is
        honoured in every environment. The hard-coded demo token is only
        returned when it has been switched on deliberately.
        """
        if self.admin_api_key:
            return self.admin_api_key
        if self.enable_demo_admin_token:
            return DEMO_ADMIN_TOKEN
        return None

    def validate(self) -> None:
        """Fail loudly on any configuration that would weaken the deployment."""
        problems: list[str] = []

        if self.environment not in VALID_ENVIRONMENTS:
            problems.append(
                f"ENVIRONMENT must be one of {', '.join(VALID_ENVIRONMENTS)}; got {self.environment!r}."
            )

        if self.enable_demo_admin_token and self.environment != DEVELOPMENT:
            problems.append(
                "ENABLE_DEMO_ADMIN_TOKEN is only permitted when ENVIRONMENT=development. "
                "Set ADMIN_API_KEY to an operator-managed secret instead."
            )

        if self.admin_api_key is not None and not self.admin_api_key.strip():
            problems.append("ADMIN_API_KEY is set but empty; unset it or provide a real secret.")

        if self.admin_api_key and self.admin_api_key == DEMO_ADMIN_TOKEN and self.environment != DEVELOPMENT:
            problems.append(
                "ADMIN_API_KEY is set to the published demo token; use a generated secret outside development."
            )

        if not self.database_url_was_explicit and self.environment != DEVELOPMENT:
            problems.append(
                "DATABASE_URL is required when ENVIRONMENT is not development. "
                "Refusing to fall back to a local SQLite file."
            )

        if problems:
            raise ConfigurationError(
                "Refusing to start due to unsafe configuration:\n  - " + "\n  - ".join(problems)
            )


def load_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    return Settings(
        environment=os.getenv("ENVIRONMENT", PRODUCTION).strip().lower(),
        admin_api_key=os.getenv("ADMIN_API_KEY"),
        enable_demo_admin_token=_flag("ENABLE_DEMO_ADMIN_TOKEN"),
        database_url=database_url or DEVELOPMENT_DATABASE_URL,
        database_url_was_explicit=bool(database_url),
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )


settings = load_settings()


def reload_settings() -> Settings:
    """Re-read the environment. Intended for tests, not for request handling."""
    global settings
    settings = load_settings()
    return settings


def study_source_namespace(study_id: object) -> str:
    """Namespace for records imported under a specific ResearchStudy."""
    return f"{STUDY_SOURCE_NAMESPACE_PREFIX}{study_id}"


def resolve_source_namespace(explicit: str | None, study_id: object | None) -> str:
    """Resolve the issuing namespace for an import.

    Precedence:

    1. an explicit ``source_namespace`` supplied by the caller;
    2. a namespace derived from the ResearchStudy the import is bound to, so
       that two studies using the same local identifier scheme stay separate;
    3. :data:`DEFAULT_SOURCE_NAMESPACE`.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    if study_id is not None:
        return study_source_namespace(study_id)
    return DEFAULT_SOURCE_NAMESPACE
