from __future__ import annotations

from urllib.parse import quote
from datetime import datetime
from typing import Optional
import re
import shutil

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload, load_only

from .config import (
    AVATAR_DIR, CONTACT_EMAIL, GENRES, ISSUE_MONTH, ISSUE_PICK_GENRES, ISSUE_TITLE, ISSUE_YEAR,
    LANGS, LANG_ZONE_GENRES, MONTH_EN, PERSIST_DIR, SITE_NAME, SITE_TAGLINE, STATIC_DIR,
    TEMPLATE_DIR, UPLOAD_DIR, current_issue_slug,
)
from .auth import attach_auth, bootstrap_admin, current_user, decorate_people, get_or_create_guest, profile_from_user, profiles_for, promote_owner_admin, public_profile
from .moderation import auto_review, publish_clean_pending
from .models import (
    Author, Book, BookFavorite, BookSubmission, Comment, CommentLike, CommentReport, Issue, Notification, Rating,
    SessionLocal, init_db,
)
from .security import (
    clean_comment, get_or_set_visitor, html_safe, rate_limit, require_csrf,
    require_staff, user_role,
)
from .accounts import register as register_accounts
from .submissions import register as register_submissions

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["e"] = html_safe
templates.env.filters["urlencode"] = lambda value: quote(str(value or ""), safe="")
from .book_nav import book_href as _book_href
from .cover_urls import (
    cover_card_sizes as _cover_card_sizes,
    cover_full as _cover_full,
    cover_full_avif as _cover_full_avif,
    cover_list_sizes as _cover_list_sizes,
    cover_thumb as _cover_thumb,
    cover_thumb_srcset as _cover_thumb_srcset,
    cover_thumb_srcset_avif as _cover_thumb_srcset_avif,
)
templates.env.globals["book_href"] = _book_href
templates.env.globals["cover_thumb"] = _cover_thumb
templates.env.globals["cover_full"] = _cover_full
templates.env.globals["cover_full_avif"] = _cover_full_avif
templates.env.globals["cover_thumb_srcset"] = _cover_thumb_srcset
templates.env.globals["cover_thumb_srcset_avif"] = _cover_thumb_srcset_avif
templates.env.globals["cover_list_sizes"] = _cover_list_sizes
templates.env.globals["cover_card_sizes"] = _cover_card_sizes
def _migrate_legacy_uploads() -> None:
    for name in ("avatars", "submissions"):
        src = STATIC_DIR / "uploads" / name
        dst = PERSIST_DIR / "uploads" / name
        dst.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            continue
        for item in src.iterdir():
            if item.is_file() and not (dst / item.name).exists():
                shutil.copy2(item, dst / item.name)


PERSIST_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
_migrate_legacy_uploads()
app.mount("/static/uploads", StaticFiles(directory=str(PERSIST_DIR / "uploads")), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/covers", StaticFiles(directory=str(STATIC_DIR / "covers")), name="covers")


@app.exception_handler(StarletteHTTPException)
async def html_http_exception(request: Request, exc: StarletteHTTPException):
    accept = request.headers.get("accept", "")
    wants_json = "application/json" in accept and "text/html" not in accept
    if (
        exc.status_code in (403, 404)
        and not request.url.path.startswith("/api/")
        and not wants_json
    ):
        tpl = "403.html" if exc.status_code == 403 else "404.html"
        title = "没有权限｜FOLIO 折页" if exc.status_code == 403 else "未找到｜FOLIO 折页"
        desc = "没有权限访问这个页面。" if exc.status_code == 403 else "没有找到这本书或这个页面。"
        return templates.TemplateResponse(
            request,
            tpl,
            base_ctx(request, title=title, description=desc),
            status_code=exc.status_code,
        )
    return await http_exception_handler(request, exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def nav_current(request: Request) -> str:
    path = request.url.path
    if path.startswith("/account") or path.startswith("/login") or path.startswith("/register"):
        return "account"
    if path.startswith("/search"):
        return "search"
    if path.startswith("/archive"):
        return "archive"
    # Check /recommendations before /recommend — the latter is a prefix of the former.
    if path.startswith("/recommendations") or path.startswith("/books") or path.startswith("/explore"):
        return "issue"
    if path == "/recommend" or path.startswith("/recommend/") or path.startswith("/my-recommendations"):
        return "submit"
    if path.startswith("/admin") or path.startswith("/studio") or path.startswith("/editor"):
        return "admin"
    if path == "/":
        return "home"
    return ""


def page_kind(request: Request) -> str:
    path = request.url.path
    if path == "/":
        return "home"
    if path.startswith("/books/"):
        return "book"
    if path.startswith("/languages/") and path.rstrip("/").endswith("/library"):
        return "lang-lib"
    if path.startswith("/languages/"):
        return "lang"
    if path.startswith("/recommendations"):
        return "issue"
    if path.startswith("/login") or path.startswith("/register") or path.startswith("/forgot") or path.startswith("/editor/login") or path.startswith("/editor/apply"):
        return "auth"
    if path.startswith("/account"):
        return "account"
    return "inner"


def clip_blurb(text: str, lo: int = 55, hi: int = 80) -> str:
    raw = re.sub(r"\s+", "", (text or "").strip())
    if not raw:
        return ""
    if len(raw) <= hi:
        return raw
    chunk = raw[:hi]
    for mark in ("。", "！", "？", "；", "，"):
        idx = chunk.rfind(mark)
        if idx >= lo - 1:
            return chunk[: idx + 1]
    return chunk.rstrip("，、；：") + "…"


def as_paragraphs(text: str):
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"\n+", raw) if p.strip()]
    if len(parts) == 1 and len(parts[0]) > 90:
        grouped, buf = [], ""
        for chunk in re.split(r"(?<=。)", parts[0]):
            if not chunk.strip():
                continue
            buf += chunk
            if len(buf) >= 72:
                grouped.append(buf.strip())
                buf = ""
        if buf.strip():
            grouped.append(buf.strip())
        return grouped or parts
    return parts


