# Database Schema

## Conventions

- PostgreSQL.
- Primary keys are `UUID`.
- Timestamps use `TIMESTAMPTZ`.
- `created_at` and `updated_at` are only present where listed in v1.
- Application validation enforces controlled vocabularies for status-like fields.
- No hard-delete workflow is defined in v1.

## patients

- `id` UUID PK
- `external_id` TEXT NOT NULL UNIQUE
- `birth_date` DATE NULL
- `sex` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL
- `updated_at` TIMESTAMPTZ NOT NULL

Purpose: canonical patient identity and deduplication boundary.

## encounters

- `id` UUID PK
- `patient_id` UUID NOT NULL FK -> `patients.id`
- `external_id` TEXT NOT NULL UNIQUE
- `status` TEXT NOT NULL
- `encounter_type` TEXT NOT NULL
- `started_at` TIMESTAMPTZ NULL
- `ended_at` TIMESTAMPTZ NULL

Indexes:

- `patient_id`
- `external_id`

Purpose: time-bounded clinical episode tied to one patient.

## observations

- `id` UUID PK
- `patient_id` UUID NOT NULL FK -> `patients.id`
- `encounter_id` UUID NULL FK -> `encounters.id`
- `external_id` TEXT NOT NULL UNIQUE
- `code` TEXT NOT NULL
- `code_system` TEXT NOT NULL
- `value` TEXT NOT NULL
- `unit` TEXT NULL
- `observed_at` TIMESTAMPTZ NOT NULL
- `status` TEXT NOT NULL

Indexes:

- `patient_id`
- `encounter_id`
- `external_id`

Purpose: normalized clinical facts such as laboratory measurements.

## research_studies

- `id` UUID PK
- `title` TEXT NOT NULL
- `description` TEXT NULL
- `status` TEXT NOT NULL

Indexes:

- `title`

Purpose: study metadata only; no patient membership relation yet.

## import_jobs

- `id` UUID PK
- `source_type` TEXT NOT NULL
- `filename` TEXT NOT NULL
- `status` TEXT NOT NULL
- `total_records` INTEGER NOT NULL
- `successful_records` INTEGER NOT NULL
- `failed_records` INTEGER NOT NULL
- `started_at` TIMESTAMPTZ NULL
- `completed_at` TIMESTAMPTZ NULL

Indexes:

- `status`
- `started_at`

Purpose: one batch import run with progress and outcome counters.

Allowed statuses: `pending`, `processing`, `completed`, `failed`.

## source_records

- `id` UUID PK
- `import_job_id` UUID NOT NULL FK -> `import_jobs.id`
- `resource_type` TEXT NOT NULL
- `resource_id` UUID NOT NULL
- `source_row` INTEGER NOT NULL
- `raw_data` JSONB NOT NULL
- `checksum` TEXT NOT NULL

Constraints:

- `resource_type + resource_id` UNIQUE
- `checksum` UNIQUE

Indexes:

- `import_job_id`
- `import_job_id + source_row`
- `resource_type + resource_id`
- `checksum`

Purpose: immutable provenance link from imported source row to the normalized resource created from it.

## Notes for implementation

- `resource_type` values in v1 are limited to `patient`, `encounter`, `observation`, and `research_study`.
- `source_records.resource_id` is a generic application-level pointer and is not a foreign key.
- `checksum` is computed from the canonicalized normalized resource payload, so repeated uploads can be deduplicated.
- If a row fails validation, it is not stored as a successful `source_record` in v1.
