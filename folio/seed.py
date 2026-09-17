from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime
from html import escape
from pathlib import Path
import json

from PIL import Image
from sqlalchemy.orm import Session

from .config import ISSUE_MONTH, ISSUE_TITLE, ISSUE_YEAR, LANGS, ROOT, STATIC_DIR, catalog_path
from .cover_urls import COVER_BASE_URL, derive_cover_urls, resolve_cover_file
from .featured import FEATURED
from .models import Author, Book, Issue, SessionLocal, init_db

# Google Books “no cover” images we accidentally saved (identical files).
BLANK_COVER_MD5 = {
    "9f6b6fe91b4fe282e7b6e1aa247862e8",
    "b2b2c857052e962da1081b5648c8a30b",
    "aacb9a42d3bb234ade46c7ce29328f3c",
}

CLEANED = catalog_path("cleaned-books.json")


def parse_date(value: str | None, year: int | None):
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    if year:
        return date(int(year), 1, 1)
    return None


def get_or_create_author(db: Session, name: str, extra: dict | None = None) -> Author | None:
    if not name:
        return None
    row = db.query(Author).filter(Author.name == name).one_or_none()
    if not row:
        row = Author(name=name)
        db.add(row)
        db.flush()
    if extra:
        row.localized_name = extra.get("localizedName") or row.localized_name
        row.biography_zh = extra.get("biographyZh") or row.biography_zh
        row.nationality = extra.get("nationality") or row.nationality
        if extra.get("verifiedAt"):
            try:
                row.verified_at = datetime.fromisoformat(extra["verifiedAt"])
            except ValueError:
                row.verified_at = datetime.utcnow()
    return row


def apply_catalog_row(db: Session, rec: dict, existing: dict[str, Book]) -> Book:
    slug = rec["slug"]
    book = existing.get(slug)
    if not book:
        book = Book(
            slug=slug,
            original_title=rec["originalTitle"],
            language_code=rec["languageCode"],
            primary_genre=rec.get("primaryGenre") or "其他",
        )
        db.add(book)
        existing[slug] = book
    author = get_or_create_author(db, rec.get("authorName") or "", {"nationality": rec.get("nationality") or ""})
    book.original_title = rec["originalTitle"]
    book.chinese_title = rec.get("chineseTitle") or ""
    book.author_id = author.id if author else None
    book.language_code = rec["languageCode"]
    book.language_name = rec.get("languageName") or LANGS.get(rec["languageCode"], {}).get("zh", "")
    book.publisher = rec.get("publisher") or ""
    book.publication_date = parse_date(rec.get("publicationDate"), rec.get("publicationYear"))
    book.publication_year = book.publication_date.year if book.publication_date else rec.get("publicationYear")
    book.isbn13 = rec.get("isbn13") or ""
    book.isbn10 = rec.get("isbn10") or ""
    book.primary_genre = rec.get("primaryGenre") or "其他"
    book.genres = ",".join(rec.get("genres") or [book.primary_genre])
    book.tags = ",".join(rec.get("tags") or [])
    book.short_description_zh = rec.get("shortDescriptionZh") or ""
    cover = rec.get("coverImage") or ""
    book.cover_image = pick_cover(
        cover,
        rec["originalTitle"],
        rec.get("chineseTitle") or "",
        rec["languageCode"],
        rec.get("authorName") or "",
    )
    thumb, full = derive_cover_urls(book.cover_image)
    book.cover_thumbnail_url = thumb
    book.cover_full_url = full
    book.verification_status = rec.get("verificationStatus") or "pending"
    book.source_file = rec.get("sourceFile") or ""
    book.source_row = rec.get("sourceRow") or 0
    book.updated_at = datetime.utcnow()
    return book


