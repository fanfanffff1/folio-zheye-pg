from __future__ import annotations

from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from PIL import Image, ImageOps
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import (
    clear_session_cookie, create_session, current_user, device_label,
    find_login_user, find_trusted_device, get_or_create_guest,
    hash_password, invalidate_favorite_counts, require_user, revoke_session, safe_next, set_session_cookie,
    staff_home, token_hash, trust_device, trusted_device_count, validate_email, validate_nickname,
    validate_password, validate_username, verify_password, decorate_people,
)
from .config import ADMIN_DEVICE_LIMIT, AVATAR_DIR, STATIC_DIR, is_owner_admin_email
from .models import (
    AuthDevice, Book, BookFavorite, BookSubmission, Comment, DeviceChallenge,
    EditorApplication, Notification, SessionLocal, User,
)
from .object_store import (
    avatar_object_key,
    delete_object,
    key_from_public_or_local_url,
    persist_user_upload,
)
from .security import rate_limit, require_admin, require_csrf, require_staff, user_role
from .submissions import STATUS_LABELS

COMMENT_LABELS = {
    "pending": "待审核",
    "published": "已公开",
    "approved": "已公开",
    "hidden": "已隐藏",
    "deleted": "已删除",
    "flagged": "已举报",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def compress_avatar(data: bytes, max_side: int = 512) -> tuple[bytes, str]:
    """Resize and recompress uploaded avatars before disk write."""
    try:
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
    except Exception as exc:
        raise HTTPException(400, "无法读取头像图片。") from exc
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGB", im.size, (255, 253, 247))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True, progressive=True)
    out = buf.getvalue()
    if not out:
        raise HTTPException(400, "头像压缩失败。")
    return out, "jpg"


def register(app, templates, base_ctx):
    @app.get("/login")
    def login_page(request: Request, next: str = "/"):
        if current_user(request):
            return RedirectResponse(safe_next(next), status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            base_ctx(
                request,
                title="登录｜FOLIO 折页",
                description="登录 FOLIO 折页，收藏书籍并推荐图书。",
                next_url=safe_next(next),
                error="",
            ),
        )

    @app.post("/login")
    async def login_post(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        rate_limit(request, "login")
        next_url = safe_next(str(form.get("next") or "/"))
        ident = str(form.get("identifier") or "")
        password = str(form.get("password") or "")
        remember = str(form.get("remember") or "") in ("1", "on", "true")
        user = find_login_user(db, ident)
        ok = user and user.status == "active" and verify_password(password, user.password_hash)
        if not ok:
            return templates.TemplateResponse(
                request,
                "login.html",
                base_ctx(
                    request,
                    title="登录｜FOLIO 折页",
                    description="登录 FOLIO 折页。",
                    next_url=next_url,
                    error="账号或密码不正确。",
                ),
                status_code=400,
            )
        secret = getattr(request.state, "device_secret", "") or ""
        device_id = None
        if user.role == "admin":
            if not secret:
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    base_ctx(request, title="登录｜FOLIO 折页", description="", next_url=next_url, error="请允许浏览器保存登录设备后再试。"),
                    status_code=400,
                )
            trusted = find_trusted_device(db, user, secret)
            if trusted:
                trusted.last_seen_at = datetime.utcnow()
                device_id = trusted.id
            elif trusted_device_count(db, user.id) == 0:
                trusted = trust_device(db, user, secret, device_label(request))
                device_id = trusted.id
            else:
                challenge = DeviceChallenge(
                    user_id=user.id,
                    token_hash=token_hash(secret),
                    label=device_label(request),
                    status="pending",
                )
                db.add(challenge)
                db.commit()
                return templates.TemplateResponse(
                    request,
                    "device_pending.html",
                    base_ctx(
                        request,
                        title="等待本机验证｜FOLIO 折页",
                        description="新设备需要在已信任的电脑上确认。",
                        challenge=challenge,
                    ),
                )
            if user.role == "admin" and (not next_url or next_url in ("/", "/login", "/account")):
                next_url = staff_home("admin")
            elif user.role == "editor" and (not next_url or next_url in ("/", "/login", "/account")):
                next_url = staff_home("editor")
        token = create_session(db, user, remember, device_id)
        db.commit()
        resp = RedirectResponse(next_url, status_code=303)
        set_session_cookie(request, resp, token, remember)
        return resp

    @app.get("/register")
    def register_page(request: Request, next: str = "/"):
        if current_user(request):
            return RedirectResponse(safe_next(next), status_code=303)
        return templates.TemplateResponse(
            request,
            "register.html",
            base_ctx(
                request,
                title="创建账号｜FOLIO 折页",
                description="创建 FOLIO 折页账号。",
                next_url=safe_next(next),
                error="",
            ),
        )

    @app.post("/register")
    async def register_post(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        rate_limit(request, "register")
        next_url = safe_next(str(form.get("next") or "/account"))
        try:
            username = validate_username(str(form.get("username") or ""))
            nickname = validate_nickname(str(form.get("nickname") or ""))
            email = validate_email(str(form.get("email") or ""))
            password = validate_password(str(form.get("password") or ""), str(form.get("confirm") or ""))
        except HTTPException as exc:
            return templates.TemplateResponse(
                request,
                "register.html",
                base_ctx(request, title="创建账号｜FOLIO 折页", description="", next_url=next_url, error=str(exc.detail)),
                status_code=400,
            )
        if db.query(User).filter(User.username == username).first():
            err = "用户名已被使用。"
        elif db.query(User).filter(User.email == email).first():
            err = "邮箱已被注册。"
        else:
            err = ""
        if err:
            return templates.TemplateResponse(
                request,
                "register.html",
                base_ctx(request, title="创建账号｜FOLIO 折页", description="", next_url=next_url, error=err),
                status_code=400,
            )
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            nickname=nickname,
            role="admin" if is_owner_admin_email(email) else "user",
            status="active",
        )
        db.add(user)
        db.flush()
        device_id = None
        secret = getattr(request.state, "device_secret", "") or ""
        if user.role == "admin" and secret:
            trusted = trust_device(db, user, secret, device_label(request))
            device_id = trusted.id
            if not next_url or next_url in ("/", "/login", "/account", "/register"):
                next_url = staff_home("admin")
        token = create_session(db, user, False, device_id)
        db.commit()
        resp = RedirectResponse(next_url, status_code=303)
        set_session_cookie(request, resp, token, False)
        return resp

    @app.get("/forgot-password")
    def forgot_page(request: Request):
        return templates.TemplateResponse(
            request,
            "forgot.html",
            base_ctx(
                request,
                title="忘记密码｜FOLIO 折页",
                description="密码重置尚未接入邮件服务。",
            ),
        )

    @app.post("/logout")
    async def logout(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        revoke_session(db, getattr(request.state, "session_token", None))
        db.commit()
        resp = RedirectResponse("/", status_code=303)
        clear_session_cookie(resp)
        return resp

    @app.get("/account")
    def account(request: Request, tab: str = "recs", db: Session = Depends(get_db)):
        user = current_user(request)
        if not user:
            return RedirectResponse("/login?next=" + quote("/account"), status_code=303)
        recs = (
            db.query(BookSubmission)
            .filter(BookSubmission.user_id == user.id)
            .order_by(BookSubmission.updated_at.desc())
            .all()
        )
        favs = (
            db.query(Book)
            .join(BookFavorite, BookFavorite.book_id == Book.id)
            .filter(BookFavorite.user_id == user.id)
            .order_by(BookFavorite.created_at.desc())
            .all()
        )
        comments = (
            db.query(Comment)
            .filter(Comment.user_id == user.id)
            .order_by(Comment.created_at.desc())
            .limit(80)
            .all()
        )
        decorate_people(db, comments)
        decorate_people(db, recs)
        replies = (
            db.query(Notification)
            .filter(Notification.user_id == user.id, Notification.type.in_(("reply", "place_review")))
            .order_by(Notification.created_at.desc())
            .limit(80)
            .all()
        )
        books = {b.id: b for b in db.query(Book).filter(Book.id.in_([c.book_id for c in comments] or [0])).all()}
        return templates.TemplateResponse(
            request,
            "account.html",
            base_ctx(
                request,
                title="个人中心｜FOLIO 折页",
                description="查看推荐、收藏、评论与账号设置。",
                tab=tab if tab in ("recs", "likes", "comments", "replies", "settings") else "recs",
                recs=recs,
                favs=favs,
                comments=comments,
                replies=replies,
                books=books,
                labels=STATUS_LABELS,
                comment_labels=COMMENT_LABELS,
            ),
        )

    @app.post("/api/account/profile")
    async def api_profile(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        rate_limit(request, "profile")
        row = db.query(User).filter(User.id == user.id).one()
        if body.get("nickname"):
            row.nickname = validate_nickname(str(body.get("nickname")))
        if body.get("password"):
            if not verify_password(str(body.get("old_password") or ""), row.password_hash):
                raise HTTPException(400, "当前密码不正确。")
            row.password_hash = hash_password(validate_password(str(body.get("password")), str(body.get("confirm") or body.get("password"))))
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "nickname": row.nickname}

    @app.post("/api/account/avatar")
    async def api_avatar(
        request: Request,
        file: UploadFile = File(...),
        csrf: str = Form(default=""),
        db: Session = Depends(get_db),
    ):
        user = require_user(request)
        require_csrf(request, csrf)
        rate_limit(request, "avatar")
        data = await file.read()
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(400, "头像请小于 2MB。")
        if not (
            data[:3] == b"\xff\xd8\xff"
            or data[:8] == b"\x89PNG\r\n\x1a\n"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        ):
            raise HTTPException(400, "头像仅支持 JPG、PNG 或 WebP。")
        compressed, ext = compress_avatar(data)
        # Versioned filename so CDN/browser caches refresh after re-upload.
        name = f"u{user.id}-{int(datetime.utcnow().timestamp())}.{ext}"
        row = db.query(User).filter(User.id == user.id).one()
        old_url = (row.avatar_url or "").strip()

        try:
            avatar_url = persist_user_upload(
                "avatars",
                name,
                compressed,
                local_dir=AVATAR_DIR,
                content_type="image/jpeg",
            )
        except Exception as exc:
            raise HTTPException(502, "头像上传失败，请稍后重试。") from exc

        # Best-effort cleanup of previous object / local file.
        old_key = key_from_public_or_local_url(old_url, "avatars")
        if old_key and old_key != avatar_object_key(name):
            delete_object(old_key)
        if old_url.startswith("/static/uploads/avatars/"):
            old_name = old_url.rsplit("/", 1)[-1]
            if old_name and old_name != name:
                try:
                    (AVATAR_DIR / old_name).unlink(missing_ok=True)
                except OSError:
                    pass
        for stale in AVATAR_DIR.glob(f"u{user.id}-*"):
            if stale.name != name:
                try:
                    stale.unlink()
                except OSError:
                    pass

        row.avatar_url = avatar_url
        row.updated_at = datetime.utcnow()
        db.commit()
        accept = request.headers.get("accept", "")
        if "text/html" in accept and "application/json" not in accept.split(",")[0]:
            return RedirectResponse("/account?tab=settings", status_code=303)
        return {"ok": True, "avatarUrl": row.avatar_url, "bytes": len(compressed)}

    @app.get("/api/guest/identity")
    def api_guest(request: Request, db: Session = Depends(get_db)):
        dummy = Response()
        guest = get_or_create_guest(db, request, dummy)
        resp = JSONResponse({"displayName": guest.display_name, "id": guest.public_id})
        for header, value in dummy.raw_headers:
            if header.lower() == b"set-cookie":
                resp.raw_headers.append((header, value))
        return resp

    @app.post("/api/books/{slug}/favorite")
    async def api_favorite(slug: str, request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        require_csrf(request, body.get("csrf") or request.headers.get("x-csrf-token") or "")
        book = db.query(Book).filter(Book.slug == slug).one_or_none()
        if not book:
            raise HTTPException(404)
        existing = (
            db.query(BookFavorite)
            .filter(BookFavorite.user_id == user.id, BookFavorite.book_id == book.id)
            .one_or_none()
        )
        if existing:
            db.delete(existing)
            favorited = False
        else:
            db.add(BookFavorite(user_id=user.id, book_id=book.id))
            favorited = True
        db.commit()
        invalidate_favorite_counts()
        like_count = (
            db.query(func.count(BookFavorite.id)).filter(BookFavorite.book_id == book.id).scalar() or 0
        )
        return {"favorited": favorited, "likeCount": int(like_count)}

    @app.get("/editor/login")
    def editor_login_page(request: Request, next: str = ""):
        user = current_user(request)
        if user and user.role in ("admin", "editor"):
            return RedirectResponse(staff_home(user.role), status_code=303)
        dest = next or "/editor/workbench"
        return templates.TemplateResponse(
            request,
            "login.html",
            base_ctx(
                request,
                title="编辑 / 管理员登录｜FOLIO 折页",
                description="编辑与管理员登录工作台。",
                next_url=safe_next(dest),
                error="",
                staff_login=True,
            ),
        )

    @app.post("/editor/login")
    async def editor_login_post(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        rate_limit(request, "login")
        ident = str(form.get("identifier") or "")
        password = str(form.get("password") or "")
        remember = str(form.get("remember") or "") in ("1", "on", "true")
        user = find_login_user(db, ident)
        ok = user and user.status == "active" and verify_password(password, user.password_hash)
        if not ok:
            return templates.TemplateResponse(
                request,
                "login.html",
                base_ctx(request, title="编辑 / 管理员登录｜FOLIO 折页", description="", next_url="/editor/workbench", error="账号或密码不正确。", staff_login=True),
                status_code=400,
            )
        if user.role not in ("admin", "editor"):
            return templates.TemplateResponse(
                request,
                "login.html",
                base_ctx(
                    request,
                    title="编辑 / 管理员登录｜FOLIO 折页",
                    description="",
                    next_url="/editor/workbench",
                    error="这个账号还没有编辑权限。请先用普通登录提交编辑申请。",
                    staff_login=True,
                ),
                status_code=403,
            )
        secret = getattr(request.state, "device_secret", "") or ""
        device_id = None
        if user.role == "admin":
            trusted = find_trusted_device(db, user, secret) if secret else None
            if trusted:
                trusted.last_seen_at = datetime.utcnow()
                device_id = trusted.id
            elif trusted_device_count(db, user.id) == 0 and secret:
                trusted = trust_device(db, user, secret, device_label(request))
                device_id = trusted.id
            else:
                challenge = DeviceChallenge(
                    user_id=user.id,
                    token_hash=token_hash(secret),
                    label=device_label(request),
                    status="pending",
                )
                db.add(challenge)
                db.commit()
                return templates.TemplateResponse(
                    request,
                    "device_pending.html",
                    base_ctx(request, title="等待本机验证｜FOLIO 折页", description="", challenge=challenge),
                )
        token = create_session(db, user, remember, device_id)
        db.commit()
        resp = RedirectResponse(staff_home(user.role), status_code=303)
        set_session_cookie(request, resp, token, remember)
        return resp

    @app.get("/studio")
    @app.get("/editor/workbench")
    def editor_workbench(request: Request, tab: str = "all", db: Session = Depends(get_db)):
        user = current_user(request)
        role = user_role(request)
        if not user and role != "admin":
            return RedirectResponse("/editor/login?next=/editor/workbench", status_code=303)
        if user and user.role not in ("admin", "editor") and role not in ("admin", "editor"):
            raise HTTPException(403, "没有编辑权限。")
        if (user and user.role == "admin" or role == "admin") and request.url.path == "/studio":
            return RedirectResponse("/admin/dashboard", status_code=303)
        q = db.query(BookSubmission).filter(BookSubmission.status != "draft")
        if user and user.role == "editor":
            q = q.filter(BookSubmission.assigned_editor_id == user.id)
        rows = q.order_by(BookSubmission.updated_at.desc()).limit(200).all()
        buckets = {
            "all": rows,
            "pending": [r for r in rows if r.status in ("pending", "unassigned")],
            "reviewing": [r for r in rows if r.status == "reviewing"],
            "needs_changes": [r for r in rows if r.status == "needs_changes"],
            "done": [r for r in rows if r.editor_task_status == "done" or r.status in ("approved", "rejected")],
        }
        current = buckets.get(tab, rows)
        decorate_people(db, current)
        return templates.TemplateResponse(
            request,
            "editor_workbench.html",
            base_ctx(
                request,
                title="编辑工作台｜FOLIO 折页",
                description="处理分配给你的图书推荐。",
                rows=current,
                tab=tab,
                counts={k: len(v) for k, v in buckets.items()},
                labels=STATUS_LABELS,
            ),
        )

    @app.get("/admin/dashboard")
    def admin_dashboard(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        role = user_role(request)
        if not user and role != "admin":
            return RedirectResponse("/editor/login?next=/admin/dashboard", status_code=303)
        if role != "admin":
            raise HTTPException(403, "编辑不能进入管理员页面。")
        rows = (
            db.query(BookSubmission)
            .filter(BookSubmission.status != "draft")
            .order_by(BookSubmission.updated_at.desc())
            .limit(200)
            .all()
        )
        decorate_people(db, rows)
        editors = db.query(User).filter(User.role.in_(["editor", "admin"]), User.status == "active").all()
        pending_apps = db.query(EditorApplication).filter(EditorApplication.status == "pending").count()
        from .models import TourMap
        pending_tours = (
            db.query(TourMap)
            .filter(TourMap.status == "pending", TourMap.deleted_at.is_(None))
            .order_by(TourMap.updated_at.asc())
            .limit(50)
            .all()
        )
        if user:
            trusted_devices = trusted_device_count(db, user.id)
            pending_devices = (
                db.query(DeviceChallenge)
                .filter(DeviceChallenge.user_id == user.id, DeviceChallenge.status == "pending")
                .count()
            )
        else:
            trusted_devices = db.query(AuthDevice).filter(AuthDevice.status == "trusted").count()
            pending_devices = db.query(DeviceChallenge).filter(DeviceChallenge.status == "pending").count()
        return templates.TemplateResponse(
            request,
            "admin_dashboard.html",
            base_ctx(
                request,
                title="管理员控制台｜FOLIO 折页",
                description="查看分配、审核编辑申请，并处理投稿。",
                rows=rows,
                editors=editors,
                labels=STATUS_LABELS,
                pending_apps=pending_apps,
                pending_tours=pending_tours,
                pending_devices=pending_devices,
                trusted_devices=trusted_devices,
                device_limit=ADMIN_DEVICE_LIMIT,
            ),
        )

    @app.get("/editor/apply")
    def editor_apply_page(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        if not user:
            return RedirectResponse("/login?next=" + quote("/editor/apply"), status_code=303)
        existing = (
            db.query(EditorApplication)
            .filter(EditorApplication.user_id == user.id)
            .order_by(EditorApplication.created_at.desc())
            .first()
        )
        return templates.TemplateResponse(
            request,
            "editor_apply.html",
            base_ctx(
                request,
                title="申请成为编辑｜FOLIO 折页",
                description="向管理员提交编辑申请。",
                existing=existing,
                error="",
            ),
        )

    @app.post("/editor/apply")
    async def editor_apply_post(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        rate_limit(request, "editor-apply")
        if user.role in ("admin", "editor"):
            return RedirectResponse(staff_home(user.role), status_code=303)
        pending = (
            db.query(EditorApplication)
            .filter(EditorApplication.user_id == user.id, EditorApplication.status == "pending")
            .first()
        )
        if pending:
            error = "你已有一份待审核的编辑申请。"
        else:
            reason = (str(form.get("reason") or "")).strip()
            if len(reason) < 8:
                error = "请用几句话说明你为什么想成为编辑。"
            else:
                db.add(EditorApplication(
                    user_id=user.id,
                    display_name=user.nickname or user.username,
                    email=user.email,
                    reason=reason[:2000],
                    status="pending",
                ))
                db.commit()
                return RedirectResponse("/editor/apply", status_code=303)
        existing = (
            db.query(EditorApplication)
            .filter(EditorApplication.user_id == user.id)
            .order_by(EditorApplication.created_at.desc())
            .first()
        )
        return templates.TemplateResponse(
            request,
            "editor_apply.html",
            base_ctx(request, title="申请成为编辑｜FOLIO 折页", description="", existing=existing, error=error),
            status_code=400,
        )

    @app.get("/admin/editors")
    def admin_editors(request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        rows = db.query(EditorApplication).order_by(EditorApplication.created_at.desc()).limit(200).all()
        return templates.TemplateResponse(
            request,
            "admin_editors.html",
            base_ctx(request, title="编辑申请审核｜FOLIO 折页", description="审核读者提交的编辑申请。", rows=rows),
        )

    @app.post("/api/admin/editors/{aid}/review")
    async def api_editor_review(aid: int, request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(EditorApplication).filter(EditorApplication.id == aid).one_or_none()
        if not row:
            raise HTTPException(404)
        action = body.get("action")
        note = (body.get("note") or "")[:1000]
        applicant = db.query(User).filter(User.id == row.user_id).one_or_none()
        if action == "approve":
            row.status = "approved"
            row.admin_note = note
            row.reviewed_at = datetime.utcnow()
            if applicant and applicant.role != "admin":
                applicant.role = "editor"
        elif action == "reject":
            row.status = "rejected"
            row.admin_note = note or "这次没有通过。"
            row.reviewed_at = datetime.utcnow()
        else:
            raise HTTPException(400, "未知操作。")
        db.commit()
        return {"ok": True, "status": row.status}

    @app.get("/admin/devices")
    def admin_devices(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        if user.role != "admin":
            raise HTTPException(403, "只有管理员可以管理登录设备。")
        devices = (
            db.query(AuthDevice)
            .filter(AuthDevice.user_id == user.id)
            .order_by(AuthDevice.created_at.desc())
            .all()
        )
        challenges = (
            db.query(DeviceChallenge)
            .filter(DeviceChallenge.user_id == user.id)
            .order_by(DeviceChallenge.created_at.desc())
            .limit(30)
            .all()
        )
        return templates.TemplateResponse(
            request,
            "admin_devices.html",
            base_ctx(
                request,
                title="管理员设备｜FOLIO 折页",
                description="确认新设备，最多保留三台永久登录设备。",
                devices=devices,
                challenges=challenges,
                limit=ADMIN_DEVICE_LIMIT,
                trusted_count=trusted_device_count(db, user.id),
            ),
        )

    @app.post("/api/admin/devices/{cid}/decide")
    async def api_device_decide(cid: int, request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        if user.role != "admin":
            raise HTTPException(403, "只有管理员可以确认设备。")
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(DeviceChallenge).filter(DeviceChallenge.id == cid, DeviceChallenge.user_id == user.id).one_or_none()
        if not row or row.status != "pending":
            raise HTTPException(404, "没有这条待确认登录。")
        action = body.get("action")
        if action == "approve":
            if trusted_device_count(db, user.id) >= ADMIN_DEVICE_LIMIT:
                raise HTTPException(400, "最多只能保留三台永久设备，请先移除一台。")
            existing = (
                db.query(AuthDevice)
                .filter(AuthDevice.user_id == user.id, AuthDevice.token_hash == row.token_hash)
                .one_or_none()
            )
            if existing:
                existing.status = "trusted"
                existing.label = row.label
                existing.last_seen_at = datetime.utcnow()
            else:
                db.add(AuthDevice(
                    user_id=user.id,
                    token_hash=row.token_hash,
                    label=row.label,
                    status="trusted",
                ))
            row.status = "approved"
        elif action == "reject":
            row.status = "rejected"
        else:
            raise HTTPException(400)
        row.resolved_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": row.status}

    @app.post("/api/admin/devices/{did}/revoke")
    async def api_device_revoke(did: int, request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        if user.role != "admin":
            raise HTTPException(403)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(AuthDevice).filter(AuthDevice.id == did, AuthDevice.user_id == user.id).one_or_none()
        if not row:
            raise HTTPException(404)
        row.status = "revoked"
        db.commit()
        return {"ok": True}

    @app.get("/api/device-challenges/{cid}")
    def api_challenge_status(cid: int, request: Request, db: Session = Depends(get_db)):
        secret = getattr(request.state, "device_secret", "") or ""
        row = db.query(DeviceChallenge).filter(DeviceChallenge.id == cid).one_or_none()
        if not row or token_hash(secret) != row.token_hash:
            raise HTTPException(404)
        return {"status": row.status}

    @app.post("/login/device-complete")
    async def login_device_complete(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        cid = int(form.get("id") or 0)
        secret = getattr(request.state, "device_secret", "") or ""
        row = db.query(DeviceChallenge).filter(DeviceChallenge.id == cid).one_or_none()
        if not row or row.status != "approved" or token_hash(secret) != row.token_hash:
            raise HTTPException(403, "这台设备还没有被本机确认。")
        user = db.query(User).filter(User.id == row.user_id).one_or_none()
        if not user:
            raise HTTPException(404)
        device = find_trusted_device(db, user, secret)
        if not device:
            raise HTTPException(403, "设备尚未加入永久名单。")
        token = create_session(db, user, True, device.id)
        db.commit()
        resp = RedirectResponse(staff_home(user.role) if user.role in ("admin", "editor") else "/studio", status_code=303)
        set_session_cookie(request, resp, token, True)
        return resp

    @app.get("/admin/comments")
    def admin_comments(request: Request, db: Session = Depends(get_db)):
        from .security import require_staff
        require_staff(request)
        rows = (
            db.query(Comment)
            .filter(Comment.deleted_at.is_(None))
            .order_by(Comment.created_at.desc())
            .limit(200)
            .all()
        )
        decorate_people(db, rows)
        return templates.TemplateResponse(
            request,
            "admin_comments.html",
            base_ctx(
                request,
                title="评论审核｜FOLIO 折页",
                description="审核读者评论。",
                rows=rows,
                comment_labels=COMMENT_LABELS,
            ),
        )
