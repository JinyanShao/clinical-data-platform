from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from clinical_data_platform.models import Encounter, Observation, Patient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def alembic_config(tmp_path: Path) -> tuple[Config, str]:
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config, url


@pytest.fixture()
def engine(alembic_config: tuple[Config, str]):
    _, url = alembic_config
    engine = create_engine(url, future=True)

    if engine.url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ARG001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def test_migration_creates_all_tables(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config
    command.upgrade(config, "head")

    engine = create_engine(url, future=True)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "encounters",
        "audit_logs",
        "import_errors",
        "import_jobs",
        "observations",
        "patients",
        "research_studies",
        "source_records",
        "study_access",
        "research_subjects",
        "users",
    } | {"alembic_version"}


def test_patient_can_be_created(engine) -> None:
    command.upgrade(_alembic_config_from_engine(engine), "head")
    with Session(engine) as session:
        patient = Patient(
            external_id="patient-001",
            birth_date=date(1980, 1, 1),
            sex="female",
        )
        session.add(patient)
        session.commit()
        assert patient.id is not None


def test_encounter_requires_patient(engine) -> None:
    command.upgrade(_alembic_config_from_engine(engine), "head")
    with Session(engine) as session:
        encounter = Encounter(
            patient_id=uuid4(),
            external_id="encounter-001",
            status="finished",
            encounter_type="inpatient",
        )
        session.add(encounter)
        with pytest.raises(IntegrityError):
            session.commit()


def test_observation_can_reference_patient_and_optional_encounter(engine) -> None:
    command.upgrade(_alembic_config_from_engine(engine), "head")
    with Session(engine) as session:
        patient = Patient(
            external_id="patient-002",
            birth_date=None,
            sex="unknown",
        )
        session.add(patient)
        session.flush()

        encounter = Encounter(
            patient_id=patient.id,
            external_id="encounter-002",
            status="finished",
            encounter_type="outpatient",
        )
        session.add(encounter)
        session.flush()

        observation = Observation(
            patient_id=patient.id,
            encounter_id=encounter.id,
            external_id="observation-001",
            code="718-7",
            code_system="LOINC",
            value="5.2",
            unit="mmol/L",
            observed_at=datetime.now(UTC),
            status="final",
        )
        session.add(observation)
        session.commit()

        loaded = session.get(Observation, observation.id)
        assert loaded is not None
        assert loaded.patient_id == patient.id
        assert loaded.encounter_id == encounter.id


def test_illegal_foreign_key_is_rejected(engine) -> None:
    command.upgrade(_alembic_config_from_engine(engine), "head")
    with Session(engine) as session:
        observation = Observation(
            patient_id=uuid4(),
            encounter_id=None,
            external_id="observation-002",
            code="1234-5",
            code_system="LOINC",
            value="positive",
            unit=None,
            observed_at=datetime.now(UTC),
            status="final",
        )
        session.add(observation)
        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_external_id_is_rejected(engine) -> None:
    command.upgrade(_alembic_config_from_engine(engine), "head")
    with Session(engine) as session:
        first = Patient(
            external_id="patient-dup",
            birth_date=None,
            sex="other",
        )
        second = Patient(
            external_id="patient-dup",
            birth_date=None,
            sex="other",
        )
        session.add(first)
        session.commit()

        session.add(second)
        with pytest.raises(IntegrityError):
            session.commit()


def _alembic_config_from_engine(engine) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", str(engine.url))
    return config
