#!/usr/bin/env python3
"""Promote username `fan` to admin, rotate password, revoke old sessions.

The generated password is written only to data/owner-password.txt (gitignored).
"""
from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.auth import hash_password  # noqa: E402
from folio.config import DATA_DIR  # noqa: E402
from folio.models import AuthSession, User, SessionLocal, init_db  # noqa: E402


def _password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%*-_"
    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(18))
        if (any(c.islower() for c in raw) and any(c.isupper() for c in raw)
                and any(c.isdigit() for c in raw) and any(c in "!@#$%*-_" for c in raw)):
            return raw


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "fan").one_or_none()
        if not user:
            raise SystemExit("没有找到用户 fan。请先注册该账号。")
        password = _password()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out = DATA_DIR / "owner-password.txt"
        out.write_text(password + "\n", encoding="utf-8")
        out.chmod(0o600)
        user.role = "admin"
        user.status = "active"
        user.password_hash = hash_password(password)
        for row in db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)):
            from datetime import datetime
            row.revoked_at = datetime.utcnow()
        db.commit()
        print("已将 fan 设为管理员，并撤销旧登录会话。")
        print("新密码只写在 data/owner-password.txt，请本机查看后自行保管。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
