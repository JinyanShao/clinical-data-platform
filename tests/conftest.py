from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
