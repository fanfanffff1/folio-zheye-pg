"""Cover URL helpers: list thumbnail vs detail full image, CDN + AVIF."""
from __future__ import annotations

import os
from pathlib import Path

from .config import STATIC_DIR

PLACEHOLDER = "/covers/placeholder.svg"
COVER_ROOT = STATIC_DIR / "covers"
# Bump when regenerating cover bytes under the same path (cache bust).
COVER_ASSET_VERSION = "avif7"
COVER_LIST_SIZES = "(max-width: 767px) 42vw, (max-width: 1023px) 25vw, 180px"
COVER_CARD_SIZES = "(max-width: 767px) 28vw, 120px"
# Public origin for covers, e.g. https://covers.example.com or https://pub-xxx.r2.dev
# Leave empty to serve from this app at /covers/...
COVER_BASE_URL = (os.environ.get("FOLIO_COVER_BASE_URL") or "").rstrip("/")
# Optional offline/local mirror of photo covers (outside the git repo).
# Example: /Users/…/inspiration/folio-covers-offline/covers
COVERS_DIR = (os.environ.get("FOLIO_COVERS_DIR") or "").rstrip("/")
_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


def _with_version(url: str) -> str:
    if not url or url == PLACEHOLDER or "?" in url:
        return url
    if url.endswith(".svg"):
        return url
    return f"{url}?v={COVER_ASSET_VERSION}"


def public_cover_url(path: str) -> str:
    """Turn /covers/foo.webp into CDN or local absolute path with version.

    Title-card SVGs and the placeholder stay on the app origin: they are not
    uploaded to R2 by the cover optimizer, and the SVG itself carries title text.
    """
    path = (path or "").strip() or PLACEHOLDER
    if path.startswith("http://") or path.startswith("https://"):
        return _with_version(path) if "://" in path and "?" not in path else path
    if not path.startswith("/"):
        path = "/" + path
    # Keep vector title cards + placeholder on this host (not on the CDN).
    if path.endswith(".svg"):
        return path
    if COVER_BASE_URL and path.startswith("/covers/"):
        return _with_version(f"{COVER_BASE_URL}{path}")
    return _with_version(path)


def _stem_from_cover(cover_image: str) -> str | None:
    path = (cover_image or "").strip()
    # Strip CDN origin for stem parsing
    if COVER_BASE_URL and path.startswith(COVER_BASE_URL):
        path = path[len(COVER_BASE_URL) :] or path
    if "://" in path:
        # foreign absolute URL: take last path segment
        name = path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    elif path.startswith("/covers/"):
        name = path.rsplit("/", 1)[-1]
    else:
        return None
    name = name.split("?", 1)[0]
    if not name or name == "placeholder.svg":
        return None
    lower = name.lower()
    for suffix in (
        "-240.webp", "-320.webp", "-600.webp",
        "-240.avif", "-320.avif", "-600.avif",
    ):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".svg"):
        if lower.endswith(ext):
            return name[: -len(ext)]
    return Path(name).stem


