from __future__ import annotations

import logging
import os

import redis
from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger, heartbeat_sent, worker_init, worker_ready

from clinical_data_platform.config import settings

REDIS_URL = settings.redis_url
WORKER_HEARTBEAT_KEY = "clinical_data_platform:worker_heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 30
logger = logging.getLogger(__name__)

celery_app = Celery(
    "clinical_data_platform",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["clinical_data_platform.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true",
    task_eager_propagates=True,
    task_publish_retry=False,
    broker_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    worker_hijack_root_logger=False,
)


@worker_init.connect
def validate_worker_configuration(**kwargs):  # noqa: ARG001
    """Apply the same fail-closed configuration checks as the API process."""
    settings.validate()


def record_worker_heartbeat() -> None:
    try:
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1).set(
            WORKER_HEARTBEAT_KEY, "ok", ex=WORKER_HEARTBEAT_TTL_SECONDS
        )
    except Exception:
        logger.warning("could not update worker heartbeat", exc_info=True)


@worker_ready.connect
def mark_worker_ready(**kwargs):  # noqa: ARG001
    record_worker_heartbeat()


@heartbeat_sent.connect
def refresh_worker_heartbeat(**kwargs):  # noqa: ARG001
    record_worker_heartbeat()


def _configure_worker_logger(logger) -> None:
    import logging

    from clinical_data_platform.operations import JsonFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]


@after_setup_logger.connect
def setup_worker_logger(logger, **kwargs):  # noqa: ARG001
    _configure_worker_logger(logger)


@after_setup_task_logger.connect
def setup_task_logger(logger, **kwargs):  # noqa: ARG001
    _configure_worker_logger(logger)
