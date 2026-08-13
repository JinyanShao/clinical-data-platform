"""Adapter for the HL7 reference FHIR Validator CLI.

The CLI is intentionally optional: developers can run the API with only the
Python structural model, while deployment environments mount a vetted Validator
JAR and set ``FHIR_VALIDATOR_JAR``. The adapter exposes only deterministic
OperationOutcome issues and never sends clinical payloads to a remote service.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from clinical_data_platform.config import settings


@dataclass(frozen=True)
class FhirValidationIssue:
    severity: str
    code: str
    diagnostics: str
    expression: tuple[str, ...]


class FhirValidator(Protocol):
    def validate(self, bundle: dict[str, Any]) -> list[FhirValidationIssue]: ...


class NoOpFhirValidator:
    def validate(self, bundle: dict[str, Any]) -> list[FhirValidationIssue]:  # noqa: ARG002
        return []


class Hl7ValidatorCli:
    """Run a locally provisioned HL7 Validator and parse its OperationOutcome."""

    def __init__(self, jar_path: str) -> None:
        self.jar_path = Path(jar_path)

    def validate(self, bundle: dict[str, Any]) -> list[FhirValidationIssue]:
        if not self.jar_path.is_file():
            raise RuntimeError(f"FHIR Validator JAR is not readable: {self.jar_path}")

        with tempfile.TemporaryDirectory(prefix="cdp-fhir-validator-") as temporary_directory:
            directory = Path(temporary_directory)
            input_path = directory / "bundle.json"
            output_path = directory / "outcome.json"
            input_path.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
            result = subprocess.run(
                [
                    "java",
                    "-jar",
                    str(self.jar_path),
                "-version",
                "4.3",
                "-tx",
                "n/a",
                "-output",
                    str(output_path),
                    str(input_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if not output_path.is_file():
                detail = (result.stderr or result.stdout).strip()[-1000:]
                raise RuntimeError(f"FHIR Validator did not produce an OperationOutcome: {detail}")
            outcome = json.loads(output_path.read_text(encoding="utf-8"))
        return _issues(outcome)


def configured_fhir_validator() -> FhirValidator:
    return Hl7ValidatorCli(settings.fhir_validator_jar) if settings.fhir_validator_jar else NoOpFhirValidator()


def _issues(outcome: dict[str, Any]) -> list[FhirValidationIssue]:
    issues: list[FhirValidationIssue] = []
    for issue in outcome.get("issue", []):
        if not isinstance(issue, dict):
            continue
        expression = issue.get("expression", [])
        if isinstance(expression, str):
            expression = [expression]
        details = issue.get("details")
        detail_text = details.get("text") if isinstance(details, dict) else None
        issues.append(
            FhirValidationIssue(
                severity=str(issue.get("severity", "error")),
                code=str(issue.get("code", "invalid")),
                diagnostics=str(issue.get("diagnostics") or detail_text or "FHIR validation failed"),
                expression=tuple(item for item in expression if isinstance(item, str)),
            )
        )
    return issues
