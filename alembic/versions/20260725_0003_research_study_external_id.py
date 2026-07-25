"""Add ResearchStudy external identity

Revision ID: 20260725_0003
Revises: 20260725_0002
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260725_0003"
down_revision = "20260725_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_studies", sa.Column("external_id", sa.Text(), nullable=True))
    op.create_index(
        "uq_research_studies_external_id",
        "research_studies",
        ["external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_research_studies_external_id", table_name="research_studies")
    op.drop_column("research_studies", "external_id")
