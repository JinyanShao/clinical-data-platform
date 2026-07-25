from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from clinical_data_platform.api.v1 import router
from clinical_data_platform.exceptions import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from clinical_data_platform.operations import RequestContextMiddleware, configure_logging, readiness_checks

tags_metadata = [
    {"name": "Patients", "description": "Create, read, list, and update patient records."},
    {"name": "Encounters", "description": "Manage patient-linked clinical encounters."},
    {"name": "Observations", "description": "Manage patient observations and optional encounter links."},
    {"name": "Research Studies", "description": "Basic CRUD for research study metadata."},
    {"name": "Import Jobs", "description": "Upload clinical CSV files and query import status and errors."},
    {"name": "Access Control", "description": "Create API users and grant ResearchStudy access."},
    {"name": "Audit", "description": "Inspect immutable records of writes and permission changes."},
    {"name": "Operations", "description": "Application liveness and dependency readiness."},
]

configure_logging()

app = FastAPI(
    title="clinical-data-platform API",
    summary="FHIR-based clinical research data platform REST API.",
    description=(
        "Core v1 API for patients, encounters, observations, research studies, "
        "and import job read models."
    ),
    version="0.1.0",
    openapi_tags=tags_metadata,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(router)


@app.get("/health", tags=["Operations"], summary="Liveness check")
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["Operations"], summary="Dependency readiness check")
def ready():
    checks = readiness_checks()
    ready_status = all(check["status"] == "ok" for check in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready_status else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready_status else "not_ready", "checks": checks},
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError):  # noqa: ARG001
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "request validation failed",
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(NotFoundError)
def not_found_handler(request: Request, exc: NotFoundError):  # noqa: ARG001
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
def conflict_handler(request: Request, exc: ConflictError):  # noqa: ARG001
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(BusinessRuleError)
def business_rule_handler(request: Request, exc: BusinessRuleError):  # noqa: ARG001
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@app.exception_handler(ForbiddenError)
def forbidden_handler(request: Request, exc: ForbiddenError):  # noqa: ARG001
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
def integrity_error_handler(request: Request, exc: IntegrityError):  # noqa: ARG001
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": "database constraint violated"})
