from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.models import Patient


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, patient: Patient) -> Patient:
        self.session.add(patient)
        self.session.flush()
        return patient

    def get_by_id(self, patient_id: UUID) -> Patient | None:
        return self.session.get(Patient, patient_id)

    def get_by_external_id(self, external_id: str) -> Patient | None:
        return self.session.scalar(sa.select(Patient).where(Patient.external_id == external_id))

    def list(self, limit: int = 100, offset: int = 0) -> list[Patient]:
        return list(self.session.scalars(sa.select(Patient).offset(offset).limit(limit)))

    def update(self, patient: Patient, **fields: object) -> Patient:
        for key, value in fields.items():
            setattr(patient, key, value)
        self.session.flush()
        return patient

    def delete(self, patient: Patient) -> None:
        self.session.delete(patient)
        self.session.flush()
