#!/usr/bin/env python3
"""Upload static map data (GeoJSON / JSON) to R2 so it is served from the CDN.

Reuses the project's S3/R2 credentials (FOLIO_S3_*). Files land under
`tour-map/...` in the bucket, matching the frontend's CDN layout:
    <MAP_CDN_BASE>/tour-map/world/countries.geojson

Usage:
    python3 scripts/upload_map_data.py            # upload everything
    python3 scripts/upload_map_data.py --dry-run  # list without uploading
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.object_store import public_base_url, s3_configured, upload_bytes  # noqa: E402

SRC = ROOT / "static" / "data" / "tour-map"
PREFIX = "tour-map"
CACHE = "public, max-age=31536000, immutable"


def content_type(path: Path) -> str:
    if path.suffix == ".geojson":
        return "application/geo+json"
    if path.suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not SRC.is_dir():
        raise SystemExit(f"missing source dir: {SRC}")
    if not args.dry_run and not s3_configured():
        raise SystemExit(
            "R2/S3 未配置：请设置 FOLIO_S3_ENDPOINT / FOLIO_S3_ACCESS_KEY / "
            "FOLIO_S3_SECRET_KEY / FOLIO_S3_BUCKET / FOLIO_S3_PUBLIC_BASE"
        )

    files = sorted(f for f in SRC.rglob("*") if f.is_file())
    n = 0
    for f in files:
        key = f"{PREFIX}/{f.relative_to(SRC).as_posix()}"
        if args.dry_run:
            print("would upload", key, f"({f.stat().st_size} B)")
            continue
        upload_bytes(key, f.read_bytes(), content_type=content_type(f), cache_control=CACHE)
        n += 1
        print("uploaded", key)

    if args.dry_run:
        print(f"dry-run: {len(files)} files")
    else:
        print(f"done: {n} files -> {public_base_url()}/{PREFIX}")


if __name__ == "__main__":
    main()
