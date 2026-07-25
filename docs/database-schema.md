# Database schema

PostgreSQL is the release database. Primary keys are UUIDs, timestamps are timezone-aware, JSON payloads use JSONB, and controlled statuses have database check constraints in addition to application validation.

## Clinical tables

### patients

Canonical patient identity: unique `external_id`, optional `birth_date` and `sex`, plus creation/update timestamps.

### encounters

Unique `external_id`, required Patient foreign key, status/type, optional start/end timestamps, and a Patient index.

### observations

Unique `external_id`, required Patient and optional Encounter foreign keys, coded value fields, observation timestamp/status, and Patient/Encounter indexes.

### research_studies

Optional unique external identity, title, description, and status. Title is indexed for catalog lookup.

## Access-control tables

### users

Unique username and API-key hash, role constrained to `admin`, `researcher`, or `auditor`, and creation timestamp. Plain API keys are never stored.

### study_access

Unique `(study_id, user_id)` grant connecting a User to a ResearchStudy.

### research_subjects

Unique `(study_id, patient_id)` enrollment connecting a Patient to a ResearchStudy.

## Import tables

### import_jobs

Stores source type, filename, unique file checksum, binary retry payload, optional Study binding, Celery task id, status, counters, failure reason, retry count, and lifecycle timestamps.

Allowed states: `pending`, `processing`, `completed`, `partial`, and `failed`.

### import_errors

Stores ImportJob foreign key, source row/entry number, field, stable error code, and message.

### source_records

Stores ImportJob foreign key, resource type/id pointer, source row, raw JSONB input, and unique checksum. One source row may produce Patient, Encounter, and Observation records.

## Audit table

### audit_logs

Stores actor, action, resource type/id, optional before/after JSONB snapshots, and indexed timestamp. There is no endpoint that modifies audit entries.

## Migration ownership

Alembic is the only schema-change mechanism. Compose runs `alembic upgrade head` before the API or worker starts, and CI runs `alembic check` against a freshly upgraded database to detect ORM/migration drift.