def as_points(text: str):
    raw = (text or "").strip()
    if not raw:
        return []
    for sep in ["。", "；", ";", "、"]:
        if sep in raw:
            return [item.strip("。；;、 ") for item in raw.split(sep) if item.strip("。；;、 ")]
    return [raw]


def dist_rows_from(summary: dict):
    total = summary.get("count") or 0
    rows = []
    for n in [5, 4, 3, 2, 1]:
        count = (summary.get("distribution") or {}).get(n, 0)
        pct = int(round(count / total * 100)) if total else 0
        rows.append({"n": n, "c": count, "pct": pct})
    return rows


def related_books(db: Session, book: Book, limit: int = 6):
    q = db.query(Book).options(joinedload(Book.author)).filter(Book.id != book.id)
    if book.author_id:
        q = q.filter(or_(
            Book.language_code == book.language_code,
            Book.primary_genre == book.primary_genre,
            Book.author_id == book.author_id,
        ))
    else:
        q = q.filter(or_(
            Book.language_code == book.language_code,
            Book.primary_genre == book.primary_genre,
        ))
    return q.order_by(Book.is_featured.desc(), Book.featured_rank.asc(), Book.id.asc()).limit(limit).all()


def base_ctx(request: Request, **extra):
    ctx = {
        "request": request,
        "site_name": SITE_NAME,
        "tagline": SITE_TAGLINE,
        "issue_title": ISSUE_TITLE,
        "issue_year": ISSUE_YEAR,
        "issue_month": ISSUE_MONTH,
        "month_en": MONTH_EN.get(ISSUE_MONTH, ""),
        "langs": LANGS,
        "genres": GENRES,
        "email": CONTACT_EMAIL,
        "now": datetime.utcnow(),
        "nav_current": nav_current(request),
        "page_kind": page_kind(request),
        "csrf": getattr(request.state, "csrf", "") or request.cookies.get("folio_csrf") or "",
        "role": user_role(request),
        "current_user": getattr(request.state, "user", None),
        "guest_name": getattr(getattr(request.state, "guest", None), "display_name", "") or "",
        "favorite_ids": getattr(request.state, "favorite_ids", set()) or set(),
        "favorite_counts": getattr(request.state, "favorite_counts", {}) or {},
        "login_next": str(request.url.path) + (("?" + request.url.query) if request.url.query else ""),
    }
    ctx.update(extra)
    return ctx


@app.middleware("http")
async def visitor_mw(request: Request, call_next):
    path = request.url.path
    # Static assets must not open Neon on every CSS/JS/image request.
    if (
        path.startswith("/static/")
        or path.startswith("/covers/")
        or path in {"/healthz", "/robots.txt", "/favicon.ico"}
    ):
        response = await call_next(request)
        if path.startswith("/static/") or path.startswith("/covers/"):
            if path.endswith((".webp", ".jpg", ".jpeg", ".png", ".svg", ".woff2")):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers.setdefault("Cache-Control", "public, max-age=86400, stale-while-revalidate=604800")
        return response
    dummy = Response()
    vid = get_or_set_visitor(request, dummy)
    request.state.visitor_id = vid
    attach_auth(request, dummy)
    response = await call_next(request)
    for header, value in dummy.raw_headers:
        if header.lower() == b"set-cookie":
            response.raw_headers.append((header, value))
    return response


@app.on_event("startup")
def startup():
    init_db()
    bootstrap_admin()
    promote_owner_admin()
    db = SessionLocal()
    try:
        if db.query(Book).filter(Book.is_featured.is_(True)).count() == 0:
            from .seed import seed
            from .config import catalog_path
            if catalog_path("cleaned-books.json").exists():
                db.close()
                seed()
                db = SessionLocal()
        publish_clean_pending(db)
    finally:
        db.close()
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "covers").mkdir(parents=True, exist_ok=True)
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)


def featured_books(db: Session, lang: str | None = None, limit: int | None = None):
    q = db.query(Book).options(joinedload(Book.author)).filter(Book.is_featured.is_(True))
    if lang:
        q = q.filter(Book.language_code == lang)
    q = q.order_by(Book.featured_rank.asc(), Book.id.asc())
    if limit:
        q = q.limit(limit)
    return q.all()


