# ADR 001: Core Data Model

## Status

Accepted

## Context

The platform needs a v1 schema that supports CSV and FHIR-style ingestion, idempotent imports, provenance tracking, and researcher queries. The first release must stay small enough to implement cleanly in SQLAlchemy and Alembic while still supporting the acceptance scenario for synthetic laboratory data.

## Decision

We will define a narrow core model with six tables:

- `patients`
- `encounters`
- `observations`
- `research_studies`
- `import_jobs`
- `source_records`

The domain will use these rules:

- `Patient` is the canonical identity anchor.
- `Encounter` belongs to one `Patient`.
- `Observation` belongs to one `Patient` and may optionally belong to one `Encounter`.
- `ResearchStudy` is metadata only in v1.
- `ImportJob` represents one ingestion batch.
- `SourceRecord` stores row-level provenance and points to exactly one imported resource through `(resource_type, resource_id)`.
- `SourceRecord` stores provenance for each normalized resource emitted by the import pipeline.

We will not introduce `ResearchStudy` to `Patient` relationships yet.

## Consequences

- SQLAlchemy models stay small and direct.
- Alembic migrations can be created without join tables or polymorphic association tables.
- Import idempotency can be enforced with unique constraints on `external_id` and `checksum`.
- A single CSV row can fan out into more than one `SourceRecord`, which is necessary for imports that create both `Patient` and `Observation` from the same row.
- Provenance is preserved without coupling source metadata into business tables.
- Study membership and advanced authorization are deferred to a later iteration.