def resolve_cover_file(url: str) -> Path | None:
    """Return an on-disk path for a /covers/... URL if present locally or in FOLIO_COVERS_DIR."""
    path = (url or "").strip().split("?", 1)[0]
    if COVER_BASE_URL and path.startswith(COVER_BASE_URL):
        path = path[len(COVER_BASE_URL) :]
    if not path.startswith("/covers/"):
        return None
    rel = path.lstrip("/")
    name = Path(rel).name
    candidates = [STATIC_DIR / rel]
    if COVERS_DIR:
        root = Path(COVERS_DIR)
        candidates.append(root / name)
        candidates.append(root / rel)
        candidates.append(root / "covers" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _is_cdn_photo_path(path: str) -> bool:
    """When R2 is configured, photo covers live on the CDN — not in the Docker image."""
    if not COVER_BASE_URL or not path.startswith("/covers/"):
        return False
    name = path.rsplit("/", 1)[-1].lower()
    if name == "placeholder.svg" or name.startswith("card-") or name.endswith(".svg"):
        return False
    return name.endswith(_PHOTO_EXTS)


def cover_file_exists(url: str) -> bool:
    """True if a local/offline file exists, or CDN is configured for photo covers."""
    path = (url or "").strip().split("?", 1)[0]
    if COVER_BASE_URL and path.startswith(COVER_BASE_URL):
        path = path[len(COVER_BASE_URL) :]
    if resolve_cover_file(path):
        return True
    return _is_cdn_photo_path(path)


def derive_cover_urls(cover_image: str) -> tuple[str, str]:
    """Return (thumbnail_path, full_path) as /covers/... paths (no CDN yet)."""
    base = (cover_image or "").strip() or PLACEHOLDER
    if base.startswith("http") and "/covers/" not in base:
        return base, base
    path = base.split("?", 1)[0]
    if COVER_BASE_URL and path.startswith(COVER_BASE_URL):
        path = path[len(COVER_BASE_URL) :] or path
    # Generated title/author cards (card-*.svg) must be kept — they carry the text.
    if path.endswith(".svg"):
        if path == PLACEHOLDER or path.endswith("/placeholder.svg"):
            return PLACEHOLDER, PLACEHOLDER
        if path.startswith("/covers/") and (cover_file_exists(path) or "/covers/card-" in path):
            return path, path
        return PLACEHOLDER, PLACEHOLDER
    stem = _stem_from_cover(path)
    if not stem:
        if path.startswith("/covers/"):
            return path, path
        return PLACEHOLDER, PLACEHOLDER
    thumb = f"/covers/{stem}-320.webp"
    full = f"/covers/{stem}-600.webp"
    thumb_ok = cover_file_exists(thumb)
    full_ok = cover_file_exists(full)
    orig = path if path.startswith("/covers/") else PLACEHOLDER
    return (thumb if thumb_ok else orig), (full if full_ok else orig)


def _canonical_cover_path(book_or_url) -> str:
    if isinstance(book_or_url, str):
        return book_or_url
    stored = getattr(book_or_url, "cover_thumbnail_url", "") or ""
    if stored and (cover_file_exists(stored) or stored.startswith("http")):
        return stored
    return getattr(book_or_url, "cover_image", "") or ""


def cover_thumb(book_or_url) -> str:
    if isinstance(book_or_url, str):
        return public_cover_url(derive_cover_urls(book_or_url)[0])
    cover = getattr(book_or_url, "cover_image", "") or ""
    stored = getattr(book_or_url, "cover_thumbnail_url", "") or ""
    if stored.startswith("http") and "/covers/" not in stored:
        return stored
    path = derive_cover_urls(cover or stored)[0]
    return public_cover_url(path)


def cover_full(book_or_url) -> str:
    if isinstance(book_or_url, str):
        return public_cover_url(derive_cover_urls(book_or_url)[1])
    cover = getattr(book_or_url, "cover_image", "") or ""
    stored = getattr(book_or_url, "cover_full_url", "") or ""
    if stored.startswith("http") and "/covers/" not in stored:
        return stored
    path = derive_cover_urls(cover or stored)[1]
    return public_cover_url(path)


def _variant_srcset(book_or_url, ext: str, widths: tuple[int, ...] = (240, 320)) -> str:
    cover = (
        book_or_url
        if isinstance(book_or_url, str)
        else (getattr(book_or_url, "cover_image", "") or "")
    )
    # Never invent WebP/AVIF for title-card SVGs.
    if (cover or "").endswith(".svg") or cover == PLACEHOLDER:
        return ""
    base = _canonical_cover_path(book_or_url)
    if not base or base.endswith(".svg") or base == PLACEHOLDER:
        return ""
    if base.startswith("http") and "/covers/" not in base:
        return ""
    stem = _stem_from_cover(cover or base)
    if not stem or stem.startswith("card-"):
        return ""
    parts: list[str] = []
    for width in widths:
        path = f"/covers/{stem}-{width}.{ext}"
        if cover_file_exists(path):
            parts.append(f"{public_cover_url(path)} {width}w")
    return ", ".join(parts)


def cover_thumb_srcset(book_or_url) -> str:
    return _variant_srcset(book_or_url, "webp")


def cover_thumb_srcset_avif(book_or_url) -> str:
    return _variant_srcset(book_or_url, "avif")


def cover_full_avif(book_or_url) -> str:
    cover = (
        book_or_url
        if isinstance(book_or_url, str)
        else (getattr(book_or_url, "cover_image", "") or "")
    )
    if (cover or "").endswith(".svg"):
        return ""
    stem = _stem_from_cover(cover)
    if not stem or stem.startswith("card-"):
        return ""
    path = f"/covers/{stem}-600.avif"
    if not cover_file_exists(path):
        return ""
    return public_cover_url(path)


def cover_list_sizes() -> str:
    return COVER_LIST_SIZES


def cover_card_sizes() -> str:
    return COVER_CARD_SIZES


def cover_title_card(book) -> str:
    """Ensure a title/author SVG card exists and return its public URL."""
    if isinstance(book, str):
        return PLACEHOLDER
    from .seed import write_title_card

    author = ""
    try:
        author = book.author.name if book.author else ""
    except Exception:
        author = ""
    path = write_title_card(
        getattr(book, "original_title", None) or "",
        getattr(book, "chinese_title", None) or "",
        getattr(book, "language_code", None) or "",
        author,
    )
    return public_cover_url(path)


def cover_thumb_safe(book) -> str:
    """List/detail thumb that never starts from a blank generic placeholder."""
    if isinstance(book, str):
        return cover_thumb(book)
    cover = (getattr(book, "cover_image", None) or "").strip()
    if not cover or cover == PLACEHOLDER or cover.endswith("/placeholder.svg"):
        return cover_title_card(book)
    return cover_thumb(book)


def cover_full_safe(book) -> str:
    if isinstance(book, str):
        return cover_full(book)
    cover = (getattr(book, "cover_image", None) or "").strip()
    if not cover or cover == PLACEHOLDER or cover.endswith("/placeholder.svg"):
        return cover_title_card(book)
    return cover_full(book)