def rating_summary(db: Session, book_id: int, visitor_id: str | None = None) -> dict:
    rows = db.query(Rating.score).filter(Rating.book_id == book_id).all()
    scores = [r[0] for r in rows]
    dist = {i: 0 for i in range(1, 6)}
    for s in scores:
        if 1 <= s <= 5:
            dist[s] += 1
    mine = None
    if visitor_id:
        mine_row = db.query(Rating).filter(Rating.book_id == book_id, Rating.visitor_id == visitor_id).one_or_none()
        mine = mine_row.score if mine_row else None
    avg = round(sum(scores) / len(scores), 1) if scores else None
    return {"count": len(scores), "average": avg, "distribution": dist, "mine": mine}


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    featured_all = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.is_featured.is_(True))
        .order_by(Book.language_code.asc(), Book.featured_rank.asc(), Book.id.asc())
        .all()
    )
    by_lang: dict[str, list] = {code: [] for code in LANGS}
    for book in featured_all:
        bucket = by_lang.get(book.language_code)
        if bucket is not None and len(bucket) < 8:
            bucket.append(book)
    english = by_lang.get("en", [])[:8]
    others = []
    lang_cards = []
    for code, meta in LANGS.items():
        books = by_lang.get(code, [])
        n = len(books)
        lang_cards.append({"code": code, "meta": meta, "count": n})
        if code != "en":
            others.append({"code": code, "meta": meta, "books": books[:4]})
    genre_counts = (
        db.query(Book.primary_genre, func.count(Book.id))
        .group_by(Book.primary_genre)
        .order_by(func.count(Book.id).desc())
        .all()
    )
    recent = (
        db.query(Comment)
        .filter(Comment.status == "published", Comment.deleted_at.is_(None), Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
        .limit(6)
        .all()
    )
    book_ids = {c.book_id for c in recent}
    books_by_id = {
        b.id: b for b in db.query(Book).filter(Book.id.in_(book_ids)).all()
    } if book_ids else {}
    recent_view = []
    for c in recent:
        book = books_by_id.get(c.book_id)
        if book:
            recent_view.append({"comment": c, "book": book})
    decorate_people(db, [item["comment"] for item in recent_view])
    top_rated = []
    rated = db.query(Rating.book_id, func.avg(Rating.score), func.count(Rating.id)).group_by(Rating.book_id).having(func.count(Rating.id) >= 1).all()
    rated_sorted = sorted(rated, key=lambda x: (-x[1], -x[2]))[:6]
    rated_ids = [book_id for book_id, _, _ in rated_sorted]
    rated_books = {
        b.id: b for b in db.query(Book).filter(Book.id.in_(rated_ids)).all()
    } if rated_ids else {}
    for book_id, avg, n in rated_sorted:
        b = rated_books.get(book_id)
        if b:
            top_rated.append({"book": b, "avg": round(avg, 1), "n": n})
    return templates.TemplateResponse(
        request,
        "home.html",
        base_ctx(
            request,
            title="FOLIO 折页 · 二〇二六年九月号",
            description="以英文原版新书为轴的多语种荐读杂志。本期六种语言各八本2026年新书。",
            english=english,
            others=others,
            lang_cards=lang_cards,
            genre_counts=genre_counts,
            recent_view=recent_view,
            top_rated=top_rated,
        ),
    )


@app.get("/recommendations")
def recommendations_hub(
    request: Request,
    genre: str = "",
    lang: str = "",
    db: Session = Depends(get_db),
):
    featured_all = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.is_featured.is_(True))
        .order_by(Book.language_code.asc(), Book.featured_rank.asc(), Book.id.asc())
        .all()
    )
    by_lang: dict[str, list] = {code: [] for code in LANGS}
    for book in featured_all:
        bucket = by_lang.get(book.language_code)
        if bucket is not None and len(bucket) < 8:
            bucket.append(book)

    genre_value = (genre or "").strip()
    lang_value = (lang or "").strip()
    if lang_value and lang_value not in LANGS:
        raise HTTPException(404)

    cards = []
    num = 0
    lang_iter = ((lang_value, LANGS[lang_value]),) if lang_value else LANGS.items()
    for code, meta in lang_iter:
        books = by_lang.get(code, [])
        if genre_value:
            books = [
                b for b in books
                if genre_value == b.primary_genre
                or genre_value in (b.genres or "")
                or genre_value in (b.tags or "")
            ]
        for idx, book in enumerate(books, start=1):
            num += 1
            blurb_src = book.short_description_zh or book.full_description_zh or book.editor_quote_zh or ""
            cards.append({
                "book": book,
                "num": num,
                "blurb": clip_blurb(blurb_src),
                "tags": (book.tag_list() or ([book.primary_genre] if book.primary_genre else []))[:3],
                "editor_pick": idx == 1 and not genre_value and not lang_value and code == "en",
            })

    pick_total = sum(len(by_lang.get(code, [])) for code in ( [lang_value] if lang_value else LANGS ))
    return templates.TemplateResponse(
        request,
        "recommendations.html",
        base_ctx(
            request,
            title=f"本期新书推荐 · {ISSUE_TITLE}",
            description="六种语言本期经过出版时间核验的原版新书。",
            cards=cards,
            pick_total=pick_total,
            active_genre=genre_value,
            active_lang=lang_value,
            pick_genres=ISSUE_PICK_GENRES,
            month_label=f"{MONTH_EN.get(ISSUE_MONTH, '')} {ISSUE_YEAR}",
            issue_slug=current_issue_slug(),
        ),
    )


