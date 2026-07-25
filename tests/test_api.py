from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from clinical_data_platform.auth import Principal, get_current_user
from clinical_data_platform.main import app
from clinical_data_platform.models import AuditLog, Encounter, Observation, Patient, ResearchStudy, SourceRecord, User
from clinical_data_platform.services.csv_import import CSV_HEADERS
from clinical_data_platform.session import get_session
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'api.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_session():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: Principal(None, "test-admin", "admin")
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_http_creates_patient_encounter_observation_flow(client: TestClient) -> None:
    patient = client.post(
        "/api/v1/patients",
        json={"external_id": "api-patient-001", "birth_date": "1980-01-01", "sex": "female"},
    )
    assert patient.status_code == 201
    patient_id = patient.json()["id"]

    started_at = datetime.now(UTC)
    encounter = client.post(
        "/api/v1/encounters",
        json={
            "patient_id": patient_id,
            "external_id": "api-encounter-001",
            "status": "finished",
            "encounter_type": "outpatient",
            "started_at": started_at.isoformat(),
            "ended_at": (started_at + timedelta(hours=1)).isoformat(),
        },
    )
    assert encounter.status_code == 201
    encounter_id = encounter.json()["id"]

    observation = client.post(
        "/api/v1/observations",
        json={
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "external_id": "api-observation-001",
            "code": "718-7",
            "code_system": "LOINC",
            "value": "5.2",
            "unit": "mmol/L",
            "observed_at": started_at.isoformat(),
            "status": "final",
        },
    )
    assert observation.status_code == 201

    assert client.get(f"/api/v1/patients/{patient_id}").status_code == 200
    assert client.get(f"/api/v1/encounters/{encounter_id}").status_code == 200
    assert client.get(f"/api/v1/observations/{observation.json()['id']}").status_code == 200
    assert len(client.get("/api/v1/patients?limit=1&offset=0").json()) == 1

    encounter_update = client.patch(
        f"/api/v1/encounters/{encounter_id}",
        json={"status": "cancelled"},
    )
    assert encounter_update.status_code == 200
    assert encounter_update.json()["status"] == "cancelled"

    observation_id = observation.json()["id"]
    observation_update = client.patch(
        f"/api/v1/observations/{observation_id}",
        json={"value": "5.4"},
    )
    assert observation_update.status_code == 200
    assert observation_update.json()["value"] == "5.4"

    assert [item["id"] for item in client.get("/api/v1/encounters?limit=1").json()] == [encounter_id]
    assert [item["id"] for item in client.get("/api/v1/observations?limit=1").json()] == [observation_id]


def test_not_found_patient_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/patients/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "patient not found"


