# Database schema

PostgreSQL is the release database. Primary keys are UUIDs, timestamps are timezone-aware, JSON payloads use JSONB, and controlled statuses have database check constraints in addition to application validation.

## Clinical tables

All four clinical tables carry `source_namespace` alongside `external_id` and enforce uniqueness on the pair, not on `external_id` alone. See [Domain model](domain-model.md#external-identity).

### patients

Canonical patient identity: unique `(source_namespace, external_id)`, optional `birth_date` and `sex`, plus creation/update timestamps.

### encounters

Unique `(source_namespace, external_id)`, required Patient foreign key, status/type, optional start/end timestamps, creation/update timestamps, and a Patient index.

### observations

Unique `(source_namespace, external_id)`, required Patient and optional Encounter foreign keys, coded value fields, observation timestamp/status, creation/update timestamps, and Patient/Encounter indexes. `value` is stored verbatim for provenance fidelity; re-import comparison normalises it numerically so `1.5` and `1.50` are one value.

### research_studies

Optional external identity unique per `source_namespace`, title, description, status, and creation/update timestamps. Title is indexed for catalog lookup.

## Access-control tables

### users

Unique username and API-key hash, role constrained to `admin`, `researcher`, or `auditor`, and creation timestamp. Plain API keys are never stored.

### study_access

Unique `(study_id, user_id)` grant connecting a User to a ResearchStudy.

### research_subjects

Unique `(study_id, patient_id)` enrollment connecting a Patient to a ResearchStudy.

## Import tables

### import_jobs

Stores source type, filename, file checksum, unique `idempotency_key`, `source_namespace`, binary retry payload, optional Study binding, Celery task id, status, counters, failure reason, retry count, and lifecycle timestamps.

`file_checksum` is indexed but not unique: the same bytes imported for a different study or namespace is a different job. Uniqueness lives on `idempotency_key`, which is `sha256(file_checksum | study_id | source_namespace)`.

Allowed states: `pending`, `processing`, `completed`, `partial`, and `failed`. Transitions are owned exclusively by `ImportJobService`; `completed` and `partial` are terminal, and `failed` moves forward only through an explicit retry.

### import_errors

Stores ImportJob foreign key, `attempt`, source row/entry number, field, stable error code, message, and timestamps. Errors are versioned by attempt rather than deleted, so a retry adds a new generation instead of duplicating the previous one.

### source_records

Append-only provenance history. Stores ImportJob foreign key, resource type/id pointer, source row, raw JSONB input, content checksum, `action` (`created` or `reasserted`), and timestamps. Unique on `(import_job_id, source_row, resource_type, resource_id)`, so reprocessing one job stays idempotent while a different import appends its own event for the same resource.

## Audit table

### audit_logs

Stores actor, action, resource type/id, optional before/after JSONB snapshots, and indexed timestamp. Timestamps are written with microsecond resolution from the application and listings order by `(timestamp, id)`, so pagination is deterministic even when entries collide on the timestamp. There is no endpoint that modifies audit entries.

## Migration ownership

Alembic is the only schema-change mechanism. Compose runs `alembic upgrade head` before the API or worker starts. CI runs `alembic check` against a freshly upgraded database to detect ORM/migration drift on both SQLite and PostgreSQL, and additionally verifies that migrations reverse cleanly (`downgrade base` then `upgrade head`) on PostgreSQL.
