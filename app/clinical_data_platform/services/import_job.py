from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.exceptions import BusinessRuleError, NotFoundError
from clinical_data_platform.models import ImportJob
from clinical_data_platform.repositories import ImportJobRepository


class ImportJobService:
    transitions = {
        "pending": {"processing", "failed"},
        "processing": {"completed", "partial", "failed"},
        "completed": set(),
        "partial": set(),
        "failed": {"pending"},
    }

    def __init__(self, session: Session) -> None:
        self.repo = ImportJobRepository(session)

    def create(
        self,
        source_type: str,
        filename: str,
        total_records: int = 0,
        file_checksum: str | None = None,
        payload: bytes | None = None,
        study_id: UUID | None = None,
    ) -> ImportJob:
        return self.repo.create(
            ImportJob(
                source_type=source_type,
                filename=filename,
                total_records=total_records,
                file_checksum=file_checksum,
                payload=payload,
                study_id=study_id,
            )
        )

    def set_status(self, import_job_id: UUID, status: str) -> ImportJob:
        import_job = self.repo.get_by_id(import_job_id)
        if not import_job:
            raise NotFoundError("import job not found")
        if status not in self.transitions[import_job.status]:
            raise BusinessRuleError(f"cannot transition import job from {import_job.status} to {status}")

        fields: dict[str, object] = {"status": status}
        if status == "processing":
            fields["started_at"] = datetime.now(UTC)
            fields["failure_reason"] = None
            fields["completed_at"] = None
        if status in {"completed", "failed"}:
            fields["completed_at"] = datetime.now(UTC)
        if status == "partial":
            fields["completed_at"] = datetime.now(UTC)
        return self.repo.update(import_job, **fields)

    def get(self, import_job_id: UUID) -> ImportJob:
        import_job = self.repo.get_by_id(import_job_id)
        if not import_job:
            raise NotFoundError("import job not found")
        return import_job

    def list(self, limit: int = 100, offset: int = 0) -> list[ImportJob]:
        return self.repo.list(limit=limit, offset=offset)
