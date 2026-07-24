from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_research_data_platform.models import Observation
from clinical_research_data_platform.repositories import (
    EncounterRepository,
    ObservationRepository,
    PatientRepository,
)


class ObservationService:
    def __init__(self, session: Session) -> None:
        self.repo = ObservationRepository(session)
        self.encounters = EncounterRepository(session)
        self.patients = PatientRepository(session)

    def create(
        self,
        patient_id: UUID,
        external_id: str,
        code: str,
        code_system: str,
        value: str,
        observed_at: datetime,
        status: str,
        unit: str | None = None,
        encounter_id: UUID | None = None,
    ) -> Observation:
        if not self.patients.get_by_id(patient_id):
            raise ValueError("patient does not exist")
        if encounter_id:
            encounter = self.encounters.get_by_id(encounter_id)
            if not encounter:
                raise ValueError("encounter does not exist")
            if encounter.patient_id != patient_id:
                raise ValueError("encounter belongs to a different patient")
        if not code.strip() or not code_system.strip() or not value.strip():
            raise ValueError("observation code, code_system, and value are required")
        if unit is not None and not unit.strip():
            raise ValueError("observation unit cannot be blank")
        if self.repo.get_by_external_id(external_id):
            raise ValueError("observation external_id already exists")
        return self.repo.create(
            Observation(
                patient_id=patient_id,
                encounter_id=encounter_id,
                external_id=external_id,
                code=code,
                code_system=code_system,
                value=value,
                unit=unit,
                observed_at=observed_at,
                status=status,
            )
        )

