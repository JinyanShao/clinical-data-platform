from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_data_platform.db import Base

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        onupdate=sa.func.current_timestamp(),
    )


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    birth_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(Text, nullable=True)

    encounters: Mapped[list[Encounter]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    observations: Mapped[list[Observation]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    research_subjects: Mapped[list[ResearchSubject]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "sex IS NULL OR sex IN ('male', 'female', 'other', 'unknown')",
            name="sex_valid",
        ),
    )


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    encounter_type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    patient: Mapped[Patient] = relationship(back_populates="encounters")
    observations: Mapped[list[Observation]] = relationship(back_populates="encounter")

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('planned', 'in-progress', 'finished', 'cancelled', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="date_order_valid",
        ),
        sa.Index("ix_encounters_patient_id", "patient_id"),
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("encounters.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    code_system: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    patient: Mapped[Patient] = relationship(back_populates="observations")
    encounter: Mapped[Encounter | None] = relationship(back_populates="observations")

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('registered', 'preliminary', 'final', 'amended', 'corrected', 'cancelled', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.Index("ix_observations_patient_id", "patient_id"),
        sa.Index("ix_observations_encounter_id", "encounter_id"),
    )


class ResearchStudy(Base):
    __tablename__ = "research_studies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    subjects: Mapped[list[ResearchSubject]] = relationship(
        back_populates="study",
        cascade="all, delete-orphan",
    )
    access_grants: Mapped[list[StudyAccess]] = relationship(
        back_populates="study",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'stopped', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.Index("ix_research_studies_title", "title"),
        sa.Index("uq_research_studies_external_id", "external_id", unique=True),
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    study_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("research_studies.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default=sa.text("'pending'"),
    )
    total_records: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    successful_records: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    failed_records: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    source_records: Mapped[list[SourceRecord]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
    )
    errors: Mapped[list[ImportError]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
        order_by="ImportError.source_row",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "source_type IN ('csv', 'fhir_bundle')",
            name="source_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'partial', 'failed')",
            name="status_valid",
        ),
        sa.CheckConstraint("total_records >= 0", name="total_records_nonnegative"),
        sa.CheckConstraint("successful_records >= 0", name="successful_records_nonnegative"),
        sa.CheckConstraint("failed_records >= 0", name="failed_records_nonnegative"),
        sa.CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        sa.Index("ix_import_jobs_status", "status"),
        sa.Index("ix_import_jobs_started_at", "started_at"),
        sa.Index("uq_import_jobs_file_checksum", "file_checksum", unique=True),
    )


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_row: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    import_job: Mapped[ImportJob] = relationship(back_populates="source_records")

    __table_args__ = (
        sa.CheckConstraint(
            "resource_type IN ('patient', 'encounter', 'observation', 'research_study')",
            name="resource_type_valid",
        ),
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_source_records_resource"),
        sa.Index("ix_source_records_import_job_id", "import_job_id"),
        sa.Index("ix_source_records_import_job_id_source_row", "import_job_id", "source_row"),
        sa.Index("ix_source_records_resource_type_resource_id", "resource_type", "resource_id"),
        sa.Index("ix_source_records_checksum", "checksum"),
    )


class ImportError(Base):
    __tablename__ = "import_errors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_row: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    field: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    import_job: Mapped[ImportJob] = relationship(back_populates="errors")

    __table_args__ = (
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
        sa.Index("ix_import_errors_import_job_id", "import_job_id"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )

    study_access: Mapped[list[StudyAccess]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.CheckConstraint("role IN ('admin', 'researcher', 'auditor')", name="role_valid"),
    )


class StudyAccess(Base):
    __tablename__ = "study_access"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_studies.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )

    study: Mapped[ResearchStudy] = relationship(back_populates="access_grants")
    user: Mapped[User] = relationship(back_populates="study_access")

    __table_args__ = (
        sa.UniqueConstraint("study_id", "user_id", name="uq_study_access"),
        sa.Index("ix_study_access_user_id", "user_id"),
    )


class ResearchSubject(Base):
    __tablename__ = "research_subjects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_studies.id", ondelete="CASCADE"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )

    study: Mapped[ResearchStudy] = relationship(back_populates="subjects")
    patient: Mapped[Patient] = relationship(back_populates="research_subjects")

    __table_args__ = (
        sa.UniqueConstraint("study_id", "patient_id", name="uq_research_subject"),
        sa.Index("ix_research_subjects_patient_id", "patient_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (sa.Index("ix_audit_logs_timestamp", "timestamp"),)
