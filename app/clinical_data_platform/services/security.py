from __future__ import annotations

import secrets
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.auth import Principal, hash_api_key
from clinical_data_platform.exceptions import ConflictError, ForbiddenError, NotFoundError
from clinical_data_platform.models import (
    AuditLog,
    Encounter,
    Observation,
    Patient,
    ResearchStudy,
    ResearchSubject,
    StudyAccess,
    User,
)

#: Roles that read across every study by design. Documented in
#: ``docs/security.md``: auditors exist to inspect imports and provenance
#: platform-wide, so study scoping does not apply to them.
GLOBAL_READ_ROLES = frozenset({"admin", "auditor"})


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, username: str, role: str) -> tuple[User, str]:
        if self.session.scalar(sa.select(User).where(User.username == username)):
            raise ConflictError("username already exists")
        api_key = secrets.token_urlsafe(32)
        user = User(username=username, role=role, api_key_hash=hash_api_key(api_key))
        self.session.add(user)
        self.session.flush()
        return user, api_key

    def get(self, user_id: UUID) -> User:
        user = self.session.get(User, user_id)
        if not user:
            raise NotFoundError("user not found")
        return user

    def grant_study(self, user_id: UUID, study_id: UUID) -> StudyAccess:
        self.get(user_id)
        if not self.session.get(ResearchStudy, study_id):
            raise NotFoundError("research study not found")
        existing = self.session.scalar(
            sa.select(StudyAccess).where(
                StudyAccess.user_id == user_id,
                StudyAccess.study_id == study_id,
            )
        )
        if existing:
            return existing
        grant = StudyAccess(user_id=user_id, study_id=study_id)
        self.session.add(grant)
        self.session.flush()
        return grant


class StudyAccessService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_subject(self, study_id: UUID, patient_id: UUID) -> ResearchSubject:
        if not self.session.get(ResearchStudy, study_id):
            raise NotFoundError("research study not found")
        if not self.session.get(Patient, patient_id):
            raise NotFoundError("patient not found")
        existing = self.session.scalar(
            sa.select(ResearchSubject).where(
                ResearchSubject.study_id == study_id,
                ResearchSubject.patient_id == patient_id,
            )
        )
        if existing:
            return existing
        subject = ResearchSubject(study_id=study_id, patient_id=patient_id)
        self.session.add(subject)
        self.session.flush()
        return subject

    def require_study(self, principal: Principal, study_id: UUID) -> None:
        if principal.role == "admin":
            return
        if principal.id is None or not self.session.scalar(
            sa.select(StudyAccess.id).where(
                StudyAccess.user_id == principal.id,
                StudyAccess.study_id == study_id,
            )
        ):
            raise ForbiddenError("research study access denied")

    def require_patient(self, principal: Principal, patient_id: UUID) -> None:
        """Grant access when the patient is enrolled in a study the caller holds.

        Now that Patient identity is namespaced, "shares a study" can no longer
        be reached by two sites' subjects silently merging into one row under a
        common local identifier.
        """
        if principal.role == "admin":
            return
        if principal.id is None or not self.session.scalar(
            sa.select(ResearchSubject.id)
            .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
            .where(
                ResearchSubject.patient_id == patient_id,
                StudyAccess.user_id == principal.id,
            )
        ):
            raise ForbiddenError("patient access denied")

    def require_resource(self, principal: Principal, resource_type: str, resource_id: UUID) -> None:
        """Authorise access to any provenance-bearing resource."""
        if principal.role in GLOBAL_READ_ROLES:
            return
        if resource_type == "research_study":
            self.require_study(principal, resource_id)
            return
        if resource_type == "patient":
            self.require_patient(principal, resource_id)
            return
        if resource_type == "encounter":
            encounter = self.session.get(Encounter, resource_id)
            if not encounter:
                raise NotFoundError("encounter not found")
            self.require_patient(principal, encounter.patient_id)
            return
        if resource_type == "observation":
            observation = self.session.get(Observation, resource_id)
            if not observation:
                raise NotFoundError("observation not found")
            self.require_patient(principal, observation.patient_id)
            return
        raise NotFoundError("unknown resource type")

    def list_patients(self, principal: Principal, limit: int, offset: int) -> list[Patient]:
        statement = sa.select(Patient)
        if principal.role != "admin":
            statement = (
                statement.join(ResearchSubject)
                .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
                .where(StudyAccess.user_id == principal.id)
                .distinct()
            )
        statement = statement.order_by(Patient.created_at.desc(), Patient.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def list_encounters(self, principal: Principal, limit: int, offset: int) -> list[Encounter]:
        statement = sa.select(Encounter)
        if principal.role != "admin":
            statement = (
                statement.join(ResearchSubject, ResearchSubject.patient_id == Encounter.patient_id)
                .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
                .where(StudyAccess.user_id == principal.id)
                .distinct()
            )
        statement = statement.order_by(Encounter.created_at.desc(), Encounter.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def list_observations(self, principal: Principal, limit: int, offset: int) -> list[Observation]:
        statement = sa.select(Observation)
        if principal.role != "admin":
            statement = (
                statement.join(ResearchSubject, ResearchSubject.patient_id == Observation.patient_id)
                .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
                .where(StudyAccess.user_id == principal.id)
                .distinct()
            )
        statement = statement.order_by(Observation.created_at.desc(), Observation.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def list_studies(self, principal: Principal, limit: int, offset: int) -> list[ResearchStudy]:
        statement = sa.select(ResearchStudy)
        if principal.role != "admin":
            statement = (
                statement.join(StudyAccess)
                .where(StudyAccess.user_id == principal.id)
                .distinct()
            )
        statement = (
            statement.order_by(ResearchStudy.created_at.desc(), ResearchStudy.id).offset(offset).limit(limit)
        )
        return list(self.session.scalars(statement))


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        principal: Principal,
        action: str,
        resource_type: str,
        resource_id: object,
        before: dict | None = None,
        after: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor=principal.username,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            before=before,
            after=after,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def list(self, limit: int, offset: int) -> list[AuditLog]:
        # ``id`` is the tiebreaker: ordering on the timestamp alone was
        # non-deterministic wherever two entries shared it, which the
        # second-granular SQL CURRENT_TIMESTAMP made routine on SQLite.
        return list(
            self.session.scalars(
                sa.select(AuditLog)
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
