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

    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parts = urlparse(raw)
    # Neon pooled host (…-pooler.…) is fine for queries but DDL/create_all is flaky.
    # Prefer the direct endpoint so seed can create tables on deploy.
    host = parts.hostname or ""
    if "-pooler." in host:
        new_host = host.replace("-pooler.", ".", 1)
        userinfo = ""
        if parts.username is not None:
            userinfo = parts.username
            if parts.password is not None:
                userinfo += f":{parts.password}"
            userinfo += "@"
        port = f":{parts.port}" if parts.port else ""
        raw = urlunparse(parts._replace(netloc=f"{userinfo}{new_host}{port}"))
        parts = urlparse(raw)

    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "channel_binding"]
    if not any(k == "sslmode" for k, _ in query):
        query.append(("sslmode", "require"))
    raw = urlunparse(parts._replace(query=urlencode(query)))

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
        "zone_zh": "英语原版书专区",
        "intro": "从伦敦的雾、北方的湖，到当代家庭隐秘的房间。这里收集值得慢慢读完的英文故事。",
        "intro_short": "从伦敦的雾，到隐秘的家庭房间，慢慢读完一个好故事。",
        "search_ph": "搜索英文书名、作者或关键词",
        "hero_quote": "A kinder world through good books.",
        "shelf_zh": "英文",
    },
    "fr": {
        "zh": "法语",
        "native": "Français",
        "tagline": "Des histoires sans frontières",
        "theme": "mint",
        "accent": "#7FB7A6",
        "cover": "/static/img/lang-fr.jpg",
        "zone_zh": "法语原版书专区",
        "intro": "从巴黎街角的光影，到更远的法语世界。这里收集值得慢慢读完的法语故事。",
        "intro_short": "从巴黎街角的光影，慢慢读完一个法语故事。",
        "search_ph": "搜索法文书名、作者或关键词",
        "hero_quote": "Des histoires sans frontières.",
        "shelf_zh": "法文",
    },
    "es": {
        "zh": "西班牙语",
        "native": "Español",
        "tagline": "Historias para un mundo más grande",
        "theme": "peach",
        "accent": "#E2B3A4",
        "cover": "/static/img/lang-es.jpg",
        "zone_zh": "西班牙语原版书专区",
        "intro": "从伊比利亚半岛到拉丁美洲的广阔语境。这里收集值得慢慢读完的西班牙语故事。",
        "intro_short": "从伊比利亚到拉丁美洲，慢慢读完一个西语故事。",
        "search_ph": "搜索西文书名、作者或关键词",
        "hero_quote": "Historias para un mundo más grande.",
        "shelf_zh": "西文",
    },
    "ja": {
        "zh": "日语",
        "native": "日本語",
        "tagline": "ことばで、もっと遠くへ",
        "theme": "sakura",
        "accent": "#D9A7B3",
        "cover": "/static/img/lang-ja.jpg",
        "zone_zh": "日语原版书专区",
        "intro": "从日常的细微声响，到更远的想象之地。这里收集值得慢慢读完的日语故事。",
        "intro_short": "从日常细微声响，慢慢读完一个日语故事。",
        "search_ph": "搜索日文书名、作者或关键词",
        "hero_quote": "ことばで、もっと遠くへ。",
        "shelf_zh": "日文",
    },
    "ko": {
        "zh": "韩语",
        "native": "한국어",
        "tagline": "이야기가 만드는 더 넓은 세상",
        "theme": "lilac",
        "accent": "#B7A7D9",
        "cover": "/static/img/lang-ko.jpg",
        "zone_zh": "韩语原版书专区",
        "intro": "从城市节奏到更柔软的内心风景。这里收集值得慢慢读完的韩语故事。",
        "intro_short": "从城市节奏到内心风景，慢慢读完一个韩语故事。",
        "search_ph": "搜索韩文书名、作者或关键词",
        "hero_quote": "이야기가 만드는 더 넓은 세상.",
        "shelf_zh": "韩文",
    },
    "it": {
        "zh": "意大利语",
        "native": "Italiano",
        "tagline": "Storie che restano",
        "theme": "cream",
        "accent": "#C9B87A",
        "cover": "/static/img/lang-it.jpg",
        "zone_zh": "意大利语原版书专区",
        "intro": "从亚平宁的光线与街道，到仍会留下来的故事。这里收集值得慢慢读完的意大利语作品。",
        "intro_short": "从亚平宁的光线与街道，慢慢读完一个意大利语故事。",
        "search_ph": "搜索意大利文书名、作者或关键词",
        "hero_quote": "Storie che restano.",
        "shelf_zh": "意大利文",
    },
}

LANG_ZONE_GENRES = [
    "文学小说", "悬疑", "爱情", "科幻", "家庭", "历史", "奇幻", "推理",
]

ISSUE_PICK_GENRES = [
    "文学小说", "悬疑", "爱情", "奇幻", "推理",
]


def current_issue_slug() -> str:
    return f"{ISSUE_YEAR}-{ISSUE_MONTH:02d}"

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
