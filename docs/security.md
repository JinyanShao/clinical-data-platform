# Security and data-use boundaries

## Intended use

This repository uses synthetic clinical records only. It is a software engineering demonstration and is not intended for diagnosis, treatment, clinical decision support, patient care, or storage of real protected health information.

The project does not claim certification or compliance with HIPAA, GDPR, Swiss FADP, or any other healthcare or privacy regulation.

## Configuration is fail-closed

Missing configuration must never produce a permissive deployment, so every default points at the strict option:

- `ENVIRONMENT` defaults to `production`. Forgetting to set it yields the tightest behaviour, not the loosest.
- There is no fallback bootstrap token. Bootstrap admin access exists only when an operator sets `ADMIN_API_KEY`, or when `ENABLE_DEMO_ADMIN_TOKEN=true` is combined with `ENVIRONMENT=development`. Enabling the demo token anywhere else aborts startup, as does supplying the published demo value as `ADMIN_API_KEY`.
- `DATABASE_URL` is mandatory outside development. The application refuses to start rather than fall back to a local SQLite file that `/ready` would report as healthy.

These checks run at API startup and at Celery worker startup, so a misconfigured process fails immediately instead of serving traffic.

`/ready` checks the database, Redis, and a short-lived Redis heartbeat emitted by the worker. It does not issue Celery control broadcasts on every readiness request.

## Authentication

The current Bearer API keys are intentionally scoped demo authentication. Only SHA-256 hashes are stored in the database, and generated keys are returned once. The Compose stack opts into the development bootstrap key explicitly so the demo can run without an external identity provider.

A production deployment should replace API keys with OAuth2/OIDC tokens issued by a managed identity provider. It should validate issuer, audience, expiry, signing keys, and organization-specific claims, and should implement key rotation and account lifecycle policies.

## Authorization

Three roles are implemented:

- `admin`: import and modify data, manage ResearchStudy records, enroll subjects, and grant access;
- `researcher`: read clinical data only for authorized studies;
- `auditor`: read import reports, provenance, and audit logs without write access.

Researcher isolation is enforced through `StudyAccess -> ResearchStudy -> ResearchSubject -> Patient`. Encounter and Observation access follows their Patient ownership.

Isolation depends on Patient identity being trustworthy. External identifiers are namespaced pairs of `(source_namespace, external_id)`, so two sites that both number their subjects `P001` produce two Patient rows rather than merging into one shared record that each site's researchers could then read.

`admin` and `auditor` read across every study by design. Auditors exist to inspect imports, provenance, and audit logs platform-wide, so study scoping does not constrain them; researcher requests are the ones scoped to granted studies.

## Audit and provenance

AuditLog records significant writes and permission changes with actor, action, resource identity, before/after state, and timestamp. Entries are ordered by `(timestamp, id)` so pagination stays stable when two entries share a timestamp. Routine reads are not audited to avoid low-value event volume.

SourceRecord is an append-only provenance history rather than a single origin pointer. Every import that creates or re-observes a resource appends an event carrying the raw input, the source row, the action (`created` or `reasserted`), and a timestamp, so `GET /api/v1/provenance/{resource_type}/{resource_id}` can answer which imports produced or re-observed a resource and when.

## Production hardening still required

- OAuth2/OIDC and centralized user lifecycle management
- TLS termination and secret management
- encrypted database volumes and managed backups
- API rate limiting and request-size limits
- a regular dependency-update process for the pinned `requirements.lock`
- malware scanning and object storage for uploaded files
- formal threat modeling, retention policy, and incident response
- jurisdiction-specific legal, privacy, and security review
- independent penetration testing and compliance assessment
