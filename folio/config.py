from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
TEMPLATE_DIR = ROOT / "templates"
CATALOG_DIR = Path(os.environ.get("FOLIO_CATALOG_DIR", str(ROOT / "catalog")))
DB_PATH = Path(os.environ.get("FOLIO_DB", DATA_DIR / "folio.db"))
PERSIST_DIR = Path(os.environ.get("FOLIO_DATA_DIR", str(DB_PATH.parent)))


def database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("FOLIO_DATABASE_URL") or "").strip()
    if not raw:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DB_PATH}"
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://") and "+psycopg" not in raw.split("://", 1)[0]:
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def uses_postgres() -> bool:
    return database_url().startswith("postgresql")


def catalog_path(name: str) -> Path:
    for folder in (CATALOG_DIR, DATA_DIR):
        path = folder / name
        if path.exists():
            return path
    return DATA_DIR / name

SITE_NAME = "FOLIO 折页"
SITE_TAGLINE = "原版新书 · 编辑荐读"
ISSUE_YEAR = 2026
ISSUE_MONTH = 9
ISSUE_TITLE = "二〇二六年九月号"
CONTACT_EMAIL = "1797098277@qq.com"
SECRET_KEY = os.environ.get("FOLIO_SECRET_KEY", "dev-change-me-in-production")
ADMIN_KEY = os.environ.get("FOLIO_ADMIN_KEY", "dev-admin-change-me")
EDITOR_KEY = os.environ.get("FOLIO_EDITOR_KEY", "")
OWNER_ADMIN_USERNAME = (os.environ.get("FOLIO_ADMIN_USERNAME") or "fan").strip().lower()


def owner_admin_emails() -> set[str]:
    emails = {(CONTACT_EMAIL or "").strip().lower()}
    extra = (os.environ.get("FOLIO_ADMIN_EMAIL") or "").strip().lower()
    if extra:
        emails.update(part.strip() for part in extra.split(",") if part.strip())
    return {e for e in emails if e}


def is_owner_admin_email(email: str) -> bool:
    return (email or "").strip().lower() in owner_admin_emails()


COOKIE_NAME = "folio_vid"
CSRF_COOKIE = "folio_csrf"
ADMIN_COOKIE = "folio_admin"
EDITOR_COOKIE = "folio_editor"
SESSION_COOKIE = "folio_sid"
GUEST_COOKIE = "folio_gid"
DEVICE_COOKIE = "folio_did"
ADMIN_DEVICE_LIMIT = 3
SESSION_DAYS = 14
SESSION_REMEMBER_DAYS = 30
RATE_WINDOW_SEC = 60
RATE_LIMIT_POST = 8
SUBMIT_HOUR_LIMIT = 3
SUBMIT_DAY_LIMIT = 10
UPLOAD_DIR = PERSIST_DIR / "uploads" / "submissions"
AVATAR_DIR = PERSIST_DIR / "uploads" / "avatars"
COVER_MAX_BYTES = 10 * 1024 * 1024
COMMENT_MIN = 2
COMMENT_MAX = 2000
NICK_MIN = 1
NICK_MAX = 24

LANGS = {
    "en": {
        "zh": "英语",
        "native": "English",
        "tagline": "Stories for a Brighter You",
        "theme": "sky",
        "accent": "#7BA7C9",
        "cover": "/static/img/lang-en.jpg",
    },
    "fr": {
        "zh": "法语",
        "native": "Français",
        "tagline": "Des histoires sans frontières",
        "theme": "mint",
        "accent": "#7FB7A6",
        "cover": "/static/img/lang-fr.jpg",
    },
    "es": {
        "zh": "西班牙语",
        "native": "Español",
        "tagline": "Historias para un mundo más grande",
        "theme": "peach",
        "accent": "#E2B3A4",
        "cover": "/static/img/lang-es.jpg",
    },
    "ja": {
        "zh": "日语",
        "native": "日本語",
        "tagline": "ことばで、もっと遠くへ",
        "theme": "sakura",
        "accent": "#D9A7B3",
        "cover": "/static/img/lang-ja.jpg",
    },
    "ko": {
        "zh": "韩语",
        "native": "한국어",
        "tagline": "이야기가 만드는 더 넓은 세상",
        "theme": "lilac",
        "accent": "#B7A7D9",
        "cover": "/static/img/lang-ko.jpg",
    },
    "it": {
        "zh": "意大利语",
        "native": "Italiano",
        "tagline": "Storie che restano",
        "theme": "cream",
        "accent": "#C9B87A",
        "cover": "/static/img/lang-it.jpg",
    },
}

MONTH_EN = {
    1: "JANUARY", 2: "FEBRUARY", 3: "MARCH", 4: "APRIL",
    5: "MAY", 6: "JUNE", 7: "JULY", 8: "AUGUST",
    9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER",
}

GENRES = [
    "悬疑", "推理", "惊悚", "科幻", "奇幻", "爱情", "历史",
    "家庭", "成长", "社会议题", "文学小说", "非虚构", "传记", "随笔", "青少年", "其他",
]

SUBMIT_LANGS = [
    ("en", "英语"),
    ("fr", "法语"),
    ("es", "西班牙语"),
    ("ja", "日语"),
    ("ko", "韩语"),
    ("de", "德语"),
    ("zh", "中文"),
    ("it", "意大利语"),
    ("pt", "葡萄牙语"),
    ("other", "其他"),
]

SUBMIT_GENRES = [
    "文学", "悬疑", "推理", "科幻", "奇幻", "爱情", "家庭", "历史",
    "社会议题", "女性题材", "非虚构", "传记", "随笔", "诗歌",
    "儿童文学", "青少年文学", "其他",
]

INFO_SOURCES = [
    "书籍版权页",
    "出版社公开信息",
    "图书馆目录",
    "作者公开资料",
    "其他",
]

REGIONS = [
    "中国", "日本", "韩国", "美国", "英国", "法国", "西班牙", "意大利",
    "德国", "葡萄牙", "加拿大", "澳大利亚", "其他",
]
