# Domain Model

## Purpose

This v1 model is the minimum structure needed to import clinical research data, normalize it into FHIR-shaped records, preserve provenance, and support researcher queries without adding study membership or hospital integration yet.

## Entities

### Patient

Patient exists as the canonical person record. It is the anchor for imported clinical data and the deduplication boundary for repeated uploads. In v1, one patient can have many encounters and many observations.

### Encounter

Encounter exists to group clinical activity into a time-bounded episode. It belongs to exactly one patient. Observations may optionally reference an encounter when the source data provides that context, but observations can also stand alone at the patient level.

### Observation

Observation exists to store measured or reported facts such as laboratory results. It belongs to exactly one patient and may optionally belong to one encounter. The model keeps `value` flexible so v1 can hold numeric and text results without splitting into specialized observation tables.

### ResearchStudy

ResearchStudy exists as a study catalog entity. It lets the platform represent study metadata now without prematurely designing subject enrollment or study-specific access control. In v1 it is independent from patient data.

### ImportJob

ImportJob exists to represent one ingestion run. It is the batch-level object that tracks source type, filenames, counts, status, and timing. Every upload creates one import job, even when the incoming rows later fail validation.

### SourceRecord

SourceRecord exists to preserve provenance for each normalized resource produced by the import pipeline. One raw input row may fan out into more than one source record if the transform step creates multiple resources from it. It makes idempotency and audit traceability possible without embedding source metadata into every business table.

## Relationships

- `Patient` 1 -> many `Encounter`
- `Patient` 1 -> many `Observation`
- `Encounter` 0 -> many `Observation`
- `ImportJob` 1 -> many `SourceRecord`
- `SourceRecord` points to exactly one imported resource via `(resource_type, resource_id)`

## Relationship rules

- `Observation.encounter_id` is optional.
- `ResearchStudy` has no direct relationship to `Patient` in v1.
- `SourceRecord.resource_type` is an application-level discriminator, not a foreign key, because it may point to more than one table type.
- More than one `SourceRecord` may share the same `source_row`.
- v1 does not use a separate join table for study membership.
