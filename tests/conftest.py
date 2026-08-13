from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Configuration is fail-closed: ENVIRONMENT defaults to "production", which
# refuses to run without an explicit DATABASE_URL. Tests declare development
# settings before anything imports the application.
os.environ["ENVIRONMENT"] = "development"
os.environ["ADMIN_API_KEY"] = "test-admin-token"

if not os.getenv("TEST_DATABASE_URL"):
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
else:
    os.environ.pop("CELERY_TASK_ALWAYS_EAGER", None)

# alembic/env.py gives DATABASE_URL precedence over the URL a caller sets with
# config.set_main_option(). The unit fixtures rely on set_main_option to build a
# per-test SQLite database, so an inherited DATABASE_URL would silently migrate
# somewhere else and leave every fixture pointing at an empty file. Only the
# integration suite, which declares TEST_DATABASE_URL, is allowed to keep it.
if not os.getenv("TEST_DATABASE_URL"):
    os.environ.pop("DATABASE_URL", None)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--with-containers",
        action="store_true",
        default=False,
        help="Start disposable PostgreSQL, Redis, and Celery backends through Testcontainers.",
    )


def pytest_configure(config) -> None:
    """Provide one-command production-backend tests for local contributors.

    CI continues to provide its own service containers. Starting containers is
    opt-in so the default unit suite stays fast and Docker-free.
    """
    if not config.getoption("--with-containers") or os.getenv("TEST_DATABASE_URL"):
        return

    from testcontainers.community.postgres import PostgresContainer
    from testcontainers.core.container import DockerContainer

    postgres = PostgresContainer("postgres:17-alpine")
    redis = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    postgres.start()
    redis.start()
    database_url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql+psycopg://")
    redis_url = f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"
    os.environ.update(
        {
            "DATABASE_URL": database_url,
            "TEST_DATABASE_URL": database_url,
            "REDIS_URL": redis_url,
            "TEST_REDIS_URL": redis_url,
        }
    )
    os.environ.pop("CELERY_TASK_ALWAYS_EAGER", None)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP)
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "clinical_data_platform.celery_app:celery_app",
            "worker",
            "--loglevel=WARNING",
            "--concurrency=1",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    config._cdp_testcontainers = (postgres, redis, worker)  # type: ignore[attr-defined]


def pytest_unconfigure(config) -> None:
    resources = getattr(config, "_cdp_testcontainers", None)
    if not resources:
        return
    postgres, redis, worker = resources
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=10)
    redis.stop()
    postgres.stop()
