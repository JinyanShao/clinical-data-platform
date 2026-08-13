from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from clinical_data_platform.services import (
    EncounterService,
    ImportJobService,
    ObservationService,
    PatientService,
)
from clinical_data_platform.services.import_pipeline import ImportPipelineService
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def session(tmp_path: Path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'test.db'}")
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"), future=True)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with Session(engine) as session:
        yield session


def test_services_create_patient_encounter_observation(session: Session) -> None:
    patient = PatientService(session).create("patient-service-001")
    encounter = EncounterService(session).create(
        patient_id=patient.id,
        external_id="encounter-service-001",
        status="finished",
        encounter_type="outpatient",
    )
    observation = ObservationService(session).create(
        patient_id=patient.id,
        encounter_id=encounter.id,
        external_id="observation-service-001",
        code="718-7",
        code_system="LOINC",
        value="5.2",
        unit="mmol/L",
        observed_at=datetime.now(UTC),
        status="final",
    )

    assert observation.patient_id == patient.id
    assert observation.encounter_id == encounter.id


def test_duplicate_patient_is_rejected(session: Session) -> None:
    service = PatientService(session)
    service.create("patient-dup")

    with pytest.raises(ValueError, match="already exists"):
        service.create("patient-dup")


def test_encounter_rejects_missing_patient(session: Session) -> None:
    with pytest.raises(ValueError, match="patient not found"):
        EncounterService(session).create(
            patient_id=uuid4(),
            external_id="encounter-missing-patient",
            status="finished",
            encounter_type="outpatient",
        )


def test_encounter_rejects_end_before_start(session: Session) -> None:
    patient = PatientService(session).create("patient-time")
    started_at = datetime.now(UTC)

    with pytest.raises(ValueError, match="ended_at"):
        EncounterService(session).create(
            patient_id=patient.id,
            external_id="encounter-bad-time",
            status="finished",
            encounter_type="outpatient",
            started_at=started_at,
            ended_at=started_at - timedelta(hours=1),
        )


def test_observation_rejects_other_patients_encounter(session: Session) -> None:
    first_patient = PatientService(session).create("patient-first")
    second_patient = PatientService(session).create("patient-second")
    encounter = EncounterService(session).create(
        patient_id=first_patient.id,
        external_id="encounter-first",
        status="finished",
        encounter_type="outpatient",
    )

    with pytest.raises(ValueError, match="different patient"):
        ObservationService(session).create(
            patient_id=second_patient.id,
            encounter_id=encounter.id,
            external_id="observation-wrong-encounter",
            code="718-7",
            code_system="LOINC",
            value="5.2",
            observed_at=datetime.now(UTC),
            status="final",
        )


def test_import_job_rejects_illegal_status_transition(session: Session) -> None:
    service = ImportJobService(session)
    import_job = service.create(source_type="csv", filename="labs.csv", total_records=100)

    with pytest.raises(ValueError, match="cannot transition"):
        service.set_status(import_job.id, "completed")


def test_import_enqueue_recovers_from_a_concurrent_idempotency_insert(session: Session, monkeypatch) -> None:
    pipeline = ImportPipelineService(session)
    content = b"same-upload"
    first = pipeline.enqueue("csv", "first.csv", content)
    session.flush()

    original_lookup = pipeline.jobs.get_by_idempotency_key
    lookups = 0

    def delayed_lookup(idempotency_key: str):
        nonlocal lookups
        lookups += 1
        return None if lookups == 1 else original_lookup(idempotency_key)

    monkeypatch.setattr(pipeline.jobs, "get_by_idempotency_key", delayed_lookup)
    recovered = pipeline.enqueue("csv", "repeat.csv", content)

    assert recovered.id == first.id
