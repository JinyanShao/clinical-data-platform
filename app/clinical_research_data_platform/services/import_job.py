from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_research_data_platform.models import ImportJob
from clinical_research_data_platform.repositories import ImportJobRepository


class ImportJobService:
    transitions = {
        "pending": {"processing", "failed"},
        "processing": {"completed", "failed"},
        "completed": set(),
        "failed": set(),
    }

    def __init__(self, session: Session) -> None:
        self.repo = ImportJobRepository(session)

    def create(self, source_type: str, filename: str, total_records: int = 0) -> ImportJob:
        return self.repo.create(
            ImportJob(source_type=source_type, filename=filename, total_records=total_records)
        )

    def set_status(self, import_job_id: UUID, status: str) -> ImportJob:
        import_job = self.repo.get_by_id(import_job_id)
        if not import_job:
            raise ValueError("import job does not exist")
        if status not in self.transitions[import_job.status]:
            raise ValueError(f"cannot transition import job from {import_job.status} to {status}")

        fields: dict[str, object] = {"status": status}
        if status == "processing":
            fields["started_at"] = datetime.now(timezone.utc)
        if status in {"completed", "failed"}:
            fields["completed_at"] = datetime.now(timezone.utc)
        return self.repo.update(import_job, **fields)

