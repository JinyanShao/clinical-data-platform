from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from sqlalchemy.orm import Session

from clinical_data_platform.models import ImportJob
from clinical_data_platform.services.import_pipeline import (
    EncounterData,
    ImportBatch,
    ImportPipelineService,
    ImportRecord,
    ImportRecordError,
    ObservationData,
    PatientData,
    ResearchStudyData,
    parse_date,
    parse_datetime,
)

SUPPORTED_RESOURCES = {"Patient", "Encounter", "Observation", "ResearchStudy"}


class ResourceRef(NamedTuple):
    """A resolved Bundle reference, carrying the target's issuing system."""

    resource_type: str
    resource_id: str
    #: ``Identifier.system`` declared by the target resource, if any. ``None``
    #: means "use the import job's namespace".
    namespace: str | None


class FhirBundleParser:
    def parse(self, content: bytes) -> ImportBatch:
        try:
            bundle = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ImportBatch([], ImportRecordError("file", "INVALID_JSON", "Expected a UTF-8 FHIR Bundle JSON document"))
        if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
            return ImportBatch([], ImportRecordError("resourceType", "INVALID_BUNDLE", "Expected resourceType Bundle"))
        entries = bundle.get("entry", [])
        if not isinstance(entries, list):
            return ImportBatch([], ImportRecordError("entry", "INVALID_BUNDLE", "Bundle.entry must be an array"))

        aliases = self._aliases(entries)
        records = [self._entry(index, entry, aliases) for index, entry in enumerate(entries, start=1)]
        priority = {"Patient": 0, "ResearchStudy": 1, "Encounter": 2, "Observation": 3}
        records.sort(key=lambda item: priority.get(item.raw_data.get("resourceType"), 4))
        return ImportBatch(records)

    def _aliases(self, entries: list) -> dict[str, ResourceRef]:
        aliases: dict[str, ResourceRef] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
                continue
            resource = entry["resource"]
            resource_type = resource.get("resourceType")
            resource_id = resource.get("id")
            if resource_type in SUPPORTED_RESOURCES and isinstance(resource_id, str) and resource_id:
                target = ResourceRef(resource_type, resource_id, self._identifier_system(resource))
                aliases[f"{resource_type}/{resource_id}"] = target
                if isinstance(entry.get("fullUrl"), str):
                    aliases[entry["fullUrl"]] = target
        return aliases

    @staticmethod
    def _identifier_system(resource: dict) -> str | None:
        """First ``Identifier.system`` declared by the resource, if any.

        FHIR identity is the pair (system, value); when the source states its
        issuing system we honour it instead of flattening everything into the
        import's namespace.
        """
        identifiers = resource.get("identifier")
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            return None
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue
            system = identifier.get("system")
            if isinstance(system, str) and system.strip():
                return system.strip()
        return None

    def _entry(self, index: int, entry: Any, aliases: dict[str, ResourceRef]) -> ImportRecord:
        raw = entry.get("resource", {}) if isinstance(entry, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        try:
            resource_type = self._required(raw, "resourceType")
            if resource_type not in SUPPORTED_RESOURCES:
                raise ImportRecordError("resourceType", "UNSUPPORTED_RESOURCE", f"Unsupported FHIR resource: {resource_type}")
            resource_id = self._required(raw, "id")
            if resource_type == "Patient":
                return ImportRecord(index, raw, patient=self._patient(raw, resource_id))
            if resource_type == "Encounter":
                return ImportRecord(index, raw, encounter=self._encounter(raw, resource_id, aliases))
            if resource_type == "Observation":
                return ImportRecord(index, raw, observation=self._observation(raw, resource_id, aliases))
            return ImportRecord(index, raw, research_study=self._study(raw, resource_id))
        except ImportRecordError as exc:
            return ImportRecord(index, raw, error=exc)

    def _patient(self, resource: dict, resource_id: str) -> PatientData:
        sex = resource.get("gender")
        if sex not in {None, "male", "female", "other", "unknown"}:
            raise ImportRecordError("gender", "INVALID_VALUE", "Expected male, female, other, or unknown")
        birth_date = resource.get("birthDate")
        return PatientData(
            external_id=resource_id,
            birth_date=parse_date(birth_date, "birthDate") if birth_date else None,
            sex=sex,
            source_namespace=self._identifier_system(resource),
        )

    def _encounter(self, resource: dict, resource_id: str, aliases) -> EncounterData:
        patient = self._reference(resource.get("subject"), "Patient", "subject", aliases)
        status = self._encounter_status(self._required(resource, "status"))
        period = resource.get("period") or {}
        if not isinstance(period, dict):
            raise ImportRecordError("period", "INVALID_VALUE", "Encounter.period must be an object")
        return EncounterData(
            external_id=resource_id,
            patient_external_id=patient.resource_id,
            status=status,
            encounter_type=self._encounter_type(resource),
            started_at=parse_datetime(period["start"], "period.start") if period.get("start") else None,
            ended_at=parse_datetime(period["end"], "period.end") if period.get("end") else None,
            source_namespace=self._identifier_system(resource),
            patient_namespace=patient.namespace,
        )

    def _observation(self, resource: dict, resource_id: str, aliases) -> ObservationData:
        patient = self._reference(resource.get("subject"), "Patient", "subject", aliases)
        encounter = None
        if resource.get("encounter") is not None:
            encounter = self._reference(resource["encounter"], "Encounter", "encounter", aliases)
        coding = self._coding(resource.get("code"), "code")
        quantity = resource.get("valueQuantity")
        if not isinstance(quantity, dict) or quantity.get("value") is None:
            raise ImportRecordError("valueQuantity.value", "REQUIRED", "Observation.valueQuantity.value is required")
        try:
            number = Decimal(str(quantity["value"]))
        except InvalidOperation as exc:
            raise ImportRecordError("valueQuantity.value", "INVALID_NUMBER", "Expected a numeric value") from exc
        if isinstance(quantity["value"], bool) or not number.is_finite():
            raise ImportRecordError("valueQuantity.value", "INVALID_NUMBER", "Expected a numeric value")
        unit = quantity.get("unit") or quantity.get("code")
        if unit is not None and not isinstance(unit, str):
            raise ImportRecordError("valueQuantity.unit", "INVALID_VALUE", "Expected a string unit")
        observed_at = resource.get("effectiveDateTime")
        if not observed_at:
            raise ImportRecordError("effectiveDateTime", "REQUIRED", "Field is required")
        status = self._required(resource, "status")
        if status not in {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"}:
            raise ImportRecordError("status", "INVALID_VALUE", "Unsupported Observation status")
        return ObservationData(
            external_id=resource_id,
            patient_external_id=patient.resource_id,
            encounter_external_id=encounter.resource_id if encounter else None,
            code=coding["code"],
            code_system=coding["system"],
            value=str(quantity["value"]),
            unit=unit,
            observed_at=parse_datetime(observed_at, "effectiveDateTime"),
            status=status,
            source_namespace=self._identifier_system(resource),
            patient_namespace=patient.namespace,
            encounter_namespace=encounter.namespace if encounter else None,
        )

    def _study(self, resource: dict, resource_id: str) -> ResearchStudyData:
        description = resource.get("description")
        if description is not None and not isinstance(description, str):
            raise ImportRecordError("description", "INVALID_VALUE", "Expected a string description")
        return ResearchStudyData(
            external_id=resource_id,
            title=self._required(resource, "title"),
            description=description,
            status=self._study_status(self._required(resource, "status")),
            source_namespace=self._identifier_system(resource),
        )

    def _reference(self, value: Any, expected_type: str, field: str, aliases) -> ResourceRef:
        if not isinstance(value, dict) or not isinstance(value.get("reference"), str):
            raise ImportRecordError(field, "REQUIRED", f"{field}.reference is required")
        reference = value["reference"]
        target = aliases.get(reference)
        if not target:
            parts = reference.rstrip("/").split("/")
            if len(parts) >= 2 and parts[-2] in SUPPORTED_RESOURCES:
                # Out-of-Bundle reference: no declared issuing system, so the
                # job namespace applies.
                target = ResourceRef(parts[-2], parts[-1], None)
        if not target or target.resource_type != expected_type or not target.resource_id:
            raise ImportRecordError(field, "INVALID_REFERENCE", f"Expected a {expected_type} reference")
        return target

    def _coding(self, value: Any, field: str) -> dict[str, str]:
        if not isinstance(value, dict) or not isinstance(value.get("coding"), list) or not value["coding"]:
            raise ImportRecordError(field, "REQUIRED", f"{field}.coding is required")
        coding = value["coding"][0]
        if (
            not isinstance(coding, dict)
            or not isinstance(coding.get("code"), str)
            or not coding["code"].strip()
            or not isinstance(coding.get("system"), str)
            or not coding["system"].strip()
        ):
            raise ImportRecordError(field, "REQUIRED", f"{field}.coding requires system and code")
        return coding

    def _encounter_type(self, resource: dict) -> str:
        class_value = resource.get("class")
        if isinstance(class_value, list) and class_value:
            class_value = class_value[0]
        if isinstance(class_value, dict) and isinstance(class_value.get("code"), str) and class_value["code"].strip():
            return class_value["code"]
        types = resource.get("type")
        if isinstance(types, list) and types:
            return self._coding(types[0], "type")["code"]
        return "unknown"

    def _encounter_status(self, status: str) -> str:
        mapping = {
            "arrived": "in-progress",
            "triaged": "in-progress",
            "onleave": "in-progress",
            "discharged": "finished",
            "completed": "finished",
            "discontinued": "cancelled",
        }
        status = mapping.get(status, status)
        if status not in {"planned", "in-progress", "finished", "cancelled", "entered-in-error", "unknown"}:
            raise ImportRecordError("status", "INVALID_VALUE", "Unsupported Encounter status")
        return status

    def _study_status(self, status: str) -> str:
        mapping = {
            "administratively-completed": "completed",
            "approved": "draft",
            "in-review": "draft",
            "withdrawn": "stopped",
            "disapproved": "stopped",
            "closed-to-accrual": "stopped",
            "closed-to-accrual-and-intervention": "stopped",
            "temporarily-closed-to-accrual": "stopped",
            "temporarily-closed-to-accrual-and-intervention": "stopped",
        }
        status = mapping.get(status, status)
        if status not in {"draft", "active", "completed", "stopped", "entered-in-error", "unknown"}:
            raise ImportRecordError("status", "INVALID_VALUE", "Unsupported ResearchStudy status")
        return status

    @staticmethod
    def _required(resource: dict, field: str) -> str:
        value = resource.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ImportRecordError(field, "REQUIRED", "Field is required")
        return value.strip()


class FhirImportService:
    def __init__(self, session: Session) -> None:
        self.pipeline = ImportPipelineService(session)

    def enqueue(
        self,
        filename: str,
        content: bytes,
        study_id=None,
        source_namespace: str | None = None,
    ) -> ImportJob:
        return self.pipeline.enqueue("fhir_bundle", filename, content, study_id, source_namespace)

    def process(self, job: ImportJob) -> ImportJob:
        return self.pipeline.process(job, FhirBundleParser())
