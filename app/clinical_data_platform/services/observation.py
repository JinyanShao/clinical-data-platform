from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from clinical_data_platform.exceptions import BusinessRuleError, ConflictError, NotFoundError
from clinical_data_platform.models import Observation
from clinical_data_platform.repositories import (
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
        self._validate(patient_id, encounter_id, code, code_system, value, unit)
        if self.repo.get_by_external_id(external_id):
            raise ConflictError("observation external_id already exists")
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

    def get(self, observation_id: UUID) -> Observation:
        observation = self.repo.get_by_id(observation_id)
        if not observation:
            raise NotFoundError("observation not found")
        return observation

    def list(self, limit: int = 100, offset: int = 0) -> list[Observation]:
        return self.repo.list(limit=limit, offset=offset)

    def update(self, observation_id: UUID, **fields: object) -> Observation:
        observation = self.get(observation_id)
        patient_id = fields.get("patient_id", observation.patient_id)
        encounter_id = fields.get("encounter_id", observation.encounter_id)
        code = fields.get("code", observation.code)
        code_system = fields.get("code_system", observation.code_system)
        value = fields.get("value", observation.value)
        unit = fields.get("unit", observation.unit)
        self._validate(patient_id, encounter_id, code, code_system, value, unit)
        external_id = fields.get("external_id")
        if external_id and external_id != observation.external_id and self.repo.get_by_external_id(str(external_id)):
            raise ConflictError("observation external_id already exists")
        return self.repo.update(observation, **fields)

    def _validate(
        self,
        patient_id: UUID,
        encounter_id: UUID | None,
        code: str,
        code_system: str,
        value: str,
        unit: str | None,
    ) -> None:
        if not self.patients.get_by_id(patient_id):
            raise NotFoundError("patient not found")
        if encounter_id:
            encounter = self.encounters.get_by_id(encounter_id)
            if not encounter:
                raise NotFoundError("encounter not found")
            if encounter.patient_id != patient_id:
                raise BusinessRuleError("encounter belongs to a different patient")
        if not code.strip() or not code_system.strip() or not value.strip():
            raise BusinessRuleError("observation code, code_system, and value are required")
        if unit is not None and not unit.strip():
            raise BusinessRuleError("observation unit cannot be blank")
