from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse

from fastapi import HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import (
    DEVICE_COOKIE, GUEST_COOKIE, SESSION_COOKIE,
    SESSION_DAYS, SESSION_REMEMBER_DAYS, SECRET_KEY,
    OWNER_ADMIN_USERNAME, is_owner_admin_email, owner_admin_emails,
)
from .models import AuthDevice, AuthSession, BookFavorite, DeviceChallenge, GuestIdentity, SessionLocal, User
from .security import rate_limit, sign, unsign

GUEST_ADJ = ["安静的", "阅读的", "温柔的", "认真的", "缓慢的", "明亮的", "沉静的", "好奇的"]
GUEST_ANI = ["水獭", "狐狸", "鲸鱼", "麋鹿", "燕子", "猫", "书虫", "海豚"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
NICK_RE = re.compile(r"^[\w\u4e00-\u9fff ·-]{1,30}$")


def public_profile(db: Session, *, user_id=None, guest_id=None, nickname="") -> dict:
    if user_id:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user:
            return {
                "nickname": (user.nickname or user.username or nickname or "读者")[:40],
                "avatarUrl": user.avatar_url or "",
            }
    if guest_id:
        guest = db.query(GuestIdentity).filter(GuestIdentity.id == guest_id).one_or_none()
        if guest:
            return {"nickname": guest.display_name or nickname or "访客", "avatarUrl": ""}
    return {"nickname": nickname or "访客", "avatarUrl": ""}


def profiles_for(db: Session, user_ids) -> dict:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}


def profile_from_user(user, nickname="") -> dict:
    if not user:
        return {"nickname": nickname or "访客", "avatarUrl": ""}
    return {
        "nickname": (user.nickname or user.username or nickname or "读者")[:40],
        "avatarUrl": user.avatar_url or "",
    }


def decorate_people(db: Session, rows, *, user_attr="user_id", nick_attr="nickname", guest_attr="guest_identity_id"):
    users = profiles_for(db, [getattr(row, user_attr, None) for row in rows])
    gids = {getattr(row, guest_attr, None) for row in rows if getattr(row, guest_attr, None)}
    guests = {}
    if gids:
        guests = {g.id: g for g in db.query(GuestIdentity).filter(GuestIdentity.id.in_(gids)).all()}
    for row in rows:
        uid = getattr(row, user_attr, None)
        gid = getattr(row, guest_attr, None)
        nick = getattr(row, nick_attr, "") or ""
        if uid and users.get(uid):
            prof = profile_from_user(users[uid], nick)
        elif gid and guests.get(gid):
            prof = {"nickname": guests[gid].display_name or nick or "访客", "avatarUrl": ""}
        else:
            prof = {"nickname": nick or "访客", "avatarUrl": ""}
        row.author_name = prof["nickname"]
        row.author_avatar = prof["avatarUrl"]
    return rows


def _hasher():
    try:
        from argon2 import PasswordHasher
        return PasswordHasher()
    except Exception:
        return None


def hash_password(password: str) -> str:
    ph = _hasher()
    if ph:
        return "argon2$" + ph.hash(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 210000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or not password:
        return False
    if stored.startswith("argon2$"):
        ph = _hasher()
        if not ph:
            return False
        try:
            return ph.verify(stored[7:], password)
        except Exception:
            return False
    if stored.startswith("pbkdf2$"):
        _, salt, digest = stored.split("$", 2)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 210000).hex()
        return hmac.compare_digest(check, digest)
    return False


def current_user(request: Request):
    return getattr(request.state, "user", None)


def require_user(request: Request) -> User:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "请先登录。")
    if user.status != "active":
        raise HTTPException(403, "账号不可用。")
    return user


def safe_next(value: str | None, fallback: str = "/") -> str:
    raw = (value or "").strip() or fallback
    if not raw.startswith("/") or raw.startswith("//"):
        return fallback
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    return raw


