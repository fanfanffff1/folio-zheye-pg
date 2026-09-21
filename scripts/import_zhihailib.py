#!/usr/bin/env python3
"""Import zhihailib crawl results into the Book table (Chinese originals only).

Reads folio-covers-offline/data-zh/zhihailib-cache.json, keeps entries whose
author tag marks them as Chinese originals, copies the candidate cover into
static/covers/<slug>.jpg and upserts Book + Author rows.

Idempotent (matched by slug, then by normalized title+author).

Usage:
    python3 scripts/import_zhihailib.py --dry-run
    python3 scripts/import_zhihailib.py --limit 1000
    DATABASE_URL="<neon>" python3 scripts/import_zhihailib.py --limit 1000   # production
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPIRATION = ROOT.parent
OFFLINE = INSPIRATION / "folio-covers-offline"
CACHE = OFFLINE / "data-zh" / "zhihailib-cache.json"
CANDS = OFFLINE / "covers-zh-candidates"
COVERS_DST = ROOT / "static" / "covers"
SOURCE_NAME = "知海图书馆"

sys.path.insert(0, str(ROOT))

from folio.cover_urls import derive_cover_urls  # noqa: E402
from folio.models import Author, Book, SessionLocal, init_db  # noqa: E402

try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return re.sub(r"[\s《》〈〉「」『』·,，.。:：;；!！?？\-—_/\\()（）\[\]【】\"'’‘“”]+", "", text)


def slugify(title: str, sid: str) -> str:
    if lazy_pinyin:
        py = "-".join(p for p in lazy_pinyin(title) if p.strip())
        py = re.sub(r"[^a-z0-9]+", "-", py.lower()).strip("-")
        if py:
            return "zh-" + py[:80]
    return "zh-hl-" + sid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-origins", action="store_true", help="include translations too")
    args = ap.parse_args()

    data = json.loads(CACHE.read_text(encoding="utf-8"))
    rows = []
    for sid, d in data.items():
        if not d.get("ok"):
            continue
        if not args.all_origins and d.get("origin") != "zh":
            continue
        rows.append((sid, d))
    rows.sort(key=lambda x: int(x[0]))
    if args.limit:
        rows = rows[: args.limit]

    if not args.dry_run:
        init_db()
    db = SessionLocal() if not args.dry_run else None
    added = updated = skipped = covers = 0
    try:
        for sid, d in rows:
            title = (d.get("title_clean") or d.get("title") or "").strip()
            author_name = (d.get("author") or "").strip()
            if not title:
                skipped += 1
                continue
            if not args.dry_run:
                author = None
                if author_name:
                    author = db.query(Author).filter(Author.name == author_name).one_or_none()
                    if not author:
                        author = Author(name=author_name, localized_name=author_name)
                        db.add(author)
                        db.flush()
                book = None
                if author:
                    book = next((b for b in db.query(Book).filter(Book.author_id == author.id, Book.language_code == "zh").all()
                                 if norm(b.chinese_title) == norm(title)), None)
                if not book:
                    base = slugify(title, sid)
                    slug = base
                    n = 2
                    while db.query(Book).filter(Book.slug == slug).first():
                        slug = f"{base}-{n}"
                        n += 1
                    book = Book(slug=slug)
                    db.add(book)
                    added += 1
                else:
                    updated += 1
                book.original_title = d.get("title") or title
                book.chinese_title = title
                book.author_id = author.id if author else None
                book.language_code = "zh"
                book.language_name = "中文"
                book.publisher = d.get("publisher") or book.publisher
                y = (d.get("pubdate") or "")[:4]
                if y.isdigit():
                    book.publication_year = int(y)
                if d.get("format"):
                    book.edition = book.edition or d.get("format")
                intro = (d.get("intro") or "").strip()
                if intro:
                    book.full_description_zh = intro
                    if not book.short_description_zh:
                        book.short_description_zh = intro[:80]
                book.primary_genre = book.primary_genre or "文学"
                book.verification_status = "verified" if d.get("publisher") else "pending"
                book.source_name = SOURCE_NAME
                book.source_url = f"https://www.zhihailib.com/book/{sid}"
                book.source_file = "zhihailib"
                cover_src = CANDS / f"{sid}.jpg"
                if cover_src.exists() and book.slug:
                    COVERS_DST.mkdir(parents=True, exist_ok=True)
                    dst = COVERS_DST / (book.slug + ".jpg")
                    if not dst.exists() or dst.stat().st_size != cover_src.stat().st_size:
                        shutil.copyfile(cover_src, dst)
                        covers += 1
                    book.cover_image = "/covers/" + dst.name
                    book.cover_thumbnail_url, book.cover_full_url = derive_cover_urls(book.cover_image)
        if not args.dry_run:
            db.commit()
        print(f"{'[dry-run] ' if args.dry_run else ''}rows={len(rows)} added={added} updated={updated} covers_copied={covers} skipped={skipped}")
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    main()
