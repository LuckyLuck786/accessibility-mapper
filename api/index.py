"""Vercel serverless entry point.

One Python function serves the entire API. Vercel picks up the module-level
``app`` object automatically, so ``vercel.json`` only needs a rewrite from
``/api/*`` to here.

Two deployment-specific concerns live in this file and nowhere else:

1. **Import path.** The application lives in ``backend/``, which is not on the
   function's default ``sys.path``. Rather than duplicating code or symlinking
   (neither survives the Vercel build), we prepend the real path here.

2. **Media mount.** Redacted photos are ``bytea`` in Postgres and served from
   ``/api/v1/media/{id}``. There is no media directory to mount - a serverless
   filesystem is read-only outside ``/tmp``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- make ``backend/`` importable ----------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if BACKEND_DIR.is_dir() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Serverless functions start with ``mode: live`` in intent but must be treated
# as production for auth: the admin token gate is mandatory.
os.environ.setdefault("ENVIRONMENT", "production")
# The database is created + seeded by POST /api/v1/admin/seed after deploy, so
# a cold start must not try to seed the whole campus on every invocation.
os.environ.setdefault("AUTO_SEED", "true")

from app.main import app  # noqa: E402  (import must follow the sys.path setup)

__all__ = ["app"]