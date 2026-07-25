from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.models import ImportJob


class ImportJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, import_job: ImportJob) -> ImportJob:
        self.session.add(import_job)
        self.session.flush()
        return import_job

    def get_by_id(self, import_job_id: UUID) -> ImportJob | None:
        return self.session.get(ImportJob, import_job_id)

    def get_by_checksum(self, checksum: str) -> ImportJob | None:
        return self.session.scalar(sa.select(ImportJob).where(ImportJob.file_checksum == checksum))

    def list(self, limit: int = 100, offset: int = 0) -> list[ImportJob]:
        return list(self.session.scalars(sa.select(ImportJob).offset(offset).limit(limit)))

    def update(self, import_job: ImportJob, **fields: object) -> ImportJob:
        for key, value in fields.items():
            setattr(import_job, key, value)
        self.session.flush()
        return import_job

    def delete(self, import_job: ImportJob) -> None:
        self.session.delete(import_job)
        self.session.flush()
