"""OIDC subject binding and PostgreSQL research-data row-level security."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260802_0006"
down_revision = "20260726_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("oidc_subject", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_users_oidc_subject", ["oidc_subject"])

    if op.get_bind().dialect.name != "postgresql":
        return

    # Runtime deployments must connect as this non-owner role. The migration
    # creates it without LOGIN for existing installations; the operator grants
    # LOGIN and supplies its password before switching DATABASE_URL.
    op.execute("DO $$ BEGIN CREATE ROLE clinical_app NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute("GRANT USAGE ON SCHEMA public TO clinical_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON patients, encounters, observations, research_studies "
        "TO clinical_app"
    )
    op.execute("GRANT SELECT ON research_subjects, study_access TO clinical_app")

    policies = {
        "patients": "id",
        "encounters": "patient_id",
        "observations": "patient_id",
    }
    for table, patient_column in policies.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        patient_expression = (
            f"{patient_column} = rs.patient_id" if table != "patients" else "rs.patient_id = patients.id"
        )
        op.execute(
            f"CREATE POLICY {table}_research_read ON {table} FOR SELECT TO clinical_app USING "
            "(current_setting('app.role', true) IN ('admin', 'auditor') OR EXISTS "
            "(SELECT 1 FROM research_subjects rs JOIN study_access sa ON sa.study_id = rs.study_id "
            f"WHERE {patient_expression} AND sa.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))"
        )
        op.execute(
            f"CREATE POLICY {table}_admin_write ON {table} FOR ALL TO clinical_app USING "
            "(current_setting('app.role', true) = 'admin') WITH CHECK "
            "(current_setting('app.role', true) = 'admin')"
        )

    op.execute("ALTER TABLE research_studies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research_studies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY research_studies_research_read ON research_studies FOR SELECT TO clinical_app USING "
        "(current_setting('app.role', true) IN ('admin', 'auditor') OR EXISTS "
        "(SELECT 1 FROM study_access sa WHERE sa.study_id = research_studies.id "
        "AND sa.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))"
    )
    op.execute(
        "CREATE POLICY research_studies_admin_write ON research_studies FOR ALL TO clinical_app USING "
        "(current_setting('app.role', true) = 'admin') WITH CHECK "
        "(current_setting('app.role', true) = 'admin')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("patients", "encounters", "observations", "research_studies"):
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS {table}_research_read ON {table}")
            op.execute(f"DROP POLICY IF EXISTS {table}_admin_write ON {table}")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_oidc_subject", type_="unique")
        batch.drop_column("oidc_subject")