@app.get("/languages/{lang}/library")
def language_library(
    lang: str,
    request: Request,
    q: str = "",
    genre: str = "",
    sort: str = "year",
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    if lang not in LANGS:
        raise HTTPException(404)
    from .library_query import LibraryQuery, fetch_library_slice, serialize_library_book
    from .cover_urls import COVER_LIST_SIZES
    import json as _json

    meta = LANGS[lang]
    keyword = (q or "").strip()
    genre_value = (genre or "").strip()
    sort_value = (sort or "year").strip() or "year"
    chunk = 48
    spec = LibraryQuery(lang=lang, keyword=keyword, genre=genre_value, sort=sort_value)
    total, books = fetch_library_slice(db, spec, offset=0, limit=chunk)
    lang_total = (
        db.query(Book).filter(Book.language_code == lang).count()
        if (keyword or genre_value)
        else total
    )
    return_path = str(request.url.path)
    if request.url.query:
        return_path = f"{return_path}?{request.url.query}"
    bootstrap = [
        serialize_library_book(
            book,
            lang=lang,
            genre=genre_value,
            q=keyword,
            sort=sort_value,
            return_to=return_path,
            index=i,
        )
        for i, book in enumerate(books)
    ]
    return templates.TemplateResponse(
        request,
        "language_library.html",
        base_ctx(
            request,
            title=f"{meta['zh']}藏书 · {meta['native']}｜FOLIO 折页",
            description=f"浏览全部{meta['zh']}原版藏书。",
            lang=lang,
            lang_meta=meta,
            library_total=total,
            library_lang_total=lang_total,
            library_q=keyword,
            library_genre=genre_value,
            library_sort=sort_value,
            library_bootstrap_json=_json.dumps(bootstrap, ensure_ascii=False),
            library_chunk=chunk,
            zone_genres=LANG_ZONE_GENRES,
            issue_slug=current_issue_slug(),
            cover_list_sizes_value=COVER_LIST_SIZES,
        ),
    )


@app.get("/api/languages/{lang}/library")
def api_language_library(
    lang: str,
    request: Request,
    q: str = "",
    genre: str = "",
    sort: str = "year",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=48, ge=1, le=96),
    db: Session = Depends(get_db),
):
    if lang not in LANGS:
        raise HTTPException(404)
    from .library_query import LibraryQuery, fetch_library_slice, serialize_library_book
    from urllib.parse import urlencode

    keyword = (q or "").strip()
    genre_value = (genre or "").strip()
    sort_value = (sort or "year").strip() or "year"
    spec = LibraryQuery(lang=lang, keyword=keyword, genre=genre_value, sort=sort_value)
    total, books = fetch_library_slice(db, spec, offset=offset, limit=limit)
    qs = urlencode(
        {k: v for k, v in {"q": keyword, "genre": genre_value, "sort": sort_value}.items() if v}
    )
    return_path = f"/languages/{lang}/library" + (f"?{qs}" if qs else "")
    items = [
        serialize_library_book(
            book,
            lang=lang,
            genre=genre_value,
            q=keyword,
            sort=sort_value,
            return_to=return_path,
            index=offset + i,
        )
        for i, book in enumerate(books)
    ]
    return {
        "lang": lang,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@app.get("/languages/{lang}")
def language_zone(lang: str, request: Request, db: Session = Depends(get_db)):
    if lang not in LANGS:
        raise HTTPException(404)
    meta = LANGS[lang]
    # Zone homepage shows this month's eight featured books — not the full library.
    books = featured_books(db, lang, 8)
    picks = []
    for book in books:
        blurb_src = book.short_description_zh or book.full_description_zh or book.editor_quote_zh or ""
        tags = book.tag_list() or ([book.primary_genre] if book.primary_genre else [])
        picks.append({
            "book": book,
            "blurb": clip_blurb(blurb_src, lo=48, hi=72),
            "tags": tags[:3],
        })
    issue_slug = current_issue_slug()
    return templates.TemplateResponse(
        request,
        "language.html",
        base_ctx(
            request,
            title=f"{meta['native']} · {meta['zone_zh']}｜FOLIO 折页",
            description=meta["intro_short"] or meta["intro"],
            lang=lang,
            lang_meta=meta,
            picks=picks,
            month_label=f"{MONTH_EN.get(ISSUE_MONTH, '')} {ISSUE_YEAR}",
            month_short=f"{MONTH_EN.get(ISSUE_MONTH, '')[:3]} {ISSUE_YEAR}",
            issue_slug=issue_slug,
            og_image=str(request.base_url).rstrip("/") + meta["cover"],
        ),
    )


@app.get("/recommendations/{lang}/{issue}")
def issue_recommendations(
    lang: str,
    issue: str,
    request: Request,
    genre: str = "",
    db: Session = Depends(get_db),
):
    if lang not in LANGS:
        raise HTTPException(404)
    if issue != current_issue_slug():
        raise HTTPException(404)
    meta = LANGS[lang]
    picks = featured_books(db, lang, 8)
    genre_value = (genre or "").strip()
    visible = picks
    if genre_value:
        visible = [
            b for b in picks
            if genre_value == b.primary_genre
            or genre_value in (b.genres or "")
            or genre_value in (b.tags or "")
        ]
    cards = []
    for idx, book in enumerate(visible, start=1):
        blurb_src = book.short_description_zh or book.full_description_zh or book.editor_quote_zh or ""
        cards.append({
            "book": book,
            "num": idx,
            "blurb": clip_blurb(blurb_src),
            "tags": (book.tag_list() or ([book.primary_genre] if book.primary_genre else []))[:3],
            "editor_pick": False,
        })
    if not genre_value and picks and cards:
        first_id = picks[0].id
        for card in cards:
            card["editor_pick"] = card["book"].id == first_id

    return templates.TemplateResponse(
        request,
        "issue.html",
        base_ctx(
            request,
            title=f"本期{meta['zh']}新书 · {ISSUE_TITLE}｜FOLIO 折页",
            description=f"八本{ISSUE_YEAR}年首次出版的{meta['zh']}原版作品总览。",
            lang=lang,
            lang_meta=meta,
            issue_slug=issue,
            month_label=f"{MONTH_EN.get(ISSUE_MONTH, '')} {ISSUE_YEAR}",
            cards=cards,
            pick_total=len(picks),
            active_genre=genre_value,
            pick_genres=ISSUE_PICK_GENRES,
            og_image=str(request.base_url).rstrip("/") + meta["cover"],
        ),
    )


@app.get("/recommendations/{lang}")
def recommendations_lang_redirect(lang: str):
    if lang not in LANGS:
        raise HTTPException(404)
    return RedirectResponse(f"/languages/{lang}", status_code=303)


def _book_recommender(db: Session, book: Book) -> Optional[dict]:
    row = (
        db.query(BookSubmission)
        .filter(BookSubmission.approved_book_id == book.id)
        .order_by(BookSubmission.id.desc())
        .first()
    )
    if not row:
        return None
    return public_profile(db, user_id=row.user_id, nickname=row.nickname)


@app.get("/issues/{issue}")
def issue_slug_redirect(issue: str, language: str = "", genre: str = ""):
    """Alias route: /issues/2026-09 → /recommendations with optional filters."""
    if issue != current_issue_slug():
        raise HTTPException(404)
    qs = []
    if language:
        qs.append(f"lang={quote(language)}")
    if genre:
        qs.append(f"genre={quote(genre)}")
    dest = "/recommendations" + (("?" + "&".join(qs)) if qs else "")
    return RedirectResponse(dest, status_code=303)


@app.get("/books/{slug}")
def book_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    from .book_nav import parse_book_nav, position_label, query_dict_from_request, resolve_siblings, current_issue_label

    book = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.slug == slug)
        .one_or_none()
    )
    if not book:
        raise HTTPException(404)

    nav = parse_book_nav(query_dict_from_request(request), book)
    fav_order: list[int] | None = None
    if nav.source == "favorites":
        user = getattr(request.state, "user", None)
        if user:
            fav_order = [
                row.book_id
                for row in (
                    db.query(BookFavorite)
                    .filter(BookFavorite.user_id == user.id)
                    .order_by(BookFavorite.created_at.desc())
                    .all()
                )
            ]
    siblings = resolve_siblings(db, book, nav, favorite_ids=fav_order)
    if not any(b.id == book.id for b in siblings):
        siblings = [book] + [b for b in siblings if b.id != book.id]
    idx = next((i for i, b in enumerate(siblings) if b.id == book.id), 0)
    prev_b = siblings[idx - 1] if idx > 0 else None
    next_b = siblings[idx + 1] if idx + 1 < len(siblings) else None
    nav.position_label = position_label(nav, idx, len(siblings))

    summary = rating_summary(db, book.id, request.state.visitor_id)
    chinese = book.chinese_title or book.original_title
    host = str(request.base_url).rstrip("/")
    cover = book.cover_image or ""
    og_image = cover if cover.startswith("http") else (host + cover if cover else "")
    lang_meta = LANGS.get(book.language_code, {})
    return templates.TemplateResponse(
        request,
        "book.html",
        base_ctx(
            request,
            title=f"《{chinese}》书籍介绍与读者评价｜FOLIO 折页",
            description=(book.short_description_zh or book.full_description_zh or f"了解{chinese}的出版信息、内容简介、推荐理由与读者讨论。")[:160],
            book=book,
            summary=summary,
            dist_rows=dist_rows_from(summary),
            prev_b=prev_b,
            next_b=next_b,
            related=related_books(db, book),
            synopsis_paras=as_paragraphs(book.full_description_zh),
            reason_paras=as_paragraphs(book.recommendation_zh),
            audience_points=as_points(book.audience_zh),
            author_paras=as_paragraphs(book.author.biography_zh if book.author else ""),
            title_status=(
                "temporary" if "暂译" in (book.chinese_title or "")
                else "official" if book.chinese_title else "missing"
            ),
            verification_note=(
                "书名、作者、出版社和出版日期已经核对。"
                if book.verification_status == "verified"
                else "部分信息仍待核对。"
                if book.verification_status == "partial"
                else "出版信息待核对。"
            ),
            csrf=getattr(request.state, "csrf", "") or request.cookies.get("folio_csrf") or "",
            visitor_id=request.state.visitor_id,
            favorited=book.id in (getattr(request.state, "favorite_ids", set()) or set()),
            og_image=og_image,
            og_type="book",
            recommender=_book_recommender(db, book),
            nav=nav,
            issue_label=current_issue_label(),
            issue_href=f"/recommendations",
            lang_zone_href=f"/languages/{book.language_code}",
            book_genres=book.genre_list() or ([book.primary_genre] if book.primary_genre else []),
        ),
    )


