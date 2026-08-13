# Deployment guide

This guide covers a small, single-host deployment of the API, Celery worker,
PostgreSQL, and Redis. It is suitable for demonstrations and internal
environments using **synthetic data only**. It is not a production compliance
runbook for protected health information.

## Prerequisites

- Docker Engine 26+ with Docker Compose v2
- A reverse proxy or load balancer that terminates TLS before port 8000
- Operator-managed secrets for PostgreSQL and `ADMIN_API_KEY`
- Persistent storage and a tested database-backup policy

Check the installation:

```bash
docker compose version
docker compose config --quiet
```

## Development demonstration

The repository Compose file is intentionally configured for local development:

```bash
docker compose up --build --wait
docker compose exec api python scripts/demo.py
docker compose exec api python scripts/verify_demo.py
```

If port 8000 is occupied, prefix the Compose commands with `API_PORT=8001`.
For a host-side verification command, also set
`API_URL=http://127.0.0.1:8001`.

`--wait` waits for the API health check; the demo then submits the synthetic
CSV and FHIR Bundle and waits for their asynchronous jobs. The verification
script exits non-zero if readiness, import completion, researcher isolation,
or provenance checks fail. It is safe to repeat: imports are idempotent and
the named demo study/user are reused.

Stop the local stack without losing its database:

```bash
docker compose down
```

To discard the local demo database as well, use `docker compose down --volumes`.
This deletes the named PostgreSQL and Redis volumes.

## Environment contract

| Variable | Required outside development | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | Yes | `development`, `staging`, or `production`; defaults to `production`. |
| `DATABASE_URL` | Yes | SQLAlchemy PostgreSQL URL, for example `postgresql+psycopg://...`. |
| `REDIS_URL` | Yes in practice | Celery broker and readiness dependency. |
| `AUTH_MODE` | Yes outside development | `oidc` (default outside development) validates Keycloak JWTs; `api_key` is a development migration mode only. |
| `OIDC_ISSUER_URL` | With OIDC | Keycloak realm issuer, e.g. `https://id.example/realms/clinical`. |
| `OIDC_AUDIENCE` | With OIDC | The API client ID configured as the token audience. |
| `OIDC_JWKS_URL` | No | Optional Keycloak certificate/JWKS endpoint override; otherwise derived from issuer. |
| `ADMIN_API_KEY` | `api_key` mode only | Legacy bootstrap administrator Bearer token; do not use for production authentication. |
| `ENABLE_DEMO_ADMIN_TOKEN` | No | Development-only switch. Never set it outside development. |
| `MAX_UPLOAD_BYTES` | No | Maximum HTTP request body size; defaults to 10 MiB and is enforced for chunked uploads too. |
| `FHIR_VALIDATOR_JAR` | No | Read-only path to the vetted HL7 Validator JAR; enables reference FHIR validation in import workers. |
| `API_PORT` | No | Local Compose host port; defaults to `8000`. |

The API and worker fail at startup if the demo token is enabled outside
development, if production/staging lacks `DATABASE_URL`, or if an invalid
environment is supplied. The application does not create an implicit admin
when `ADMIN_API_KEY` is missing.

## Keycloak OIDC and database RLS

Production uses Keycloak realm access tokens. Configure a confidential or
public API client with audience `clinical-data-platform-api`, HTTPS-only
redirect URIs, and exactly one realm role per user: `admin`, `researcher`, or
`auditor`. The API verifies JWT issuer, audience, expiry, issued-at time, and
signature using Keycloak's cached JWKS endpoint; it does not send each request
to token introspection. The Keycloak `sub` claim is the stable local identity;
`preferred_username` is display-only.

The migration enables PostgreSQL RLS on patients, encounters, observations,
and research studies. The runtime connection must use non-owner role
`clinical_app`; the migration role remains the table owner. Before deployment,
create/login-enable `clinical_app`, set a strong password, grant it only the
rights supplied by the migration, and point API/worker `DATABASE_URL` at it.
RLS uses transaction-local `app.user_id` and `app.role` settings populated
only after JWT verification. Background imports run with the admin context.
Never run API/worker using a PostgreSQL superuser or table owner, because those
roles bypass RLS.

