#!/usr/bin/env python
"""Idempotent database seeding from the command line.

Equivalent to ``POST /api/v1/admin/seed`` but usable without the API running -
useful for a first local Postgres, or for CI. Safe to run repeatedly: it only
seeds when the campus graph is empty.

Usage::

    DATABASE_URL=postgresql://... python scripts/seed.py
    python scripts/seed.py --reset      # wipe and rebuild
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "accessibility-mapper" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Ghost Space database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="wipe all demo data and rebuild it (destructive)",
    )
    args = parser.parse_args()

    from app.core.database import Base, SessionLocal, database_kind, engine, init_db
    from app.db import models as _models  # noqa: F401
    from app.db import space_models as _space_models  # noqa: F401
    from app.db.seed import seed, seed_if_empty
    from app.services.graph_service import graph_service

    print(f"target database: {database_kind()}")
    init_db(seed=False)

    with SessionLocal() as db:
        if args.reset:
            counts = seed(db, reset=True)
            print(f"reset complete: {counts}")
        else:
            created = seed_if_empty(db)
            print("seeded demo data" if created else "already seeded - nothing to do")
            if not created:
                counts = {}
        graph_service.invalidate()
        graph_service.recompute_weights(db)
        db.commit()
        stats = graph_service.stats(db)

    print(
        f"graph: {stats['nodes']} nodes / {stats['edges']} edges "
        f"(version {stats.get('graph_version')})"
    )
    print(f"counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())