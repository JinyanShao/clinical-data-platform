from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from clinical_data_platform.exceptions import ConflictError, NotFoundError
from clinical_data_platform.models import Patient
from clinical_data_platform.repositories import PatientRepository


class PatientService:
    def __init__(self, session: Session) -> None:
        self.repo = PatientRepository(session)

    def create(self, external_id: str, birth_date: date | None = None, sex: str | None = None) -> Patient:
        if self.repo.get_by_external_id(external_id):
            raise ConflictError("patient external_id already exists")
        return self.repo.create(Patient(external_id=external_id, birth_date=birth_date, sex=sex))

    def get(self, patient_id) -> Patient:
        patient = self.repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundError("patient not found")
        return patient

    def list(self, limit: int = 100, offset: int = 0) -> list[Patient]:
        return self.repo.list(limit=limit, offset=offset)

    def update(self, patient_id, **fields: object) -> Patient:
        patient = self.get(patient_id)
        external_id = fields.get("external_id")
        if external_id and external_id != patient.external_id and self.repo.get_by_external_id(str(external_id)):
            raise ConflictError("patient external_id already exists")
        return self.repo.update(patient, **fields)
