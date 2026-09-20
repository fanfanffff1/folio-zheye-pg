#!/usr/bin/env python3
"""Upload an arbitrary file to R2 with long cache headers (e.g. a PMTiles basemap).

Reuses the project's S3/R2 credentials (FOLIO_S3_*). Streams the file, so it is
safe for multi-GB PMTiles archives.

Usage:
    python3 scripts/upload_r2.py <local-file> <key>
    python3 scripts/upload_r2.py region.pmtiles tour-map/region.pmtiles
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.object_store import public_base_url, s3_configured, upload_file  # noqa: E402

TYPES = {
    ".pmtiles": "application/vnd.pmtiles",
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".mbtiles": "application/vnd.mapbox-vector-tile",
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python3 scripts/upload_r2.py <local-file> <key>")
    src = Path(sys.argv[1])
    key = sys.argv[2].lstrip("/")
    if not src.is_file():
        raise SystemExit(f"not a file: {src}")
    if not s3_configured():
        raise SystemExit("R2/S3 未配置（FOLIO_S3_*）")
    url = upload_file(
        key, src,
        content_type=TYPES.get(src.suffix, "application/octet-stream"),
        cache_control="public, max-age=31536000, immutable",
    )
    print("uploaded ->", url or f"{public_base_url()}/{key}")


if __name__ == "__main__":
    main()
