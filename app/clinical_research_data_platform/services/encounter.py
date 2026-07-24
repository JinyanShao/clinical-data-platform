from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_research_data_platform.models import Encounter
from clinical_research_data_platform.repositories import EncounterRepository, PatientRepository


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
            raise ValueError("patient does not exist")
        if started_at and ended_at and ended_at < started_at:
            raise ValueError("encounter ended_at cannot be before started_at")
        if self.repo.get_by_external_id(external_id):
            raise ValueError("encounter external_id already exists")
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

