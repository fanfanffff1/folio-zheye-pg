from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .config import (
    ADMIN_COOKIE, ADMIN_KEY, COVER_MAX_BYTES, EDITOR_COOKIE, EDITOR_KEY, GENRES,
    INFO_SOURCES, REGIONS, STATIC_DIR, SUBMIT_GENRES, SUBMIT_LANGS, UPLOAD_DIR,
)
from .assign import assign_submission, close_editor_task
from .auth import current_user, login_url, public_profile, require_user, decorate_people
from .models import Author, Book, BookSubmission, SessionLocal, SiteNotice, SubmissionAuditLog, User
from .security import (
    html_safe, is_admin, require_csrf, require_staff, submit_rate_ok, user_role,
)

STATUS_LABELS = {
    "draft": "草稿",
    "unassigned": "待分配",
    "pending": "待审核",
    "reviewing": "审核中",
    "needs_changes": "需补充",
    "editor_approve": "编辑建议通过",
    "editor_reject": "编辑建议拒绝",
    "approved": "已通过",
    "rejected": "未通过",
    "withdrawn": "已撤回",
}

CHECK_ITEMS = [
    ("title", "书名是否正确"),
    ("author", "作者是否正确"),
    ("cover", "封面是否匹配"),
    ("pub", "出版信息是否可信"),
    ("isbn", "ISBN是否有效"),
    ("intro", "内容介绍是否与书籍相关"),
    ("ads", "是否包含广告"),
    ("copy", "是否涉嫌抄袭"),
    ("dup", "是否与现有书籍重复"),
    ("lang", "语言和分类是否正确"),
    ("public", "是否适合公开展示"),
]

LANG_MAP = {code: name for code, name in SUBMIT_LANGS}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def intro_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf。，、；：？！“”‘’（）《》【】—…]", text or ""))


def strip_text(value: str, max_len: int = 400) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").replace("\x00", "")).strip()
    lowered = cleaned.lower()
    if "<script" in lowered or "javascript:" in lowered:
        raise HTTPException(400, "内容包含不被允许的脚本。")
    return cleaned[:max_len]


def looks_spam(text: str) -> bool:
    raw = re.sub(r"\s+", "", text or "")
    if len(raw) < 50:
        return False
    chunk = raw[:12]
    return bool(chunk) and raw.count(chunk) >= 4