@app.get("/explore")
def explore(request: Request, genre: str = "", db: Session = Depends(get_db)):
    q = db.query(Book).filter(Book.is_recommended.is_(True))
    if genre:
        q = q.filter(or_(Book.primary_genre == genre, Book.genres.contains(genre)))
    books = q.order_by(Book.language_code, Book.featured_rank).all()
    return templates.TemplateResponse(
        request,
        "explore.html",
        base_ctx(
            request,
            title=f"按类型浏览 · {genre or '全部'}",
            description="按标准化类型浏览本期推荐图书。",
            books=books,
            active_genre=genre,
        ),
    )


@app.get("/archive")
def archive(
    request: Request,
    year: Optional[str] = Query(default=None),
    month: Optional[str] = Query(default=None),
    lang: str = "",
    genre: str = "",
    db: Session = Depends(get_db),
):
    def to_int(value: Optional[str]):
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    year_n = to_int(year)
    month_n = to_int(month)
    q = db.query(Book).filter(Book.is_recommended.is_(True), Book.issue_id.isnot(None))
    if year_n or month_n:
        q = q.join(Issue, Book.issue_id == Issue.id)
        if year_n:
            q = q.filter(Issue.year == year_n)
        if month_n:
            q = q.filter(Issue.month == month_n)
    if lang:
        q = q.filter(Book.language_code == lang)
    if genre:
        q = q.filter(or_(Book.primary_genre == genre, Book.genres.contains(genre)))
    books = q.order_by(Book.language_code, Book.featured_rank, Book.id).all()
    if not books:
        if (year_n and year_n != ISSUE_YEAR) or (month_n and month_n != ISSUE_MONTH):
            empty_reason = "尚无该期书单。目前仅发布 2026 年 9 月号。"
        else:
            empty_reason = "这一期还没有可展示的书单。"
    else:
        empty_reason = ""
    return templates.TemplateResponse(
        request,
        "archive.html",
        base_ctx(
            request,
            title="往期推荐",
            description="按年份与月份归档的编辑荐读书单。",
            books=books,
            year=year_n or ISSUE_YEAR,
            month=month_n or ISSUE_MONTH,
            lang=lang,
            genre=genre,
            empty_reason=empty_reason,
            current_only=not (year_n or month_n) or (year_n == ISSUE_YEAR and (not month_n or month_n == ISSUE_MONTH)),
        ),
    )


