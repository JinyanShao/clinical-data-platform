# Clinical Data Platform

Clinical Data Platform is a backend-focused system for ingesting, validating, and standardizing clinical research data using FHIR.

It is designed around real data-engineering concerns: heterogeneous input formats, data quality, provenance, idempotent processing, and controlled access to research data.

FHIR-based clinical research data platform for reliable ingestion, validation, standardization, and traceability of healthcare data.

This project is under active development.

## v1 scope

- Resources: `Patient`, `Encounter`, `Observation`, `ResearchStudy`
- Imports: CSV and FHIR Bundle
- Capabilities: async import jobs, idempotency, validation, error reports, audit trail, RBAC

## Tech stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Redis/Celery or Dramatiq
- Docker
- pytest

## Current status

- Core domain model completed
- PostgreSQL persistence layer completed
- Alembic migrations configured
- Repository layer implemented
- Service layer with business validation implemented
- Automated tests covering core domain rules

Next milestone: REST API layer

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Database

```bash
.venv/bin/alembic upgrade head
```

By default this uses a local SQLite database for development checks. Set `DATABASE_URL` to target PostgreSQL.

## Tests

```bash
.venv/bin/pytest
```

## First milestone

Define the business and data boundaries first, then design the database model.

See [PROJECT_SPEC.md](./PROJECT_SPEC.md).
