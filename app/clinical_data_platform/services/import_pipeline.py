from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.config import resolve_source_namespace
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


def build_idempotency_key(file_checksum: str, study_id: object | None, source_namespace: str) -> str:
    """Idempotency key for an import.

    Keyed on the payload *and* its destination. Two uploads of identical bytes
    aimed at different studies or namespaces are genuinely different imports;
    keying on the payload alone made the second one silently reuse the first
    one's job, so its patients were never bound to the second study.
    """
    material = f"{file_checksum}|{study_id or ''}|{source_namespace}"
    return hashlib.sha256(material.encode()).hexdigest()


def values_match(stored: str, incoming: str) -> bool:
    """Compare observation values numerically where both sides are numeric.

    Values are stored verbatim for provenance fidelity, so a re-import of the
    same measurement formatted as ``1.50`` rather than ``1.5`` used to raise a
    spurious DATA_CONFLICT.
    """
    if stored == incoming:
        return True
    try:
        return Decimal(stored) == Decimal(incoming)
    except (InvalidOperation, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class PatientData:
    external_id: str
    birth_date: date | None = None
    sex: str | None = None
    #: Issuing system declared by the source, if any. Falls back to the job's
    #: namespace when absent.
    source_namespace: str | None = None


@dataclass(frozen=True)
class EncounterData:
    external_id: str
    patient_external_id: str
    status: str
    encounter_type: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    source_namespace: str | None = None
    patient_namespace: str | None = None


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
    source_namespace: str | None = None
    patient_namespace: str | None = None
    encounter_namespace: str | None = None


@dataclass(frozen=True)
class ResearchStudyData:
    external_id: str
    title: str
    description: str | None
    status: str
    source_namespace: str | None = None


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
        #: (source_row, resource_type, resource_id) -> action recorded by a
        #: previous attempt of the job currently being processed.
        self._prior_actions: dict[tuple[int, str, str], str] = {}

    def enqueue(
        self,
        source_type: str,
        filename: str,
        content: bytes,
        study_id=None,
        source_namespace: str | None = None,
    ) -> ImportJob:
        file_checksum = hashlib.sha256(content).hexdigest()
        namespace = resolve_source_namespace(source_namespace, study_id)
        idempotency_key = build_idempotency_key(file_checksum, study_id, namespace)
        existing_job = self.jobs.get_by_idempotency_key(idempotency_key)
        if existing_job:
            # Re-uploading after a failure should retry rather than silently
            # hand back the failed job and do nothing.
            if existing_job.status == "failed":
                return self.job_service.mark_pending_for_retry(existing_job.id)
            return existing_job
        return self.job_service.create(
            source_type,
            filename,
            file_checksum=file_checksum,
            idempotency_key=idempotency_key,
            source_namespace=namespace,
            payload=content,
            study_id=study_id,
        )

    def process(self, job: ImportJob, parser: ImportParser) -> ImportJob:
        if not job.payload:
            raise ValueError("import payload is missing")
        self.job_service.set_status(job.id, "processing")
        attempt = job.retry_count
        # This job's own rows are rewritten from scratch on every attempt: that
        # keeps (job, row, resource) unique and stops a redelivered task from
        # duplicating error rows within one attempt. Other imports' provenance
        # for the same resources is left untouched.
        self._reset_attempt(job, attempt)

        batch = parser.parse(job.payload)
        if batch.fatal_error:
            self._record_error(job, 1, batch.fatal_error, attempt)
            self.jobs.update(
                job,
                total_records=0,
                successful_records=0,
                failed_records=1,
                failure_reason=str(batch.fatal_error),
            )
            return self.job_service.set_status(job.id, "failed")

        self.jobs.update(job, total_records=len(batch.records))
        successful = 0
        for record in batch.records:
            if record.error:
                self._record_error(job, record.source_row, record.error, attempt)
                continue
            try:
                with self.session.begin_nested():
                    self._persist_record(job, record)
                successful += 1
            except ImportRecordError as exc:
                self._record_error(job, record.source_row, exc, attempt)

        self.jobs.update(
            job,
            successful_records=successful,
            failed_records=len(batch.records) - successful,
        )
        return self.job_service.set_status(
            job.id, "partial" if successful < len(batch.records) else "completed"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_record(self, job: ImportJob, record: ImportRecord) -> None:
        if record.patient:
            patient = self._patient(job, record, record.patient)
            if job.study_id:
                self._bind_subject(job.study_id, patient.id)
        if record.research_study:
            self._study(job, record, record.research_study)
        if record.encounter:
            self._encounter(job, record, record.encounter)
        if record.observation:
            self._observation(job, record, record.observation)

    def _namespace(self, job: ImportJob, declared: str | None) -> str:
        return declared or job.source_namespace

    def _patient(self, job: ImportJob, record: ImportRecord, data: PatientData):
        namespace = self._namespace(job, data.source_namespace)
        patient = self.patients.get_by_identity(namespace, data.external_id)
        if patient:
            if data.birth_date is not None and patient.birth_date != data.birth_date:
                raise ImportRecordError("birth_date", "DATA_CONFLICT", "Patient birth date does not match existing data")
            if data.sex is not None and patient.sex != data.sex:
                raise ImportRecordError("sex", "DATA_CONFLICT", "Patient sex does not match existing data")
            self._source(job, record, "patient", patient.id, action="reasserted")
            return patient
        patient = PatientService(self.session).create(
            data.external_id, data.birth_date, data.sex, source_namespace=namespace
        )
        self._source(job, record, "patient", patient.id, action="created")
        return patient

    def _encounter(self, job: ImportJob, record: ImportRecord, data: EncounterData):
        namespace = self._namespace(job, data.source_namespace)
        patient_namespace = self._namespace(job, data.patient_namespace)
        patient = self.patients.get_by_identity(patient_namespace, data.patient_external_id)
        if not patient:
            raise ImportRecordError("patient_reference", "INVALID_REFERENCE", "Referenced Patient was not found")
        if job.study_id:
            self._bind_subject(job.study_id, patient.id)
        if data.started_at and data.ended_at and data.ended_at < data.started_at:
            raise ImportRecordError("ended_at", "INVALID_TIME_RANGE", "Encounter end cannot be before start")

        encounter = self.encounters.get_by_identity(namespace, data.external_id)
        if encounter:
            if encounter.patient_id != patient.id:
                raise ImportRecordError("encounter_external_id", "DATA_CONFLICT", "Encounter belongs to a different patient")
            self._source(job, record, "encounter", encounter.id, action="reasserted")
            return encounter
        encounter = EncounterService(self.session).create(
            patient_id=patient.id,
            external_id=data.external_id,
            status=data.status,
            encounter_type=data.encounter_type,
            started_at=data.started_at,
            ended_at=data.ended_at,
            source_namespace=namespace,
        )
        self._source(job, record, "encounter", encounter.id, action="created")
        return encounter

    def _observation(self, job: ImportJob, record: ImportRecord, data: ObservationData):
        namespace = self._namespace(job, data.source_namespace)
        patient_namespace = self._namespace(job, data.patient_namespace)
        patient = self.patients.get_by_identity(patient_namespace, data.patient_external_id)
        if not patient:
            raise ImportRecordError("patient_reference", "INVALID_REFERENCE", "Referenced Patient was not found")
        if job.study_id:
            self._bind_subject(job.study_id, patient.id)
        encounter = None
        if data.encounter_external_id:
            encounter_namespace = self._namespace(job, data.encounter_namespace)
            encounter = self.encounters.get_by_identity(encounter_namespace, data.encounter_external_id)
            if not encounter:
                raise ImportRecordError("encounter_reference", "INVALID_REFERENCE", "Referenced Encounter was not found")
            if encounter.patient_id != patient.id:
                raise ImportRecordError("encounter_reference", "INVALID_REFERENCE", "Encounter belongs to a different Patient")

        observation = self.observations.get_by_identity(namespace, data.external_id)
        if observation:
            if observation.patient_id != patient.id or observation.encounter_id != (encounter.id if encounter else None):
                raise ImportRecordError("observation_external_id", "DATA_CONFLICT", "Observation links do not match existing data")
            if (
                observation.code != data.code
                or observation.code_system != data.code_system
                or not values_match(observation.value, data.value)
            ):
                raise ImportRecordError("observation_external_id", "DATA_CONFLICT", "Observation does not match existing data")
            self._source(job, record, "observation", observation.id, action="reasserted")
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
            source_namespace=namespace,
        )
        self._source(job, record, "observation", observation.id, action="created")
        return observation

    def _study(self, job: ImportJob, record: ImportRecord, data: ResearchStudyData):
        namespace = self._namespace(job, data.source_namespace)
        study = self.studies.get_by_identity(namespace, data.external_id)
        if study:
            if study.title != data.title:
                raise ImportRecordError("title", "DATA_CONFLICT", "ResearchStudy title does not match existing data")
            self._source(job, record, "research_study", study.id, action="reasserted")
            return study
        study = ResearchStudyService(self.session).create(
            external_id=data.external_id,
            title=data.title,
            description=data.description,
            status=data.status,
            source_namespace=namespace,
        )
        self._source(job, record, "research_study", study.id, action="created")
        return study

    # ------------------------------------------------------------------
    # Provenance and error reporting
    # ------------------------------------------------------------------

    def _reset_attempt(self, job: ImportJob, attempt: int) -> None:
        """Clear this job's rows for a fresh attempt, remembering prior actions.

        The action must survive: if an earlier attempt already recorded that
        this import *created* a resource, rewriting it as ``reasserted`` would
        leave no import claiming to have created it at all.
        """
        self._prior_actions = {
            (row, resource_type, str(resource_id)): action
            for row, resource_type, resource_id, action in self.session.execute(
                sa.select(
                    SourceRecord.source_row,
                    SourceRecord.resource_type,
                    SourceRecord.resource_id,
                    SourceRecord.action,
                ).where(SourceRecord.import_job_id == job.id)
            ).all()
        }
        self.session.execute(
            sa.delete(SourceRecord).where(SourceRecord.import_job_id == job.id),
            execution_options={"synchronize_session": False},
        )
        self.session.execute(
            sa.delete(ImportError).where(
                ImportError.import_job_id == job.id,
                ImportError.attempt == attempt,
            ),
            execution_options={"synchronize_session": False},
        )
        self.session.flush()
        self.session.expire(job, ["source_records"])
        self.session.expire(job, ["errors"])

    def _source(
        self,
        job: ImportJob,
        record: ImportRecord,
        resource_type: str,
        resource_id,
        action: str,
    ) -> None:
        """Append one provenance event.

        Written for re-assertions as well as first creation, so the history
        answers "which imports touched this resource, from which source row,
        and when" rather than only recording its origin.
        """
        checksum = hashlib.sha256(
            f"{job.file_checksum or ''}:{record.source_row}:{resource_type}:{resource_id}".encode()
        ).hexdigest()
        prior = self._prior_actions.get((record.source_row, resource_type, str(resource_id)))
        if prior == "created":
            action = "created"
        self.session.add(
            SourceRecord(
                import_job_id=job.id,
                resource_type=resource_type,
                resource_id=resource_id,
                source_row=record.source_row,
                raw_data=record.raw_data,
                checksum=checksum,
                action=action,
            )
        )
        self.session.flush()

    def _record_error(
        self, job: ImportJob, row_number: int, exc: ImportRecordError, attempt: int
    ) -> None:
        self.session.add(
            ImportError(
                import_job_id=job.id,
                attempt=attempt,
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
