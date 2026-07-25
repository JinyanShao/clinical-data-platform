from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from clinical_data_platform.models import ImportError, ImportJob, SourceRecord
from clinical_data_platform.repositories import (
    EncounterRepository,
    ImportJobRepository,
    ObservationRepository,
    PatientRepository,
    ResearchStudyRepository,
)
from clinical_data_platform.services.encounter import EncounterService
from clinical_data_platform.services.import_job import ImportJobService
from clinical_data_platform.services.observation import ObservationService
from clinical_data_platform.services.patient import PatientService
from clinical_data_platform.services.research_study import ResearchStudyService


class ImportRecordError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


@dataclass(frozen=True)
class PatientData:
    external_id: str
    birth_date: date | None = None
    sex: str | None = None


@dataclass(frozen=True)
class EncounterData:
    external_id: str
    patient_external_id: str
    status: str
    encounter_type: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class ObservationData:
    external_id: str
    patient_external_id: str
    encounter_external_id: str | None
    code: str
    code_system: str
    value: str
    unit: str | None
    observed_at: datetime
    status: str


@dataclass(frozen=True)
class ResearchStudyData:
    external_id: str
    title: str
    description: str | None
    status: str


@dataclass(frozen=True)
class ImportRecord:
    source_row: int
    raw_data: dict
    patient: PatientData | None = None
    encounter: EncounterData | None = None
    observation: ObservationData | None = None
    research_study: ResearchStudyData | None = None
    error: ImportRecordError | None = None


@dataclass(frozen=True)
class ImportBatch:
    records: list[ImportRecord]
    fatal_error: ImportRecordError | None = None


class ImportParser(Protocol):
    def parse(self, content: bytes) -> ImportBatch: ...


