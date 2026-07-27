from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from clinical_data_platform.models import Observation


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, observation: Observation) -> Observation:
        self.session.add(observation)
        self.session.flush()
        return observation

    def get_by_id(self, observation_id: UUID) -> Observation | None:
        return self.session.get(Observation, observation_id)

    def get_by_identity(self, source_namespace: str, external_id: str) -> Observation | None:
        return self.session.scalar(
            sa.select(Observation).where(
                Observation.source_namespace == source_namespace,
                Observation.external_id == external_id,
            )
        )

    def list(self, limit: int = 100, offset: int = 0) -> list[Observation]:
        statement = (
            sa.select(Observation)
            .order_by(Observation.created_at.desc(), Observation.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def update(self, observation: Observation, **fields: object) -> Observation:
        for key, value in fields.items():
            setattr(observation, key, value)
        self.session.flush()
        return observation

    def delete(self, observation: Observation) -> None:
        self.session.delete(observation)
        self.session.flush()