def test_duplicate_patient_external_id_returns_409(client: TestClient) -> None:
    payload = {"external_id": "api-patient-dup"}
    assert client.post("/api/v1/patients", json=payload).status_code == 201

    response = client.post("/api/v1/patients", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "patient external_id already exists"


def test_validation_error_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/patients", json={"external_id": "", "sex": "invalid"})
    assert response.status_code == 422
    assert response.json()["detail"] == "request validation failed"
    assert response.json()["errors"]


def test_invalid_encounter_time_returns_400(client: TestClient) -> None:
    patient_id = client.post("/api/v1/patients", json={"external_id": "api-patient-time"}).json()["id"]
    started_at = datetime.now(UTC)

    response = client.post(
        "/api/v1/encounters",
        json={
            "patient_id": patient_id,
            "external_id": "api-encounter-bad-time",
            "status": "finished",
            "encounter_type": "outpatient",
            "started_at": started_at.isoformat(),
            "ended_at": (started_at - timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 400
    assert "ended_at" in response.json()["detail"]


def test_observation_rejects_other_patients_encounter(client: TestClient) -> None:
    first = client.post("/api/v1/patients", json={"external_id": "api-patient-first"}).json()
    second = client.post("/api/v1/patients", json={"external_id": "api-patient-second"}).json()
    encounter = client.post(
        "/api/v1/encounters",
        json={
            "patient_id": first["id"],
            "external_id": "api-encounter-first",
            "status": "finished",
            "encounter_type": "outpatient",
        },
    ).json()

    response = client.post(
        "/api/v1/observations",
        json={
            "patient_id": second["id"],
            "encounter_id": encounter["id"],
            "external_id": "api-observation-wrong-encounter",
            "code": "718-7",
            "code_system": "LOINC",
            "value": "5.2",
            "observed_at": datetime.now(UTC).isoformat(),
            "status": "final",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "encounter belongs to a different patient"


def test_research_study_crud(client: TestClient) -> None:
    created = client.post(
        "/api/v1/research-studies",
        json={"title": "Synthetic Lab Study", "description": "v1 test study", "status": "active"},
    )
    assert created.status_code == 201
    study_id = created.json()["id"]

    patched = client.patch(f"/api/v1/research-studies/{study_id}", json={"status": "completed"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "completed"
    assert client.get(f"/api/v1/research-studies/{study_id}").status_code == 200
    assert client.delete(f"/api/v1/research-studies/{study_id}").status_code == 204
    assert client.get(f"/api/v1/research-studies/{study_id}").status_code == 404


def test_import_job_query_is_read_only_for_now(client: TestClient) -> None:
    assert client.get("/api/v1/import-jobs").json() == []
    assert client.get(f"/api/v1/import-jobs/{uuid4()}").status_code == 404


def _csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _clinical_row(number: int) -> dict[str, str]:
    return {
        "patient_external_id": f"csv-patient-{number}",
        "birth_date": "1980-01-01",
        "sex": "female",
        "encounter_external_id": f"csv-encounter-{number}",
        "encounter_start": "2026-07-25T08:00:00+00:00",
        "encounter_end": "2026-07-25T09:00:00+00:00",
        "observation_external_id": f"csv-observation-{number}",
        "observation_code": "718-7",
        "observation_value": "5.2",
        "observation_unit": "mmol/L",
        "observed_at": "2026-07-25T08:30:00+00:00",
    }


def _upload_csv(client: TestClient, content: bytes, filename: str = "clinical.csv"):
    return client.post("/api/v1/imports/csv", files={"file": (filename, content, "text/csv")})


def _test_session(client: TestClient) -> Session:
    dependency = app.dependency_overrides[get_session]()
    session = next(dependency)
    session.info["dependency_generator"] = dependency
    return session


def test_csv_imports_100_valid_rows(client: TestClient) -> None:
    response = _upload_csv(client, _csv([_clinical_row(number) for number in range(100)]))

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert response.json()["total_records"] == 100
    assert response.json()["successful_records"] == 100
    assert response.json()["failed_records"] == 0


def test_csv_import_continues_after_error_and_preserves_source(client: TestClient) -> None:
    invalid = _clinical_row(2)
    invalid["observation_value"] = "not-a-number"
    response = _upload_csv(client, _csv([_clinical_row(1), invalid, _clinical_row(3)]))

    report = response.json()
    assert report["status"] == "partial"
    assert (report["total_records"], report["successful_records"], report["failed_records"]) == (3, 2, 1)
    assert report["errors"] == [
        {
            "row": 3,
            "field": "observation_value",
            "code": "INVALID_NUMBER",
            "message": "Expected a numeric value",
        }
    ]

    session = _test_session(client)
    try:
        source = session.scalar(
            select(SourceRecord).where(
                SourceRecord.import_job_id == UUID(report["id"]),
                SourceRecord.resource_type == "observation",
                SourceRecord.source_row == 2,
            )
        )
        assert source is not None
        assert source.raw_data["observation_external_id"] == "csv-observation-1"
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
    finally:
        session.close()


def test_csv_import_is_idempotent_for_duplicate_ids_and_reupload(client: TestClient) -> None:
    row = _clinical_row(10)
    content = _csv([row, row])
    first = _upload_csv(client, content)
    second = _upload_csv(client, content)

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["successful_records"] == 2

    session = _test_session(client)
    try:
        assert session.scalar(select(func.count()).select_from(Patient)) == 1
        assert session.scalar(select(func.count()).select_from(Encounter)) == 1
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 3
    finally:
        session.close()


def test_csv_rejects_unknown_header(client: TestClient) -> None:
    response = _upload_csv(client, b"patient_external_id,unknown\np-1,value\n")

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["code"] == "INVALID_HEADER"


def _fhir_bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "fhir-observation-1",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "718-7"}]},
                    "subject": {"reference": "urn:uuid:fhir-patient-1"},
                    "encounter": {"reference": "urn:uuid:fhir-encounter-1"},
                    "valueQuantity": {"value": 5.2, "unit": "mmol/L"},
                    "effectiveDateTime": "2026-07-25T08:30:00Z",
                }
            },
            {
                "fullUrl": "urn:uuid:fhir-encounter-1",
                "resource": {
                    "resourceType": "Encounter",
                    "id": "fhir-encounter-1",
                    "status": "finished",
                    "class": {"code": "AMB"},
                    "subject": {"reference": "urn:uuid:fhir-patient-1"},
                    "period": {
                        "start": "2026-07-25T08:00:00Z",
                        "end": "2026-07-25T09:00:00Z",
                    },
                },
            },
            {
                "fullUrl": "urn:uuid:fhir-patient-1",
                "resource": {
                    "resourceType": "Patient",
                    "id": "fhir-patient-1",
                    "birthDate": "1980-01-01",
                    "gender": "female",
                },
            },
            {
                "resource": {
                    "resourceType": "ResearchStudy",
                    "id": "fhir-study-1",
                    "title": "FHIR Import Study",
                    "status": "active",
                    "description": "Synthetic study",
                }
            },
        ],
    }


def test_fhir_bundle_imports_all_supported_resources_and_is_idempotent(client: TestClient) -> None:
    bundle = _fhir_bundle()
    first = client.post("/api/v1/imports/fhir", json=bundle)
    second = client.post("/api/v1/imports/fhir", json={**bundle, "type": "collection"})

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert (first.json()["total_records"], first.json()["successful_records"], first.json()["failed_records"]) == (4, 4, 0)
    assert first.json()["errors"] == []

    assert client.get("/api/v1/patients").json()[0]["external_id"] == "fhir-patient-1"
    assert client.get("/api/v1/encounters").json()[0]["external_id"] == "fhir-encounter-1"
    assert client.get("/api/v1/observations").json()[0]["code_system"] == "http://loinc.org"
    assert client.get("/api/v1/research-studies").json()[0]["external_id"] == "fhir-study-1"

    session = _test_session(client)
    try:
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 4
        assert session.scalar(select(func.count()).select_from(ResearchStudy)) == 1
        source = session.scalar(
            select(SourceRecord).where(SourceRecord.resource_type == "observation")
        )
        assert source.raw_data["resourceType"] == "Observation"
    finally:
        session.close()


def test_fhir_bundle_reports_entry_errors_without_rolling_back_valid_entries(client: TestClient) -> None:
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "partial-patient", "gender": "unknown"}},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "bad-reference-observation",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "718-7"}]},
                    "subject": {"reference": "Patient/partial-patient"},
                    "encounter": {"reference": "Encounter/missing"},
                    "valueQuantity": {"value": 5.2},
                    "effectiveDateTime": "2026-07-25T08:30:00Z",
                }
            },
            {"resource": {"resourceType": "Condition", "id": "unsupported"}},
        ],
    }

    response = client.post("/api/v1/imports/fhir", json=bundle)
    report = response.json()

    assert response.status_code == 202
    assert (report["total_records"], report["successful_records"], report["failed_records"]) == (3, 1, 2)
    assert [(error["row"], error["code"]) for error in report["errors"]] == [
        (2, "INVALID_REFERENCE"),
        (3, "UNSUPPORTED_RESOURCE"),
    ]
    assert client.get("/api/v1/patients").json()[0]["external_id"] == "partial-patient"
    assert client.get("/api/v1/observations").json() == []


