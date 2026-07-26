from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.config import DEFAULT_SOURCE_NAMESPACE
from clinical_data_platform.exceptions import ConflictError, NotFoundError
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
        source_namespace: str = DEFAULT_SOURCE_NAMESPACE,
    ) -> ResearchStudy:
        if external_id and self.repo.get_by_identity(source_namespace, external_id):
            raise ConflictError("research study external_id already exists in this source namespace")
        return self.repo.create(
            ResearchStudy(
                source_namespace=source_namespace,
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
        study = self.get(study_id)
        # A PATCH body may carry an explicit null; dropping the key keeps
        # it from being stringified to "None" and then written as NULL.
        if fields.get("source_namespace") is None:
            fields.pop("source_namespace", None)
        namespace = str(fields.get("source_namespace", study.source_namespace))
        external_id = fields.get("external_id", study.external_id)
        identity_changed = (namespace, external_id) != (study.source_namespace, study.external_id)
        if identity_changed and external_id and self.repo.get_by_identity(namespace, str(external_id)):
            raise ConflictError("research study external_id already exists in this source namespace")
        return self.repo.update(study, **fields)

    def delete(self, study_id: UUID) -> None:
        self.repo.delete(self.get(study_id))