For a repeatable local Keycloak setup, use
[`compose.identity.yml`](../compose.identity.yml) with the checked-in
[`clinical` realm definition](../deploy/keycloak/clinical-realm.json). Create
an ignored `.env.identity.local` containing `KEYCLOAK_ADMIN_USERNAME`,
`KEYCLOAK_ADMIN_PASSWORD`, and `CLINICAL_APP_PASSWORD`; then enable the database
role as the migration owner before starting the overlay:

```bash
docker compose exec -T postgres psql -U clinical -d clinical_data_platform \
  -c "ALTER ROLE clinical_app LOGIN PASSWORD 'replace-with-a-secret'"
docker compose --env-file .env.identity.local -f docker-compose.yml -f compose.identity.yml up -d --build --wait
```

The development realm is intentionally loopback-only and uses HTTP. Production
must run Keycloak behind TLS with exact HTTPS redirect URIs; do not copy the
development client redirect wildcards into production.

## FHIR validation

The Python application validates its supported R4B resources with
`fhir.resources`. To also apply FHIR invariants and selected implementation
guide profiles, provision the official HL7 Validator JAR as an operator-managed
artifact, mount it read-only into both the API and worker containers, and set
`FHIR_VALIDATOR_JAR` to that path. The image includes a Java runtime for this
purpose. The validator is local: no clinical payload is sent to a third-party
service.

Keep the host mount in an operator-owned Compose override, for example:

```yaml
services:
  api:
    volumes: ["/srv/clinical/fhir-validator.jar:/opt/fhir-validator.jar:ro"]
  worker:
    volumes: ["/srv/clinical/fhir-validator.jar:/opt/fhir-validator.jar:ro"]
```

Set `FHIR_VALIDATOR_JAR=/opt/fhir-validator.jar` in the production `.env`.

The supplied synthetic FHIR bundle passes reference validation with warnings
only. Treat warning severity as review material; error/fatal severity becomes
an import row error. Pin and checksum the JAR in the deployment process rather
than downloading `latest` during image build.

Generate a bootstrap token without putting it into shell history:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## Production Compose overlay

Keep secrets outside version control. Copy
[`../.env.production.example`](../.env.production.example) to an
operator-owned `.env` file, replace every placeholder, and restrict it with
`chmod 600 .env`. The supplied
[`../compose.production.yml`](../compose.production.yml) overlay disables the
demo token, removes public PostgreSQL/Redis ports, and binds the API only to
loopback for a TLS proxy to front.

`DATABASE_URL` is an independent, complete URL. If the password contains URL
special characters, percent-encode it in this URL.

Validate the resolved configuration and start it:

```bash
docker compose --env-file .env -f docker-compose.yml -f compose.production.yml config --quiet
docker compose --env-file .env -f docker-compose.yml -f compose.production.yml up -d --build --wait
curl --fail --silent --show-error http://127.0.0.1:8000/ready
```

Put the API behind a TLS-enabled proxy and only expose that proxy publicly.
Restrict PostgreSQL and Redis to the application network. Back up PostgreSQL,
test restoration, rotate the bootstrap credential, and replace the demo API
key model with OAuth2/OIDC before any real-world deployment. See
[Security](security.md) for the remaining hardening requirements.

## Upgrade and rollback

1. Back up the database and record the running image digest.
2. Build/pull the intended version.
3. Run `docker compose ... run --rm migrate alembic upgrade head`.
4. Start API and worker with `up -d --wait`, then check `/ready` and run a
   smoke import in a non-production study.
5. If rollback is required, stop the application services, restore the backup,
   and deploy the previously recorded image. Review the Alembic revision before
   attempting a database downgrade; not every operational rollback should use
   an automatic schema downgrade.

## Operations checklist

- Monitor `/health` for process liveness and `/ready` for database, Redis, and
  worker heartbeat readiness.
- Retain structured API/worker logs and alert on failed or repeatedly retried
  import jobs.
- Limit request body size and rate at the proxy; uploads are currently read
  fully into memory.
- Use encrypted volumes, least-privilege network rules, managed secrets, and
  documented retention/incident-response procedures.