def isbn_digits(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def isbn_ok(value: str) -> bool:
    digits = isbn_digits(value)
    if not digits:
        return True
    return len(digits) in (10, 13) and bool(re.fullmatch(r"[0-9]{9}[0-9X]|[0-9]{13}", digits))


def year_ok(year: Optional[int]) -> bool:
    if year is None:
        return True
    return 1450 <= year <= datetime.utcnow().year + 1


def completeness_of(row: BookSubmission) -> int:
    fields = [
        row.original_title, row.chinese_title, row.publisher, row.isbn,
        row.language_code, row.region, row.genres, row.tags,
        row.recommendation_reason, row.suitable_readers, row.author_biography,
        row.information_source, row.publication_year and str(row.publication_year),
        row.publication_date,
    ]
    filled = sum(1 for x in fields if str(x or "").strip())
    return int(round(100 * filled / max(len(fields), 1)))


def language_label(row: BookSubmission) -> str:
    if row.language_code == "other":
        return row.language_other or "其他"
    return LANG_MAP.get(row.language_code, row.language_code or "")


def add_log(db: Session, row: BookSubmission, operator: str, action: str, nxt: str, note: str = ""):
    db.add(SubmissionAuditLog(
        submission_id=row.id,
        operator_id=operator,
        action=action,
        previous_status=row.status,
        next_status=nxt,
        note=note[:2000],
    ))


def notify(db: Session, visitor_id: str, submission_id: int, title: str, body: str, kind: str = "info", user_id: Optional[int] = None):
    db.add(SiteNotice(
        visitor_id=visitor_id,
        user_id=user_id,
        submission_id=submission_id,
        title=title,
        body=body,
        kind=kind,
    ))


def next_number(db: Session) -> str:
    year = datetime.utcnow().year
    prefix = f"SUB-{year}-"
    last = (
        db.query(BookSubmission.submission_number)
        .filter(BookSubmission.submission_number.like(f"{prefix}%"))
        .order_by(BookSubmission.submission_number.desc())
        .first()
    )
    n = 1
    if last and last[0]:
        try:
            n = int(last[0].split("-")[-1]) + 1
        except ValueError:
            n = 1
    return f"{prefix}{n:06d}"


def own_or_404(db: Session, sid: int, request: Request) -> BookSubmission:
    row = db.query(BookSubmission).filter(BookSubmission.id == sid).one_or_none()
    user = current_user(request)
    if not row:
        raise HTTPException(404, "没有找到这份投稿。")
    if user and row.user_id == user.id:
        return row
    if not user:
        raise HTTPException(401, "请先登录。")
    raise HTTPException(404, "没有找到这份投稿。")
    return row


def find_duplicates(db: Session, title: str, isbn: str, authors: str):
    hits = []
    digits = isbn_digits(isbn)
    q = db.query(Book)
    if digits:
        found = q.filter(or_(Book.isbn13 == digits, Book.isbn10 == digits, Book.isbn13 == isbn, Book.isbn10 == isbn)).limit(5).all()
        hits.extend(found)
    if title:
        like = f"%{title.strip()}%"
        found = (
            db.query(Book)
            .filter(or_(Book.original_title.ilike(like), Book.chinese_title.ilike(like)))
            .limit(6)
            .all()
        )
        hits.extend(found)
    seen = set()
    unique = []
    for b in hits:
        if b.id in seen:
            continue
        seen.add(b.id)
        unique.append({
            "id": b.id,
            "slug": b.slug,
            "title": b.original_title,
            "chinese": b.chinese_title,
            "cover": b.cover_image,
            "author": b.author.name if b.author else "",
        })
    return unique[:6]


def pack(row: BookSubmission, include_private: bool = False, db: Optional[Session] = None) -> dict:
    data = {
        "id": row.id,
        "submissionNumber": row.submission_number,
        "title": row.title,
        "originalTitle": row.original_title,
        "chineseTitle": row.chinese_title,
        "chineseTitleIsTemporary": row.chinese_title_is_temporary,
        "authors": row.authors,
        "coverUrl": row.cover_url,
        "introduction": row.introduction,
        "recommendationReason": row.recommendation_reason,
        "suitableReaders": row.suitable_readers,
        "authorBiography": row.author_biography,
        "publicationYear": row.publication_year,
        "publicationDate": row.publication_date,
        "publisher": row.publisher,
        "isbn": row.isbn,
        "language": row.language_code,
        "languageOther": row.language_other,
        "languageLabel": language_label(row),
        "region": row.region,
        "genres": [g for g in (row.genres or "").split(",") if g],
        "tags": [t for t in (row.tags or "").split(",") if t],
        "informationSource": row.information_source,
        "informationSourceNote": row.information_source_note,
        "status": row.status,
        "statusLabel": STATUS_LABELS.get(row.status, row.status),
        "publicFeedback": row.public_feedback,
        "completeness": row.completeness,
        "duplicateFlag": row.duplicate_flag,
        "nickname": row.nickname,
        "avatarUrl": "",
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        "submittedAt": row.submitted_at.isoformat() if row.submitted_at else "",
        "approvedBookId": row.approved_book_id,
        "introLen": intro_len(row.introduction),
    }
    if include_private:
        data["contactEmail"] = row.contact_email
        data["internalNotes"] = row.internal_notes
        data["assignedEditor"] = row.assigned_editor
        data["checklist"] = json.loads(row.checklist or "{}")
        data["candidatePool"] = row.candidate_pool
    if db is not None:
        prof = public_profile(db, user_id=row.user_id, nickname=row.nickname)
        data["nickname"] = prof["nickname"]
        data["avatarUrl"] = prof["avatarUrl"]
    return data


def apply_payload(row: BookSubmission, payload: dict, *, draft: bool) -> None:
    title = strip_text(payload.get("title") or "", 150)
    authors = strip_text(payload.get("authors") or payload.get("author") or "", 100)
    intro = (payload.get("introduction") or "").replace("\x00", "").strip()
    if not draft:
        if len(title) < 2 or not re.search(r"[\w\u4e00-\u9fff]", title):
            raise HTTPException(400, "请填写封面上的完整书名。")
        if len(authors) < 2:
            raise HTTPException(400, "请填写作者姓名。")
        if intro_len(intro) < 50:
            raise HTTPException(400, "内容介绍请至少写满 50 个中文字。")
        if len(intro) > 2000:
            raise HTTPException(400, "内容介绍请控制在 2000 字以内。")
        if looks_spam(intro):
            raise HTTPException(400, "介绍看起来像重复粘贴，请用自己的话写一写。")
        if not row.cover_url:
            raise HTTPException(400, "请上传书籍封面。")
        if not payload.get("confirmTruth") or not payload.get("confirmReview"):
            raise HTTPException(400, "请勾选两项确认后再提交。")
    year = payload.get("publicationYear")
    if year in ("", None):
        year = None
    else:
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise HTTPException(400, "出版年份格式不正确。")
        if not year_ok(year):
            raise HTTPException(400, "出版年份超出合理范围。")
    isbn = strip_text(payload.get("isbn") or "", 32)
    if isbn and not isbn_ok(isbn) and not draft:
        raise HTTPException(400, "ISBN 格式看起来不正确。")
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,，、]", tags) if t.strip()]
    tags = [strip_text(t, 15) for t in tags][:5]
    genres = payload.get("genres") or []
    if isinstance(genres, str):
        genres = [g for g in genres.split(",") if g]
    genres = [g for g in genres if g in SUBMIT_GENRES][:8]
    row.title = title
    row.authors = authors
    row.introduction = intro[:2000]
    row.original_title = strip_text(payload.get("originalTitle") or "", 400)
    row.chinese_title = strip_text(payload.get("chineseTitle") or "", 400)
    row.chinese_title_is_temporary = bool(payload.get("chineseTitleIsTemporary"))
    row.recommendation_reason = (payload.get("recommendationReason") or "")[:1000]
    row.suitable_readers = (payload.get("suitableReaders") or "")[:400]
    row.author_biography = (payload.get("authorBiography") or "")[:1000]
    row.publication_year = year
    row.publication_date = strip_text(payload.get("publicationDate") or "", 20)
    row.publisher = strip_text(payload.get("publisher") or "", 200)
    row.isbn = isbn
    lang = strip_text(payload.get("language") or "", 16)
    row.language_code = lang if lang in LANG_MAP else ""
    row.language_other = strip_text(payload.get("languageOther") or "", 80) if row.language_code == "other" else ""
    row.region = strip_text(payload.get("region") or "", 80)
    row.genres = ",".join(genres)
    row.tags = ",".join(tags)
    src = strip_text(payload.get("informationSource") or "", 80)
    row.information_source = src if src in INFO_SOURCES else ""
    row.information_source_note = strip_text(payload.get("informationSourceNote") or "", 400)
    row.completeness = completeness_of(row)
    row.updated_at = datetime.utcnow()


