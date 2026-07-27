from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.models import Encounter


class EncounterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, encounter: Encounter) -> Encounter:
        self.session.add(encounter)
        self.session.flush()
        return encounter

    def get_by_id(self, encounter_id: UUID) -> Encounter | None:
        return self.session.get(Encounter, encounter_id)

    def get_by_identity(self, source_namespace: str, external_id: str) -> Encounter | None:
        return self.session.scalar(
            sa.select(Encounter).where(
                Encounter.source_namespace == source_namespace,
                Encounter.external_id == external_id,
            )
        )

    def list(self, limit: int = 100, offset: int = 0) -> list[Encounter]:
        statement = (
            sa.select(Encounter)
            .order_by(Encounter.created_at.desc(), Encounter.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def update(self, encounter: Encounter, **fields: object) -> Encounter:
        for key, value in fields.items():
            setattr(encounter, key, value)
        self.session.flush()
        return encounter

    def delete(self, encounter: Encounter) -> None:
        self.session.delete(encounter)
        self.session.flush()
