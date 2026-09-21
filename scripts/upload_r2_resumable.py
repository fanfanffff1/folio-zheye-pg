#!/usr/bin/env python3
"""Resumable multipart upload to R2 (survives dropped connections / re-runs).

boto3's upload_file() restarts from scratch when the connection dies mid-way
(e.g. a flaky proxy killing a 64GB upload). This keeps the multipart upload open
and only sends the parts that are still missing, so a re-run resumes instead of
re-uploading everything.

Usage:
    python3 scripts/upload_r2_resumable.py <local-file> <key>
    python3 scripts/upload_r2_resumable.py ~/folio-map-data/world.pmtiles tour-map/world.pmtiles
    # start over (abort the pending multipart upload first):
    python3 scripts/upload_r2_resumable.py <file> <key> --abort
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.object_store import _env, public_object_url, s3_configured  # noqa: E402


def make_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_env("FOLIO_S3_ENDPOINT"),
        aws_access_key_id=_env("FOLIO_S3_ACCESS_KEY"),
        aws_secret_access_key=_env("FOLIO_S3_SECRET_KEY"),
        region_name=_env("FOLIO_S3_REGION") or "auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 10, "mode": "standard"},
                      read_timeout=120, connect_timeout=30),
    )


def find_upload(client, bucket: str, key: str):
    for up in client.list_multipart_uploads(Bucket=bucket, Prefix=key).get("Uploads", []):
        if up["Key"] == key:
            return up["UploadId"]
    return None


def list_all_parts(client, bucket: str, key: str, upload_id: str) -> list[dict]:
    """list_parts returns at most 1000 per call — paginate."""
    parts, marker = [], 0
    while True:
        page = client.list_parts(Bucket=bucket, Key=key, UploadId=upload_id,
                                 PartNumberMarker=marker, MaxParts=1000)
        batch = page.get("Parts", [])
        parts.extend(batch)
        if not page.get("IsTruncated"):
            return parts
        marker = page.get("NextPartNumberMarker", 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("key")
    ap.add_argument("--part-mb", type=int, default=64, help="part size when starting fresh")
    ap.add_argument("--content-type", default="application/vnd.pmtiles")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--retries", type=int, default=8)
    ap.add_argument("--abort", action="store_true", help="abort the pending upload and start over")
    args = ap.parse_args()

    if not s3_configured():
        raise SystemExit("R2/S3 未配置（FOLIO_S3_*）")
    src = Path(args.src).expanduser()
    if not src.is_file():
        raise SystemExit(f"not a file: {src}")
    key = args.key.lstrip("/")
    size = src.stat().st_size
    client = make_client()
    bucket = _env("FOLIO_S3_BUCKET")

    upload_id = find_upload(client, bucket, key)
    if upload_id and args.abort:
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        print("aborted previous upload", upload_id)
        upload_id = None

    if not upload_id:
        upload_id = client.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType=args.content_type,
            CacheControl="public, max-age=31536000, immutable",
        )["UploadId"]
        print(f"started new multipart upload {upload_id}")
        part = args.part_mb * 1024 * 1024
    else:
        print(f"resuming multipart upload {upload_id}")
        part = None

    done = {}
    for p in list_all_parts(client, bucket, key, upload_id):
        done[p["PartNumber"]] = p
        if part is None and p["PartNumber"] == 1:
            part = p["Size"]  # match the chunk size already in use
    if part is None:
        part = args.part_mb * 1024 * 1024

    total = (size + part - 1) // part
    missing = [n for n in range(1, total + 1) if n not in done]
    print(f"file={size/1e9:.2f}GB part={part/1e6:.0f}MB parts={total} done={len(done)} missing={len(missing)}")

    t0 = time.time()
    sent = 0

    def put(n: int):
        off = (n - 1) * part
        with open(src, "rb") as fh:
            fh.seek(off)
            data = fh.read(part)
        last = None
        for a in range(args.retries):
            try:
                r = client.upload_part(Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=n, Body=data)
                return n, r["ETag"], len(data)
            except Exception as e:  # noqa: BLE001
                last = e
                wait = min(30, 2 * (a + 1))
                print(f"  part {n} failed ({type(e).__name__}); retry {a + 1}/{args.retries} in {wait}s", flush=True)
                time.sleep(wait)
        raise SystemExit(f"part {n} failed permanently: {last}")

    if missing:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(put, n): n for n in missing}
            for i, fut in enumerate(as_completed(futs), 1):
                n, etag, nb = fut.result()
                sent += nb
                if i % 10 == 0 or i == len(missing):
                    rate = sent / max(1e-6, time.time() - t0) / 1e6
                    left = (len(missing) - i) * part
                    eta = left / max(1e-6, sent / max(1e-6, time.time() - t0))
                    print(f"  [{i}/{len(missing)}] {sent/1e9:.1f}GB sent | {rate:.1f}MB/s | ETA {eta/60:.0f}min", flush=True)

    parts = [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]}
             for p in list_all_parts(client, bucket, key, upload_id)]
    parts.sort(key=lambda x: x["PartNumber"])
    print(f"completing with {len(parts)} parts ...")
    client.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts})
    print("done ->", public_object_url(key))
    print("(if a run is interrupted, just run the same command again to resume)")


if __name__ == "__main__":
    main()
