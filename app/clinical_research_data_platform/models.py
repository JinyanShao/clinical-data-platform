from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_research_data_platform.db import Base

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

    encounters: Mapped[list["Encounter"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    observations: Mapped[list["Observation"]] = relationship(
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
    observations: Mapped[list["Observation"]] = relationship(back_populates="encounter")

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('planned', 'in-progress', 'finished', 'cancelled', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="date_order_valid",
        ),
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
    )


class ResearchStudy(Base):
    __tablename__ = "research_studies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'stopped', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
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

    source_records: Mapped[list["SourceRecord"]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "source_type IN ('csv', 'fhir_bundle')",
            name="source_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="status_valid",
        ),
        sa.CheckConstraint("total_records >= 0", name="total_records_nonnegative"),
        sa.CheckConstraint("successful_records >= 0", name="successful_records_nonnegative"),
        sa.CheckConstraint("failed_records >= 0", name="failed_records_nonnegative"),
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
    )
