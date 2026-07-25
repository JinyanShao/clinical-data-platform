from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

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
    ) -> Encounter:
        if not self.patients.get_by_id(patient_id):
            raise NotFoundError("patient not found")
        if started_at and ended_at and ended_at < started_at:
            raise BusinessRuleError("encounter ended_at cannot be before started_at")
        if self.repo.get_by_external_id(external_id):
            raise ConflictError("encounter external_id already exists")
        return self.repo.create(
            Encounter(
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
        external_id = fields.get("external_id")
        if external_id and external_id != encounter.external_id and self.repo.get_by_external_id(str(external_id)):
            raise ConflictError("encounter external_id already exists")
        return self.repo.update(encounter, **fields)