def login_url(next_url: str = "/") -> str:
    return "/login?next=" + quote(safe_next(next_url), safe="/")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_secure(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


def device_label(request: Request) -> str:
    ua = (request.headers.get("user-agent") or "未知设备")[:80]
    return ua


def get_or_set_device_secret(request: Request, response: Response) -> str:
    raw = request.cookies.get(DEVICE_COOKIE)
    secret = unsign(raw) if raw else None
    if not secret:
        secret = secrets.token_urlsafe(24)
        response.set_cookie(
            DEVICE_COOKIE,
            sign(secret),
            httponly=True,
            samesite="lax",
            secure=cookie_secure(request),
            max_age=60 * 60 * 24 * 400,
            path="/",
        )
    request.state.device_secret = secret
    return secret


def trusted_device_count(db: Session, user_id: int) -> int:
    return db.query(AuthDevice).filter(AuthDevice.user_id == user_id, AuthDevice.status == "trusted").count()


def find_trusted_device(db: Session, user: User, secret: str) -> AuthDevice | None:
    return (
        db.query(AuthDevice)
        .filter(
            AuthDevice.user_id == user.id,
            AuthDevice.token_hash == token_hash(secret),
            AuthDevice.status == "trusted",
        )
        .one_or_none()
    )


def trust_device(db: Session, user: User, secret: str, label: str) -> AuthDevice:
    row = (
        db.query(AuthDevice)
        .filter(AuthDevice.user_id == user.id, AuthDevice.token_hash == token_hash(secret))
        .one_or_none()
    )
    if row:
        row.status = "trusted"
        row.label = label[:80]
        row.last_seen_at = datetime.utcnow()
        return row
    row = AuthDevice(
        user_id=user.id,
        token_hash=token_hash(secret),
        label=label[:80],
        status="trusted",
    )
    db.add(row)
    db.flush()
    return row


def promote_owner_admin() -> None:
    db = SessionLocal()
    try:
        emails = owner_admin_emails()
        users = []
        if emails:
            users.extend(db.query(User).filter(User.email.in_(emails)).all())
        named = db.query(User).filter(User.username == OWNER_ADMIN_USERNAME).one_or_none()
        if named:
            users.append(named)
        seen = set()
        for user in users:
            if user.id in seen:
                continue
            seen.add(user.id)
            user.role = "admin"
            user.status = "active"
        if seen:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def staff_home(role: str) -> str:
    if role == "admin":
        return "/admin/dashboard"
    if role == "editor":
        return "/editor/workbench"
    return "/"


def set_session_cookie(request: Request, response: Response, token: str, remember: bool) -> None:
    days = SESSION_REMEMBER_DAYS if remember else SESSION_DAYS
    response.set_cookie(
        SESSION_COOKIE,
        sign(token),
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        max_age=days * 86400,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def create_session(db: Session, user: User, remember: bool, device_id: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    days = SESSION_REMEMBER_DAYS if remember else SESSION_DAYS
    db.add(AuthSession(
        user_id=user.id,
        device_id=device_id,
        token_hash=token_hash(token),
        expires_at=datetime.utcnow() + timedelta(days=days),
    ))
    return token


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).one_or_none()
    if row and not row.revoked_at:
        row.revoked_at = datetime.utcnow()


def load_session_user(db: Session, request: Request) -> User | None:
    raw = request.cookies.get(SESSION_COOKIE)
    token = unsign(raw) if raw else None
    if not token:
        return None
    row = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).one_or_none()
    if not row or row.revoked_at or row.expires_at < datetime.utcnow():
        return None
    user = db.query(User).filter(User.id == row.user_id).one_or_none()
    if not user or user.status != "active":
        return None
    if user.role == "admin":
        if not row.device_id:
            return None
        device = db.query(AuthDevice).filter(AuthDevice.id == row.device_id).one_or_none()
        if not device or device.status != "trusted" or device.user_id != user.id:
            return None
        secret = getattr(request.state, "device_secret", "") or ""
        if token_hash(secret) != device.token_hash:
            return None
        device.last_seen_at = datetime.utcnow()
    request.state.session_token = token
    return user


def attach_auth(request: Request, response: Response) -> None:
    db = SessionLocal()
    try:
        get_or_set_device_secret(request, response)
        request.state.user = load_session_user(db, request)
        guest = load_guest(db, request)
        request.state.guest = guest
        if guest:
            stamp_guest_cookie(request, response, guest.public_id)
        user = request.state.user
        try:
            if user:
                request.state.favorite_ids = {
                    int(row.book_id)
                    for row in db.query(BookFavorite).filter(BookFavorite.user_id == user.id).all()
                }
            else:
                request.state.favorite_ids = set()
            request.state.favorite_counts = {
                int(book_id): int(n)
                for book_id, n in db.query(BookFavorite.book_id, func.count(BookFavorite.id))
                .group_by(BookFavorite.book_id)
                .all()
            }
        except Exception:
            request.state.favorite_ids = getattr(request.state, "favorite_ids", set()) or set()
            request.state.favorite_counts = {}
    except Exception:
        request.state.user = None
        request.state.guest = None
        request.state.favorite_ids = set()
        request.state.favorite_counts = {}
    finally:
        db.close()


def random_guest_name(db: Session) -> str:
    for _ in range(40):
        name = f"{secrets.choice(GUEST_ADJ)}{secrets.choice(GUEST_ANI)}{secrets.randbelow(900) + 100}"
        if not db.query(GuestIdentity).filter(GuestIdentity.display_name == name).first():
            return name
    return f"安静的读者{secrets.randbelow(900) + 100}"


def load_guest(db: Session, request: Request) -> GuestIdentity | None:
    raw = request.cookies.get(GUEST_COOKIE)
    public_id = unsign(raw) if raw else None
    if not public_id:
        return None
    row = db.query(GuestIdentity).filter(GuestIdentity.public_id == public_id).one_or_none()
    if row:
        row.last_seen_at = datetime.utcnow()
        if request.state.visitor_id and not row.visitor_id:
            row.visitor_id = request.state.visitor_id
        db.commit()
    return row


def stamp_guest_cookie(request: Request, response: Response, public_id: str) -> None:
    response.set_cookie(
        GUEST_COOKIE,
        sign(public_id),
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        max_age=60 * 60 * 24 * 400,
        path="/",
    )


def get_or_create_guest(db: Session, request: Request, response: Response | None = None) -> GuestIdentity:
    existing = getattr(request.state, "guest", None) or load_guest(db, request)
    if existing:
        request.state.guest = existing
        return existing
    token = secrets.token_urlsafe(24)
    row = GuestIdentity(
        public_id=secrets.token_hex(12),
        display_name=random_guest_name(db),
        token_hash=token_hash(token),
        visitor_id=getattr(request.state, "visitor_id", "") or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    request.state.guest = row
    if response is not None:
        stamp_guest_cookie(request, response, row.public_id)
    return row


def validate_username(value: str) -> str:
    raw = (value or "").strip()
    if not USER_RE.match(raw):
        raise HTTPException(400, "用户名需为 3–30 位字母、数字或下划线。")
    return raw.lower()


def validate_email(value: str) -> str:
    raw = (value or "").strip().lower()
    if not EMAIL_RE.match(raw) or len(raw) > 200:
        raise HTTPException(400, "请输入有效邮箱。")
    return raw


def validate_nickname(value: str) -> str:
    raw = (value or "").strip()
    if not NICK_RE.match(raw):
        raise HTTPException(400, "昵称请使用 1–30 字，不要包含特殊符号。")
    return raw


def validate_password(password: str, confirm: str | None = None) -> str:
    if len(password or "") < 8:
        raise HTTPException(400, "密码至少 8 位。")
    if confirm is not None and password != confirm:
        raise HTTPException(400, "两次输入的密码不一致。")
    return password


def find_login_user(db: Session, identifier: str) -> User | None:
    ident = (identifier or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return db.query(User).filter(User.email == ident.lower()).one_or_none()
    return db.query(User).filter(User.username == ident.lower()).one_or_none()


def bootstrap_admin() -> None:
    email = (os.environ.get("FOLIO_ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("FOLIO_ADMIN_PASSWORD") or ""
    if not email or not password:
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user:
            if user.role != "admin":
                user.role = "admin"
                db.commit()
            return
        username = validate_username(os.environ.get("FOLIO_ADMIN_USERNAME") or "fan")
        if db.query(User).filter(User.username == username).one_or_none():
            username = "admin_" + secrets.token_hex(3)
        db.add(User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            nickname="编辑",
            role="admin",
            status="active",
        ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