class ImportPipelineService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = ImportJobRepository(session)
        self.job_service = ImportJobService(session)
        self.patients = PatientRepository(session)
        self.encounters = EncounterRepository(session)
        self.observations = ObservationRepository(session)
        self.studies = ResearchStudyRepository(session)

    def enqueue(
        self,
        source_type: str,
        filename: str,
        content: bytes,
        study_id=None,
    ) -> ImportJob:
        file_checksum = hashlib.sha256(content).hexdigest()
        existing_job = self.jobs.get_by_checksum(file_checksum)
        if existing_job:
            return existing_job
        return self.job_service.create(
            source_type,
            filename,
            file_checksum=file_checksum,
            payload=content,
            study_id=study_id,
        )

    def process(self, job: ImportJob, parser: ImportParser) -> ImportJob:
        if not job.payload:
            raise ValueError("import payload is missing")
        self.job_service.set_status(job.id, "processing")
        batch = parser.parse(job.payload)
        if batch.fatal_error:
            self._record_error(job, 1, batch.fatal_error)
            self.jobs.update(job, failed_records=1, failure_reason=str(batch.fatal_error))
            return self.job_service.set_status(job.id, "failed")

        self.jobs.update(job, total_records=len(batch.records))
        successful = 0
        for record in batch.records:
            if record.error:
                self._record_error(job, record.source_row, record.error)
                continue
            try:
                with self.session.begin_nested():
                    self._persist_record(job, record, job.file_checksum or "")
                successful += 1
            except ImportRecordError as exc:
                self._record_error(job, record.source_row, exc)

        self.jobs.update(
            job,
            successful_records=successful,
            failed_records=len(batch.records) - successful,
        )
        return self.job_service.set_status(job.id, "partial" if successful < len(batch.records) else "completed")

    def _persist_record(self, job: ImportJob, record: ImportRecord, file_checksum: str) -> None:
        if record.patient:
            patient = self._patient(job, record, record.patient, file_checksum)
            if job.study_id:
                self._bind_subject(job.study_id, patient.id)
        if record.research_study:
            self._study(job, record, record.research_study, file_checksum)
        if record.encounter:
            self._encounter(job, record, record.encounter, file_checksum)
        if record.observation:
            self._observation(job, record, record.observation, file_checksum)

    def _patient(self, job, record, data: PatientData, checksum):
        patient = self.patients.get_by_external_id(data.external_id)
        if patient:
            if data.birth_date is not None and patient.birth_date != data.birth_date:
                raise ImportRecordError("birth_date", "DATA_CONFLICT", "Patient birth date does not match existing data")
            if data.sex is not None and patient.sex != data.sex:
                raise ImportRecordError("sex", "DATA_CONFLICT", "Patient sex does not match existing data")
            return patient
        patient = PatientService(self.session).create(data.external_id, data.birth_date, data.sex)
        self._source(job, record, "patient", patient.id, checksum)
        return patient

    def _encounter(self, job, record, data: EncounterData, checksum):
        patient = self.patients.get_by_external_id(data.patient_external_id)
        if not patient:
            raise ImportRecordError("patient_reference", "INVALID_REFERENCE", "Referenced Patient was not found")
        if job.study_id:
            self._bind_subject(job.study_id, patient.id)
        if data.started_at and data.ended_at and data.ended_at < data.started_at:
            raise ImportRecordError("ended_at", "INVALID_TIME_RANGE", "Encounter end cannot be before start")

        encounter = self.encounters.get_by_external_id(data.external_id)
        if encounter:
            if encounter.patient_id != patient.id:
                raise ImportRecordError("encounter_external_id", "DATA_CONFLICT", "Encounter belongs to a different patient")
            return encounter
        encounter = EncounterService(self.session).create(
            patient_id=patient.id,
            external_id=data.external_id,
            status=data.status,
            encounter_type=data.encounter_type,
            started_at=data.started_at,
            ended_at=data.ended_at,
        )
        self._source(job, record, "encounter", encounter.id, checksum)
        return encounter

    def _observation(self, job, record, data: ObservationData, checksum):
        patient = self.patients.get_by_external_id(data.patient_external_id)
        if not patient:
            raise ImportRecordError("patient_reference", "INVALID_REFERENCE", "Referenced Patient was not found")
        if job.study_id:
            self._bind_subject(job.study_id, patient.id)
        encounter = None
        if data.encounter_external_id:
            encounter = self.encounters.get_by_external_id(data.encounter_external_id)
            if not encounter:
                raise ImportRecordError("encounter_reference", "INVALID_REFERENCE", "Referenced Encounter was not found")
            if encounter.patient_id != patient.id:
                raise ImportRecordError("encounter_reference", "INVALID_REFERENCE", "Encounter belongs to a different Patient")

        observation = self.observations.get_by_external_id(data.external_id)
        if observation:
            if observation.patient_id != patient.id or observation.encounter_id != (encounter.id if encounter else None):
                raise ImportRecordError("observation_external_id", "DATA_CONFLICT", "Observation links do not match existing data")
            if observation.code != data.code or observation.code_system != data.code_system or observation.value != data.value:
                raise ImportRecordError("observation_external_id", "DATA_CONFLICT", "Observation does not match existing data")
            return observation
        observation = ObservationService(self.session).create(
            patient_id=patient.id,
            encounter_id=encounter.id if encounter else None,
            external_id=data.external_id,
            code=data.code,
            code_system=data.code_system,
            value=data.value,
            unit=data.unit,
            observed_at=data.observed_at,
            status=data.status,
        )
        self._source(job, record, "observation", observation.id, checksum)
        return observation

    def _study(self, job, record, data: ResearchStudyData, checksum):
        study = self.studies.get_by_external_id(data.external_id)
        if study:
            if study.title != data.title:
                raise ImportRecordError("title", "DATA_CONFLICT", "ResearchStudy title does not match existing data")
            return study
        study = ResearchStudyService(self.session).create(
            external_id=data.external_id,
            title=data.title,
            description=data.description,
            status=data.status,
        )
        self._source(job, record, "research_study", study.id, checksum)
        return study

    def _source(self, job, record: ImportRecord, resource_type, resource_id, file_checksum) -> None:
        checksum = hashlib.sha256(
            f"{file_checksum}:{record.source_row}:{resource_type}".encode()
        ).hexdigest()
        self.session.add(
            SourceRecord(
                import_job_id=job.id,
                resource_type=resource_type,
                resource_id=resource_id,
                source_row=record.source_row,
                raw_data=record.raw_data,
                checksum=checksum,
            )
        )
        self.session.flush()

    def _record_error(self, job: ImportJob, row_number: int, exc: ImportRecordError) -> None:
        self.session.add(
            ImportError(
                import_job_id=job.id,
                source_row=row_number,
                field=exc.field,
                code=exc.code,
                message=str(exc),
            )
        )
        self.session.flush()

    def _bind_subject(self, study_id, patient_id) -> None:
        from clinical_data_platform.services.security import StudyAccessService

        StudyAccessService(self.session).add_subject(study_id, patient_id)


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ImportRecordError(field, "INVALID_DATE", "Expected an ISO date (YYYY-MM-DD)") from exc


def parse_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ImportRecordError(field, "INVALID_DATETIME", "Expected an ISO 8601 datetime") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