def test_fhir_rejects_non_bundle_document(client: TestClient) -> None:
    response = client.post("/api/v1/imports/fhir", json={"resourceType": "Patient", "id": "p-1"})

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["code"] == "INVALID_BUNDLE"


def _actor(role: str, user_id: str | None = None, username: str | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: Principal(
        UUID(user_id) if user_id else None,
        username or f"test-{role}",
        role,
    )


def _study(client: TestClient, title: str) -> dict:
    return client.post("/api/v1/research-studies", json={"title": title, "status": "active"}).json()


def _patient(client: TestClient, external_id: str) -> dict:
    return client.post("/api/v1/patients", json={"external_id": external_id}).json()


def _user(client: TestClient, username: str, role: str = "researcher") -> dict:
    return client.post("/api/v1/users", json={"username": username, "role": role}).json()


def test_api_requires_authentication(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)
    response = client.get("/api/v1/patients")
    assert response.status_code == 401


def test_researcher_cannot_create_patient(client: TestClient) -> None:
    _actor("researcher")
    assert client.post("/api/v1/patients", json={"external_id": "denied"}).status_code == 403


def test_auditor_cannot_read_clinical_data(client: TestClient) -> None:
    _actor("auditor")
    assert client.get("/api/v1/patients").status_code == 403


def test_admin_creates_hashed_api_key_user(client: TestClient) -> None:
    created = _user(client, "alice")
    assert created["role"] == "researcher"
    assert created["api_key"]

    session = _test_session(client)
    try:
        user = session.get(User, UUID(created["id"]))
        assert user.api_key_hash != created["api_key"]
        assert len(user.api_key_hash) == 64
    finally:
        session.close()


def test_database_api_key_authenticates_user(client: TestClient) -> None:
    created = _user(client, "real-token-user")
    app.dependency_overrides.pop(get_current_user)

    response = client.get(
        "/api/v1/research-studies",
        headers={"Authorization": f"Bearer {created['api_key']}"},
    )
    assert response.status_code == 200


def test_duplicate_username_returns_conflict(client: TestClient) -> None:
    _user(client, "duplicate-user")
    assert client.post(
        "/api/v1/users", json={"username": "duplicate-user", "role": "auditor"}
    ).status_code == 409


def test_researcher_only_lists_authorized_studies(client: TestClient) -> None:
    allowed = _study(client, "Allowed Study")
    _study(client, "Hidden Study")
    user = _user(client, "study-reader")
    assert client.post(f"/api/v1/research-studies/{allowed['id']}/access/{user['id']}").status_code == 201

    _actor("researcher", user["id"], "study-reader")
    studies = client.get("/api/v1/research-studies").json()
    assert [study["id"] for study in studies] == [allowed["id"]]


def test_researcher_cannot_read_patient_from_other_study(client: TestClient) -> None:
    allowed_study = _study(client, "Allowed")
    denied_study = _study(client, "Denied")
    allowed_patient = _patient(client, "allowed-patient")
    denied_patient = _patient(client, "denied-patient")
    user = _user(client, "isolated-reader")
    client.post(f"/api/v1/research-studies/{allowed_study['id']}/access/{user['id']}")
    client.post(f"/api/v1/research-studies/{allowed_study['id']}/patients/{allowed_patient['id']}")
    client.post(f"/api/v1/research-studies/{denied_study['id']}/patients/{denied_patient['id']}")

    _actor("researcher", user["id"], "isolated-reader")
    assert client.get(f"/api/v1/patients/{allowed_patient['id']}").status_code == 200
    assert client.get(f"/api/v1/patients/{denied_patient['id']}").status_code == 403
    assert [patient["id"] for patient in client.get("/api/v1/patients").json()] == [allowed_patient["id"]]


def test_researcher_encounter_and_observation_lists_are_study_scoped(client: TestClient) -> None:
    study = _study(client, "Scoped")
    patient = _patient(client, "scoped-patient")
    hidden = _patient(client, "hidden-patient")
    user = _user(client, "clinical-reader")
    client.post(f"/api/v1/research-studies/{study['id']}/access/{user['id']}")
    client.post(f"/api/v1/research-studies/{study['id']}/patients/{patient['id']}")
    for index, owner in enumerate((patient, hidden)):
        encounter = client.post(
            "/api/v1/encounters",
            json={"patient_id": owner["id"], "external_id": f"scope-enc-{index}", "status": "finished", "encounter_type": "AMB"},
        ).json()
        client.post(
            "/api/v1/observations",
            json={
                "patient_id": owner["id"], "encounter_id": encounter["id"],
                "external_id": f"scope-obs-{index}", "code": "718-7", "code_system": "LOINC",
                "value": "5.2", "observed_at": "2026-07-25T08:00:00Z", "status": "final",
            },
        )

    _actor("researcher", user["id"], "clinical-reader")
    assert [item["external_id"] for item in client.get("/api/v1/encounters").json()] == ["scope-enc-0"]
    assert [item["external_id"] for item in client.get("/api/v1/observations").json()] == ["scope-obs-0"]


def test_manual_update_records_audit_before_and_after(client: TestClient) -> None:
    patient = _patient(client, "audit-patient")
    client.patch(f"/api/v1/patients/{patient['id']}", json={"sex": "unknown"})

    _actor("auditor")
    logs = client.get("/api/v1/audit-logs").json()
    update = next(log for log in logs if log["action"] == "update" and log["resource_id"] == patient["id"])
    assert update["before"]["sex"] is None
    assert update["after"]["sex"] == "unknown"


def test_permission_changes_are_audited(client: TestClient) -> None:
    study = _study(client, "Audit Access")
    user = _user(client, "audit-access-user")
    client.post(f"/api/v1/research-studies/{study['id']}/access/{user['id']}")

    session = _test_session(client)
    try:
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "grant_access")
        ) == 1
    finally:
        session.close()


