# Security and data-use boundaries

## Intended use

This repository uses synthetic clinical records only. It is a software engineering demonstration and is not intended for diagnosis, treatment, clinical decision support, patient care, or storage of real protected health information.

The project does not claim certification or compliance with HIPAA, GDPR, Swiss FADP, or any other healthcare or privacy regulation.

## Authentication

The current Bearer API keys are intentionally scoped demo authentication. Only SHA-256 hashes are stored in the database, and generated keys are returned once. The Compose stack provides a development bootstrap key so the demo can run without an external identity provider.

A production deployment should replace API keys with OAuth2/OIDC tokens issued by a managed identity provider. It should validate issuer, audience, expiry, signing keys, and organization-specific claims, and should implement key rotation and account lifecycle policies.

## Authorization

Three roles are implemented:

- `admin`: import and modify data, manage ResearchStudy records, enroll subjects, and grant access;
- `researcher`: read clinical data only for authorized studies;
- `auditor`: read import reports, provenance, and audit logs without write access.

Researcher isolation is enforced through `StudyAccess -> ResearchStudy -> ResearchSubject -> Patient`. Encounter and Observation access follows their Patient ownership.

## Audit and provenance

AuditLog records significant writes and permission changes with actor, action, resource identity, before/after state, and timestamp. SourceRecord stores import provenance and the original synthetic row or Bundle entry. Routine reads are not audited to avoid low-value event volume.

## Production hardening still required

- OAuth2/OIDC and centralized user lifecycle management
- TLS termination and secret management
- encrypted database volumes and managed backups
- API rate limiting and request-size limits
- malware scanning and object storage for uploaded files
- formal threat modeling, retention policy, and incident response
- jurisdiction-specific legal, privacy, and security review
- independent penetration testing and compliance assessment
