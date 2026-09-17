"""Book detail navigation context: source, safe return, siblings, breadcrumbs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from sqlalchemy.orm import Session, joinedload

from .config import ISSUE_MONTH, ISSUE_TITLE, ISSUE_YEAR, LANGS, current_issue_slug
from .models import Book


ALLOWED_SOURCES = frozenset({
    "issue", "language", "library", "search", "genre", "favorites", "home", "archive", "direct",
})


def safe_return_path(raw: Optional[str], default: str = "/search") -> str:
    """Only allow same-origin relative paths."""
    if not raw:
        return default
    path = str(raw).strip()
    if not path.startswith("/") or path.startswith("//"):
        return default
    if "://" in path or "\\" in path or path.startswith("/\\"):
        return default
    # Block protocol-relative and control characters
    if any(ord(c) < 32 for c in path):
        return default
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        return default
    return urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))


def book_href(
    slug: str,
    *,
    source: str = "direct",
    return_to: Optional[str] = None,
    **extra,
) -> str:
    src = source if source in ALLOWED_SOURCES else "direct"
    params: dict[str, str] = {"from": src}
    if return_to:
        params["return"] = safe_return_path(return_to, default="/search")
    for key, value in extra.items():
        if value is None or value == "":
            continue
        params[key] = str(value)
    return f"/books/{quote(slug, safe='')}?{urlencode(params)}"


@dataclass
class BookNavContext:
    source: str = "direct"
    return_to: str = "/search"
    back_label: str = "← 返回书籍检索"
    issue: str = ""
    language: str = ""
    genre: str = ""
    keyword: str = ""
    sort: str = ""
    page: str = ""
    scope: str = ""
    crumbs: list[tuple[str, str]] = field(default_factory=list)
    # (label, href) — last crumb is current book (href empty)
    position_label: str = ""
    query_passthrough: str = ""


def parse_book_nav(request_query: dict, book: Book) -> BookNavContext:
    raw_source = (request_query.get("from") or request_query.get("source") or "direct").strip().lower()
    source = raw_source if raw_source in ALLOWED_SOURCES else "direct"

    language = (request_query.get("language") or request_query.get("lang") or "").strip()
    if language and language not in LANGS:
        language = ""

    genre = (request_query.get("genre") or "").strip()
    keyword = (request_query.get("q") or request_query.get("keyword") or "").strip()
    sort = (request_query.get("sort") or "").strip()
    page = (request_query.get("page") or "").strip()
    scope = (request_query.get("scope") or "").strip()
    issue = (request_query.get("issue") or "").strip() or current_issue_slug()

    default_return = {
        "issue": "/recommendations",
        "language": f"/languages/{language or book.language_code}",
        "library": f"/languages/{language or book.language_code}/library",
        "search": "/search",
        "genre": f"/explore?genre={quote(genre)}" if genre else "/explore",
        "favorites": "/account?tab=likes",
        "home": "/",
        "archive": "/archive",
        "direct": "/search",
    }.get(source, "/search")

    return_to = safe_return_path(request_query.get("return"), default=default_return)

    lang_code = language or book.language_code or ""
    lang_meta = LANGS.get(lang_code, {})
    lang_native = lang_meta.get("native") or book.language_name or "语言"
    lang_zh = lang_meta.get("zh") or book.language_name or "语言"

    if source == "issue":
        back_label = "← 返回本期新书"
        crumbs = [("首页", "/"), ("本期新书", return_to), (book.chinese_title or book.original_title, "")]
    elif source == "language":
        back_label = f"← 返回{lang_native}专区"
        crumbs = [("首页", "/"), (lang_native, return_to), (book.chinese_title or book.original_title, "")]
    elif source == "library":
        back_label = f"← 返回{lang_zh}藏书"
        crumbs = [("首页", "/"), (lang_native, f"/languages/{language or book.language_code}"), ("藏书", return_to), (book.chinese_title or book.original_title, "")]
    elif source == "search":
        back_label = "← 返回搜索结果"
        crumbs = [("首页", "/"), ("书籍检索", return_to), (book.chinese_title or book.original_title, "")]
    elif source == "genre":
        gname = genre or book.primary_genre or "类型"
        back_label = f"← 返回{gname}分类"
        crumbs = [("首页", "/"), (gname, return_to), (book.chinese_title or book.original_title, "")]
    elif source == "favorites":
        back_label = "← 返回我的喜欢"
        crumbs = [("首页", "/"), ("我的喜欢", return_to), (book.chinese_title or book.original_title, "")]
    elif source == "home":
        back_label = "← 返回首页"
        crumbs = [("首页", return_to or "/"), (book.chinese_title or book.original_title, "")]
    elif source == "archive":
        back_label = "← 返回往期推荐"
        crumbs = [("首页", "/"), ("往期推荐", return_to), (book.chinese_title or book.original_title, "")]
    else:
        back_label = "← 返回书籍检索"
        crumbs = [("首页", "/"), ("书籍检索", "/search"), (book.chinese_title or book.original_title, "")]

    # Preserve nav params for prev/next links
    passthrough = {
        "from": source,
        "return": return_to,
    }
    if language:
        passthrough["lang"] = language
    if genre:
        passthrough["genre"] = genre
    if keyword:
        passthrough["q"] = keyword
    if sort:
        passthrough["sort"] = sort
    if page:
        passthrough["page"] = page
    if scope:
        passthrough["scope"] = scope
    if issue and source == "issue":
        passthrough["issue"] = issue

    return BookNavContext(
        source=source,
        return_to=return_to,
        back_label=back_label,
        issue=issue,
        language=language,
        genre=genre,
        keyword=keyword,
        sort=sort,
        page=page,
        scope=scope,
        crumbs=crumbs,
        query_passthrough=urlencode(passthrough),
    )


def _featured_all(db: Session, lang: str | None = None) -> list[Book]:
    q = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.is_featured.is_(True))
    )
    if lang:
        q = q.filter(Book.language_code == lang)
    return q.order_by(Book.language_code.asc(), Book.featured_rank.asc(), Book.id.asc()).all()


def resolve_siblings(
    db: Session,
    book: Book,
    ctx: BookNavContext,
    *,
    favorite_ids: Optional[list[int]] = None,
) -> list[Book]:
    source = ctx.source
    lang = ctx.language  # only when explicitly provided in the entry context

    if source == "issue":
        return _featured_all(db, lang or None)

    if source == "language":
        code = lang or book.language_code
        return (
            db.query(Book)
            .options(joinedload(Book.author))
            .filter(Book.is_featured.is_(True), Book.language_code == code)
            .order_by(Book.featured_rank.asc(), Book.id.asc())
            .limit(8)
            .all()
        )

    if source == "library":
        code = lang or book.language_code
        q = db.query(Book).options(joinedload(Book.author)).filter(Book.language_code == code)
        if ctx.genre:
            q = q.filter(
                (Book.primary_genre == ctx.genre)
                | Book.genres.contains(ctx.genre)
                | Book.tags.contains(ctx.genre)
            )
        if ctx.keyword:
            like = f"%{ctx.keyword}%"
            q = q.filter(
                Book.original_title.ilike(like)
                | Book.chinese_title.ilike(like)
                | Book.short_description_zh.ilike(like)
            )
        if ctx.sort == "title":
            q = q.order_by(Book.original_title.asc(), Book.id.asc())
        elif ctx.sort == "new":
            q = q.order_by(Book.publication_year.desc(), Book.id.desc())
        else:
            q = q.order_by(Book.publication_year.desc(), Book.original_title.asc())
        return q.limit(100).all()

    if source == "search":
        from sqlalchemy import or_

        q = db.query(Book).options(joinedload(Book.author))
        if ctx.keyword:
            like = f"%{ctx.keyword}%"
            q = q.filter(
                or_(
                    Book.original_title.ilike(like),
                    Book.chinese_title.ilike(like),
                    Book.short_description_zh.ilike(like),
                    Book.tags.ilike(like),
                )
            )
        if ctx.language:
            q = q.filter(Book.language_code == ctx.language)
        if ctx.genre:
            q = q.filter(
                (Book.primary_genre == ctx.genre)
                | Book.genres.contains(ctx.genre)
            )
        return q.order_by(Book.publication_year.desc(), Book.id.desc()).limit(100).all()

    if source == "genre":
        g = ctx.genre or book.primary_genre
        return (
            db.query(Book)
            .options(joinedload(Book.author))
            .filter(Book.is_recommended.is_(True))
            .filter((Book.primary_genre == g) | Book.genres.contains(g))
            .order_by(Book.language_code.asc(), Book.featured_rank.asc())
            .limit(100)
            .all()
        )

    if source == "favorites":
        if not favorite_ids:
            return [book]
        rows = (
            db.query(Book)
            .options(joinedload(Book.author))
            .filter(Book.id.in_(favorite_ids))
            .all()
        )
        by_id = {b.id: b for b in rows}
        ordered = [by_id[i] for i in favorite_ids if i in by_id]
        return ordered or [book]

    if source == "home":
        return _featured_all(db, "en")[:8]

    if source == "archive":
        return _featured_all(db, ctx.language or None)

    # direct / fallback: featured shelf of same language
    if book.is_featured:
        return _featured_all(db, book.language_code)
    return (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.language_code == book.language_code)
        .order_by(Book.publication_year.desc(), Book.id.asc())
        .limit(24)
        .all()
    )


def position_label(ctx: BookNavContext, index: int, total: int) -> str:
    if total <= 0 or index < 0:
        return ""
    n = index + 1
    if ctx.source == "issue":
        if ctx.language:
            return f"本期第 {n:02d} / {total} 本"
        return f"本期第 {n:02d} / {total} 本"
    if ctx.source == "language":
        return f"本月推荐第 {n:02d} / {total} 本"
    if ctx.source == "library":
        return f"藏书第 {n:02d} / {total} 本"
    if ctx.source == "search":
        return f"检索第 {n:02d} / {total} 本"
    if ctx.source == "genre":
        return f"分类第 {n:02d} / {total} 本"
    if ctx.source == "favorites":
        return f"喜欢第 {n:02d} / {total} 本"
    if total > 1:
        return f"第 {n:02d} / {total} 本"
    return ""


def current_issue_label() -> str:
    return f"{ISSUE_YEAR}年{ISSUE_MONTH}月本期新书"


def query_dict_from_request(request) -> dict:
    # Flatten multi-values: take first
    out = {}
    for key, value in request.query_params.multi_items():
        if key not in out:
            out[key] = value
    return out