def apply_featured(db: Session, feat: dict, existing: dict[str, Book], issue: Issue, rank: int) -> Book:
    lang = feat["languageCode"]
    title = feat["matchTitle"]
    book = (
        db.query(Book)
        .filter(Book.language_code == lang, Book.original_title == title)
        .first()
    )
    if not book:
        isbn = feat.get("isbn13") or ""
        digest = hashlib.sha1(f"{lang}|{title}".encode("utf-8")).hexdigest()[:12]
        slug = f"{lang}-{isbn}" if isbn else f"{lang}-feat-{digest}"
        book = existing.get(slug) or Book(
            slug=slug,
            original_title=title,
            language_code=lang,
            primary_genre=feat.get("primaryGenre") or "其他",
        )
        if slug not in existing:
            db.add(book)
            existing[slug] = book
    author = get_or_create_author(db, feat["author"]["name"], feat["author"])
    book.original_title = title
    chinese = feat["chineseTitle"] or ""
    if chinese and "暂译" not in chinese:
        chinese = f"{chinese}（暂译）"
    book.chinese_title = chinese
    book.author_id = author.id if author else None
    book.language_code = lang
    book.language_name = LANGS[lang]["zh"]
    book.publisher = feat["publisher"]
    book.publication_date = parse_date(feat.get("publicationDate"), 2026)
    book.publication_year = book.publication_date.year if book.publication_date else 2026
    if feat.get("isbn13"):
        book.isbn13 = feat["isbn13"]
    book.primary_genre = feat["primaryGenre"]
    book.genres = ",".join(feat["genres"])
    book.tags = ",".join(feat["tags"])
    book.full_description_zh = feat["fullDescriptionZh"]
    book.recommendation_zh = feat["recommendationZh"]
    book.audience_zh = feat["audienceZh"]
    book.reading_mood_zh = feat["readingMoodZh"]
    book.editor_quote_zh = feat["editorQuoteZh"]
    book.short_description_zh = feat["fullDescriptionZh"][:148] + "…"
    book.cover_image = pick_cover(
        feat.get("coverImage") or "",
        title,
        chinese,
        lang,
        feat["author"]["name"],
        prefer=feat.get("coverImage") or "",
        keep=book.cover_image or "",
        slug=book.slug or "",
    )
    thumb, full = derive_cover_urls(book.cover_image)
    book.cover_thumbnail_url = thumb
    book.cover_full_url = full
    book.is_featured = True
    book.is_recommended = True
    book.issue_id = issue.id
    book.featured_rank = rank
    book.verification_status = feat["verificationStatus"]
    try:
        book.verified_at = datetime.fromisoformat(feat["verifiedAt"])
    except Exception:
        book.verified_at = datetime.utcnow()
    book.source_name = feat.get("sourceName") or ""
    book.source_url = feat.get("sourceUrl") or ""
    book.selection_reason = feat.get("selectionReason") or ""
    book.updated_at = datetime.utcnow()
    return book


def copy_provided_covers() -> None:
    src = ROOT / "covers"
    dst = STATIC_DIR / "covers"
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for path in src.glob("*.jpg"):
        shutil.copy2(path, dst / path.name)