@app.get("/search")
def search(
    request: Request,
    q: str = "",
    lang: str = "",
    language: str = "",
    genre: str = "",
    year: Optional[str] = Query(default=None),
    recommended: str = "",
    sort: str = "year",
    db: Session = Depends(get_db),
):
    from .models import Author
    query = db.query(Book)
    keyword = (q or "").strip()
    lang = (lang or language or "").strip()
    year_value = None
    raw_year = (year or "").strip()
    if raw_year:
        try:
            year_value = int(raw_year)
        except ValueError:
            year_value = None
    if keyword:
        like = f"%{keyword}%"
        author_ids = [a.id for a in db.query(Author).filter(Author.name.ilike(like)).all()]
        filters = [
            Book.original_title.ilike(like),
            Book.chinese_title.ilike(like),
            Book.isbn13.ilike(like),
            Book.isbn10.ilike(like),
            Book.short_description_zh.ilike(like),
            Book.full_description_zh.ilike(like),
            Book.tags.ilike(like),
            Book.publisher.ilike(like),
        ]
        if author_ids:
            filters.append(Book.author_id.in_(author_ids))
        query = query.filter(or_(*filters))
    if lang:
        query = query.filter(Book.language_code == lang)
    if genre:
        query = query.filter(or_(Book.primary_genre == genre, Book.genres.contains(genre), Book.tags.contains(genre)))
    if year_value:
        query = query.filter(Book.publication_year == year_value)
    if recommended == "1":
        query = query.filter(Book.is_recommended.is_(True))
    elif recommended == "0":
        query = query.filter(Book.is_recommended.is_(False))
    if sort == "title":
        query = query.order_by(Book.original_title.asc())
    elif sort == "rating":
        query = query.outerjoin(Rating).group_by(Book.id).order_by(func.avg(Rating.score).desc(), Book.publication_year.desc())
    else:
        query = query.order_by(Book.publication_year.desc(), Book.original_title.asc())
    # Allow browsing a whole language shelf without a keyword.
    need_keyword = not keyword and not lang
    if need_keyword:
        books = []
    else:
        books = query.options(joinedload(Book.author)).limit(200).all()
    summaries = {b.id: rating_summary(db, b.id) for b in books[:80]}
    empty_message = "请输入书名、作者、ISBN 或关键词后再检索。出版年、语言和类型都是可选项。"
    if lang and not keyword and not books:
        empty_message = f"暂无{LANGS.get(lang, {}).get('zh', '')}藏书。"
    elif keyword and not books:
        empty_message = "没有符合条件的书。试试只保留关键词，或去掉年份等筛选。"
    return templates.TemplateResponse(
        request,
        "search.html",
        base_ctx(
            request,
            title=("英语藏书检索｜FOLIO 折页" if lang == "en" and not keyword else "高级搜索｜FOLIO 折页"),
            description="检索全部已整理原版书目与正式推荐。",
            books=books,
            q=keyword,
            lang=lang,
            genre=genre,
            year=raw_year,
            recommended=recommended,
            sort=sort,
            summaries=summaries,
            years=list(range(2026, 1999, -1)),
            empty_message=empty_message,
            need_keyword=need_keyword,
        ),
    )


class RatingIn(BaseModel):
    score: int = Field(ge=1, le=5)
    csrf: str = ""


class CommentIn(BaseModel):
    nickname: str = ""
    content: str
    parent_id: Optional[int] = None
    spoiler: bool = False
    csrf: str = ""


@app.get("/api/books/{slug}/ratings")
def api_ratings(slug: str, request: Request, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.slug == slug).one_or_none()
    if not book:
        raise HTTPException(404)
    return rating_summary(db, book.id, request.state.visitor_id)


@app.post("/api/books/{slug}/ratings")
def api_rate(slug: str, payload: RatingIn, request: Request, db: Session = Depends(get_db)):
    require_csrf(request, payload.csrf)
    rate_limit(request, "rate")
    book = db.query(Book).filter(Book.slug == slug).one_or_none()
    if not book:
        raise HTTPException(404)
    vid = request.state.visitor_id
    row = db.query(Rating).filter(Rating.book_id == book.id, Rating.visitor_id == vid).one_or_none()
    if row:
        row.score = payload.score
        row.updated_at = datetime.utcnow()
    else:
        db.add(Rating(book_id=book.id, visitor_id=vid, score=payload.score))
    db.commit()
    return rating_summary(db, book.id, vid)


