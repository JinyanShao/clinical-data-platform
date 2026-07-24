from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from clinical_research_data_platform.models import Patient
from clinical_research_data_platform.repositories import PatientRepository


class PatientService:
    def __init__(self, session: Session) -> None:
        self.repo = PatientRepository(session)

    def create(self, external_id: str, birth_date: date | None = None, sex: str | None = None) -> Patient:
        if self.repo.get_by_external_id(external_id):
            raise ValueError("patient external_id already exists")
        return self.repo.create(Patient(external_id=external_id, birth_date=birth_date, sex=sex))

