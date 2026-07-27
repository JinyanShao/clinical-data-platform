from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.models import ResearchStudy


class ResearchStudyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, study: ResearchStudy) -> ResearchStudy:
        self.session.add(study)
        self.session.flush()
        return study

    def get_by_id(self, study_id: UUID) -> ResearchStudy | None:
        return self.session.get(ResearchStudy, study_id)

    def get_by_identity(self, source_namespace: str, external_id: str) -> ResearchStudy | None:
        return self.session.scalar(
            sa.select(ResearchStudy).where(
                ResearchStudy.source_namespace == source_namespace,
                ResearchStudy.external_id == external_id,
            )
        )

    def list(self, limit: int = 100, offset: int = 0) -> list[ResearchStudy]:
        statement = (
            sa.select(ResearchStudy)
            .order_by(ResearchStudy.created_at.desc(), ResearchStudy.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def update(self, study: ResearchStudy, **fields: object) -> ResearchStudy:
        for key, value in fields.items():
            setattr(study, key, value)
        self.session.flush()
        return study

    def delete(self, study: ResearchStudy) -> None:
        self.session.delete(study)
        self.session.flush()
