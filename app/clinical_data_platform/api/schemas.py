from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from clinical_data_platform.config import DEFAULT_SOURCE_NAMESPACE, study_source_namespace

Sex = Literal["male", "female", "other", "unknown"]
EncounterStatus = Literal["planned", "in-progress", "finished", "cancelled", "entered-in-error", "unknown"]
ObservationStatus = Literal[
    "registered",
    "preliminary",
    "final",
    "amended",
    "corrected",
    "cancelled",
    "entered-in-error",
    "unknown",
]
ResearchStudyStatus = Literal["draft", "active", "completed", "stopped", "entered-in-error", "unknown"]
ProvenanceResourceType = Literal["patient", "encounter", "observation", "research_study"]
ProvenanceAction = Literal["created", "reasserted"]

SOURCE_NAMESPACE_DESCRIPTION = (
    "Issuing system for external_id, following the FHIR Identifier (system, value) model. "
    "Identity is the pair, so the same local id under two namespaces is two records."
)


class ErrorResponse(BaseModel):
    detail: str
    errors: list[dict[str, object]] | None = None


class PatientCreate(BaseModel):
    external_id: str = Field(min_length=1)
    source_namespace: str = Field(
        default=DEFAULT_SOURCE_NAMESPACE,
        min_length=1,
        description=SOURCE_NAMESPACE_DESCRIPTION,
    )
    birth_date: date | None = None
    sex: Sex | None = None


class PatientUpdate(BaseModel):
    external_id: str | None = Field(default=None, min_length=1)
    source_namespace: str | None = Field(default=None, min_length=1)
    birth_date: date | None = None
    sex: Sex | None = None


class PatientRead(PatientCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class EncounterCreate(BaseModel):
    patient_id: UUID
    external_id: str = Field(min_length=1)
    source_namespace: str = Field(
        default=DEFAULT_SOURCE_NAMESPACE,
        min_length=1,
        description=SOURCE_NAMESPACE_DESCRIPTION,
    )
    status: EncounterStatus
    encounter_type: str = Field(min_length=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class EncounterUpdate(BaseModel):
    patient_id: UUID | None = None
    external_id: str | None = Field(default=None, min_length=1)
    source_namespace: str | None = Field(default=None, min_length=1)
    status: EncounterStatus | None = None
    encounter_type: str | None = Field(default=None, min_length=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class EncounterRead(EncounterCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ObservationCreate(BaseModel):
    patient_id: UUID
    encounter_id: UUID | None = None
    external_id: str = Field(min_length=1)
    source_namespace: str = Field(
        default=DEFAULT_SOURCE_NAMESPACE,
        min_length=1,
        description=SOURCE_NAMESPACE_DESCRIPTION,
    )
    code: str = Field(min_length=1)
    code_system: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: str | None = None
    observed_at: datetime
    status: ObservationStatus


class ObservationUpdate(BaseModel):
    patient_id: UUID | None = None
    encounter_id: UUID | None = None
    external_id: str | None = Field(default=None, min_length=1)
    source_namespace: str | None = Field(default=None, min_length=1)
    code: str | None = Field(default=None, min_length=1)
    code_system: str | None = Field(default=None, min_length=1)
    value: str | None = Field(default=None, min_length=1)
    unit: str | None = None
    observed_at: datetime | None = None
    status: ObservationStatus | None = None


class ObservationRead(ObservationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ResearchStudyCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    status: ResearchStudyStatus


class ResearchStudyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: ResearchStudyStatus | None = None


class ResearchStudyRead(ResearchStudyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str | None
    source_namespace: str
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subject_namespace(self) -> str:
        """Namespace applied to records imported under this study by default.

        Exposed so a caller pre-creating resources through the API can put them
        in the namespace a later study-scoped import will resolve against.
        """
        return study_source_namespace(self.id)


class ImportErrorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_row: int = Field(serialization_alias="row")
    #: Processing attempt that produced this error. Compare against
    #: ``ImportJobRead.retry_count`` to isolate the current attempt.
    attempt: int
    field: str
    code: str
    message: str


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: str
    filename: str
    status: str
    total_records: int
    successful_records: int
    failed_records: int
    study_id: UUID | None
    source_namespace: str
    file_checksum: str | None
    idempotency_key: str | None
    task_id: str | None
    failure_reason: str | None
    retry_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    #: Every attempt's errors, newest attempt first. Retries version this list
    #: via ``attempt`` rather than appending duplicates to it.
    errors: list[ImportErrorRead] = Field(default_factory=list)


Role = Literal["admin", "researcher", "auditor"]


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    role: Role


class UserCreated(BaseModel):
    id: UUID
    username: str
    role: Role
    api_key: str


class StudyAccessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    study_id: UUID
    user_id: UUID
    created_at: datetime


class ResearchSubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    study_id: UUID
    patient_id: UUID
    created_at: datetime


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor: str
    action: str
    resource_type: str
    resource_id: str
    before: dict | None
    after: dict | None
    timestamp: datetime


class SourceRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_job_id: UUID
    resource_type: str
    resource_id: UUID
    source_row: int
    raw_data: dict
    checksum: str
    #: ``created`` for the import that first materialised the resource,
    #: ``reasserted`` for later imports that observed it again.
    action: ProvenanceAction
    created_at: datetime


class ProvenanceEventRead(SourceRecordRead):
    """One provenance event enriched with the originating import's context."""

    import_filename: str
    import_source_type: str
    import_study_id: UUID | None
    import_source_namespace: str
