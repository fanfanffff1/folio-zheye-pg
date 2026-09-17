from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from html import escape

from fastapi import HTTPException, Request, Response

from .config import (
    ADMIN_COOKIE, ADMIN_KEY, COMMENT_MAX, COMMENT_MIN, COOKIE_NAME, CSRF_COOKIE,
    EDITOR_COOKIE, EDITOR_KEY, NICK_MAX, NICK_MIN, RATE_LIMIT_POST, RATE_WINDOW_SEC,
    SECRET_KEY, SUBMIT_DAY_LIMIT, SUBMIT_HOUR_LIMIT,
)

_RATE: dict[str, deque] = defaultdict(deque)


def sign(value: str) -> str:
    digest = hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def unsign(token: str) -> str | None:
    if "." not in token:
        return None
    value, digest = token.rsplit(".", 1)
    expected = hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    return value


def get_or_set_visitor(request: Request, response: Response) -> str:
    raw = request.cookies.get(COOKIE_NAME)
    vid = unsign(raw) if raw else None
    if not vid:
        vid = secrets.token_hex(16)
        response.set_cookie(
            COOKIE_NAME, sign(vid), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 400, path="/"
        )
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        csrf = secrets.token_urlsafe(24)
        response.set_cookie(
            CSRF_COOKIE, csrf, httponly=False, samesite="lax",
            max_age=60 * 60 * 24 * 400, path="/"
        )
    request.state.csrf = csrf
    return vid


def require_csrf(request: Request, token: str) -> None:
    cookie = request.cookies.get(CSRF_COOKIE) or ""
    if not token or not cookie or not hmac.compare_digest(token, cookie):
        raise HTTPException(403, "CSRF 校验失败，请刷新后重试。")


def rate_limit(request: Request, key: str) -> None:
    ip = request.client.host if request.client else "unknown"
    bucket = f"{ip}:{key}"
    now = time.time()
    q = _RATE[bucket]
    while q and now - q[0] > RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= RATE_LIMIT_POST:
        raise HTTPException(429, "操作过于频繁，请稍后再试。")
    q.append(now)


def clean_text(text: str, min_len: int, max_len: int, field: str) -> str:
    value = (text or "").replace("\x00", "").strip()
    if len(value) < min_len or len(value) > max_len:
        raise HTTPException(400, f"{field}长度需在 {min_len}–{max_len} 字之间。")
    lowered = value.lower()
    if "<script" in lowered or "javascript:" in lowered:
        raise HTTPException(400, "评论包含不被允许的内容。")
    return value


def clean_nick(nick: str) -> str:
    return clean_text(nick, NICK_MIN, NICK_MAX, "昵称")


def clean_comment(content: str) -> str:
    return clean_text(content, COMMENT_MIN, COMMENT_MAX, "评论")


def is_admin(request: Request) -> bool:
    candidates = [
        request.headers.get("x-folio-admin") or "",
        request.query_params.get("admin") or "",
        request.cookies.get(ADMIN_COOKIE) or "",
    ]
    for value in candidates:
        if value and len(value) == len(ADMIN_KEY) and hmac.compare_digest(value, ADMIN_KEY):
            return True
    return False


def is_editor(request: Request) -> bool:
    if is_admin(request):
        return True
    key = (EDITOR_KEY or "").strip()
    if not key:
        return False
    candidates = [
        request.headers.get("x-folio-editor") or "",
        request.cookies.get(EDITOR_COOKIE) or "",
    ]
    for value in candidates:
        if value and len(value) == len(key) and hmac.compare_digest(value, key):
            return True
    return False


def user_role(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is not None and getattr(user, "status", "") == "active":
        if getattr(user, "role", "") == "admin":
            return "admin"
        if getattr(user, "role", "") == "editor":
            return "editor"
    if is_admin(request):
        return "admin"
    if is_editor(request):
        return "editor"
    if user is not None:
        return "user"
    return "reader"


def require_staff(request: Request) -> str:
    role = user_role(request)
    if role not in ("editor", "admin"):
        raise HTTPException(403, "没有审核权限。")
    return role


def require_admin(request: Request) -> str:
    if user_role(request) != "admin" and not is_admin(request):
        raise HTTPException(403, "需要管理员权限。")
    return "admin"


def submit_rate_ok(request: Request, submitted_times: list) -> None:
    now = time.time()
    hour = [t for t in submitted_times if now - t < 3600]
    day = [t for t in submitted_times if now - t < 86400]
    if len(hour) >= SUBMIT_HOUR_LIMIT:
        raise HTTPException(429, "每小时最多提交 3 次推荐，请稍后再试。")
    if len(day) >= SUBMIT_DAY_LIMIT:
        raise HTTPException(429, "每天最多提交 10 次推荐，请明天再来。")
    rate_limit(request, "submit")


def html_safe(text: str) -> str:
    return escape(text or "", quote=True)