def test_auditor_reads_import_provenance_but_cannot_import(client: TestClient) -> None:
    imported = _upload_csv(client, _csv([_clinical_row(500)])).json()
    _actor("auditor")
    assert client.get(f"/api/v1/import-jobs/{imported['id']}/source-records").status_code == 200
    assert _upload_csv(client, _csv([_clinical_row(501)])).status_code == 403


def test_import_binds_existing_patient_to_selected_study(client: TestClient) -> None:
    study = _study(client, "Import Study")
    patient = _patient(client, "existing-fhir-patient")
    user = _user(client, "import-study-reader")
    client.post(f"/api/v1/research-studies/{study['id']}/access/{user['id']}")
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "existing-patient-observation",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "718-7"}]},
                    "subject": {"reference": "Patient/existing-fhir-patient"},
                    "valueQuantity": {"value": 5.2},
                    "effectiveDateTime": "2026-07-25T08:30:00Z",
                }
            }
        ],
    }
    assert client.post(f"/api/v1/imports/fhir?study_id={study['id']}", json=bundle).status_code == 202

    _actor("researcher", user["id"], "import-study-reader")
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 200


def test_import_endpoint_only_dispatches_when_not_eager(client: TestClient, monkeypatch) -> None:
    from clinical_data_platform import tasks
    from clinical_data_platform.celery_app import celery_app

    class Result:
        id = "celery-task-1"

    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = False
    monkeypatch.setattr(tasks.run_import, "delay", lambda job_id: Result())
    try:
        response = _upload_csv(client, _csv([_clinical_row(600)]))
    finally:
        celery_app.conf.task_always_eager = previous

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["task_id"] == "celery-task-1"
    assert client.get("/api/v1/patients").json() == []


