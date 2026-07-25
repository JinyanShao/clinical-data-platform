from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class ErrorResponse(BaseModel):
    detail: str
    errors: list[dict[str, object]] | None = None


class PatientCreate(BaseModel):
    external_id: str = Field(min_length=1)
    birth_date: date | None = None
    sex: Sex | None = None


class PatientUpdate(BaseModel):
    external_id: str | None = Field(default=None, min_length=1)
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
    status: EncounterStatus
    encounter_type: str = Field(min_length=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class EncounterUpdate(BaseModel):
    patient_id: UUID | None = None
    external_id: str | None = Field(default=None, min_length=1)
    status: EncounterStatus | None = None
    encounter_type: str | None = Field(default=None, min_length=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class EncounterRead(EncounterCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class ObservationCreate(BaseModel):
    patient_id: UUID
    encounter_id: UUID | None = None
    external_id: str = Field(min_length=1)
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
    code: str | None = Field(default=None, min_length=1)
    code_system: str | None = Field(default=None, min_length=1)
    value: str | None = Field(default=None, min_length=1)
    unit: str | None = None
    observed_at: datetime | None = None
    status: ObservationStatus | None = None


class ObservationRead(ObservationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


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


class ImportErrorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_row: int = Field(serialization_alias="row")
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
    task_id: str | None
    failure_reason: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
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
