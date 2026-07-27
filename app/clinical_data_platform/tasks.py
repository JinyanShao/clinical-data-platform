from __future__ import annotations

import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from clinical_data_platform.celery_app import celery_app
from clinical_data_platform.models import ImportJob
from clinical_data_platform.services.csv_import import CsvImportService
from clinical_data_platform.services.fhir_import import FhirImportService
from clinical_data_platform.services.import_job import ImportJobService
from clinical_data_platform.session import SessionLocal

logger = logging.getLogger(__name__)


def process_import_job(session: Session, import_job_id: UUID) -> ImportJob:
    service = ImportJobService(session)
    job = service.repo.get_by_id(import_job_id)
    if not job:
        raise ValueError("import job not found")
    if not service.is_runnable(job):
        # Terminal jobs are never reprocessed. This is what makes a duplicate
        # or late broker delivery harmless: it can no longer resurrect a
        # finished job or overwrite its outcome.
        logger.info(
            "skipping import job that is not runnable",
            extra={"import_job_id": str(job.id), "import_status": job.status},
        )
        return job

    importer = CsvImportService(session) if job.source_type == "csv" else FhirImportService(session)
    result = importer.process(job)
    session.commit()
    logger.info(
        "import completed",
        extra={"import_job_id": str(job.id), "import_status": result.status},
    )
    return result


def _fail(session: Session, import_job_id: UUID, reason: str) -> ImportJob | None:
    """Roll back the failed attempt and record the failure via the state machine."""
    session.rollback()
    job = ImportJobService(session).mark_failed(import_job_id, reason)
    session.commit()
    return job


def _requeue(session: Session, import_job_id: UUID) -> ImportJob | None:
    """Open a new attempt, but only from a state the machine permits."""
    service = ImportJobService(session)
    job = service.repo.get_by_id(import_job_id)
    if not job or not service.can_transition(job.status, "pending"):
        logger.warning(
            "not requeueing import job from its current state",
            extra={
                "import_job_id": str(import_job_id),
                "import_status": job.status if job else "missing",
            },
        )
        return None
    job = service.mark_pending_for_retry(import_job_id)
    session.commit()
    return job


@celery_app.task(bind=True, max_retries=3, soft_time_limit=300, time_limit=330)
def run_import(self, import_job_id: str) -> str:
    job_id = UUID(import_job_id)
    with SessionLocal() as session:
        try:
            return str(process_import_job(session, job_id).id)
        except SoftTimeLimitExceeded:
            _fail(session, job_id, "import timed out")
            logger.exception("import timed out", extra={"import_job_id": import_job_id})
            raise
        except Exception as exc:
            _fail(session, job_id, f"{type(exc).__name__}: {exc}")
            logger.exception("import failed", extra={"import_job_id": import_job_id})
            if self.request.retries < self.max_retries and _requeue(session, job_id):
                raise self.retry(exc=exc, countdown=min(2 ** self.request.retries, 30)) from exc
            raise


def dispatch_import(session: Session, job: ImportJob) -> ImportJob:
    service = ImportJobService(session)
    if job.status != "pending" or job.task_id:
        return job
    if celery_app.conf.task_always_eager:
        return process_import_job(session, job.id)

    job_id = job.id
    session.commit()
    try:
        result = run_import.delay(str(job_id))
        service.repo.update(service.get(job_id), task_id=result.id)
    except Exception as exc:
        service.mark_failed(job_id, f"queue unavailable: {exc}")
        logger.exception("failed to enqueue import", extra={"import_job_id": str(job_id)})
    session.commit()
    return service.get(job_id)