@app.get("/api/books/{slug}/comments")
def api_comments(
    slug: str,
    request: Request,
    sort: str = "newest",
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    book = db.query(Book).filter(Book.slug == slug).one_or_none()
    if not book:
        raise HTTPException(404)
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    vid = request.state.visitor_id
    user = current_user(request)
    own = [Comment.visitor_id == vid]
    if user:
        own.append(Comment.user_id == user.id)
    visible = or_(
        Comment.status.in_(["published", "approved"]),
        and_(Comment.status == "pending", or_(*own)),
    )
    q = db.query(Comment).filter(
        Comment.book_id == book.id, Comment.parent_id.is_(None),
        Comment.deleted_at.is_(None), visible,
    )
    if sort == "oldest":
        q = q.order_by(Comment.created_at.asc())
    elif sort == "popular":
        q = q.order_by(Comment.like_count.desc(), Comment.created_at.desc())
    else:
        q = q.order_by(Comment.created_at.desc())
    total = q.count()
    roots = q.offset(offset).limit(limit).all()
    liked = {
        x.comment_id for x in db.query(CommentLike).filter(CommentLike.visitor_id == vid).all()
    }
    reply_rows = []
    for c in roots:
        reply_rows.extend(
            db.query(Comment)
            .filter(Comment.parent_id == c.id, Comment.deleted_at.is_(None), visible)
            .order_by(Comment.created_at.asc())
            .all()
        )
    users = profiles_for(db, [c.user_id for c in roots] + [r.user_id for r in reply_rows])

    def unpack(text: str):
        spoiler = (text or "").startswith("[剧透]")
        body = (text or "")[3:].lstrip() if spoiler else (text or "")
        return spoiler, body

    def person(c: Comment):
        if c.user_id and users.get(c.user_id):
            return profile_from_user(users[c.user_id], c.nickname)
        return public_profile(db, user_id=c.user_id, guest_id=c.guest_identity_id, nickname=c.nickname)

    def pack(c: Comment, replies=None):
        spoiler, body = unpack(c.content)
        if replies is None:
            replies = [r for r in reply_rows if r.parent_id == c.id]
        packed_replies = []
        for r in replies:
            rs, rb = unpack(r.content)
            rp = person(r)
            packed_replies.append({
                "id": r.id,
                "nickname": rp["nickname"],
                "avatarUrl": rp["avatarUrl"],
                "content": rb,
                "containsSpoiler": rs,
                "createdAt": r.created_at.isoformat(),
                "likeCount": r.like_count,
                "liked": r.id in liked,
                "mine": r.visitor_id == vid or (user and r.user_id == user.id),
                "status": r.status,
            })
        p = person(c)
        return {
            "id": c.id,
            "nickname": p["nickname"],
            "avatarUrl": p["avatarUrl"],
            "content": body,
            "containsSpoiler": spoiler,
            "createdAt": c.created_at.isoformat(),
            "likeCount": c.like_count,
            "liked": c.id in liked,
            "mine": c.visitor_id == vid or (user and c.user_id == user.id),
            "status": c.status,
            "replies": packed_replies,
        }

    return {"comments": [pack(c) for c in roots], "total": total, "offset": offset, "hasMore": offset + len(roots) < total}


@app.post("/api/books/{slug}/comments")
def api_comment(slug: str, payload: CommentIn, request: Request, db: Session = Depends(get_db)):
    require_csrf(request, payload.csrf)
    rate_limit(request, "comment")
    book = db.query(Book).filter(Book.slug == slug).one_or_none()
    if not book:
        raise HTTPException(404)
    user = current_user(request)
    dummy = Response()
    guest = None if user else get_or_create_guest(db, request, dummy)
    nick = user.nickname if user else guest.display_name
    avatar = user.avatar_url if user else ""
    content = clean_comment(payload.content)
    if payload.spoiler and not content.startswith("[剧透]"):
        content = "[剧透] " + content
    parent = None
    if payload.parent_id:
        parent = db.query(Comment).filter(Comment.id == payload.parent_id, Comment.book_id == book.id).one_or_none()
        if not parent or parent.parent_id is not None:
            raise HTTPException(400, "只能回复一层评论。")
        if parent.status not in ("published", "approved") or parent.deleted_at:
            raise HTTPException(400, "原评论不可回复。")
    verdict = auto_review(content)
    row = Comment(
        book_id=book.id,
        visitor_id=request.state.visitor_id,
        user_id=user.id if user else None,
        guest_identity_id=None if user else guest.id,
        nickname=nick,
        content=content,
        parent_id=parent.id if parent else None,
        status=verdict["status"],
    )
    db.add(row)
    if parent and parent.user_id and (not user or parent.user_id != user.id) and verdict["status"] == "published":
        db.add(Notification(
            user_id=parent.user_id,
            type="reply",
            actor_name=nick,
            book_id=book.id,
            comment_id=row.id,
            title="有人回复了你",
            message=content[:200],
        ))
    db.commit()
    payload_out = {
        "ok": True,
        "id": row.id,
        "status": row.status,
        "nickname": nick,
        "avatarUrl": avatar,
        "message": verdict["message"],
    }
    resp = JSONResponse(payload_out)
    for header, value in dummy.raw_headers:
        if header.lower() == b"set-cookie":
            resp.raw_headers.append((header, value))
    return resp


@app.post("/api/comments/{cid}/like")
async def api_like(cid: int, request: Request, db: Session = Depends(get_db)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    csrf = body.get("csrf") or request.headers.get("x-csrf-token") or ""
    require_csrf(request, csrf)
    rate_limit(request, "like")
    comment = db.query(Comment).filter(Comment.id == cid, Comment.deleted_at.is_(None)).one_or_none()
    if not comment:
        raise HTTPException(404)
    vid = request.state.visitor_id
    existing = db.query(CommentLike).filter(CommentLike.comment_id == cid, CommentLike.visitor_id == vid).one_or_none()
    if existing:
        db.delete(existing)
        comment.like_count = max(0, comment.like_count - 1)
        liked = False
    else:
        db.add(CommentLike(comment_id=cid, visitor_id=vid))
        comment.like_count += 1
        liked = True
    db.commit()
    return {"liked": liked, "likeCount": comment.like_count}


@app.post("/api/comments/{cid}/like-json")
async def api_like_json(cid: int, request: Request, db: Session = Depends(get_db)):
    return await api_like(cid, request, db)


@app.post("/api/comments/{cid}/delete")
async def api_delete(cid: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    require_csrf(request, body.get("csrf", ""))
    comment = db.query(Comment).filter(Comment.id == cid).one_or_none()
    if not comment:
        raise HTTPException(404)
    user = current_user(request)
    own = comment.visitor_id == request.state.visitor_id or (user and comment.user_id == user.id)
    if not own and user_role(request) not in ("admin", "editor"):
        raise HTTPException(403, "不能删除他人评论。")
    comment.deleted_at = datetime.utcnow()
    comment.status = "deleted"
    db.commit()
    return {"ok": True}


@app.post("/api/comments/{cid}/edit")
async def api_edit(cid: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    require_csrf(request, body.get("csrf", ""))
    comment = db.query(Comment).filter(Comment.id == cid, Comment.deleted_at.is_(None)).one_or_none()
    if not comment:
        raise HTTPException(404)
    user = current_user(request)
    own = comment.visitor_id == request.state.visitor_id or (user and comment.user_id == user.id)
    if not own:
        raise HTTPException(403, "不能编辑他人评论。")
    comment.content = clean_comment(body.get("content") or "")
    verdict = auto_review(comment.content)
    comment.status = verdict["status"]
    comment.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "content": comment.content, "status": comment.status, "message": verdict["message"]}


@app.post("/api/comments/{cid}/report")
async def api_report(cid: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    require_csrf(request, body.get("csrf", ""))
    rate_limit(request, "report")
    comment = db.query(Comment).filter(Comment.id == cid).one_or_none()
    if not comment:
        raise HTTPException(404)
    db.add(CommentReport(
        comment_id=cid,
        visitor_id=request.state.visitor_id,
        reason=(body.get("reason") or "")[:200],
    ))
    comment.status = "flagged"
    db.commit()
    return {"ok": True}


@app.post("/api/admin/comments/{cid}/moderate")
async def api_moderate(cid: int, request: Request, db: Session = Depends(get_db)):
    require_staff(request)
    body = await request.json()
    comment = db.query(Comment).filter(Comment.id == cid).one_or_none()
    if not comment:
        raise HTTPException(404)
    action = body.get("action")
    if action == "approve":
        comment.status = "published"
        comment.deleted_at = None
    elif action == "hide":
        comment.status = "hidden"
    elif action == "restore":
        comment.status = "published"
        comment.deleted_at = None
    elif action == "delete":
        comment.status = "deleted"
        comment.deleted_at = datetime.utcnow()
    else:
        raise HTTPException(400)
    db.commit()
    return {"ok": True, "status": comment.status}


@app.get("/api/search/suggest")
def search_suggest(q: str = "", db: Session = Depends(get_db)):
    keyword = (q or "").strip()
    if len(keyword) < 1:
        return {"results": []}
    like = f"%{keyword}%"
    from .models import Author
    author_ids = [a.id for a in db.query(Author).filter(Author.name.ilike(like)).limit(8).all()]
    filters = [
        Book.original_title.ilike(like),
        Book.chinese_title.ilike(like),
        Book.isbn13.ilike(like),
        Book.isbn10.ilike(like),
        Book.tags.ilike(like),
        Book.primary_genre.ilike(like),
        Book.language_name.ilike(like),
        Book.language_code.ilike(like),
    ]
    if author_ids:
        filters.append(Book.author_id.in_(author_ids))
    books = db.query(Book).filter(or_(*filters)).order_by(Book.is_featured.desc(), Book.id.desc()).limit(8).all()
    return {
        "results": [
            {
                "slug": b.slug,
                "title": b.original_title,
                "chinese": b.chinese_title,
                "cover": _cover_thumb(b),
            }
            for b in books
        ]
    }


@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n")


@app.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    host = str(request.base_url).rstrip("/")
    urls = ["/", "/recommendations", "/search", "/archive", "/explore", "/recommend"]
    for code in LANGS:
        urls.append(f"/languages/{code}")
        urls.append(f"/languages/{code}/library")
        urls.append(f"/recommendations/{code}/{current_issue_slug()}")
    for b in db.query(Book.slug).all():
        urls.append(f"/books/{b[0]}")
    xml = ['<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"<url><loc>{host}{u}</loc></url>")
    xml.append("</urlset>")
    return Response("".join(xml), media_type="application/xml")


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    n = db.query(func.count(Book.id)).scalar()
    return {"ok": True, "books": n}


register_submissions(app, templates, base_ctx)
register_accounts(app, templates, base_ctx)
