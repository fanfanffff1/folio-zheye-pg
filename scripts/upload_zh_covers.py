#!/usr/bin/env python3
"""Upload Chinese cover files (source + WebP/AVIF variants) to R2.

The generic uploaders only push the *variant* files, but the detail page can fall
back to the source .jpg, so for the Chinese library we push both. Keys are
`covers/<filename>` — matching the CDN layout used by folio/cover_urls.py.

Usage:
    python3 scripts/upload_zh_covers.py --dry-run
    python3 scripts/upload_zh_covers.py                 # all zh-* covers
    python3 scripts/upload_zh_covers.py --prefix zh-san # only some
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.cover_urls import COVER_BASE_URL  # noqa: E402
from folio.object_store import public_base_url, s3_configured, upload_file  # noqa: E402

COVER_DIR = ROOT / "static" / "covers"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="zh-", help="filename prefix to upload (default zh-)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in COVER_DIR.iterdir() if p.is_file() and p.suffix.lower() in EXTS and p.name.startswith(args.prefix))
    if not files:
        raise SystemExit(f"no files matching {args.prefix}* in {COVER_DIR}")
    if not args.dry_run and not s3_configured():
        raise SystemExit("R2/S3 未配置（FOLIO_S3_*）")

    n = 0
    total = 0
    for p in files:
        key = f"covers/{p.name}"
        total += p.stat().st_size
        if args.dry_run:
            if n < 10:
                print("would upload", key, p.stat().st_size)
            n += 1
            continue
        upload_file(key, p, content_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                    cache_control="public, max-age=86400")
        n += 1
        if n % 200 == 0:
            print(f"... {n}/{len(files)}")
    print(f"{'dry-run: ' if args.dry_run else ''}{n} files, {total/1e6:.1f}MB -> {public_base_url() or COVER_BASE_URL}/covers/")


if __name__ == "__main__":
    main()
