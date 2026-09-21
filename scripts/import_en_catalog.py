#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import the generated English catalog (data/en-10k-catalog.json) into the DB.

Idempotent and non-destructive: a book is skipped when its slug, ISBN or
(title, author) already exists. Existing curated content is never overwritten.

Local:  python3 scripts/import_en_catalog.py
Neon:   DATABASE_URL='postgresql://...' python3 scripts/import_en_catalog.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.cover_urls import derive_cover_urls  # noqa: E402
from folio.models import Author, Book, SessionLocal, init_db  # noqa: E402

DEFAULT_CATALOG = ROOT / "data" / "en-10k-catalog.json"
WS_RE = re.compile(r"\s+")


def norm(value: str) -> str:
    s = (value or "").replace("\u2019", "'").replace("\u2018", "'")
    return WS_RE.sub(" ", s).strip().lower()


def trunc(value, n: int) -> str:
    """Postgres enforces varchar(n); SQLite does not. Trim to fit the column."""
    s = value if isinstance(value, str) else ("" if value is None else str(value))
    return s[:n]


def load_existing(db) -> tuple[set, set, set]:
    slugs, isbns, title_author = set(), set(), set()
    for slug, otitle, i13, i10, aname in db.query(
        Book.slug, Book.original_title, Book.isbn13, Book.isbn10, Author.name
    ).outerjoin(Author, Author.id == Book.author_id).all():
        slugs.add((slug or "").lower())
        if i13:
            isbns.add(i13)
        if i10:
            isbns.add(i10)
        t = norm(otitle)
        a = norm(aname or "")
        if t:
            title_author.add(f"{t}|{a}")
    return slugs, isbns, title_author


def get_or_create_author(db, cache: dict, name: str, rec: dict) -> Author | None:
    if not name:
        return None
    key = norm(name)
    author = cache.get(key)
    if author is None:
        author = db.query(Author).filter(Author.name == name).one_or_none()
        if not author:
            author = Author(name=trunc(name, 200))
            db.add(author)
            db.flush()
        cache[key] = author
    if rec.get("authorNameZh") and not author.localized_name:
        author.localized_name = trunc(rec["authorNameZh"], 200)
    if rec.get("nationality") and not author.nationality:
        author.nationality = trunc(rec["nationality"], 120)
    if rec.get("authorBiographyZh") and not author.biography_zh:
        author.biography_zh = rec["authorBiographyZh"]
    return author


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    catalog = Path(args.catalog)
    if not catalog.exists():
        raise SystemExit(f"catalog not found: {catalog}")
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    books = payload["books"]
    if args.limit:
        books = books[: args.limit]

    init_db()
    db = SessionLocal()
    inserted = skipped = 0
    author_cache: dict = {}
    try:
        slugs, isbns, title_author = load_existing(db)
        for i, rec in enumerate(books, 1):
            slug = (rec.get("slug") or "").strip()
            isbn13 = (rec.get("isbn13") or "").strip()
            isbn10 = (rec.get("isbn10") or "").strip()
            ta = f"{norm(rec.get('originalTitle'))}|{norm(rec.get('authorName'))}"
            if slug.lower() in slugs or (isbn13 and isbn13 in isbns) or (isbn10 and isbn10 in isbns) or ta in title_author:
                skipped += 1
                continue
            if args.dry_run:
                inserted += 1
                continue
            author = get_or_create_author(db, author_cache, rec.get("authorName") or "", rec)
            book = Book(
                slug=trunc(slug, 160),
                original_title=trunc(rec.get("originalTitle"), 400),
                chinese_title=trunc(rec.get("chineseTitle"), 400),
                author_id=author.id if author else None,
                language_code="en",
                language_name="英语",
                publisher=trunc(rec.get("publisher"), 200),
                publication_year=rec.get("publicationYear"),
                isbn13=trunc(isbn13, 20),
                isbn10=trunc(isbn10, 16),
                primary_genre=trunc(rec.get("primaryGenre") or "其他", 40),
                genres=trunc(",".join(rec.get("genres") or []), 400),
                tags=trunc(",".join(rec.get("tags") or []), 400),
                short_description_zh=trunc(rec.get("shortDescriptionZh"), 2000),
                full_description_zh=trunc(rec.get("fullDescriptionZh"), 4000),
                audience_zh=trunc(rec.get("audienceHintZh"), 400),
                cover_image=trunc(rec.get("coverImage") or "/covers/placeholder.svg", 300),
                verification_status=trunc(rec.get("verificationStatus") or "pending", 20),
                source_name=trunc(rec.get("sourceName"), 200),
                source_file=trunc(rec.get("sourceFile"), 200),
                source_row=rec.get("sourceRow") or 0,
                selection_reason=trunc(rec.get("selectionReason"), 2000),
            )
            if rec.get("publicationDate"):
                from datetime import date

                try:
                    book.publication_date = date.fromisoformat(rec["publicationDate"][:10])
                except ValueError:
                    pass
            thumb, full = derive_cover_urls(book.cover_image)
            book.cover_thumbnail_url = thumb
            book.cover_full_url = full
            db.add(book)
            slugs.add(slug.lower())
            if isbn13:
                isbns.add(isbn13)
            if isbn10:
                isbns.add(isbn10)
            title_author.add(ta)
            inserted += 1
            if i % 500 == 0:
                db.commit()
                print(f"  {i}/{len(books)} inserted={inserted}", flush=True)
        if not args.dry_run:
            db.commit()
    finally:
        db.close()
    print(f"done: inserted={inserted} skipped={skipped} total={len(books)} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
