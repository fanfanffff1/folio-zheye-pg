#!/usr/bin/env python3
"""Delete tour media that stayed in temp for more than N hours.

  python3 scripts/cleanup_tour_media.py [--hours 24] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.models import SessionLocal, TourMedia  # noqa: E402
from folio.object_store import delete_object, key_from_public_or_local_url  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff = datetime.utcnow() - timedelta(hours=args.hours)
    db = SessionLocal()
    try:
        rows = db.query(TourMedia).filter(
            TourMedia.status == "temp", TourMedia.created_at < cutoff
        ).all()
        n = 0
        for m in rows:
            print(f"{'DRY ' if args.dry_run else ''}clean {m.id} {m.url}")
            if args.dry_run:
                continue
            key = key_from_public_or_local_url(m.url, "tours")
            if key:
                delete_object(key)
            m.status = "deleted"
            n += 1
        if not args.dry_run:
            db.commit()
        print(f"done cleaned={n} dry_run={args.dry_run}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
