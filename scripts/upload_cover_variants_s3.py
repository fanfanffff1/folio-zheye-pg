#!/usr/bin/env python3
"""Upload cover WebP/AVIF variants to R2 and overwrite existing objects with the same key.

Loads optional project .env via python-dotenv.

Required env (same as other R2 scripts):
  FOLIO_S3_ENDPOINT
  FOLIO_S3_ACCESS_KEY
  FOLIO_S3_SECRET_KEY
  FOLIO_S3_BUCKET
  FOLIO_S3_PUBLIC_BASE   (or FOLIO_COVER_BASE_URL)

Examples:
  # Only the six newly replaced English covers (overwrite on R2):
  python3 scripts/upload_cover_variants_s3.py \\
    --stem gods-country --stem best-i-never-had --stem calamities \\
    --stem immortal-rose --stem sister-kill --stem dear-debbie --stem en-dear-debbie

  # All local variants:
  python3 scripts/upload_cover_variants_s3.py --all

  python3 scripts/upload_cover_variants_s3.py --stem gods-country --dry-run
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVER_DIR = ROOT / "static" / "covers"
WIDTH_MARKERS = ("-240", "-320", "-600")
VARIANT_EXTS = {".webp", ".avif"}


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv as _load

        _load(env_path)
    except ImportError:
        # Minimal .env parser
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            os.environ.setdefault(key, val)


def require_env(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    raise SystemExit(f"Missing env {' / '.join(names)}")


def is_variant(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in VARIANT_EXTS:
        return False
    return any(path.stem.endswith(m) for m in WIDTH_MARKERS)


def stem_of_variant(path: Path) -> str:
    name = path.stem
    for m in WIDTH_MARKERS:
        if name.endswith(m):
            return name[: -len(m)]
    return name


def collect_files(stems: set[str] | None, all_files: bool) -> list[Path]:
    files = [p for p in COVER_DIR.iterdir() if is_variant(p)]
    if all_files:
        return sorted(files)
    if not stems:
        raise SystemExit("Pass --stem NAME (repeatable) or --all")
    return sorted(p for p in files if stem_of_variant(p) in stems)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Upload cover variants to R2, overwriting same keys"
    )
    parser.add_argument(
        "--stem",
        action="append",
        default=[],
        help="Cover stem to upload (e.g. gods-country). Repeatable.",
    )
    parser.add_argument("--all", action="store_true", help="Upload every local variant")
    parser.add_argument("--dry-run", action="store_true")
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
    public_base = require_env("FOLIO_S3_PUBLIC_BASE", "FOLIO_COVER_BASE_URL").rstrip("/")
    prefix = (os.environ.get("FOLIO_S3_PREFIX") or "covers").strip().strip("/")
    region = (os.environ.get("FOLIO_S3_REGION") or "auto").strip()

    stems = {s.strip() for s in args.stem if s.strip()}
    files = collect_files(stems or None, all_files=args.all)
    if not files:
        print("No matching variant files in static/covers/", file=sys.stderr)
        return 1

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )

    print(f"bucket={bucket} prefix={prefix}/ overwrite=yes files={len(files)}")
    uploaded = 0
    for path in files:
        key = f"{prefix}/{path.name}"
        ctype = mimetypes.guess_type(path.name)[0] or (
            "image/avif" if path.suffix.lower() == ".avif" else "image/webp"
        )
        print(f"{'DRY ' if args.dry_run else ''}PUT s3://{bucket}/{key} ({path.stat().st_size} bytes)")
        if args.dry_run:
            continue
        client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                "ContentType": ctype,
                # short cache so overwritten covers refresh without waiting a year
                "CacheControl": "public, max-age=86400",
            },
        )
        uploaded += 1

    print(f"done uploaded={uploaded} dry_run={args.dry_run}")
    if files:
        sample = files[0].name
        print(f"Sample URL: {public_base}/{prefix}/{sample}")
    print("Note: site uses ?v= on cover URLs; bump COVER_ASSET_VERSION if browsers still show old art.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
