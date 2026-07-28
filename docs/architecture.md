# Architecture

## System context

The platform separates interactive API work from potentially large imports. FastAPI handles authentication, authorization, query operations, and task creation. Celery workers consume import tasks through Redis and use the same Service Layer as manual API writes.

```mermaid
flowchart TB
    Client[API client or Swagger]
    API[FastAPI]
    Services[Service Layer]
    PostgreSQL[(PostgreSQL)]
    Redis[(Redis)]
    Worker[Celery Worker]
    CSV[CSV Parser]
    FHIR[FHIR Bundle Parser]
    Pipeline[Normalized Import Pipeline]
    Validation[Business and reference validation]
    Trace[SourceRecord provenance and ImportJob report]
    Audit[AuditLog]

    Client --> API
    API --> Services
    Services --> PostgreSQL
    API -->|enqueue job id| Redis
    Redis --> Worker
    Worker --> CSV
    Worker --> FHIR
    CSV --> Pipeline
    FHIR --> Pipeline
    Pipeline --> Validation
    Validation --> Services
    Services --> Trace
    Services --> Audit
    Trace --> PostgreSQL
    Audit --> PostgreSQL
```

## Import flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Queue as Redis
    participant Worker as Celery Worker
    participant Pipeline as Import Pipeline

    Client->>API: POST CSV or FHIR Bundle
    API->>DB: Create pending ImportJob and store payload
    API->>Queue: Publish job id
    API-->>Client: 202 Accepted with ImportJob id
    Queue->>Worker: Deliver job
    Worker->>DB: Mark processing
    Worker->>Pipeline: Parse normalized records
    loop Each row or Bundle entry
        Pipeline->>DB: Savepoint, validate, persist, record provenance
        alt Record is invalid
            Pipeline->>DB: Roll back savepoint and add ImportError
        end
    end
    Worker->>DB: Mark completed, partial, or failed
```

The HTTP request never performs parsing or domain persistence. The payload and job state are committed before publishing so a worker can always recover the task from PostgreSQL. Celery uses late acknowledgement, bounded execution time, exponential retry, and diagnostic failure reasons.

## Shared normalization boundary

`CsvParser` and `FhirBundleParser` produce the same normalized structures: `PatientData`, `EncounterData`, `ObservationData`, and `ResearchStudyData`. `ImportPipelineService` owns all behavior after mapping:

- domain and reference checks;
- external identifier reuse;
- Study enrollment through ResearchSubject;
- SQL savepoint isolation;
- SourceRecord creation;
- ImportError and ImportJob counts.

This boundary prevents CSV and FHIR imports from drifting into separate business implementations.

## Study isolation

```mermaid
erDiagram
    USER ||--o{ STUDY_ACCESS : receives
    RESEARCH_STUDY ||--o{ STUDY_ACCESS : grants
    RESEARCH_STUDY ||--o{ RESEARCH_SUBJECT : contains
    PATIENT ||--o{ RESEARCH_SUBJECT : enrolled_as
    PATIENT ||--o{ ENCOUNTER : has
    PATIENT ||--o{ OBSERVATION : has
```

Researchers can query a Patient only when a StudyAccess grant and ResearchSubject enrollment connect that user to the patient. Encounter and Observation access follows the owning Patient. Admins bypass Study filtering; auditors cannot query clinical records.

## Operational behavior

- `/health` reports process liveness without external calls.
- `/ready` checks PostgreSQL, Redis, and a short-lived Redis heartbeat emitted by the Celery worker. It does not issue Celery control broadcasts.
- `X-Request-ID` is accepted or generated and returned on every HTTP response.
- Application logs are JSON and include request or import-job correlation fields.
- AuditLog captures manual writes, access grants, subject enrollment, import submission, and retries. Routine GET requests are intentionally excluded.
