from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import sqlalchemy as sa
from clinical_data_platform.auth import hash_api_key
from clinical_data_platform.models import User
from clinical_data_platform.session import SessionLocal

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "demo-admin-token")
RESEARCHER_API_KEY = "demo-researcher-token"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_API_KEY}"}


def request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def ensure_user() -> User:
    with SessionLocal() as session:
        user = session.scalar(sa.select(User).where(User.username == "demo-researcher"))
        api_key_hash = hash_api_key(RESEARCHER_API_KEY)
        if not user:
            user = User(
                username="demo-researcher",
                role="researcher",
                api_key_hash=api_key_hash,
            )
            session.add(user)
        else:
            user.api_key_hash = api_key_hash
            user.role = "researcher"
        session.commit()
        session.refresh(user)
        return user


def ensure_study(client: httpx.Client) -> dict:
    studies = request(client, "GET", "/api/v1/research-studies").json()
    for study in studies:
        if study["title"] == "Clinical Data Platform Demo Study":
            return study
    return request(
        client,
        "POST",
        "/api/v1/research-studies",
        json={
            "title": "Clinical Data Platform Demo Study",
            "description": "Synthetic records used to demonstrate isolated research access.",
            "status": "active",
        },
    ).json()


def wait_for_job(client: httpx.Client, job_id: str) -> dict:
    for _ in range(60):
        job = request(client, "GET", f"/api/v1/import-jobs/{job_id}").json()
        if job["status"] in {"completed", "partial", "failed"}:
            return job
        time.sleep(1)
    raise TimeoutError(f"Import job {job_id} did not finish within 60 seconds")


def main() -> None:
    with httpx.Client(base_url=API_URL, headers=ADMIN_HEADERS, timeout=30) as client:
        study = ensure_study(client)
        user = ensure_user()
        request(
            client,
            "POST",
            f"/api/v1/research-studies/{study['id']}/access/{user.id}",
        )

        with (ROOT / "demo" / "clinical_records.csv").open("rb") as csv_file:
            csv_job = request(
                client,
                "POST",
                "/api/v1/imports/csv",
                data={"study_id": study["id"]},
                files={"file": ("clinical_records.csv", csv_file, "text/csv")},
            ).json()
        bundle = json.loads((ROOT / "demo" / "fhir_bundle.json").read_text())
        fhir_job = request(
            client,
            "POST",
            f"/api/v1/imports/fhir?study_id={study['id']}",
            json=bundle,
        ).json()

        csv_report = wait_for_job(client, csv_job["id"])
        fhir_report = wait_for_job(client, fhir_job["id"])

    with httpx.Client(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {RESEARCHER_API_KEY}"},
        timeout=10,
    ) as researcher:
        patients = request(researcher, "GET", "/api/v1/patients").json()

    print(f"Study: {study['title']} ({study['id']})")
    print(f"CSV job: {csv_report['status']} ({csv_report['id']})")
    print(f"FHIR job: {fhir_report['status']} ({fhir_report['id']})")
    print(f"Researcher-visible patients: {len(patients)}")
    print(f"Researcher token: {RESEARCHER_API_KEY}")


if __name__ == "__main__":
    main()
