"""Namespaced external identity, per-target import idempotency, provenance history

Three structural corrections:

1. External identity becomes the FHIR-style pair ``(source_namespace,
   external_id)`` on Patient, Encounter, Observation and ResearchStudy. A bare
   ``external_id`` was globally unique, so two sites both using ``P001``
   silently collapsed into one row.
2. Import idempotency moves from ``file_checksum`` to ``idempotency_key``,
   which folds in the target study and namespace. The same file can now be
   imported for two different studies instead of the second upload silently
   reusing the first study's job.
3. ``source_records`` becomes an append-only provenance history: the
   one-row-per-resource unique constraint is replaced by one row per
   (job, row, resource), and ``action`` distinguishes first creation from
   later re-assertion.

Also adds ``import_errors.attempt`` so retries version the error report rather
than duplicating rows into it, and backfills ``created_at``/``updated_at`` on
the tables that lacked them.

Revision ID: 20260726_0005
Revises: 20260725_0004
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260726_0005"
down_revision = "20260725_0004"
branch_labels = None
depends_on = None

DEFAULT_SOURCE_NAMESPACE = "urn:cdp:default"
NAMESPACE_DEFAULT = sa.text(f"'{DEFAULT_SOURCE_NAMESPACE}'")
NOW = sa.text("CURRENT_TIMESTAMP")

#: Tables that gain (created_at, updated_at).
TIMESTAMPED = ("encounters", "observations", "research_studies", "import_jobs", "source_records", "import_errors")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Namespaced identity
    # ------------------------------------------------------------------
    with op.batch_alter_table("patients") as batch:
        batch.add_column(
            sa.Column("source_namespace", sa.Text(), server_default=NAMESPACE_DEFAULT, nullable=False)
        )
        batch.drop_constraint("uq_patients_external_id", type_="unique")
        batch.create_unique_constraint("uq_patients_identity", ["source_namespace", "external_id"])

    with op.batch_alter_table("encounters") as batch:
        batch.add_column(
            sa.Column("source_namespace", sa.Text(), server_default=NAMESPACE_DEFAULT, nullable=False)
        )
        for column in _timestamp_columns():
            batch.add_column(column)
        batch.drop_constraint("uq_encounters_external_id", type_="unique")
        batch.create_unique_constraint("uq_encounters_identity", ["source_namespace", "external_id"])

    with op.batch_alter_table("observations") as batch:
        batch.add_column(
            sa.Column("source_namespace", sa.Text(), server_default=NAMESPACE_DEFAULT, nullable=False)
        )
        for column in _timestamp_columns():
            batch.add_column(column)
        batch.drop_constraint("uq_observations_external_id", type_="unique")
        batch.create_unique_constraint("uq_observations_identity", ["source_namespace", "external_id"])

    # research_studies.external_id was a unique *index*, not a constraint.
    op.drop_index("uq_research_studies_external_id", table_name="research_studies")
    with op.batch_alter_table("research_studies") as batch:
        batch.add_column(
            sa.Column("source_namespace", sa.Text(), server_default=NAMESPACE_DEFAULT, nullable=False)
        )
        for column in _timestamp_columns():
            batch.add_column(column)
    op.create_index(
        "uq_research_studies_identity",
        "research_studies",
        ["source_namespace", "external_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 2. Import idempotency keyed on (payload, study, namespace)
    # ------------------------------------------------------------------
    op.drop_index("uq_import_jobs_file_checksum", table_name="import_jobs")
    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(
            sa.Column("source_namespace", sa.Text(), server_default=NAMESPACE_DEFAULT, nullable=False)
        )
        batch.add_column(sa.Column("idempotency_key", sa.Text(), nullable=True))
        for column in _timestamp_columns():
            batch.add_column(column)

    # Existing rows had globally unique file checksums, so reusing the checksum
    # as the key preserves uniqueness and keeps prior uploads idempotent.
    op.execute(
        sa.text(
            "UPDATE import_jobs SET idempotency_key = file_checksum "
            "WHERE idempotency_key IS NULL AND file_checksum IS NOT NULL"
        )
    )

    op.create_index("ix_import_jobs_file_checksum", "import_jobs", ["file_checksum"])
    op.create_index("uq_import_jobs_idempotency_key", "import_jobs", ["idempotency_key"], unique=True)
    op.create_index("ix_import_jobs_created_at", "import_jobs", ["created_at"])

    # ------------------------------------------------------------------
    # 3. Provenance history
    # ------------------------------------------------------------------
    with op.batch_alter_table("source_records") as batch:
        batch.add_column(
            sa.Column("action", sa.Text(), server_default=sa.text("'created'"), nullable=False)
        )
        for column in _timestamp_columns():
            batch.add_column(column)
        batch.drop_constraint("uq_source_records_resource", type_="unique")
        batch.drop_constraint("uq_source_records_checksum", type_="unique")
        batch.create_unique_constraint(
            "uq_source_records_job_row_resource",
            ["import_job_id", "source_row", "resource_type", "resource_id"],
        )
        batch.create_check_constraint("action_valid", "action IN ('created', 'reasserted')")

    op.create_index(
        "ix_source_records_resource_history",
        "source_records",
        ["resource_type", "resource_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # 4. Versioned import error reports
    # ------------------------------------------------------------------
    with op.batch_alter_table("import_errors") as batch:
        batch.add_column(sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False))
        for column in _timestamp_columns():
            batch.add_column(column)
        batch.create_check_constraint("attempt_nonnegative", "attempt >= 0")

    op.create_index(
        "ix_import_errors_import_job_id_attempt",
        "import_errors",
        ["import_job_id", "attempt"],
    )

    # ------------------------------------------------------------------
    # 5. Deterministic ordering support
    # ------------------------------------------------------------------
    op.create_index("ix_patients_created_at", "patients", ["created_at"])
    op.create_index("ix_encounters_created_at", "encounters", ["created_at"])
    op.create_index("ix_observations_created_at", "observations", ["created_at"])
    op.create_index("ix_research_studies_created_at", "research_studies", ["created_at"])
    op.create_index("ix_audit_logs_timestamp_id", "audit_logs", ["timestamp", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_timestamp_id", table_name="audit_logs")
    op.drop_index("ix_research_studies_created_at", table_name="research_studies")
    op.drop_index("ix_observations_created_at", table_name="observations")
    op.drop_index("ix_encounters_created_at", table_name="encounters")
    op.drop_index("ix_patients_created_at", table_name="patients")

    op.drop_index("ix_import_errors_import_job_id_attempt", table_name="import_errors")
    with op.batch_alter_table("import_errors") as batch:
        batch.drop_constraint("attempt_nonnegative", type_="check")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("attempt")

    op.drop_index("ix_source_records_resource_history", table_name="source_records")
    # The upgraded table deliberately holds many provenance rows per resource,
    # which the restored unique constraints forbid. Downgrading is therefore
    # lossy by construction: keep the earliest event per resource and drop the
    # rest, otherwise the constraint creation fails on any database that has
    # actually run an import.
    op.execute(
        sa.text(
            "DELETE FROM source_records WHERE id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY resource_type, resource_id ORDER BY created_at, id"
            "    ) AS rank_in_resource FROM source_records"
            "  ) ranked WHERE rank_in_resource = 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM source_records WHERE id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY checksum ORDER BY created_at, id"
            "    ) AS rank_by_checksum FROM source_records"
            "  ) ranked WHERE rank_by_checksum = 1"
            ")"
        )
    )
    with op.batch_alter_table("source_records") as batch:
        batch.drop_constraint("action_valid", type_="check")
        batch.drop_constraint("uq_source_records_job_row_resource", type_="unique")
        batch.create_unique_constraint("uq_source_records_checksum", ["checksum"])
        batch.create_unique_constraint("uq_source_records_resource", ["resource_type", "resource_id"])
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("action")

    op.drop_index("ix_import_jobs_created_at", table_name="import_jobs")
    op.drop_index("uq_import_jobs_idempotency_key", table_name="import_jobs")
    op.drop_index("ix_import_jobs_file_checksum", table_name="import_jobs")
    # v0.1.0 allowed only one non-null job per file checksum. Keep the earliest
    # job for each checksum before restoring that lossy legacy constraint.
    op.execute(
        sa.text(
            "DELETE FROM source_records WHERE import_job_id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY file_checksum ORDER BY created_at, id"
            "    ) AS rank_by_checksum FROM import_jobs"
            "    WHERE file_checksum IS NOT NULL"
            "  ) ranked WHERE rank_by_checksum > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM import_errors WHERE import_job_id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY file_checksum ORDER BY created_at, id"
            "    ) AS rank_by_checksum FROM import_jobs"
            "    WHERE file_checksum IS NOT NULL"
            "  ) ranked WHERE rank_by_checksum > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM import_jobs WHERE id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY file_checksum ORDER BY created_at, id"
            "    ) AS rank_by_checksum FROM import_jobs"
            "    WHERE file_checksum IS NOT NULL"
            "  ) ranked WHERE rank_by_checksum = 1"
            ") AND file_checksum IS NOT NULL"
        )
    )
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("idempotency_key")
        batch.drop_column("source_namespace")
    op.create_index("uq_import_jobs_file_checksum", "import_jobs", ["file_checksum"], unique=True)

    # The legacy schema cannot represent two namespaces with one external id.
    # Downgrade is intentionally lossy: remove dependent rows belonging to
    # duplicate identities before restoring each old global unique constraint.
    for child_table, parent_column, parent_table in (
        ("observations", "patient_id", "patients"),
        ("encounters", "patient_id", "patients"),
        ("research_subjects", "patient_id", "patients"),
    ):
        op.execute(
            sa.text(
                f"DELETE FROM {child_table} WHERE {parent_column} IN ("
                f"  SELECT id FROM ("
                f"    SELECT id, ROW_NUMBER() OVER ("
                f"      PARTITION BY external_id ORDER BY created_at, id"
                f"    ) AS rank_by_identity FROM {parent_table}"
                f"  ) ranked WHERE rank_by_identity > 1"
                f")"
            )
        )
    op.execute(
        sa.text(
            "DELETE FROM patients WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM patients"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM observations WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM observations"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM encounters WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM encounters"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM study_access WHERE study_id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM research_studies"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM research_subjects WHERE study_id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM research_studies"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM research_studies WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY external_id ORDER BY created_at, id"
            "    ) AS rank_by_identity FROM research_studies"
            "  ) ranked WHERE rank_by_identity > 1"
            ")"
        )
    )

    op.drop_index("uq_research_studies_identity", table_name="research_studies")
    with op.batch_alter_table("research_studies") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("source_namespace")
    op.create_index("uq_research_studies_external_id", "research_studies", ["external_id"], unique=True)

    with op.batch_alter_table("observations") as batch:
        batch.drop_constraint("uq_observations_identity", type_="unique")
        batch.create_unique_constraint("uq_observations_external_id", ["external_id"])
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("source_namespace")

    with op.batch_alter_table("encounters") as batch:
        batch.drop_constraint("uq_encounters_identity", type_="unique")
        batch.create_unique_constraint("uq_encounters_external_id", ["external_id"])
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("source_namespace")

    with op.batch_alter_table("patients") as batch:
        batch.drop_constraint("uq_patients_identity", type_="unique")
        batch.create_unique_constraint("uq_patients_external_id", ["external_id"])
        batch.drop_column("source_namespace")
