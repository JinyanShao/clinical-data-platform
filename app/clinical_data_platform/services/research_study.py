from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.exceptions import NotFoundError
from clinical_data_platform.models import ResearchStudy
from clinical_data_platform.repositories import ResearchStudyRepository


class ResearchStudyService:
    def __init__(self, session: Session) -> None:
        self.repo = ResearchStudyRepository(session)

    def create(
        self,
        title: str,
        status: str,
        description: str | None = None,
        external_id: str | None = None,
    ) -> ResearchStudy:
        return self.repo.create(
            ResearchStudy(
                external_id=external_id,
                title=title,
                description=description,
                status=status,
            )
        )

    def get(self, study_id: UUID) -> ResearchStudy:
        study = self.repo.get_by_id(study_id)
        if not study:
            raise NotFoundError("research study not found")
        return study

    def list(self, limit: int = 100, offset: int = 0) -> list[ResearchStudy]:
        return self.repo.list(limit=limit, offset=offset)

    def update(self, study_id: UUID, **fields: object) -> ResearchStudy:
        return self.repo.update(self.get(study_id), **fields)

    def delete(self, study_id: UUID) -> None:
        self.repo.delete(self.get(study_id))
