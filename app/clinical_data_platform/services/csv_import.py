from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

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
    parse_date,
    parse_datetime,
)

CSV_HEADERS = (
    "patient_external_id",
    "birth_date",
    "sex",
    "encounter_external_id",
    "encounter_start",
    "encounter_end",
    "observation_external_id",
    "observation_code",
    "observation_value",
    "observation_unit",
    "observed_at",
)


class CsvParser:
    def parse(self, content: bytes) -> ImportBatch:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ImportBatch([], ImportRecordError("file", "INVALID_ENCODING", "Expected UTF-8 encoded CSV"))

        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != CSV_HEADERS:
            return ImportBatch(
                [],
                ImportRecordError("header", "INVALID_HEADER", f"Expected headers: {', '.join(CSV_HEADERS)}"),
            )

        records = []
        for row_number, raw in enumerate(reader, start=2):
            raw = dict(raw)
            try:
                records.append(self._record(row_number, raw))
            except ImportRecordError as exc:
                records.append(ImportRecord(row_number, raw, error=exc))
        return ImportBatch(records)

    def _record(self, row_number: int, raw: dict) -> ImportRecord:
        if None in raw:
            raise ImportRecordError("row", "INVALID_COLUMN_COUNT", "Row has more columns than the header")
        values = {field: (value or "").strip() for field, value in raw.items()}
        required = (
            "patient_external_id",
            "encounter_external_id",
            "encounter_start",
            "observation_external_id",
            "observation_code",
            "observation_value",
            "observed_at",
        )
        for field in required:
            if not values[field]:
                raise ImportRecordError(field, "REQUIRED", "Field is required")

        sex = values["sex"] or None
        if sex not in {None, "male", "female", "other", "unknown"}:
            raise ImportRecordError("sex", "INVALID_VALUE", "Expected male, female, other, or unknown")
        try:
            number = Decimal(values["observation_value"])
        except InvalidOperation as exc:
            raise ImportRecordError("observation_value", "INVALID_NUMBER", "Expected a numeric value") from exc
        if not number.is_finite():
            raise ImportRecordError("observation_value", "INVALID_NUMBER", "Expected a numeric value")

        patient = PatientData(
            external_id=values["patient_external_id"],
            birth_date=parse_date(values["birth_date"], "birth_date") if values["birth_date"] else None,
            sex=sex,
        )
        encounter = EncounterData(
            external_id=values["encounter_external_id"],
            patient_external_id=patient.external_id,
            status="finished",
            encounter_type="csv-import",
            started_at=parse_datetime(values["encounter_start"], "encounter_start"),
            ended_at=parse_datetime(values["encounter_end"], "encounter_end") if values["encounter_end"] else None,
        )
        observation = ObservationData(
            external_id=values["observation_external_id"],
            patient_external_id=patient.external_id,
            encounter_external_id=encounter.external_id,
            code=values["observation_code"],
            code_system="LOINC",
            value=values["observation_value"],
            unit=values["observation_unit"] or None,
            observed_at=parse_datetime(values["observed_at"], "observed_at"),
            status="final",
        )
        return ImportRecord(row_number, raw, patient=patient, encounter=encounter, observation=observation)


class CsvImportService:
    def __init__(self, session: Session) -> None:
        self.pipeline = ImportPipelineService(session)

    def enqueue(self, filename: str, content: bytes, study_id=None) -> ImportJob:
        return self.pipeline.enqueue("csv", filename, content, study_id)

    def process(self, job: ImportJob) -> ImportJob:
        return self.pipeline.process(job, CsvParser())
