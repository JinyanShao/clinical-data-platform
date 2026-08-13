from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from clinical_data_platform.config import settings

# ``settings.database_url`` only falls back to a local SQLite file in
# development; ``Settings.validate()`` (invoked at application and worker
# startup) refuses to run any other environment without an explicit
# DATABASE_URL, so a misconfigured deployment fails loudly instead of silently
# serving from a throwaway file.
DATABASE_URL = settings.database_url
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def set_rls_context(session: Session, user_id: UUID | None, role: str) -> None:
    """Bind the authenticated principal to PostgreSQL RLS for this transaction.

    ``set_config(..., true)`` is transaction-local, so pooled connections cannot
    retain a previous user's identity. SQLite unit tests intentionally no-op.
    """
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id or "")})
        session.execute(text("SELECT set_config('app.role', :role, true)"), {"role": role})


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_session() -> Generator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
