#!/usr/bin/env python3
"""Migrate local user uploads (avatars + submission covers) to R2 and rewrite DB URLs.

Requires FOLIO_S3_* (+ FOLIO_COVER_BASE_URL or FOLIO_S3_PUBLIC_BASE) and DATABASE_URL.

  python3 scripts/upload_user_uploads_s3.py
  python3 scripts/upload_user_uploads_s3.py --dry-run
  python3 scripts/upload_user_uploads_s3.py --kind avatars
  python3 scripts/upload_user_uploads_s3.py --kind submissions
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.config import AVATAR_DIR, UPLOAD_DIR  # noqa: E402
from folio.models import BookSubmission, SessionLocal, User  # noqa: E402
from folio.object_store import (  # noqa: E402
    content_type_for_ext,
    local_static_url,
    public_object_url,
    s3_configured,
    upload_bytes,
    user_upload_key,
)


def migrate_kind(kind: str, local_dir: Path, dry_run: bool) -> tuple[int, int]:
    local_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in local_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    print(f"[{kind}] dir={local_dir} files={len(files)}")
    uploaded = updated = 0
    db = SessionLocal()
    try:
        for path in files:
            key = user_upload_key(kind, path.name)
            url = public_object_url(key)
            print(f"{'DRY ' if dry_run else ''}PUT {path.name} -> {url}")
            if not dry_run:
                upload_bytes(
                    key,
                    path.read_bytes(),
                    content_type=content_type_for_ext(path.suffix),
                )
                uploaded += 1

            local_url = local_static_url(kind, path.name)
            if kind == "avatars":
                rows = db.query(User).filter(User.avatar_url == local_url).all()
                for row in rows:
                    print(f"  user#{row.id} {row.username} -> {url}")
                    if not dry_run:
                        row.avatar_url = url
                        updated += 1
            else:
                rows = db.query(BookSubmission).filter(BookSubmission.cover_url == local_url).all()
                for row in rows:
                    print(f"  submission#{row.id} {row.submission_number} -> {url}")
                    if not dry_run:
                        row.cover_url = url
                        updated += 1
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return uploaded, updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate user uploads to R2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kind", choices=("avatars", "submissions", "all"), default="all")
    args = parser.parse_args()

    if not s3_configured():
        print(
            "Missing R2 env (FOLIO_S3_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET "
            "+ FOLIO_S3_PUBLIC_BASE or FOLIO_COVER_BASE_URL)",
            file=sys.stderr,
        )
        return 1

    total_up = total_db = 0
    kinds = [("avatars", AVATAR_DIR), ("submissions", UPLOAD_DIR)]
    if args.kind != "all":
        kinds = [k for k in kinds if k[0] == args.kind]
    for kind, directory in kinds:
        up, dbn = migrate_kind(kind, directory, args.dry_run)
        total_up += up
        total_db += dbn
    print(f"done uploaded={total_up} rows_updated={total_db} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
