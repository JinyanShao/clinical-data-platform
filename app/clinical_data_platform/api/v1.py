from __future__ import annotations

import json
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from clinical_data_platform.api.schemas import (
    AuditLogRead,
    EncounterCreate,
    EncounterRead,
    EncounterUpdate,
    ErrorResponse,
    ImportErrorRead,
    ImportJobRead,
    ObservationCreate,
    ObservationRead,
    ObservationUpdate,
    PatientCreate,
    PatientRead,
    PatientUpdate,
    ProvenanceEventRead,
    ProvenanceResourceType,
    ResearchStudyCreate,
    ResearchStudyRead,
    ResearchStudyUpdate,
    ResearchSubjectRead,
    SourceRecordRead,
    StudyAccessRead,
    UserCreate,
    UserCreated,
)
from clinical_data_platform.auth import Principal, require_roles
from clinical_data_platform.models import ImportError as ImportErrorRow
from clinical_data_platform.models import ImportJob, SourceRecord
from clinical_data_platform.services import (
    CsvImportService,
    EncounterService,
    FhirImportService,
    ImportJobService,
    ObservationService,
    PatientService,
    ResearchStudyService,
)
from clinical_data_platform.services.security import AuditService, StudyAccessService, UserService
from clinical_data_platform.session import get_session
from clinical_data_platform.tasks import dispatch_import

