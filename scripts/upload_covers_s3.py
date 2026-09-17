#!/usr/bin/env python3
"""Upload optimized covers to S3-compatible storage (Cloudflare R2, AWS S3, etc.).

Required env:
  FOLIO_S3_ENDPOINT     e.g. https://<accountid>.r2.cloudflarestorage.com
  FOLIO_S3_ACCESS_KEY
  FOLIO_S3_SECRET_KEY
  FOLIO_S3_BUCKET       e.g. folio-covers
  FOLIO_S3_PUBLIC_BASE  public URL origin, e.g. https://covers.yourdomain.com
                        or https://pub-xxxxx.r2.dev

Optional:
  FOLIO_S3_PREFIX       key prefix, default "covers"
  FOLIO_S3_REGION       default "auto"

After upload, set on the web service:
  FOLIO_COVER_BASE_URL=<same as FOLIO_S3_PUBLIC_BASE>

Example:
  export FOLIO_S3_ENDPOINT=...
  export FOLIO_S3_ACCESS_KEY=...
  export FOLIO_S3_SECRET_KEY=...
  export FOLIO_S3_BUCKET=folio-covers
  export FOLIO_S3_PUBLIC_BASE=https://pub-xxx.r2.dev
  python3 scripts/upload_covers_s3.py
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVER_DIR = ROOT / "static" / "covers"
VARIANTS = (".webp", ".avif")
WIDTH_MARKERS = ("-240", "-320", "-600")


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing env {name}")
    return value


def is_upload_candidate(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in VARIANTS:
        return False
    return any(path.stem.endswith(m) for m in WIDTH_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload FOLIO covers to R2/S3")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise SystemExit("Install boto3 first: python3 -m pip install boto3") from None

    endpoint = require_env("FOLIO_S3_ENDPOINT")
    access = require_env("FOLIO_S3_ACCESS_KEY")
    secret = require_env("FOLIO_S3_SECRET_KEY")
    bucket = require_env("FOLIO_S3_BUCKET")
    public_base = require_env("FOLIO_S3_PUBLIC_BASE").rstrip("/")
    prefix = (os.environ.get("FOLIO_S3_PREFIX") or "covers").strip().strip("/")
    region = (os.environ.get("FOLIO_S3_REGION") or "auto").strip()

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )

    files = sorted(p for p in COVER_DIR.iterdir() if is_upload_candidate(p))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("No variant covers to upload.", file=sys.stderr)
        return 1

    uploaded = 0
    for path in files:
        key = f"{prefix}/{path.name}"
        ctype = mimetypes.guess_type(path.name)[0] or (
            "image/avif" if path.suffix.lower() == ".avif" else "image/webp"
        )
        print(f"{'DRY ' if args.dry_run else ''}PUT s3://{bucket}/{key} ({ctype})")
        if args.dry_run:
            continue
        extra = {
            "ContentType": ctype,
            "CacheControl": "public, max-age=31536000, immutable",
        }
        client.upload_file(str(path), bucket, key, ExtraArgs=extra)
        uploaded += 1

    print(f"done files={len(files)} uploaded={uploaded}")
    print(f"Set FOLIO_COVER_BASE_URL={public_base}")
    print(f"Sample: {public_base}/{prefix}/sleeping-sisters-320.webp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