def is_real_cover_path(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return False
    raw = path.read_bytes()
    if len(raw) < 8000:
        return False
    if hashlib.md5(raw).hexdigest() in BLANK_COVER_MD5:
        return False
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return False
    if min(im.size) < 80:
        return False
    small = im.resize((40, 60), Image.Resampling.BILINEAR)
    flat = list(getattr(small, "get_flattened_data", small.getdata)())
    return len(set(flat)) >= 400


def accept_photo_cover(candidate: str) -> bool:
    """True if the cover is a real local/offline photo, or a CDN path when R2 is on."""
    c = (candidate or "").strip()
    if not c.startswith("/covers/") or not c.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    if "placeholder" in c:
        return False
    disk = resolve_cover_file(c)
    if disk and is_real_cover_path(disk):
        return True
    # Production bakes no JPGs; featured/enrichment paths are authoritative on R2.
    return bool(COVER_BASE_URL)


def purge_blank_covers() -> int:
    dst = STATIC_DIR / "covers"
    if not dst.exists():
        return 0
    n = 0
    for path in list(dst.glob("*.jpg")):
        if is_real_cover_path(path):
            continue
        path.unlink(missing_ok=True)
        n += 1
    return n


def wrap_card_text(text: str, width: int, limit: int) -> list[str]:
    text = (text or "").strip()
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= width:
            lines.append(buf)
            buf = ""
        if len(lines) >= limit:
            break
    if buf and len(lines) < limit:
        lines.append(buf)
    return lines


def pick_cover(
    cover_image: str,
    title: str,
    chinese: str,
    lang: str,
    author: str = "",
    prefer: str = "",
    keep: str = "",
    slug: str = "",
) -> str:
    """Prefer a real photo cover; never invent WebP paths.

    ``keep`` / ``slug`` stop light-seed featured passes from wiping a cover that
    was already upgraded (enrichment or manual) back to an SVG title card when
    featured.py still says placeholder.svg.
    """
    copy_provided_covers()
    candidates: list[str] = []
    for raw in (prefer, cover_image, keep, f"/covers/{slug}.jpg" if slug else ""):
        c = (raw or "").strip()
        if c and c not in candidates:
            candidates.append(c)
    for candidate in candidates:
        if accept_photo_cover(candidate):
            return candidate
    return write_title_card(title, chinese, lang, author)


def write_title_card(title: str, chinese: str, lang: str, author: str = "") -> str:
    dst = STATIC_DIR / "covers"
    dst.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{lang}|{title}".encode("utf-8")).hexdigest()[:10]
    name = f"card-{lang}-{digest}.svg"
    path = dst / name
    path.write_text(placeholder_svg(title, chinese, lang, author), encoding="utf-8")
    return f"/covers/{name}"


def placeholder_svg(title: str, chinese: str, lang: str, author: str = "") -> str:
    title_lines = wrap_card_text(title, 12, 4) or ["Untitled"]
    texts = []
    y = 220
    for line in title_lines:
        texts.append(
            f'<text x="36" y="{y}" fill="#f4efe6" font-size="22" font-family="Palatino, serif">{escape(line)}</text>'
        )
        y += 32
    y += 12
    for line in wrap_card_text(author, 16, 2):
        texts.append(
            f'<text x="36" y="{y}" fill="#c4a574" font-size="14" font-family="Palatino, serif">{escape(line)}</text>'
        )
        y += 24
    native = LANGS.get(lang, {}).get("native", lang)
    zh = (chinese or "")[:24]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600" role="img" aria-label="{escape(title)} 封面待补">
  <rect width="400" height="600" fill="#1b1712"/>
  <rect x="16" y="16" width="368" height="568" fill="none" stroke="#c4a574" stroke-width="1"/>
  <text x="36" y="64" fill="#c4a574" font-size="13" font-family="Avenir Next, sans-serif" letter-spacing="6">FOLIO</text>
  <text x="36" y="88" fill="#8a8173" font-size="12" font-family="sans-serif">{escape(native)}</text>
  {''.join(texts)}
  <text x="36" y="468" fill="#c4a574" font-size="14" font-family="Songti SC, serif">{escape(zh)}</text>
  <text x="36" y="548" fill="#8a8173" font-size="12">封面待补 · 非真实书封</text>
</svg>
'''


def apply_enrichment_overlay(db: Session) -> None:
    path = catalog_path("enrichment.json")
    if not path.exists():
        return
    overlay = json.loads(path.read_text(encoding="utf-8")).get("bySlug") or {}
    books = {b.slug: b for b in db.query(Book).all()}
    for slug, extra in overlay.items():
        book = books.get(slug)
        if not book:
            continue
        if extra.get("isbn13") and not book.isbn13:
            book.isbn13 = extra["isbn13"]
        if extra.get("isbn10") and not book.isbn10:
            book.isbn10 = extra["isbn10"]
        if extra.get("publicationYear") and not book.publication_year:
            book.publication_year = extra["publicationYear"]
            book.publication_date = parse_date(None, extra["publicationYear"])
        cover = extra.get("coverImage") or ""
        if cover.endswith((".jpg", ".jpeg", ".png", ".webp")):
            current = book.cover_image or ""
            if accept_photo_cover(cover) and not accept_photo_cover(current):
                book.cover_image = cover
        if extra.get("verificationStatus") == "verified":
            book.verification_status = "verified"
        if extra.get("sourceName"):
            book.source_name = extra["sourceName"]
        if extra.get("selectionReason"):
            book.selection_reason = extra["selectionReason"]


def sync_cover_variant_urls(db: Session) -> int:
    """Fill cover_thumbnail_url / cover_full_url from on-disk WebP variants."""
    updated = 0
    for book in db.query(Book).all():
        thumb, full = derive_cover_urls(book.cover_image or "")
        if book.cover_thumbnail_url != thumb or book.cover_full_url != full:
            book.cover_thumbnail_url = thumb
            book.cover_full_url = full
            updated += 1
    return updated


def seed() -> None:
    import json as _json
    import os

    force = (os.environ.get("FOLIO_FORCE_SEED") or "").strip().lower() in {"1", "true", "yes"}
    try:
        init_db()
    except Exception as exc:
        raise SystemExit(
            "数据库初始化失败。请确认 Render 的 DATABASE_URL 是 Neon Connect 里 "
            "Role=neondb_owner 的 postgresql:// 串；Connect 里关掉 Pooled connection，"
            "主机名不要含 -pooler；不要用 authenticator / REST / Auth。"
            f"\n原始错误: {exc}"
        ) from exc
    if not CLEANED.exists():
        raise SystemExit("Run: python3 scripts/import_xlsx.py")

    db = SessionLocal()
    try:
        existing_count = db.query(Book).count()
        light = existing_count > 0 and not force
        if light:
            print(f"seed light: catalog already has {existing_count} books; skip full import")
        else:
            purge_blank_covers()
            copy_provided_covers()

        payload = _json.loads(CLEANED.read_text(encoding="utf-8"))
        issue = db.query(Issue).filter(Issue.year == ISSUE_YEAR, Issue.month == ISSUE_MONTH).one_or_none()
        if not issue:
            issue = Issue(
                year=ISSUE_YEAR,
                month=ISSUE_MONTH,
                title=ISSUE_TITLE,
                subtitle="以英语为轴，通向六种原版阅读",
                description="本期从各语言书目中选出八本日历年2026首次出版的原版新书。",
                cover_theme="paper-september",
                published_at=datetime(ISSUE_YEAR, ISSUE_MONTH, 1),
            )
            db.add(issue)
            db.flush()

        existing = {b.slug: b for b in db.query(Book).all()}
        if not light:
            for rec in payload["books"]:
                apply_catalog_row(db, rec, existing)
            db.flush()

        db.query(Book).update({Book.is_featured: False, Book.is_recommended: False, Book.featured_rank: 0})
        db.flush()

        ranks: dict[str, int] = {}
        for feat in FEATURED:
            ranks[feat["languageCode"]] = ranks.get(feat["languageCode"], 0) + 1
            apply_featured(db, feat, existing, issue, ranks[feat["languageCode"]])
        # Always run: light deploys used to skip this, so SVG placeholders stuck
        # even after new JPGs shipped in the image / enrichment overlay.
        apply_enrichment_overlay(db)
        cover_n = sync_cover_variant_urls(db)
        db.commit()
        total = db.query(Book).count()
        featured = db.query(Book).filter(Book.is_featured.is_(True)).count()
        mode = "light" if light else "full"
        print(f"seeded ({mode}) books={total} featured={featured} cover_urls={cover_n}")
        for code in LANGS:
            n = db.query(Book).filter(Book.language_code == code, Book.is_featured.is_(True)).count()
            print(f"  featured {code}: {n}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
