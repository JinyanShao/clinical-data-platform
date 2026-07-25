# clinical-data-platform

[![CI](https://github.com/JinyanShao/clinical-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/JinyanShao/clinical-data-platform/actions/workflows/ci.yml)

FHIR-based clinical research data platform for reliable ingestion, validation, provenance, access control, and asynchronous processing.

Clinical research teams receive data in inconsistent CSV exports and FHIR payloads. Loading those records safely requires more than parsing: invalid rows must not block valid data, references must remain consistent, repeated uploads must be idempotent, every normalized resource needs provenance, and researchers must only see patients in studies they are authorized to access.

This project implements that complete backend workflow with synthetic data.

## Core capabilities

- CSV and FHIR Bundle ingestion through one normalized import pipeline
- Patient, Encounter, Observation, and ResearchStudy validation
- Row/entry-level error reports with `completed`, `partial`, and `failed` outcomes
- SHA-256 import idempotency and external identifier deduplication
- SourceRecord provenance linking normalized resources to original input
- Celery workers, Redis queueing, retry, timeout, and failure diagnostics
- API-key authentication with admin, researcher, and auditor roles
- ResearchStudy access grants and ResearchSubject patient isolation
- Audit logs with actor, action, before/after state, and timestamp
- JSON logs, request IDs, liveness, and dependency readiness checks

## Architecture

```mermaid
flowchart LR
    Client --> API[FastAPI API]
    API --> Services[Service Layer]
    Services --> DB[(PostgreSQL)]
    API --> Redis[(Redis)]
    Redis --> Worker[Celery Worker]
    Worker --> Pipeline[Shared Import Pipeline]
    CSV[CSV Parser] --> Pipeline
    FHIR[FHIR Bundle Parser] --> Pipeline
    Pipeline --> Validation[Validation and normalization]
    Validation --> Services
    Services --> Provenance[Provenance and audit]
```

CSV and FHIR parsers only map source-specific input. Validation, domain services, persistence, idempotency, provenance, Study binding, and reporting are shared. See [Architecture](docs/architecture.md) for request, import, access-control, and failure flows.

## Quick start

Requirements: Docker with Compose v2.

```bash
git clone https://github.com/JinyanShao/clinical-data-platform.git
cd clinical-data-platform
docker compose up --build
```

The command starts PostgreSQL, Redis, migrations, FastAPI, and a Celery worker. When the services are healthy:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Liveness: [http://localhost:8000/health](http://localhost:8000/health)
- Readiness: [http://localhost:8000/ready](http://localhost:8000/ready)
- Development admin token: `demo-admin-token`

In Swagger, select **Authorize** and enter `demo-admin-token`.

## Run the demo

With the Compose stack running:

```bash
docker compose exec api python scripts/demo.py
```

The repeatable script:

1. Creates or reuses a synthetic ResearchStudy.
2. Creates a researcher and grants access to that Study.
3. submits [clinical_records.csv](demo/clinical_records.csv) and [fhir_bundle.json](demo/fhir_bundle.json).
4. Waits for both Celery jobs and prints their final status.
5. Queries patients with the researcher's restricted API key.

Inspect the results through:

```bash
curl -H 'Authorization: Bearer demo-admin-token' http://localhost:8000/api/v1/import-jobs
curl -H 'Authorization: Bearer demo-researcher-token' http://localhost:8000/api/v1/patients
```

## Import model

```text
CSV  -> CSV parser  --\
                       -> normalized records -> shared pipeline -> domain services
FHIR -> FHIR parser --/                              |               |
                                                    v               v
                                              error report     PostgreSQL
                                                                    |
                                                          provenance + audit
```

The FHIR importer supports Bundle entries for `Patient`, `Encounter`, `Observation`, and `ResearchStudy`. It resolves `ResourceType/id`, absolute URL, and Bundle `fullUrl` references. This is a deliberately scoped clinical data pipeline, not a complete implementation of every FHIR resource or profile.

## Roles

| Role | Access |
| --- | --- |
| `admin` | Imports data, modifies clinical resources, manages studies and grants |
| `researcher` | Reads patients and clinical data in explicitly authorized studies |
| `auditor` | Reads import reports, provenance, and audit logs without modifying data |

API keys are demo authentication. Production deployment should replace them with OAuth2/OIDC and managed identity. See [Security](docs/security.md).

## Technology

- Python 3.12, FastAPI, Pydantic
- SQLAlchemy 2, Alembic, PostgreSQL
- Celery and Redis
- Docker Compose
- pytest, Coverage, Ruff, GitHub Actions

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m alembic upgrade head
.venv/bin/ruff check .
.venv/bin/coverage run -m pytest -q
.venv/bin/coverage report
```

The release contains **46 automated tests** and enforces at least **85% coverage** in CI. CI also verifies migration drift and builds the application image.

## Current limitations

- Synthetic data only; not intended for clinical care or production patient data
- Scoped FHIR Bundle support rather than full profile/terminology validation
- Demo API-key authentication rather than OAuth2/OIDC
- Import payloads are stored in PostgreSQL for retry; object storage is the next scale step
- No user interface beyond OpenAPI/Swagger
- No claim of HIPAA, GDPR, or Swiss FADP certification or compliance

## Documentation

- [Architecture](docs/architecture.md)
- [Security](docs/security.md)
- [Domain model](docs/domain-model.md)
- [Database schema](docs/database-schema.md)
- [Core data model decision](docs/decisions/001-core-data-model.md)

## License

No license has been assigned. All rights are reserved by the repository owner.
