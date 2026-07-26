from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.config import DEFAULT_SOURCE_NAMESPACE
from clinical_data_platform.exceptions import BusinessRuleError, ConflictError, NotFoundError
from clinical_data_platform.models import Encounter
from clinical_data_platform.repositories import EncounterRepository, PatientRepository


class EncounterService:
    def __init__(self, session: Session) -> None:
        self.repo = EncounterRepository(session)
        self.patients = PatientRepository(session)

    def create(
        self,
        patient_id: UUID,
        external_id: str,
        status: str,
        encounter_type: str,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        source_namespace: str = DEFAULT_SOURCE_NAMESPACE,
    ) -> Encounter:
        if not self.patients.get_by_id(patient_id):
            raise NotFoundError("patient not found")
        if started_at and ended_at and ended_at < started_at:
            raise BusinessRuleError("encounter ended_at cannot be before started_at")
        if self.repo.get_by_identity(source_namespace, external_id):
            raise ConflictError("encounter external_id already exists in this source namespace")
        return self.repo.create(
            Encounter(
                source_namespace=source_namespace,
                patient_id=patient_id,
                external_id=external_id,
                status=status,
                encounter_type=encounter_type,
                started_at=started_at,
                ended_at=ended_at,
            )
        )

    def get(self, encounter_id: UUID) -> Encounter:
        encounter = self.repo.get_by_id(encounter_id)
        if not encounter:
            raise NotFoundError("encounter not found")
        return encounter

    def list(self, limit: int = 100, offset: int = 0) -> list[Encounter]:
        return self.repo.list(limit=limit, offset=offset)

    def update(self, encounter_id: UUID, **fields: object) -> Encounter:
        encounter = self.get(encounter_id)
        patient_id = fields.get("patient_id", encounter.patient_id)
        if not self.patients.get_by_id(patient_id):
            raise NotFoundError("patient not found")
        started_at = fields.get("started_at", encounter.started_at)
        ended_at = fields.get("ended_at", encounter.ended_at)
        if started_at and ended_at and ended_at < started_at:
            raise BusinessRuleError("encounter ended_at cannot be before started_at")
        # A PATCH body may carry an explicit null; dropping the key keeps
        # it from being stringified to "None" and then written as NULL.
        if fields.get("source_namespace") is None:
            fields.pop("source_namespace", None)
        namespace = str(fields.get("source_namespace", encounter.source_namespace))
        external_id = fields.get("external_id", encounter.external_id)
        identity_changed = (namespace, external_id) != (encounter.source_namespace, encounter.external_id)
        if identity_changed and self.repo.get_by_identity(namespace, str(external_id)):
            raise ConflictError("encounter external_id already exists in this source namespace")
        return self.repo.update(encounter, **fields)