def sniff_image(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise HTTPException(400, "仅支持 JPG、PNG 或 WebP 封面。")


def stamp_submitter(row: BookSubmission, user) -> None:
    row.user_id = user.id
    row.nickname = (user.nickname or user.username or "")[:40]
    row.contact_email = (user.email or "")[:200]


def counts_for(db: Session, user_id: int) -> dict:
    rows = db.query(BookSubmission.status, func.count(BookSubmission.id)).filter(
        BookSubmission.user_id == user_id
    ).group_by(BookSubmission.status).all()
    data = {k: 0 for k in STATUS_LABELS}
    for status, n in rows:
        data[status] = n
    return data


class SubmissionIn(BaseModel):
    title: str = ""
    authors: str = ""
    author: str = ""
    introduction: str = ""
    originalTitle: str = ""
    chineseTitle: str = ""
    chineseTitleIsTemporary: bool = False
    recommendationReason: str = ""
    suitableReaders: str = ""
    authorBiography: str = ""
    publicationYear: Optional[str] = None
    publicationDate: str = ""
    publisher: str = ""
    isbn: str = ""
    language: str = ""
    languageOther: str = ""
    region: str = ""
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    informationSource: str = ""
    informationSourceNote: str = ""
    nickname: str = ""
    contactEmail: str = ""
    confirmTruth: bool = False
    confirmReview: bool = False
    csrf: str = ""
    id: Optional[int] = None


class ReviewIn(BaseModel):
    action: str
    note: str = ""
    internalNotes: str = ""
    assignedEditor: str = ""
    checklist: dict = Field(default_factory=dict)
    publicTitle: str = ""
    publicAuthors: str = ""
    language: str = ""
    genre: str = ""
    catalogOnly: bool = True
    candidatePool: bool = False
    csrf: str = ""


def register(app, templates, base_ctx):
    @app.get("/recommend")
    def recommend_page(request: Request, id: Optional[int] = None, db: Session = Depends(get_db)):
        user = current_user(request)
        if not user:
            return templates.TemplateResponse(
                request,
                "login_needed.html",
                base_ctx(
                    request,
                    title="登录后推荐图书｜FOLIO 折页",
                    description="推荐图书需要登录。",
                    next_url="/recommend",
                    reason="recommend",
                ),
            )
        vid = request.state.visitor_id
        row = None
        if id:
            row = own_or_404(db, id, request)
        else:
            row = (
                db.query(BookSubmission)
                .filter(BookSubmission.user_id == user.id, BookSubmission.status.in_(["draft", "needs_changes"]))
                .order_by(BookSubmission.updated_at.desc())
                .first()
            )
        notices = (
            db.query(SiteNotice)
            .filter(or_(SiteNotice.user_id == user.id, SiteNotice.visitor_id == vid), SiteNotice.is_read.is_(False))
            .order_by(SiteNotice.created_at.desc())
            .limit(6)
            .all()
        )
        return templates.TemplateResponse(
            request,
            "submit.html",
            base_ctx(
                request,
                title="推荐一本好书｜FOLIO 折页",
                description="把打动你的故事分享给更多读者。投稿需经编辑审核，通过后才会进入书籍库。",
                submit_langs=SUBMIT_LANGS,
                submit_genres=SUBMIT_GENRES,
                info_sources=INFO_SOURCES,
                regions=REGIONS,
                draft=pack(row, db=db) if row else None,
                my_counts=counts_for(db, user.id),
                notices=notices,
                current_year=datetime.utcnow().year,
            ),
        )

    @app.get("/recommend/success/{number}")
    def recommend_success(number: str, request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        row = db.query(BookSubmission).filter(
            BookSubmission.submission_number == number,
            BookSubmission.user_id == user.id,
        ).one_or_none()
        if not row:
            raise HTTPException(404)
        return templates.TemplateResponse(
            request,
            "submit_success.html",
            base_ctx(
                request,
                title="推荐已收到｜FOLIO 折页",
                description="编辑会核验你的投稿。审核结果可在我的推荐中查看。",
                row=row,
            ),
        )

    @app.get("/my-recommendations")
    def my_recommendations(request: Request, db: Session = Depends(get_db)):
        if not current_user(request):
            return RedirectResponse(login_url("/account?tab=recs"), status_code=303)
        return RedirectResponse("/account?tab=recs", status_code=303)

    @app.get("/admin/login")
    def admin_login_page(request: Request):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            base_ctx(request, title="编辑登录｜FOLIO 折页", description="编辑与管理员登录审核后台。"),
        )

    @app.post("/admin/login")
    async def admin_login(request: Request):
        form = await request.form()
        key = str(form.get("key") or "")
        require_csrf(request, str(form.get("csrf") or ""))
        resp = RedirectResponse("/admin/submissions", status_code=303)
        if ADMIN_KEY and hmac_eq(key, ADMIN_KEY):
            resp.set_cookie(ADMIN_COOKIE, key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30, path="/")
            return resp
        if EDITOR_KEY and hmac_eq(key, EDITOR_KEY):
            resp.set_cookie(EDITOR_COOKIE, key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30, path="/")
            return resp
        raise HTTPException(403, "密钥不正确。")

    @app.get("/admin/submissions")
    def admin_list(
        request: Request,
        q: str = "",
        status: str = "",
        lang: str = "",
        duplicate: str = "",
        db: Session = Depends(get_db),
    ):
        role = require_staff(request)
        user = current_user(request)
        query = db.query(BookSubmission).filter(BookSubmission.status != "draft")
        if role == "editor" and user:
            query = query.filter(BookSubmission.assigned_editor_id == user.id)
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(or_(
                BookSubmission.submission_number.ilike(like),
                BookSubmission.title.ilike(like),
                BookSubmission.authors.ilike(like),
                BookSubmission.nickname.ilike(like),
                BookSubmission.contact_email.ilike(like),
            ))
        if status:
            query = query.filter(BookSubmission.status == status)
        if lang:
            query = query.filter(BookSubmission.language_code == lang)
        if duplicate == "1":
            query = query.filter(BookSubmission.duplicate_flag.is_(True))
        rows = query.order_by(BookSubmission.submitted_at.desc(), BookSubmission.id.desc()).limit(200).all()
        decorate_people(db, rows)
        today = datetime.utcnow().date()
        month = datetime.utcnow().strftime("%Y-%m")
        stats = {
            "pending": db.query(BookSubmission).filter(BookSubmission.status == "pending").count(),
            "reviewing": db.query(BookSubmission).filter(BookSubmission.status == "reviewing").count(),
            "needs_changes": db.query(BookSubmission).filter(BookSubmission.status == "needs_changes").count(),
            "today": db.query(BookSubmission).filter(BookSubmission.submitted_at.isnot(None)).all(),
        }
        today_n = sum(1 for r in stats["today"] if r.submitted_at and r.submitted_at.date() == today)
        approved_month = db.query(BookSubmission).filter(BookSubmission.status == "approved").all()
        rejected_month = db.query(BookSubmission).filter(BookSubmission.status == "rejected").all()
        return templates.TemplateResponse(
            request,
            "admin_submissions.html",
            base_ctx(
                request,
                title="书籍投稿审核｜FOLIO 折页",
                description="编辑审核读者推荐的书籍。",
                rows=rows,
                labels=STATUS_LABELS,
                q=q,
                status=status,
                lang=lang,
                stats={
                    "pending": stats["pending"],
                    "reviewing": stats["reviewing"],
                    "needs_changes": stats["needs_changes"],
                    "today": today_n,
                    "approved_month": sum(1 for r in approved_month if r.reviewed_at and r.reviewed_at.strftime("%Y-%m") == month),
                    "rejected_month": sum(1 for r in rejected_month if r.reviewed_at and r.reviewed_at.strftime("%Y-%m") == month),
                },
                submit_langs=SUBMIT_LANGS,
            ),
        )

    @app.get("/admin/submissions/{sid}")
    def admin_detail(sid: int, request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        user = current_user(request)
        row = db.query(BookSubmission).filter(BookSubmission.id == sid).one_or_none()
        if not row:
            raise HTTPException(404)
        if user_role(request) == "editor" and user and row.assigned_editor_id != user.id:
            raise HTTPException(403, "只能审核分配给你的投稿。")
        logs = (
            db.query(SubmissionAuditLog)
            .filter(SubmissionAuditLog.submission_id == row.id)
            .order_by(SubmissionAuditLog.created_at.asc())
            .all()
        )
        dups = find_duplicates(db, row.title or row.original_title or row.chinese_title, row.isbn, row.authors)
        return templates.TemplateResponse(
            request,
            "admin_submission_detail.html",
            base_ctx(
                request,
                title=f"审核 {row.submission_number}｜FOLIO 折页",
                description="核验读者投稿并决定是否收录。",
                row=row,
                packed=pack(row, include_private=True, db=db),
                logs=logs,
                duplicates=dups,
                checks=CHECK_ITEMS,
                labels=STATUS_LABELS,
                genres=GENRES,
            ),
        )

    @app.get("/api/submissions/duplicates")
    def api_dups(q: str = "", isbn: str = "", db: Session = Depends(get_db)):
        return {"results": find_duplicates(db, q, isbn, "")}

    @app.post("/api/submissions/cover")
    async def api_cover(
        request: Request,
        file: UploadFile = File(...),
        id: Optional[int] = Form(default=None),
        csrf: str = Form(default=""),
        db: Session = Depends(get_db),
    ):
        require_csrf(request, csrf)
        user = require_user(request)
        data = await file.read()
        if len(data) > COVER_MAX_BYTES:
            raise HTTPException(400, "封面请小于 10MB。")
        if len(data) < 24:
            raise HTTPException(400, "图片文件不完整。")
        ext = sniff_image(data)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{request.state.visitor_id[:8]}-{secrets.token_hex(8)}.{ext}"
        path = UPLOAD_DIR / name
        path.write_bytes(data)
        url = f"/static/uploads/submissions/{name}"
        row = None
        if id:
            row = own_or_404(db, id, request)
            if row.status not in ("draft", "needs_changes"):
                raise HTTPException(400, "当前状态不能更换封面。")
        else:
            row = BookSubmission(
                visitor_id=request.state.visitor_id,
                status="draft",
                submission_number=next_number(db),
            )
            db.add(row)
            db.flush()
            add_log(db, row, request.state.visitor_id, "created", "draft", "创建草稿并上传封面")
        stamp_submitter(row, user)
        row.cover_url = url
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "id": row.id, "coverUrl": url, "submissionNumber": row.submission_number}

    @app.post("/api/submissions/draft")
    def api_draft(payload: SubmissionIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        vid = request.state.visitor_id
        row = None
        if payload.id:
            row = own_or_404(db, payload.id, request)
            if row.status not in ("draft", "needs_changes"):
                raise HTTPException(400, "当前状态不能覆盖保存。")
        else:
            row = BookSubmission(visitor_id=vid, status="draft", submission_number=next_number(db))
            db.add(row)
            db.flush()
            add_log(db, row, vid, "created", "draft")
        apply_payload(row, payload.model_dump(), draft=True)
        stamp_submitter(row, user)
        db.commit()
        return {"ok": True, "id": row.id, "submissionNumber": row.submission_number, "status": row.status}

    @app.post("/api/submissions/submit")
    def api_submit(payload: SubmissionIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        if "@" not in (user.email or ""):
            raise HTTPException(400, "请使用绑定了邮箱的账号登录后再推荐图书。")
        vid = request.state.visitor_id
        recent = (
            db.query(BookSubmission.submitted_at)
            .filter(BookSubmission.user_id == user.id, BookSubmission.submitted_at.isnot(None))
            .all()
        )
        submit_rate_ok(request, [r[0].timestamp() for r in recent if r[0]])
        if payload.id:
            row = own_or_404(db, payload.id, request)
            if row.status not in ("draft", "needs_changes", "rejected", "withdrawn"):
                raise HTTPException(400, "这份投稿正在审核，不能再次覆盖提交。")
        else:
            row = BookSubmission(visitor_id=vid, status="draft", submission_number=next_number(db))
            db.add(row)
            db.flush()
        apply_payload(row, payload.model_dump(), draft=False)
        stamp_submitter(row, user)
        dups = find_duplicates(db, row.title, row.isbn, row.authors)
        row.duplicate_flag = bool(dups)
        prev = row.status
        assign_submission(db, row)
        row.submitted_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        add_log(db, row, vid, "resubmitted" if prev in ("needs_changes", "rejected") else "submitted", row.status, row.assign_reason)
        notify(db, vid, row.id, "推荐已收到", f"投稿编号 {row.submission_number} 已进入审核。", "success", user_id=user.id)
        db.commit()
        return {
            "ok": True,
            "id": row.id,
            "submissionNumber": row.submission_number,
            "duplicates": dups,
            "redirect": f"/recommend/success/{row.submission_number}",
        }

    @app.post("/api/submissions/{sid}/withdraw")
    def api_withdraw(sid: int, payload: ReviewIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        row = own_or_404(db, sid, request)
        if row.status not in ("pending", "unassigned"):
            raise HTTPException(400, "只有待审核或待分配的投稿可以撤回。")
        add_log(db, row, str(user.id), "withdrawn", "withdrawn", payload.note)
        row.status = "withdrawn"
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": row.status}

    @app.post("/api/admin/submissions/{sid}/review")
    def api_review(sid: int, payload: ReviewIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        role = require_staff(request)
        user = current_user(request)
        row = db.query(BookSubmission).filter(BookSubmission.id == sid).one_or_none()
        if not row:
            raise HTTPException(404)
        if role == "editor" and user and row.assigned_editor_id != user.id:
            raise HTTPException(403, "只能审核分配给你的投稿。")
        op = (user.username if user else "staff")
        action = payload.action
        if payload.internalNotes:
            row.internal_notes = payload.internalNotes[:2000]
        if payload.checklist:
            row.checklist = json.dumps(payload.checklist, ensure_ascii=False)
        if action == "reassign" and role == "admin":
            eid = int(payload.assignedEditor or 0) if str(payload.assignedEditor).isdigit() else 0
            editor = db.query(User).filter(User.id == eid, User.role.in_(["editor", "admin"])).one_or_none()
            if not editor:
                raise HTTPException(400, "请选择有效的编辑。")
            row.assigned_editor_id = editor.id
            row.assigned_editor = editor.nickname or editor.username
            row.assigned_at = datetime.utcnow()
            row.assign_reason = "管理员手动分配"
            row.editor_task_status = "open"
            if row.status == "unassigned":
                row.status = "pending"
            add_log(db, row, op, "assigned", row.status, f"editor:{editor.id}")
        elif action == "claim" and role == "admin" and user:
            row.assigned_editor_id = user.id
            row.assigned_editor = user.nickname or user.username
            row.assigned_at = datetime.utcnow()
            row.assign_reason = "管理员亲自审核"
            row.editor_task_status = "open"
            if row.status == "unassigned":
                row.status = "pending"
            row.status = "reviewing"
            add_log(db, row, op, "claimed", "reviewing")
        elif action == "save_notes":
            add_log(db, row, op, "assigned", row.status, "保存内部备注")
        elif action == "start":
            row.status = "reviewing"
            add_log(db, row, op, "review_started", "reviewing")
            notify(db, row.visitor_id, row.id, "开始审核", f"{row.submission_number} 正在核验中。", "info", user_id=row.user_id)
        elif action == "changes":
            if not (payload.note or "").strip():
                raise HTTPException(400, "请填写需要补充的内容。")
            row.status = "needs_changes"
            row.public_feedback = payload.note.strip()[:1000]
            add_log(db, row, op, "changes_requested", "needs_changes", payload.note)
            notify(db, row.visitor_id, row.id, "需要补充资料", row.public_feedback, "warning", user_id=row.user_id)
        elif action == "suggest_approve":
            if role != "editor":
                raise HTTPException(403, "建议通过是编辑操作。")
            row.status = "editor_approve"
            row.public_feedback = (payload.note or "编辑建议通过。")[:1000]
            add_log(db, row, op, "editor_approve", "editor_approve", payload.note)
        elif action == "suggest_reject":
            if role != "editor":
                raise HTTPException(403, "建议拒绝是编辑操作。")
            if not (payload.note or "").strip():
                raise HTTPException(400, "请填写建议拒绝的原因。")
            row.status = "editor_reject"
            row.public_feedback = payload.note.strip()[:1000]
            add_log(db, row, op, "editor_reject", "editor_reject", payload.note)
        elif action == "reject":
            if role != "admin":
                raise HTTPException(403, "只有管理员可以最终拒绝。")
            if not (payload.note or "").strip():
                raise HTTPException(400, "不予通过必须填写原因。")
            row.status = "rejected"
            row.public_feedback = payload.note.strip()[:1000]
            close_editor_task(row)
            add_log(db, row, op, "admin_rejected", "rejected", payload.note)
            notify(db, row.visitor_id, row.id, "这次没有通过审核", row.public_feedback, "error", user_id=row.user_id)
        elif action == "approve":
            if role != "admin":
                raise HTTPException(403, "只有管理员可以最终通过。")
            book = publish_book(db, row, payload)
            row.status = "approved"
            row.approved_book_id = book.id
            row.candidate_pool = bool(payload.candidatePool)
            row.public_feedback = "已收录到书籍库。是否进入本期推荐，由编辑另外决定。"
            close_editor_task(row)
            add_log(db, row, op, "admin_approved", "approved", f"book:{book.slug}")
            notify(db, row.visitor_id, row.id, "审核通过", "你的推荐已进入 FOLIO 书籍库。", "success", user_id=row.user_id)
        elif action == "delete":
            if role != "admin":
                raise HTTPException(403, "只有管理员可以删除投稿。")
            row.status = "withdrawn"
            close_editor_task(row)
            add_log(db, row, op, "withdrawn", "withdrawn", "管理员删除")
        else:
            raise HTTPException(400, "未知审核操作。")
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": row.status, "bookId": row.approved_book_id}

    def hmac_eq(a: str, b: str) -> bool:
        import hmac
        if not a or not b or len(a) != len(b):
            return False
        return hmac.compare_digest(a, b)

    def publish_book(db: Session, row: BookSubmission, payload: ReviewIn) -> Book:
        title = strip_text(payload.publicTitle or row.original_title or row.title, 400)
        authors = strip_text(payload.publicAuthors or row.authors, 200)
        author = db.query(Author).filter(Author.name == authors.split("、")[0]).one_or_none()
        if not author:
            author = Author(name=authors.split("、")[0], localized_name="", biography_zh=row.author_biography)
            db.add(author)
            db.flush()
        lang = payload.language or row.language_code or "en"
        lang_name = LANG_MAP.get(lang, row.language_other or lang)
        code = lang if lang != "other" else "ot"
        digits = isbn_digits(row.isbn)
        slug_base = re.sub(r"[^a-z0-9]+", "-", (title or row.submission_number).lower()).strip("-")[:80] or row.submission_number.lower()
        slug = slug_base
        n = 2
        while db.query(Book).filter(Book.slug == slug).one_or_none():
            slug = f"{slug_base}-{n}"
            n += 1
        genre = payload.genre or (row.genres.split(",")[0] if row.genres else "其他")
        cover = row.cover_url or "/covers/placeholder.svg"
        book = Book(
            slug=slug,
            original_title=title,
            chinese_title=row.chinese_title or (f"{row.title}（暂译）" if row.chinese_title_is_temporary else row.title),
            author_id=author.id,
            language_code=code,
            language_name=lang_name,
            publisher=row.publisher,
            publication_year=row.publication_year,
            isbn13=digits if len(digits) == 13 else "",
            isbn10=digits if len(digits) == 10 else "",
            primary_genre=genre,
            genres=row.genres,
            tags=row.tags,
            short_description_zh=row.introduction[:180],
            full_description_zh=row.introduction,
            recommendation_zh=row.recommendation_reason,
            audience_zh=row.suitable_readers,
            cover_image=cover,
            is_featured=False,
            is_recommended=bool(payload.candidatePool),
            verification_status="partial",
            source_name="读者投稿",
            selection_reason=f"来源投稿 {row.submission_number}",
        )
        db.add(book)
        db.flush()
        return book


def hmac_eq(a: str, b: str) -> bool:
    import hmac
    if not a or not b or len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)
