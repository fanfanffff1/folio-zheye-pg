#!/usr/bin/env python3
"""Step 1 migration for UGC places.

- creates the new tables (tour_place_books / tour_place_reports / tour_place_reviews)
- adds the new tour_places columns (status, city_key, address, source_url, ...)
- backfills status='published' and city_key for existing places

Idempotent: safe to run more than once.

Usage:
    python3 scripts/migrate_places_step1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import or_  # noqa: E402

from folio.models import SessionLocal, TourPlace, init_db  # noqa: E402


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        blank = or_(TourPlace.status.is_(None), TourPlace.status == "")
        n_status = db.query(TourPlace).filter(blank).update(
            {TourPlace.status: "published"}, synchronize_session=False
        )
        n_city = 0
        for p in (
            db.query(TourPlace)
            .filter(TourPlace.level == "city")
            .filter(or_(TourPlace.city_key.is_(None), TourPlace.city_key == ""))
            .all()
        ):
            p.city_key = p.key
            n_city += 1
        db.commit()
        total = db.query(TourPlace).count()
        published = db.query(TourPlace).filter(TourPlace.status == "published").count()
        print(
            f"places total={total} published={published} "
            f"status_backfilled={n_status} city_key_backfilled={n_city}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
