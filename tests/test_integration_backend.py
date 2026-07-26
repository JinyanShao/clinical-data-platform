"""Integration coverage against the real production backends.

Everything else in the suite runs on SQLite with Celery in eager mode, so the
PostgreSQL-only paths (the JSONB variant on ``source_records.raw_data`` and
``audit_logs.before/after``, the psycopg driver, ``ondelete`` semantics) and
the Redis broker were never executed. These tests run only when
``TEST_DATABASE_URL`` / ``TEST_REDIS_URL`` point at real services, which CI
supplies via service containers.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from clinical_data_platform.models import AuditLog, ImportJob, Patient, SourceRecord
from clinical_data_platform.services.csv_import import CSV_HEADERS, CsvImportService
from clinical_data_platform.services.import_pipeline import ImportPipelineService
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REDIS_URL = os.getenv("TEST_REDIS_URL")

requires_postgres = pytest.mark.skipif(
    not DATABASE_URL or not DATABASE_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL must point at a PostgreSQL instance",
)
requires_redis = pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set")


def _csv_bytes(patient: str) -> bytes:
    row = {
        "patient_external_id": patient,
        "birth_date": "1980-01-01",
        "sex": "female",
        "encounter_external_id": f"{patient}-enc",
        "encounter_start": "2026-07-25T08:00:00+00:00",
        "encounter_end": "2026-07-25T09:00:00+00:00",
        "observation_external_id": f"{patient}-obs",
        "observation_code": "718-7",
        "observation_value": "5.2",
        "observation_unit": "mmol/L",
        "observed_at": "2026-07-25T08:30:00+00:00",
    }
    lines = [",".join(CSV_HEADERS), ",".join(row[header] for header in CSV_HEADERS)]
    return ("\r\n".join(lines) + "\r\n").encode()


def _alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "head")
    return engine


@pytest.fixture()
def pg_session(pg_engine):
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session
        session.rollback()


@requires_postgres
def test_migrations_round_trip_on_postgresql() -> None:
    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@requires_postgres
def test_jsonb_provenance_and_audit_payloads_round_trip(pg_session: Session) -> None:
    """raw_data / before / after use the JSONB variant only on PostgreSQL."""
    job = ImportPipelineService(pg_session).enqueue("csv", "labs.csv", _csv_bytes("pg-patient-1"))
    pg_session.commit()

    CsvImportService(pg_session).process(job)
    pg_session.commit()

    record = pg_session.scalar(
        select(SourceRecord).where(
            SourceRecord.import_job_id == job.id,
            SourceRecord.resource_type == "patient",
        )
    )
    assert record is not None
    assert record.raw_data["patient_external_id"] == "pg-patient-1"
    assert record.action == "created"

    pg_session.add(
        AuditLog(
            actor="integration",
            action="update",
            resource_type="Patient",
            resource_id=str(record.resource_id),
            before={"sex": "female", "tags": ["a", "b"]},
            after={"sex": "male", "tags": []},
        )
    )
    pg_session.commit()

    entry = pg_session.scalar(select(AuditLog).where(AuditLog.actor == "integration"))
    assert entry.before["tags"] == ["a", "b"]
    assert entry.after["tags"] == []


@requires_postgres
def test_namespaced_identity_is_enforced_by_postgresql(pg_session: Session) -> None:
    namespace_a = "urn:integration:site-a"
    namespace_b = "urn:integration:site-b"
    pg_session.add_all(
        [
            Patient(source_namespace=namespace_a, external_id="P001"),
            Patient(source_namespace=namespace_b, external_id="P001"),
        ]
    )
    pg_session.commit()

    count = pg_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.external_id == "P001")
    )
    assert count == 2


@requires_postgres
def test_idempotency_key_allows_the_same_file_per_target(pg_session: Session) -> None:
    content = _csv_bytes("pg-patient-2")
    pipeline = ImportPipelineService(pg_session)

    first = pipeline.enqueue("csv", "labs.csv", content, None, "urn:integration:one")
    second = pipeline.enqueue("csv", "labs.csv", content, None, "urn:integration:two")
    repeat = pipeline.enqueue("csv", "labs.csv", content, None, "urn:integration:one")
    pg_session.commit()

    assert first.id != second.id
    assert first.id == repeat.id
    assert first.file_checksum == second.file_checksum
    assert (
        pg_session.scalar(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.file_checksum == first.file_checksum)
        )
        == 2
    )


@requires_redis
def test_redis_broker_is_reachable() -> None:
    import redis

    client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=5, socket_timeout=5)
    assert client.ping() is True
