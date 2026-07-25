"""CSV import pipeline reporting

Revision ID: 20260725_0002
Revises: 20260724_0001
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260725_0002"
down_revision = "20260724_0001"
branch_labels = None
depends_on = None

uuid_type = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.add_column("import_jobs", sa.Column("file_checksum", sa.Text(), nullable=True))
    op.create_index(
        "uq_import_jobs_file_checksum",
        "import_jobs",
        ["file_checksum"],
        unique=True,
    )
    op.create_table(
        "import_errors",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "import_job_id",
            uuid_type,
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.CheckConstraint("source_row > 0", name="source_row_positive"),
    )
    op.create_index("ix_import_errors_import_job_id", "import_errors", ["import_job_id"])


def downgrade() -> None:
    op.drop_index("ix_import_errors_import_job_id", table_name="import_errors")
    op.drop_table("import_errors")
    op.drop_index("uq_import_jobs_file_checksum", table_name="import_jobs")
    op.drop_column("import_jobs", "file_checksum")
