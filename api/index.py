"""Vercel serverless entry point.

One Python function serves the entire API. Vercel picks up the module-level
``app`` object automatically, so ``vercel.json`` only needs a rewrite from
``/api/*`` to here.

Two deployment-specific concerns live in this file and nowhere else:

1. **Import path.** The application package lives under
   ``accessibility-mapper/backend/`` in the repo, but Vercel's
   ``includeFiles`` copies files preserving their *repo-relative* layout. So
   inside the function the package is at
   ``/var/task/accessibility-mapper/backend/app``, not ``/var/task/backend``.
   Rather than hardcode one guess, we search the plausible locations and fail
   loudly if none of them contain ``app/main.py`` - a silent miss here shows up
   as an opaque ``ModuleNotFoundError`` at cold start.

2. **Media.** Redacted photos are ``bytea`` in Postgres and served from
   ``/api/v1/media/{id}``. There is no media directory to mount: a serverless
   filesystem is read-only outside ``/tmp``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Candidate roots, most specific first. ``includeFiles`` keeps the repo-relative
# path, so the first entry is the one that actually hits in production; the
# others keep local invocations and future relayouts working.
_CANDIDATES = [
    ROOT / "accessibility-mapper" / "backend",  # deployed layout
    ROOT / "backend",                            # flattened layout
    ROOT,                                        # app/ directly at the root
]

BACKEND_DIR = next(
    (candidate for candidate in _CANDIDATES if (candidate / "app" / "main.py").is_file()),
    None,
)

if BACKEND_DIR is None:
    searched = "\n  ".join(str(c) for c in _CANDIDATES)
    raise RuntimeError(
        "Could not locate the 'app' Python package inside the function bundle. "
        f"Searched:\n  {searched}\n\n"
        "Check that vercel.json 'functions.api/index.py.includeFiles' still "
        "covers accessibility-mapper/backend/app/**/*.py."
    )

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Production for auth purposes: the admin token gate becomes mandatory. The
# database is created + seeded via POST /api/v1/admin/seed after deploy.
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("AUTO_SEED", "true")

from app.main import app  # noqa: E402  (import must follow the sys.path setup)

__all__ = ["app"]