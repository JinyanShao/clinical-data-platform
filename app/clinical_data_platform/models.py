from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_data_platform.config import DEFAULT_SOURCE_NAMESPACE
from clinical_data_platform.db import Base

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

#: Values allowed for :attr:`SourceRecord.action`.
PROVENANCE_ACTIONS = ("created", "reasserted")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    # Defaults are applied in Python for microsecond resolution. The SQL
    # CURRENT_TIMESTAMP default is only second-granular on SQLite, which made
    # every "ORDER BY created_at, id" tie on the timestamp and fall back to a
    # random UUID. Server defaults are retained for rows written outside the ORM.
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class SourceIdentityMixin:
    """Namespaced external identity.

    A bare ``external_id`` is not a globally meaningful identity: two research
    sites routinely both call a subject ``P001``. Following the FHIR
    ``Identifier`` model, identity is the pair ``(system, value)`` — here
    ``(source_namespace, external_id)``. Uniqueness is enforced on the pair, so
    records that merely share a local numbering scheme never collapse into one
    row.
    """

    source_namespace: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_SOURCE_NAMESPACE}'"),
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)


class Patient(TimestampMixin, SourceIdentityMixin, Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
        sa.UniqueConstraint("source_namespace", "external_id", name="uq_patients_identity"),
        sa.Index("ix_patients_created_at", "created_at"),
    )


class Encounter(TimestampMixin, SourceIdentityMixin, Base):
    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
    )
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
        sa.UniqueConstraint("source_namespace", "external_id", name="uq_encounters_identity"),
        sa.Index("ix_encounters_patient_id", "patient_id"),
        sa.Index("ix_encounters_created_at", "created_at"),
    )


class Observation(TimestampMixin, SourceIdentityMixin, Base):
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
    code: Mapped[str] = mapped_column(Text, nullable=False)
    code_system: Mapped[str] = mapped_column(Text, nullable=False)
    #: Verbatim source representation, retained for provenance fidelity.
    #: Re-import comparison normalises this numerically (see
    #: ``services/import_pipeline.py``) so "1.5" and "1.50" are one value.
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
        sa.UniqueConstraint("source_namespace", "external_id", name="uq_observations_identity"),
        sa.Index("ix_observations_patient_id", "patient_id"),
        sa.Index("ix_observations_encounter_id", "encounter_id"),
        sa.Index("ix_observations_created_at", "created_at"),
    )


class ResearchStudy(TimestampMixin, Base):
    __tablename__ = "research_studies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_namespace: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_SOURCE_NAMESPACE}'"),
    )
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
        sa.Index("ix_research_studies_created_at", "created_at"),
        sa.Index(
            "uq_research_studies_identity",
            "source_namespace",
            "external_id",
            unique=True,
        ),
    )


class ImportJob(TimestampMixin, Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 of the uploaded bytes. Not unique on its own: the same file may
    #: legitimately be imported into more than one study or namespace.
    file_checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The actual idempotency key: derived from the payload *and* the target
    #: (study, namespace). Unique, so re-uploading the same file for the same
    #: target is a no-op while a different target creates a real new job.
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Issuing namespace applied to every resource this job creates.
    source_namespace: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_SOURCE_NAMESPACE}'"),
    )
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
        order_by="[ImportError.attempt.desc(), ImportError.source_row]",
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
        sa.Index("ix_import_jobs_created_at", "created_at"),
        sa.Index("ix_import_jobs_file_checksum", "file_checksum"),
        sa.Index("uq_import_jobs_idempotency_key", "idempotency_key", unique=True),
    )

    @property
    def current_attempt(self) -> int:
        """Attempt number the job is currently on; matches ``retry_count``."""
        return self.retry_count


class SourceRecord(TimestampMixin, Base):
    """One provenance event: an import asserting a resource.

    A resource may have many of these. ``action`` distinguishes the import that
    first materialised the resource from later imports that re-observed it, so
    the table answers "which imports, which source rows, and when" rather than
    merely "where did this originate".
    """

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
    #: Content address of this provenance event. Indexed, not unique: the same
    #: bytes may legitimately be asserted by more than one import.
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="created",
        server_default=sa.text("'created'"),
    )

    import_job: Mapped[ImportJob] = relationship(back_populates="source_records")

    __table_args__ = (
        sa.CheckConstraint(
            "resource_type IN ('patient', 'encounter', 'observation', 'research_study')",
            name="resource_type_valid",
        ),
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
        sa.CheckConstraint(
            "action IN ('created', 'reasserted')",
            name="action_valid",
        ),
        # One provenance row per (job, row, resource): re-running the same job
        # stays idempotent, while a different import adds a new event.
        sa.UniqueConstraint(
            "import_job_id",
            "source_row",
            "resource_type",
            "resource_id",
            name="uq_source_records_job_row_resource",
        ),
        sa.Index("ix_source_records_import_job_id", "import_job_id"),
        sa.Index("ix_source_records_import_job_id_source_row", "import_job_id", "source_row"),
        sa.Index("ix_source_records_resource_type_resource_id", "resource_type", "resource_id"),
        sa.Index("ix_source_records_resource_history", "resource_type", "resource_id", "created_at"),
        sa.Index("ix_source_records_checksum", "checksum"),
    )


class ImportError(TimestampMixin, Base):
    __tablename__ = "import_errors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Which processing attempt produced this error. Matches
    #: :attr:`ImportJob.retry_count` at the time it was recorded, so retries
    #: version the error report instead of duplicating rows into it.
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))
    source_row: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    field: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    import_job: Mapped[ImportJob] = relationship(back_populates="errors")

    __table_args__ = (
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
        sa.CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        sa.Index("ix_import_errors_import_job_id", "import_job_id"),
        sa.Index("ix_import_errors_import_job_id_attempt", "import_job_id", "attempt"),
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
    # Set in Python for microsecond resolution: the SQL CURRENT_TIMESTAMP
    # default is only second-granular on SQLite, which made ordering by
    # timestamp alone non-deterministic. The server default is retained for
    # rows written outside the ORM.
    timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        sa.Index("ix_audit_logs_timestamp", "timestamp"),
        sa.Index("ix_audit_logs_timestamp_id", "timestamp", "id"),
    )
