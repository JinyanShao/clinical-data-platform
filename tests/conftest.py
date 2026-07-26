from __future__ import annotations

import os
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
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["ADMIN_API_KEY"] = "test-admin-token"

# alembic/env.py gives DATABASE_URL precedence over the URL a caller sets with
# config.set_main_option(). The unit fixtures rely on set_main_option to build a
# per-test SQLite database, so an inherited DATABASE_URL would silently migrate
# somewhere else and leave every fixture pointing at an empty file. Only the
# integration suite, which declares TEST_DATABASE_URL, is allowed to keep it.
if not os.getenv("TEST_DATABASE_URL"):
    os.environ.pop("DATABASE_URL", None)
