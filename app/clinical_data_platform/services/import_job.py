from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.exceptions import BusinessRuleError, NotFoundError
from clinical_data_platform.models import ImportJob
from clinical_data_platform.repositories import ImportJobRepository

logger = logging.getLogger(__name__)

#: Statuses from which no further transition is allowed.
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})

#: Statuses a worker is allowed to pick up and process.
RUNNABLE_STATUSES = frozenset({"pending", "processing"})


class ImportJobService:
    """Sole owner of ImportJob status.

    Every status change in the codebase goes through this class. Nothing else
    assigns ``job.status`` directly — that previously allowed the Celery task
    to write transitions (``failed -> failed``, ``completed -> failed``) that
    the state machine here explicitly forbids.
    """

    transitions = {
        "pending": {"processing", "failed"},
        # "processing" repeats itself so a task redelivered by the broker
        # (task_acks_late) can safely re-enter processing rather than hitting an
        # illegal write. A worker may also hand a job back to the queue.
        "processing": {"processing", "completed", "partial", "failed", "pending"},
        "completed": set(),
        # A partial import is the common case when a few rows are bad, so an
        # explicit retry must be able to re-run it. It stays out of
        # RUNNABLE_STATUSES, so a stray broker delivery still cannot resurrect it.
        "partial": {"pending"},
        # Only an explicit retry moves a failed job forward.
        "failed": {"pending"},
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ImportJobRepository(session)

    def create(
        self,
        source_type: str,
        filename: str,
        total_records: int = 0,
        file_checksum: str | None = None,
        idempotency_key: str | None = None,
        source_namespace: str | None = None,
        payload: bytes | None = None,
        study_id: UUID | None = None,
    ) -> ImportJob:
        job = ImportJob(
            source_type=source_type,
            filename=filename,
            total_records=total_records,
            file_checksum=file_checksum,
            idempotency_key=idempotency_key,
            payload=payload,
            study_id=study_id,
        )
        if source_namespace is not None:
            job.source_namespace = source_namespace
        return self.repo.create(job)

    def can_transition(self, current: str, target: str) -> bool:
        return target in self.transitions.get(current, set())

    def set_status(self, import_job_id: UUID, status: str, **extra: object) -> ImportJob:
        import_job = self.get(import_job_id)
        if not self.can_transition(import_job.status, status):
            raise BusinessRuleError(
                f"cannot transition import job from {import_job.status} to {status}"
            )

        fields: dict[str, object] = {"status": status}
        if status == "processing":
            fields["started_at"] = datetime.now(UTC)
            fields["failure_reason"] = None
            fields["completed_at"] = None
        if status in {"completed", "failed", "partial"}:
            fields["completed_at"] = datetime.now(UTC)
        if status == "pending":
            # Clear the whole outcome of the previous attempt, not just the
            # status: a requeued job advertising a stale failure_reason reads as
            # if it had already failed again.
            fields["completed_at"] = None
            fields["started_at"] = None
            fields["failure_reason"] = None
            fields["task_id"] = None
        fields.update(extra)
        return self.repo.update(import_job, **fields)

    def mark_failed(self, import_job_id: UUID, reason: str) -> ImportJob | None:
        """Record a failure without ever forcing an illegal transition.

        A job that already reached a terminal state is left untouched: a
        duplicate or late worker delivery must not overwrite a ``completed``
        result, and re-failing an already ``failed`` job is a no-op rather than
        a forbidden ``failed -> failed`` write.
        """
        import_job = self.repo.get_by_id(import_job_id)
        if not import_job:
            return None
        if import_job.status in TERMINAL_STATUSES:
            logger.warning(
                "ignoring failure for job already in a terminal state",
                extra={"import_job_id": str(import_job_id), "import_status": import_job.status},
            )
            return import_job
        return self.set_status(import_job_id, "failed", failure_reason=reason[:2000])

    def mark_pending_for_retry(self, import_job_id: UUID) -> ImportJob:
        """Hand a job back to the queue and open a new attempt.

        Bumping ``retry_count`` here is what versions the error report: errors
        recorded from now on carry the new attempt number instead of piling up
        alongside the previous attempt's rows.
        """
        import_job = self.get(import_job_id)
        return self.set_status(
            import_job_id,
            "pending",
            retry_count=import_job.retry_count + 1,
            task_id=None,
        )

    def is_runnable(self, import_job: ImportJob) -> bool:
        return import_job.status in RUNNABLE_STATUSES

    def get(self, import_job_id: UUID) -> ImportJob:
        import_job = self.repo.get_by_id(import_job_id)
        if not import_job:
            raise NotFoundError("import job not found")
        return import_job

    def list(self, limit: int = 100, offset: int = 0) -> list[ImportJob]:
        return self.repo.list(limit=limit, offset=offset)
