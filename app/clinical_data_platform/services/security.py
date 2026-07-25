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

    def list_patients(self, principal: Principal, limit: int, offset: int) -> list[Patient]:
        if principal.role == "admin":
            return list(self.session.scalars(sa.select(Patient).offset(offset).limit(limit)))
        statement = (
            sa.select(Patient)
            .join(ResearchSubject)
            .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
            .where(StudyAccess.user_id == principal.id)
            .distinct()
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_encounters(self, principal: Principal, limit: int, offset: int) -> list[Encounter]:
        if principal.role == "admin":
            return list(self.session.scalars(sa.select(Encounter).offset(offset).limit(limit)))
        statement = (
            sa.select(Encounter)
            .join(ResearchSubject, ResearchSubject.patient_id == Encounter.patient_id)
            .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
            .where(StudyAccess.user_id == principal.id)
            .distinct()
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_observations(self, principal: Principal, limit: int, offset: int) -> list[Observation]:
        if principal.role == "admin":
            return list(self.session.scalars(sa.select(Observation).offset(offset).limit(limit)))
        statement = (
            sa.select(Observation)
            .join(ResearchSubject, ResearchSubject.patient_id == Observation.patient_id)
            .join(StudyAccess, StudyAccess.study_id == ResearchSubject.study_id)
            .where(StudyAccess.user_id == principal.id)
            .distinct()
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_studies(self, principal: Principal, limit: int, offset: int) -> list[ResearchStudy]:
        if principal.role == "admin":
            statement = sa.select(ResearchStudy)
        else:
            statement = (
                sa.select(ResearchStudy)
                .join(StudyAccess)
                .where(StudyAccess.user_id == principal.id)
            )
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


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
        return list(
            self.session.scalars(
                sa.select(AuditLog).order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit)
            )
        )
