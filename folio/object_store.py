"""Optional S3-compatible object store (Cloudflare R2) for durable user uploads."""
from __future__ import annotations

import logging
import mimetypes
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("folio.object_store")

USER_UPLOAD_KINDS = ("avatars", "submissions", "tours")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def public_base_url() -> str:
    """Public origin for objects, e.g. https://pub-xxxxx.r2.dev"""
    return (_env("FOLIO_S3_PUBLIC_BASE") or _env("FOLIO_COVER_BASE_URL")).rstrip("/")


def s3_configured() -> bool:
    return bool(
        _env("FOLIO_S3_ENDPOINT")
        and _env("FOLIO_S3_ACCESS_KEY")
        and _env("FOLIO_S3_SECRET_KEY")
        and _env("FOLIO_S3_BUCKET")
        and public_base_url()
    )


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_env("FOLIO_S3_ENDPOINT"),
        aws_access_key_id=_env("FOLIO_S3_ACCESS_KEY"),
        aws_secret_access_key=_env("FOLIO_S3_SECRET_KEY"),
        region_name=_env("FOLIO_S3_REGION") or "auto",
        config=Config(signature_version="s3v4"),
    )


def reset_client_cache() -> None:
    """Clear cached boto3 client (tests / env changes)."""
    _client.cache_clear()


def public_object_url(key: str) -> str:
    key = (key or "").lstrip("/")
    base = public_base_url()
    if not base:
        raise RuntimeError("FOLIO_S3_PUBLIC_BASE / FOLIO_COVER_BASE_URL is not set")
    return f"{base}/{key}"


def upload_bytes(
    key: str,
    data: bytes,
    *,
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=31536000, immutable",
    content_encoding: Optional[str] = None,
) -> str:
    """Upload bytes to the configured bucket. Returns the public HTTPS URL.

    Set ``content_encoding="gzip"`` when ``data`` is already gzipped so the CDN
    serves it compressed without re-compressing (smaller storage + transfer).
    """
    if not s3_configured():
        raise RuntimeError("S3/R2 is not configured")
    key = key.lstrip("/")
    ctype = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    bucket = _env("FOLIO_S3_BUCKET")
    extra = {"ContentType": ctype, "CacheControl": cache_control}
    if content_encoding:
        extra["ContentEncoding"] = content_encoding
    _client().put_object(Bucket=bucket, Key=key, Body=data, **extra)
    url = public_object_url(key)
    log.info("uploaded s3://%s/%s -> %s (%s bytes)", bucket, key, url, len(data))
    return url


def upload_file(
    key: str,
    path,
    *,
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=31536000, immutable",
    content_encoding: Optional[str] = None,
) -> str:
    """Stream a local file to the bucket (multipart for big files, e.g. PMTiles)."""
    if not s3_configured():
        raise RuntimeError("S3/R2 is not configured")
    key = key.lstrip("/")
    ctype = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    bucket = _env("FOLIO_S3_BUCKET")
    extra = {"ContentType": ctype, "CacheControl": cache_control}
    if content_encoding:
        extra["ContentEncoding"] = content_encoding
    _client().upload_file(str(path), bucket, key, ExtraArgs=extra)
    url = public_object_url(key)
    log.info("uploaded s3://%s/%s -> %s", bucket, key, url)
    return url


def delete_object(key: str) -> None:
    if not s3_configured():
        return
    key = key.lstrip("/")
    try:
        _client().delete_object(Bucket=_env("FOLIO_S3_BUCKET"), Key=key)
    except Exception:
        log.exception("failed to delete s3 object %s", key)


def user_upload_key(kind: str, filename: str) -> str:
    kind = (kind or "").strip().strip("/")
    if kind not in USER_UPLOAD_KINDS:
        raise ValueError(f"unsupported upload kind: {kind}")
    name = (filename or "").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("invalid upload filename")
    return f"{kind}/{name}"


def avatar_object_key(filename: str) -> str:
    return user_upload_key("avatars", filename)


def submission_object_key(filename: str) -> str:
    return user_upload_key("submissions", filename)


def content_type_for_ext(ext: str) -> str:
    ext = (ext or "").lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "avif": "image/avif",
    }.get(ext, "application/octet-stream")


def local_static_url(kind: str, filename: str) -> str:
    return f"/static/uploads/{kind}/{filename}"


def key_from_public_or_local_url(url: str, kind: str) -> Optional[str]:
    """Best-effort extract object key from a stored avatar/submission URL."""
    raw = (url or "").strip().split("?", 1)[0]
    if not raw:
        return None
    marker = f"/{kind}/"
    if marker in raw:
        name = raw.split(marker, 1)[-1].lstrip("/")
        if name and "/" not in name:
            return user_upload_key(kind, name)
    return None


def persist_user_upload(
    kind: str,
    filename: str,
    data: bytes,
    *,
    local_dir: Path,
    content_type: Optional[str] = None,
) -> str:
    """Store a user upload on R2 when configured, otherwise on local disk.

    Returns the URL to save in the database (HTTPS CDN or /static/uploads/...).
    """
    key = user_upload_key(kind, filename)
    ctype = content_type or content_type_for_ext(Path(filename).suffix)
    if s3_configured():
        return upload_bytes(key, data, content_type=ctype)
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / filename).write_bytes(data)
    return local_static_url(kind, filename)
