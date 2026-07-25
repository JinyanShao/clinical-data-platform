"""core data model

Revision ID: 20260724_0001
Revises:
Create Date: 2026-07-24 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260724_0001"
down_revision = None
branch_labels = None
depends_on = None

uuid_type = sa.Uuid(as_uuid=True)
json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sex IS NULL OR sex IN ('male', 'female', 'other', 'unknown')",
            name="sex_valid",
        ),
        sa.UniqueConstraint("external_id", name="uq_patients_external_id"),
    )

    op.create_table(
        "research_studies",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'stopped', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("total_records", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("successful_records", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_records", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_table(
        "encounters",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "patient_id",
            uuid_type,
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("encounter_type", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned', 'in-progress', 'finished', 'cancelled', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="date_order_valid",
        ),
        sa.UniqueConstraint("external_id", name="uq_encounters_external_id"),
    )

    op.create_table(
        "observations",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "patient_id",
            uuid_type,
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "encounter_id",
            uuid_type,
            sa.ForeignKey("encounters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("code_system", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('registered', 'preliminary', 'final', 'amended', 'corrected', 'cancelled', 'entered-in-error', 'unknown')",
            name="status_valid",
        ),
        sa.UniqueConstraint("external_id", name="uq_observations_external_id"),
    )

    op.create_table(
        "source_records",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "import_job_id",
            uuid_type,
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", uuid_type, nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("raw_data", json_type, nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "resource_type IN ('patient', 'encounter', 'observation', 'research_study')",
            name="resource_type_valid",
        ),
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
        sa.CheckConstraint(
            "resource_type IS NOT NULL AND resource_id IS NOT NULL",
            name="resource_reference_present",
        ),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_source_records_resource"),
        sa.UniqueConstraint("checksum", name="uq_source_records_checksum"),
    )

    op.create_index("ix_encounters_patient_id", "encounters", ["patient_id"])
    op.create_index("ix_observations_patient_id", "observations", ["patient_id"])
    op.create_index("ix_observations_encounter_id", "observations", ["encounter_id"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])
    op.create_index("ix_import_jobs_started_at", "import_jobs", ["started_at"])
    op.create_index("ix_source_records_import_job_id", "source_records", ["import_job_id"])
    op.create_index(
        "ix_source_records_import_job_id_source_row",
        "source_records",
        ["import_job_id", "source_row"],
    )
    op.create_index(
        "ix_source_records_resource_type_resource_id",
        "source_records",
        ["resource_type", "resource_id"],
    )
    op.create_index("ix_source_records_checksum", "source_records", ["checksum"])
    op.create_index("ix_research_studies_title", "research_studies", ["title"])


def downgrade() -> None:
    op.drop_index("ix_research_studies_title", table_name="research_studies")
    op.drop_index("ix_source_records_checksum", table_name="source_records")
    op.drop_index("ix_source_records_resource_type_resource_id", table_name="source_records")
    op.drop_index("ix_source_records_import_job_id_source_row", table_name="source_records")
    op.drop_index("ix_source_records_import_job_id", table_name="source_records")
    op.drop_index("ix_import_jobs_started_at", table_name="import_jobs")
    op.drop_index("ix_import_jobs_status", table_name="import_jobs")
    op.drop_index("ix_observations_encounter_id", table_name="observations")
    op.drop_index("ix_observations_patient_id", table_name="observations")
    op.drop_index("ix_encounters_patient_id", table_name="encounters")
    op.drop_table("source_records")
    op.drop_table("observations")
    op.drop_table("encounters")
    op.drop_table("import_jobs")
    op.drop_table("research_studies")
    op.drop_table("patients")
