from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from clinical_data_platform.config import DEFAULT_SOURCE_NAMESPACE
from clinical_data_platform.exceptions import ConflictError, NotFoundError
from clinical_data_platform.models import Patient
from clinical_data_platform.repositories import PatientRepository


class PatientService:
    def __init__(self, session: Session) -> None:
        self.repo = PatientRepository(session)

    def create(
        self,
        external_id: str,
        birth_date: date | None = None,
        sex: str | None = None,
        source_namespace: str = DEFAULT_SOURCE_NAMESPACE,
    ) -> Patient:
        if self.repo.get_by_identity(source_namespace, external_id):
            raise ConflictError("patient external_id already exists in this source namespace")
        return self.repo.create(
            Patient(
                source_namespace=source_namespace,
                external_id=external_id,
                birth_date=birth_date,
                sex=sex,
            )
        )

    def get(self, patient_id) -> Patient:
        patient = self.repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundError("patient not found")
        return patient

    def list(self, limit: int = 100, offset: int = 0) -> list[Patient]:
        return self.repo.list(limit=limit, offset=offset)

    def update(self, patient_id, **fields: object) -> Patient:
        patient = self.get(patient_id)
        # A PATCH body may carry an explicit null; dropping the key keeps
        # it from being stringified to "None" and then written as NULL.
        if fields.get("source_namespace") is None:
            fields.pop("source_namespace", None)
        namespace = str(fields.get("source_namespace", patient.source_namespace))
        external_id = fields.get("external_id", patient.external_id)
        identity_changed = (namespace, external_id) != (patient.source_namespace, patient.external_id)
        if identity_changed and self.repo.get_by_identity(namespace, str(external_id)):
            raise ConflictError("patient external_id already exists in this source namespace")
        return self.repo.update(patient, **fields)
