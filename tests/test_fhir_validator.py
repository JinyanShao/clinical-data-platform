from __future__ import annotations

from clinical_data_platform.services.fhir_import import FhirBundleParser
from clinical_data_platform.services.fhir_validator import FhirValidationIssue, _issues


class StaticValidator:
    def __init__(self, issues: list[FhirValidationIssue]) -> None:
        self.issues = issues

    def validate(self, bundle: dict) -> list[FhirValidationIssue]:  # noqa: ARG002
        return self.issues


def _bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "patient-1", "gender": "female"}},
        ],
    }


def test_fhir_resources_rejects_invalid_supported_resource_shape() -> None:
    bundle = _bundle()
    bundle["entry"][0]["resource"]["birthDate"] = "not-a-date"

    batch = FhirBundleParser().parse(__import__("json").dumps(bundle).encode())

    assert batch.records[0].error is not None
    assert batch.records[0].error.code == "FHIR_STRUCTURE_INVALID"


def test_hl7_validation_error_is_mapped_to_the_matching_bundle_entry() -> None:
    parser = FhirBundleParser(
        StaticValidator(
            [
                FhirValidationIssue(
                    severity="error",
                    code="invalid",
                    diagnostics="Profile requires an identifier",
                    expression=("Bundle.entry[0].resource.identifier",),
                )
            ]
        )
    )

    batch = parser.parse(__import__("json").dumps(_bundle()).encode())

    assert batch.records[0].error is not None
    assert batch.records[0].error.code == "FHIR_INVALID"
    assert batch.records[0].error.field == "Bundle.entry[0].resource.identifier"


def test_operation_outcome_parsing_handles_details_and_expression() -> None:
    issues = _issues(
        {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "required",
                    "details": {"text": "Missing Patient identifier"},
                    "expression": ["Bundle.entry[0].resource.identifier"],
                }
            ],
        }
    )

    assert issues == [
        FhirValidationIssue(
            severity="error",
            code="required",
            diagnostics="Missing Patient identifier",
            expression=("Bundle.entry[0].resource.identifier",),
        )
    ]
