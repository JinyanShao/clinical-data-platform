from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from clinical_data_platform.celery_app import celery_app
from clinical_data_platform.models import ImportJob
from clinical_data_platform.services.csv_import import CsvImportService
from clinical_data_platform.services.fhir_import import FhirImportService
from clinical_data_platform.session import SessionLocal

logger = logging.getLogger(__name__)


def process_import_job(session: Session, import_job_id: UUID) -> ImportJob:
    job = session.get(ImportJob, import_job_id)
    if not job:
        raise ValueError("import job not found")
    if job.status in {"completed", "partial"}:
        return job
    service = CsvImportService(session) if job.source_type == "csv" else FhirImportService(session)
    result = service.process(job)
    session.commit()
    logger.info(
        "import completed",
        extra={"import_job_id": str(job.id), "import_status": result.status},
    )
    return result


def _mark_failure(session: Session, import_job_id: UUID, reason: str) -> ImportJob | None:
    session.rollback()
    job = session.get(ImportJob, import_job_id)
    if not job:
        return None
    job.status = "failed"
    job.failure_reason = reason[:2000]
    job.completed_at = datetime.now(UTC)
    session.commit()
    return job


@celery_app.task(bind=True, max_retries=3, soft_time_limit=300, time_limit=330)
def run_import(self, import_job_id: str) -> str:
    job_id = UUID(import_job_id)
    with SessionLocal() as session:
        try:
            return str(process_import_job(session, job_id).id)
        except SoftTimeLimitExceeded:
            _mark_failure(session, job_id, "import timed out")
            logger.exception("import timed out", extra={"import_job_id": import_job_id})
            raise
        except Exception as exc:
            job = _mark_failure(session, job_id, f"{type(exc).__name__}: {exc}")
            logger.exception("import failed", extra={"import_job_id": import_job_id})
            if job and self.request.retries < self.max_retries:
                job.status = "pending"
                job.retry_count += 1
                session.commit()
                raise self.retry(exc=exc, countdown=min(2 ** self.request.retries, 30)) from exc
            raise


def dispatch_import(session: Session, job: ImportJob) -> ImportJob:
    if job.status != "pending" or job.task_id:
        return job
    if celery_app.conf.task_always_eager:
        return process_import_job(session, job.id)

    session.commit()
    try:
        result = run_import.delay(str(job.id))
        job = session.get(ImportJob, job.id)
        job.task_id = result.id
    except Exception as exc:
        job = session.get(ImportJob, job.id)
        job.status = "failed"
        job.failure_reason = f"queue unavailable: {exc}"[:2000]
        job.completed_at = datetime.now(UTC)
        logger.exception("failed to enqueue import", extra={"import_job_id": str(job.id)})
    session.commit()
    return job