def test_queue_failure_is_diagnostic(client: TestClient, monkeypatch) -> None:
    from clinical_data_platform import tasks
    from clinical_data_platform.celery_app import celery_app

    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = False
    monkeypatch.setattr(tasks.run_import, "delay", lambda job_id: (_ for _ in ()).throw(RuntimeError("redis down")))
    try:
        response = _upload_csv(client, _csv([_clinical_row(700)]))
    finally:
        celery_app.conf.task_always_eager = previous

    assert response.json()["status"] == "failed"
    assert "redis down" in response.json()["failure_reason"]


def test_failed_import_can_be_retried(client: TestClient) -> None:
    failed = _upload_csv(client, b"bad,header\n1,2\n").json()
    assert failed["status"] == "failed"

    retried = client.post(f"/api/v1/import-jobs/{failed['id']}/retry")
    assert retried.status_code == 202
    assert retried.json()["status"] == "failed"
    assert retried.json()["retry_count"] == 1


def test_health_returns_correlation_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "request-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"


def test_ready_reports_component_failure(client: TestClient, monkeypatch) -> None:
    import clinical_data_platform.main as main_module

    monkeypatch.setattr(
        main_module,
        "readiness_checks",
        lambda: {
            "database": {"status": "ok"},
            "redis": {"status": "error", "detail": "unavailable"},
            "worker": {"status": "error", "detail": "no workers"},
        },
    )
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["status"] == "error"


def test_ready_returns_200_when_all_dependencies_are_ready(client: TestClient, monkeypatch) -> None:
    import clinical_data_platform.main as main_module

    monkeypatch.setattr(
        main_module,
        "readiness_checks",
        lambda: {name: {"status": "ok"} for name in ("database", "redis", "worker")},
    )
    assert client.get("/ready").status_code == 200
