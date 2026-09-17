"""Shared language-library listing queries (HTML page + JSON API)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload, load_only

from .config import LANGS
from .cover_urls import (
    cover_thumb_safe,
    cover_thumb_srcset,
    cover_thumb_srcset_avif,
    cover_title_card,
)
from .book_nav import book_href
from .models import Author, Book


@dataclass
class LibraryQuery:
    lang: str
    keyword: str = ""
    genre: str = ""
    sort: str = "year"


def build_library_query(db: Session, spec: LibraryQuery):
    library_q = db.query(Book).filter(Book.language_code == spec.lang)
    if spec.keyword:
        like = f"%{spec.keyword}%"
        author_ids = [a.id for a in db.query(Author).filter(Author.name.ilike(like)).all()]
        filters = [
            Book.original_title.ilike(like),
            Book.chinese_title.ilike(like),
            Book.short_description_zh.ilike(like),
            Book.tags.ilike(like),
            Book.publisher.ilike(like),
        ]
        if author_ids:
            filters.append(Book.author_id.in_(author_ids))
        from sqlalchemy import or_

        library_q = library_q.filter(or_(*filters))
    if spec.genre:
        from sqlalchemy import or_

        library_q = library_q.filter(
            or_(
                Book.primary_genre == spec.genre,
                Book.genres.contains(spec.genre),
                Book.tags.contains(spec.genre),
            )
        )
    if spec.sort == "title":
        library_q = library_q.order_by(Book.original_title.asc(), Book.id.asc())
    elif spec.sort == "new":
        library_q = library_q.order_by(Book.publication_year.desc(), Book.id.desc())
    else:
        library_q = library_q.order_by(Book.publication_year.desc(), Book.original_title.asc())
    return library_q


def fetch_library_slice(db: Session, spec: LibraryQuery, *, offset: int, limit: int):
    library_q = build_library_query(db, spec)
    total = library_q.count()
    offset = max(0, offset)
    limit = max(1, min(limit, 96))
    books = []
    if total:
        books = (
            library_q.options(
                load_only(
                    Book.id,
                    Book.slug,
                    Book.original_title,
                    Book.chinese_title,
                    Book.cover_image,
                    Book.cover_thumbnail_url,
                    Book.cover_full_url,
                    Book.primary_genre,
                    Book.language_code,
                    Book.language_name,
                    Book.publication_year,
                    Book.short_description_zh,
                    Book.editor_quote_zh,
                    Book.author_id,
                ),
                joinedload(Book.author).load_only(Author.id, Author.name),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
    return total, books


def serialize_library_book(
    book: Book,
    *,
    lang: str,
    genre: str,
    q: str,
    sort: str,
    return_to: str,
    index: int,
) -> dict:
    blurb_src = book.short_description_zh or book.editor_quote_zh or ""
    blurb = blurb_src[:90] + ("…" if len(blurb_src) > 90 else "")
    lang_meta = LANGS.get(book.language_code or lang) or {}
    page_hint = (index // 24) + 1
    href = book_href(
        book.slug,
        source="library",
        return_to=return_to,
        lang=lang,
        genre=genre,
        q=q,
        sort=sort,
        page=page_hint,
        scope="library",
    )
    return {
        "slug": book.slug,
        "href": href,
        "title": book.original_title or "",
        "chinese": book.chinese_title or "",
        "author": book.author.name if book.author else "作者待核",
        "year": book.publication_year,
        "genre": book.primary_genre or "",
        "lang": book.language_code or lang,
        "langZh": lang_meta.get("zh") or book.language_name or lang,
        "blurb": blurb,
        "cover": cover_thumb_safe(book),
        "coverFallback": cover_title_card(book),
        "coverAvif": cover_thumb_srcset_avif(book),
        "coverWebp": cover_thumb_srcset(book),
    }
