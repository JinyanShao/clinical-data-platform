"""Coverage for the Celery worker path.

``run_import`` and its failure handling previously had no tests at all, which
is precisely where the state-machine bypass and the duplicated error rows
lived. These exercise the real task body rather than the eager dispatch
shortcut.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from billiard.exceptions import SoftTimeLimitExceeded
from clinical_data_platform import tasks
from clinical_data_platform.models import ImportError as ImportErrorRow
from clinical_data_platform.models import SourceRecord
from clinical_data_platform.services.csv_import import CSV_HEADERS
from clinical_data_platform.services.import_job import ImportJobService
from clinical_data_platform.services.import_pipeline import ImportPipelineService
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def _csv_bytes(*, extra_bad_row: bool = False) -> bytes:
    row = {
        "patient_external_id": "task-patient-1",
        "birth_date": "1980-01-01",
        "sex": "female",
        "encounter_external_id": "task-encounter-1",
        "encounter_start": "2026-07-25T08:00:00+00:00",
        "encounter_end": "2026-07-25T09:00:00+00:00",
        "observation_external_id": "task-observation-1",
        "observation_code": "718-7",
        "observation_value": "5.2",
        "observation_unit": "mmol/L",
        "observed_at": "2026-07-25T08:30:00+00:00",
    }
    lines = [",".join(CSV_HEADERS), ",".join(row[header] for header in CSV_HEADERS)]
    if extra_bad_row:
        # A second row that fails validation, so the job lands in "partial" -
        # the only non-failed state an explicit retry is allowed to re-open.
        bad = dict(row)
        bad["patient_external_id"] = "task-patient-bad"
        bad["encounter_external_id"] = "task-encounter-bad"
        bad["observation_external_id"] = "task-observation-bad"
        bad["observation_value"] = "not-a-number"
        lines.append(",".join(bad[header] for header in CSV_HEADERS))
    return ("\r\n".join(lines) + "\r\n").encode()


@pytest.fixture()
def session_factory(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'tasks.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    # run_import opens its own session; point it at this test database.
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    return factory


def _enqueue(session, content: bytes | None = None):
    job = ImportPipelineService(session).enqueue(
        "csv", "labs.csv", content if content is not None else _csv_bytes()
    )
    session.commit()
    return job


# ----------------------------------------------------------------------
# process_import_job
# ----------------------------------------------------------------------


def test_run_import_processes_a_pending_job(session_factory) -> None:
    with session_factory() as session:
        job_id = _enqueue(session).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        job = ImportJobService(session).get(job_id)
        assert job.status == "completed"
        assert (job.total_records, job.successful_records, job.failed_records) == (1, 1, 0)


def test_process_import_job_skips_a_job_in_a_terminal_state(session_factory) -> None:
    """A duplicate broker delivery must not reprocess a finished job."""
    with session_factory() as session:
        job_id = _enqueue(session).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        before = ImportJobService(session).get(job_id)
        completed_at = before.completed_at
        result = tasks.process_import_job(session, job_id)
        assert result.status == "completed"
        assert result.completed_at == completed_at
        assert result.retry_count == 0


# ----------------------------------------------------------------------
# Failure handling goes through the state machine
# ----------------------------------------------------------------------


def test_failure_never_overwrites_a_terminal_result(session_factory) -> None:
    """The transition the old code could reach: completed -> failed."""
    with session_factory() as session:
        job_id = _enqueue(session).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        job = tasks._fail(session, job_id, "late duplicate delivery")
        assert job is not None
        assert job.status == "completed"
        assert job.failure_reason is None


def test_failure_from_processing_is_recorded(session_factory) -> None:
    with session_factory() as session:
        job = _enqueue(session)
        ImportJobService(session).set_status(job.id, "processing")
        session.commit()
        job_id = job.id

    with session_factory() as session:
        failed = tasks._fail(session, job_id, "RuntimeError: boom")
        assert failed.status == "failed"
        assert failed.failure_reason == "RuntimeError: boom"
        assert failed.completed_at is not None


def test_requeue_opens_a_new_attempt(session_factory) -> None:
    with session_factory() as session:
        job = _enqueue(session)
        ImportJobService(session).set_status(job.id, "processing")
        session.commit()
        job_id = job.id

    with session_factory() as session:
        tasks._fail(session, job_id, "transient")
        requeued = tasks._requeue(session, job_id)
        assert requeued is not None
        assert requeued.status == "pending"
        assert requeued.retry_count == 1
        assert requeued.task_id is None
        assert requeued.completed_at is None


def test_requeue_refuses_a_completed_job(session_factory) -> None:
    with session_factory() as session:
        job_id = _enqueue(session).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        assert tasks._requeue(session, job_id) is None
        assert ImportJobService(session).get(job_id).status == "completed"


def test_soft_time_limit_marks_the_job_failed(session_factory, monkeypatch) -> None:
    with session_factory() as session:
        job_id = _enqueue(session).id

    def _timeout(session, import_job_id):  # noqa: ARG001
        raise SoftTimeLimitExceeded

    monkeypatch.setattr(tasks, "process_import_job", _timeout)
    result = tasks.run_import.apply(args=[str(job_id)], throw=False)
    assert result.failed()

    with session_factory() as session:
        job = ImportJobService(session).get(job_id)
        assert job.status == "failed"
        assert job.failure_reason == "import timed out"
        # A timeout is not retried, so no new attempt is opened.
        assert job.retry_count == 0


# ----------------------------------------------------------------------
# Error reports are versioned, not duplicated
# ----------------------------------------------------------------------


def test_reprocessing_versions_errors_instead_of_duplicating_them(session_factory) -> None:
    bad_header = b"bad,header\r\n1,2\r\n"
    with session_factory() as session:
        job_id = _enqueue(session, bad_header).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        assert ImportJobService(session).get(job_id).status == "failed"
        assert session.scalar(select(func.count()).select_from(ImportErrorRow)) == 1
        tasks._requeue(session, job_id)

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        attempts = session.scalars(
            select(ImportErrorRow.attempt).order_by(ImportErrorRow.attempt)
        ).all()
        # Two rows, one per attempt, each tagged - not two indistinguishable
        # copies of the same error.
        assert attempts == [0, 1]


# ----------------------------------------------------------------------
# Regressions found while reviewing this change
# ----------------------------------------------------------------------


def test_retry_does_not_erase_who_created_a_resource(session_factory) -> None:
    """A rewritten attempt must not downgrade 'created' to 'reasserted'.

    Otherwise the history ends up with no import claiming to have created the
    resource at all, which is the question the table exists to answer.
    """
    with session_factory() as session:
        job_id = _enqueue(session, _csv_bytes(extra_bad_row=True)).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        assert ImportJobService(session).get(job_id).status == "partial"
        actions = session.scalars(
            select(SourceRecord.action).where(SourceRecord.import_job_id == job_id)
        ).all()
        assert sorted(actions) == ["created"] * 3
        ImportJobService(session).mark_pending_for_retry(job_id)
        session.commit()

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        actions = session.scalars(
            select(SourceRecord.action).where(SourceRecord.import_job_id == job_id)
        ).all()
        assert sorted(actions) == ["created"] * 3


def test_redelivery_within_one_attempt_does_not_duplicate_errors(session_factory) -> None:
    bad_header = b"bad,header\r\n1,2\r\n"
    with session_factory() as session:
        job_id = _enqueue(session, bad_header).id

    tasks.run_import.apply(args=[str(job_id)])

    # Simulate the broker redelivering the same task: the job is put back into
    # "processing" and reprocessed under the same attempt number.
    with session_factory() as session:
        ImportJobService(session).set_status(job_id, "pending")
        session.commit()
        ImportJobService(session).set_status(job_id, "processing")
        session.commit()

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        rows = session.scalars(
            select(ImportErrorRow.attempt).where(ImportErrorRow.import_job_id == job_id)
        ).all()
        assert rows == [0]


def test_fatal_failure_resets_stale_counters(session_factory) -> None:
    with session_factory() as session:
        job_id = _enqueue(session, _csv_bytes(extra_bad_row=True)).id

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        service = ImportJobService(session)
        job = service.get(job_id)
        assert (job.total_records, job.successful_records, job.failed_records) == (2, 1, 1)
        # Replace the payload with something that fails header validation and
        # re-run: the previous run's counters must not survive.
        job.payload = b"bad,header\r\n1,2\r\n"
        service.mark_pending_for_retry(job_id)
        session.commit()

    tasks.run_import.apply(args=[str(job_id)])

    with session_factory() as session:
        job = ImportJobService(session).get(job_id)
        assert job.status == "failed"
        assert (job.total_records, job.successful_records, job.failed_records) == (0, 0, 1)


def test_requeue_clears_the_previous_failure_reason(session_factory) -> None:
    with session_factory() as session:
        job = _enqueue(session)
        ImportJobService(session).set_status(job.id, "processing")
        session.commit()
        job_id = job.id

    with session_factory() as session:
        tasks._fail(session, job_id, "RuntimeError: boom")
        requeued = tasks._requeue(session, job_id)
        assert requeued.failure_reason is None
        assert requeued.started_at is None


def test_partial_imports_can_be_retried(session_factory) -> None:
    with session_factory() as session:
        job = _enqueue(session)
        service = ImportJobService(session)
        service.set_status(job.id, "processing")
        service.set_status(job.id, "partial")
        session.commit()
        job_id = job.id

    with session_factory() as session:
        requeued = ImportJobService(session).mark_pending_for_retry(job_id)
        assert requeued.status == "pending"
        assert requeued.retry_count == 1
