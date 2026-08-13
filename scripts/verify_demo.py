from __future__ import annotations

import json
import os
from typing import Any

import httpx

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "demo-admin-token")
RESEARCHER_API_KEY = os.getenv("RESEARCHER_API_KEY", "demo-researcher-token")
DEMO_STUDY_TITLE = "Clinical Data Platform Demo Study"
EXPECTED_PATIENT_IDS = {
    "demo-csv-patient-001",
    "demo-csv-patient-002",
    "demo-csv-patient-003",
    "demo-fhir-patient-001",
}


def get(client: httpx.Client, path: str) -> Any:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def main() -> None:
    report: dict[str, Any] = {"api_url": API_URL, "checks": {}}
    try:
        with httpx.Client(base_url=API_URL, timeout=15) as public_client:
            ready = get(public_client, "/ready")
            assert ready["status"] == "ready", ready
            report["checks"]["readiness"] = ready["status"]

        with httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {ADMIN_API_KEY}"},
            timeout=15,
        ) as admin_client:
            studies = get(admin_client, "/api/v1/research-studies")
            study = next(item for item in studies if item["title"] == DEMO_STUDY_TITLE)
            jobs = get(admin_client, "/api/v1/import-jobs")
            demo_jobs = [job for job in jobs if job.get("study_id") == study["id"]]
            assert len(demo_jobs) >= 2, "expected both CSV and FHIR demo import jobs"
            unexpected = [job for job in demo_jobs if job["status"] != "completed"]
            assert not unexpected, f"non-completed demo jobs: {unexpected}"
            report["checks"]["completed_import_jobs"] = len(demo_jobs)

        with httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {RESEARCHER_API_KEY}"},
            timeout=15,
        ) as researcher_client:
            patients = get(researcher_client, "/api/v1/patients")
            identifiers = {patient["external_id"] for patient in patients}
            assert identifiers == EXPECTED_PATIENT_IDS, {
                "expected": sorted(EXPECTED_PATIENT_IDS),
                "actual": sorted(identifiers),
            }
            report["checks"]["researcher_patient_ids"] = sorted(identifiers)

            denied = researcher_client.post("/api/v1/patients", json={"external_id": "must-not-create"})
            assert denied.status_code == 403, denied.text
            report["checks"]["researcher_write_denied"] = denied.status_code

            patient = next(item for item in patients if item["external_id"] == "demo-csv-patient-001")
            provenance = get(researcher_client, f"/api/v1/provenance/patient/{patient['id']}")
            assert provenance, "expected at least one provenance event"
            report["checks"]["provenance_events"] = len(provenance)
    except (AssertionError, httpx.HTTPError, KeyError, StopIteration) as exc:
        report["result"] = "failed"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(1) from exc

    report["result"] = "passed"
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
