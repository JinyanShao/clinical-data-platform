"""Production backend security and operations model

Revision ID: 20260725_0004
Revises: 20260725_0003
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260725_0004"
down_revision = "20260725_0003"
branch_labels = None
depends_on = None

uuid_type = sa.Uuid(as_uuid=True)
json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'researcher', 'auditor')", name="role_valid"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("api_key_hash", name="uq_users_api_key_hash"),
    )
    op.create_table(
        "study_access",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("study_id", uuid_type, sa.ForeignKey("research_studies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("study_id", "user_id", name="uq_study_access"),
    )
    op.create_table(
        "research_subjects",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("study_id", uuid_type, sa.ForeignKey("research_studies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", uuid_type, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("study_id", "patient_id", name="uq_research_subject"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("before", json_type, nullable=True),
        sa.Column("after", json_type, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )

    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_constraint("status_valid", type_="check")
        batch.add_column(sa.Column("payload", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("study_id", uuid_type, nullable=True))
        batch.add_column(sa.Column("task_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
        batch.create_foreign_key("fk_import_jobs_study_id", "research_studies", ["study_id"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint(
            "status_valid",
            "status IN ('pending', 'processing', 'completed', 'partial', 'failed')",
        )
        batch.create_check_constraint("retry_count_nonnegative", "retry_count >= 0")

    op.create_index("ix_study_access_user_id", "study_access", ["user_id"])
    op.create_index("ix_research_subjects_patient_id", "research_subjects", ["patient_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_research_subjects_patient_id", table_name="research_subjects")
    op.drop_index("ix_study_access_user_id", table_name="study_access")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_constraint("retry_count_nonnegative", type_="check")
        batch.drop_constraint("status_valid", type_="check")
        batch.drop_constraint("fk_import_jobs_study_id", type_="foreignkey")
        batch.drop_column("retry_count")
        batch.drop_column("failure_reason")
        batch.drop_column("task_id")
        batch.drop_column("study_id")
        batch.drop_column("payload")
        batch.create_check_constraint(
            "status_valid", "status IN ('pending', 'processing', 'completed', 'failed')"
        )
    op.drop_table("audit_logs")
    op.drop_table("research_subjects")
    op.drop_table("study_access")
    op.drop_table("users")