router = APIRouter(
    prefix="/api/v1",
    responses={
        400: {"model": ErrorResponse, "description": "Business rule violation"},
        401: {"model": ErrorResponse, "description": "Authentication required"},
        403: {"model": ErrorResponse, "description": "Insufficient permissions"},
        404: {"model": ErrorResponse, "description": "Resource not found"},
        409: {"model": ErrorResponse, "description": "Resource conflict"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
    },
)

admin = require_roles("admin")
clinical_reader = require_roles("admin", "researcher")
audit_reader = require_roles("admin", "auditor")
provenance_reader = require_roles("admin", "researcher", "auditor")


def page(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> tuple[int, int]:
    return limit, offset


def _dump(schema, value) -> dict:
    return schema.model_validate(value).model_dump(mode="json")


@router.post("/patients", response_model=PatientRead, status_code=201, tags=["Patients"])
def create_patient(payload: PatientCreate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    patient = PatientService(session).create(**payload.model_dump())
    AuditService(session).record(actor, "create", "Patient", patient.id, after=_dump(PatientRead, patient))
    return patient


@router.get("/patients/{patient_id}", response_model=PatientRead, tags=["Patients"])
def get_patient(patient_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    patient = PatientService(session).get(patient_id)
    StudyAccessService(session).require_patient(actor, patient.id)
    return patient


@router.get("/patients", response_model=list[PatientRead], tags=["Patients"])
def list_patients(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    return StudyAccessService(session).list_patients(actor, *pagination)


@router.patch("/patients/{patient_id}", response_model=PatientRead, tags=["Patients"])
def update_patient(patient_id: UUID, payload: PatientUpdate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = PatientService(session)
    patient = service.get(patient_id)
    before = _dump(PatientRead, patient)
    patient = service.update(patient_id, **payload.model_dump(exclude_unset=True))
    AuditService(session).record(actor, "update", "Patient", patient.id, before, _dump(PatientRead, patient))
    return patient


@router.post("/encounters", response_model=EncounterRead, status_code=201, tags=["Encounters"])
def create_encounter(payload: EncounterCreate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    encounter = EncounterService(session).create(**payload.model_dump())
    AuditService(session).record(actor, "create", "Encounter", encounter.id, after=_dump(EncounterRead, encounter))
    return encounter


@router.get("/encounters/{encounter_id}", response_model=EncounterRead, tags=["Encounters"])
def get_encounter(encounter_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    encounter = EncounterService(session).get(encounter_id)
    StudyAccessService(session).require_patient(actor, encounter.patient_id)
    return encounter


@router.get("/encounters", response_model=list[EncounterRead], tags=["Encounters"])
def list_encounters(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    return StudyAccessService(session).list_encounters(actor, *pagination)


@router.patch("/encounters/{encounter_id}", response_model=EncounterRead, tags=["Encounters"])
def update_encounter(encounter_id: UUID, payload: EncounterUpdate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = EncounterService(session)
    encounter = service.get(encounter_id)
    before = _dump(EncounterRead, encounter)
    encounter = service.update(encounter_id, **payload.model_dump(exclude_unset=True))
    AuditService(session).record(actor, "update", "Encounter", encounter.id, before, _dump(EncounterRead, encounter))
    return encounter


@router.post("/observations", response_model=ObservationRead, status_code=201, tags=["Observations"])
def create_observation(payload: ObservationCreate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    observation = ObservationService(session).create(**payload.model_dump())
    AuditService(session).record(actor, "create", "Observation", observation.id, after=_dump(ObservationRead, observation))
    return observation


@router.get("/observations/{observation_id}", response_model=ObservationRead, tags=["Observations"])
def get_observation(observation_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    observation = ObservationService(session).get(observation_id)
    StudyAccessService(session).require_patient(actor, observation.patient_id)
    return observation


@router.get("/observations", response_model=list[ObservationRead], tags=["Observations"])
def list_observations(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    return StudyAccessService(session).list_observations(actor, *pagination)


@router.patch("/observations/{observation_id}", response_model=ObservationRead, tags=["Observations"])
def update_observation(observation_id: UUID, payload: ObservationUpdate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = ObservationService(session)
    observation = service.get(observation_id)
    before = _dump(ObservationRead, observation)
    observation = service.update(observation_id, **payload.model_dump(exclude_unset=True))
    AuditService(session).record(actor, "update", "Observation", observation.id, before, _dump(ObservationRead, observation))
    return observation


@router.post("/research-studies", response_model=ResearchStudyRead, status_code=201, tags=["Research Studies"])
def create_research_study(payload: ResearchStudyCreate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    study = ResearchStudyService(session).create(**payload.model_dump())
    AuditService(session).record(actor, "create", "ResearchStudy", study.id, after=_dump(ResearchStudyRead, study))
    return study


@router.get("/research-studies/{study_id}", response_model=ResearchStudyRead, tags=["Research Studies"])
def get_research_study(study_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    study = ResearchStudyService(session).get(study_id)
    StudyAccessService(session).require_study(actor, study.id)
    return study


@router.get("/research-studies", response_model=list[ResearchStudyRead], tags=["Research Studies"])
def list_research_studies(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(clinical_reader)):
    return StudyAccessService(session).list_studies(actor, *pagination)


@router.patch("/research-studies/{study_id}", response_model=ResearchStudyRead, tags=["Research Studies"])
def update_research_study(study_id: UUID, payload: ResearchStudyUpdate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = ResearchStudyService(session)
    study = service.get(study_id)
    before = _dump(ResearchStudyRead, study)
    study = service.update(study_id, **payload.model_dump(exclude_unset=True))
    AuditService(session).record(actor, "update", "ResearchStudy", study.id, before, _dump(ResearchStudyRead, study))
    return study


@router.delete("/research-studies/{study_id}", status_code=204, tags=["Research Studies"])
def delete_research_study(study_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = ResearchStudyService(session)
    study = service.get(study_id)
    before = _dump(ResearchStudyRead, study)
    AuditService(session).record(actor, "delete", "ResearchStudy", study.id, before=before)
    service.delete(study_id)
    return Response(status_code=204)


@router.post("/users", response_model=UserCreated, status_code=201, tags=["Access Control"])
def create_user(payload: UserCreate, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    user, api_key = UserService(session).create(payload.username, payload.role)
    AuditService(session).record(actor, "create", "User", user.id, after={"username": user.username, "role": user.role})
    return UserCreated(id=user.id, username=user.username, role=user.role, api_key=api_key)


@router.post("/research-studies/{study_id}/access/{user_id}", response_model=StudyAccessRead, status_code=201, tags=["Access Control"])
def grant_study_access(study_id: UUID, user_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    grant = UserService(session).grant_study(user_id, study_id)
    AuditService(session).record(actor, "grant_access", "ResearchStudy", study_id, after={"user_id": str(user_id)})
    return grant


@router.post("/research-studies/{study_id}/patients/{patient_id}", response_model=ResearchSubjectRead, status_code=201, tags=["Research Studies"])
def add_research_subject(study_id: UUID, patient_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    subject = StudyAccessService(session).add_subject(study_id, patient_id)
    AuditService(session).record(actor, "add_subject", "ResearchStudy", study_id, after={"patient_id": str(patient_id)})
    return subject


@router.get("/import-jobs/{import_job_id}", response_model=ImportJobRead, tags=["Import Jobs"])
def get_import_job(import_job_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(audit_reader)):
    return ImportJobService(session).get(import_job_id)


@router.get("/import-jobs", response_model=list[ImportJobRead], tags=["Import Jobs"])
def list_import_jobs(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(audit_reader)):
    return ImportJobService(session).list(limit=pagination[0], offset=pagination[1])


@router.get(
    "/import-jobs/{import_job_id}/errors",
    response_model=list[ImportErrorRead],
    tags=["Import Jobs"],
    summary="Import errors, optionally for one attempt",
)
def list_import_errors(
    import_job_id: UUID,
    attempt: int | None = Query(
        None,
        ge=0,
        description="Attempt to filter on. Omit for every attempt; use the job's retry_count for the current one.",
    ),
    pagination=Depends(page),
    session: Session = Depends(get_session),
    actor: Principal = Depends(audit_reader),
):
    ImportJobService(session).get(import_job_id)
    statement = sa.select(ImportErrorRow).where(ImportErrorRow.import_job_id == import_job_id)
    if attempt is not None:
        statement = statement.where(ImportErrorRow.attempt == attempt)
    statement = (
        statement.order_by(
            ImportErrorRow.attempt.desc(), ImportErrorRow.source_row, ImportErrorRow.id
        )
        .offset(pagination[1])
        .limit(pagination[0])
    )
    return list(session.scalars(statement))


@router.get("/import-jobs/{import_job_id}/source-records", response_model=list[SourceRecordRead], tags=["Import Jobs"])
def list_source_records(import_job_id: UUID, pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(audit_reader)):
    ImportJobService(session).get(import_job_id)
    statement = (
        sa.select(SourceRecord)
        .where(SourceRecord.import_job_id == import_job_id)
        .order_by(SourceRecord.source_row, SourceRecord.id)
        .offset(pagination[1])
        .limit(pagination[0])
    )
    return list(session.scalars(statement))


@router.get(
    "/provenance/{resource_type}/{resource_id}",
    response_model=list[ProvenanceEventRead],
    tags=["Import Jobs"],
    summary="Full provenance history for one resource",
)
def get_resource_provenance(
    resource_type: ProvenanceResourceType,
    resource_id: UUID,
    pagination=Depends(page),
    session: Session = Depends(get_session),
    actor: Principal = Depends(provenance_reader),
):
    """Every import that produced or re-observed this resource, oldest first.

    Answers "which imports, which source rows, and when" — a resource is no
    longer limited to a single origin record.
    """
    StudyAccessService(session).require_resource(actor, resource_type, resource_id)
    statement = (
        sa.select(SourceRecord, ImportJob)
        .join(ImportJob, ImportJob.id == SourceRecord.import_job_id)
        .where(
            SourceRecord.resource_type == resource_type,
            SourceRecord.resource_id == resource_id,
        )
        .order_by(SourceRecord.created_at, SourceRecord.id)
        .offset(pagination[1])
        .limit(pagination[0])
    )
    return [
        ProvenanceEventRead(
            id=record.id,
            import_job_id=record.import_job_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            source_row=record.source_row,
            raw_data=record.raw_data,
            checksum=record.checksum,
            action=record.action,
            created_at=record.created_at,
            import_filename=job.filename,
            import_source_type=job.source_type,
            import_study_id=job.study_id,
            import_source_namespace=job.source_namespace,
        )
        for record, job in session.execute(statement).all()
    ]


@router.post("/import-jobs/{import_job_id}/retry", response_model=ImportJobRead, status_code=202, tags=["Import Jobs"])
def retry_import(import_job_id: UUID, session: Session = Depends(get_session), actor: Principal = Depends(admin)):
    service = ImportJobService(session)
    # Opens a new attempt through the state machine: it validates the
    # transition, clears task_id/completed_at and bumps retry_count so the next
    # run's errors are recorded under a new attempt number.
    job = service.mark_pending_for_retry(import_job_id)
    AuditService(session).record(actor, "retry", "ImportJob", job.id, after={"retry_count": job.retry_count})
    return dispatch_import(session, job)


@router.post("/imports/csv", response_model=ImportJobRead, response_model_by_alias=True, status_code=202, tags=["Import Jobs"])
async def import_csv(
    file: UploadFile = File(...),
    study_id: UUID | None = Form(None),
    source_namespace: str | None = Form(
        None,
        description=(
            "Issuing system for the identifiers in this file. Defaults to a namespace "
            "derived from study_id, so two studies using the same local ids stay separate."
        ),
    ),
    session: Session = Depends(get_session),
    actor: Principal = Depends(admin),
):
    if study_id:
        ResearchStudyService(session).get(study_id)
    job = CsvImportService(session).enqueue(
        file.filename or "upload.csv", await file.read(), study_id, source_namespace
    )
    AuditService(session).record(
        actor,
        "enqueue",
        "ImportJob",
        job.id,
        after={
            "source_type": "csv",
            "study_id": str(study_id) if study_id else None,
            "source_namespace": job.source_namespace,
        },
    )
    return dispatch_import(session, job)


@router.post("/imports/fhir", response_model=ImportJobRead, response_model_by_alias=True, status_code=202, tags=["Import Jobs"])
def import_fhir(
    bundle: dict = Body(...),
    study_id: UUID | None = Query(None),
    source_namespace: str | None = Query(
        None,
        description=(
            "Fallback issuing system for Bundle entries that declare no Identifier.system. "
            "Defaults to a namespace derived from study_id."
        ),
    ),
    session: Session = Depends(get_session),
    actor: Principal = Depends(admin),
):
    if study_id:
        ResearchStudyService(session).get(study_id)
    content = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    job = FhirImportService(session).enqueue("bundle.json", content, study_id, source_namespace)
    AuditService(session).record(
        actor,
        "enqueue",
        "ImportJob",
        job.id,
        after={
            "source_type": "fhir_bundle",
            "study_id": str(study_id) if study_id else None,
            "source_namespace": job.source_namespace,
        },
    )
    return dispatch_import(session, job)


@router.get("/audit-logs", response_model=list[AuditLogRead], tags=["Audit"])
def list_audit_logs(pagination=Depends(page), session: Session = Depends(get_session), actor: Principal = Depends(audit_reader)):
    return AuditService(session).list(limit=pagination[0], offset=pagination[1])
