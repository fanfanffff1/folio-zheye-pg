"""地图巡礼 (user-created literary pilgrimage maps).

Phase 1: create a tour, drop city-level stops on a self-hosted GeoJSON base map.
Phase 2: auto region colouring (continent / China region), custom colour tags,
         footprint route line, stop photos on R2.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .auth import current_user, require_user
from .config import GENRES, PERSIST_DIR, ROOT
from .models import (
    Author, Book, BookSubmission, Notification, SessionLocal, TourMap, TourPlace, TourPlaceBook,
    TourPlaceLike, TourPlaceReport, TourPlaceReview, TourStop,
    TourStopCategory, TourMedia, TourStopNote, TourStopNoteLike, TourStopRevision, User,
)
from .object_store import (
    content_type_for_ext, delete_object, key_from_public_or_local_url, persist_user_upload,
)
from .security import rate_limit, require_csrf, require_staff, user_role
from .submissions import next_number

SCOPES = ("world", "china")
MAX_STOPS = 300
PLACE_MIN_DESC = 30  # minimum characters for a user-added place description
PHOTO_MAX_BYTES = 8 * 1024 * 1024
TOUR_UPLOAD_DIR = PERSIST_DIR / "uploads" / "tours"

# scope -> (center_lat, center_lon, zoom)
SCOPE_DEFAULT_VIEW = {
    "world": (22.0, 8.0, 2),
    "china": (35.0, 104.0, 4),
}

# 分类颜色按“大洋/大区”自动分配，用户无需手动选。
CONTINENT_ZH = {
    "Asia": "亚洲", "Europe": "欧洲", "Africa": "非洲",
    "North America": "北美洲", "South America": "南美洲", "Oceania": "大洋洲",
}
WORLD_CATEGORIES = [
    ("亚洲", "#7FB09A"), ("欧洲", "#8FA9C9"), ("非洲", "#D2A06E"),
    ("北美洲", "#9BA7CE"), ("南美洲", "#C98AA0"), ("大洋洲", "#7FC0B8"),
    ("其他", "#B0A6C0"),
]
CHINA_CATEGORIES = [
    ("华北", "#9BB3C9"), ("东北", "#A6C88E"), ("华东", "#8FC0B8"),
    ("华中", "#B9BE74"), ("华南", "#D2956E"), ("西南", "#86C3A2"),
    ("西北", "#E0B65C"), ("港澳台", "#DEA5AB"), ("其他", "#B0A6C0"),
]
CHINA_PROVINCE_REGION = {
    "北京市": "华北", "天津市": "华北", "河北省": "华北", "山西省": "华北", "内蒙古自治区": "华北",
    "辽宁省": "东北", "吉林省": "东北", "黑龙江省": "东北",
    "上海市": "华东", "江苏省": "华东", "浙江省": "华东", "安徽省": "华东",
    "福建省": "华东", "江西省": "华东", "山东省": "华东",
    "河南省": "华中", "湖北省": "华中", "湖南省": "华中",
    "广东省": "华南", "广西壮族自治区": "华南", "海南省": "华南",
    "重庆市": "西南", "四川省": "西南", "贵州省": "西南", "云南省": "西南", "西藏自治区": "西南",
    "陕西省": "西北", "甘肃省": "西北", "青海省": "西北",
    "宁夏回族自治区": "西北", "新疆维吾尔自治区": "西北",
    "香港特别行政区": "港澳台", "澳门特别行政区": "港澳台", "台湾省": "港澳台",
}

_COUNTRY_CONTINENT: dict[str, str] | None = None


def _country_continent() -> dict[str, str]:
    global _COUNTRY_CONTINENT
    if _COUNTRY_CONTINENT is None:
        table: dict[str, str] = {}
        path = ROOT / "static" / "data" / "tour-map" / "world" / "countries.geojson"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for f in data.get("features", []):
                p = f.get("properties") or {}
                cont = p.get("CONTINENT")
                if not cont:
                    continue
                for key in (p.get("NAME"), p.get("ADMIN"), p.get("ISO_A3")):
                    if key:
                        table[str(key).strip().lower()] = cont
        except Exception:
            table = {}
        _COUNTRY_CONTINENT = table
    return _COUNTRY_CONTINENT


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60]


def _unique_slug(db: Session, title: str) -> str:
    base = _slugify(title) or ("tour-" + secrets.token_hex(3))
    slug, n = base, 2
    while db.query(TourMap).filter(TourMap.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _own_tour(db: Session, slug: str, request: Request) -> TourMap:
    user = current_user(request)
    row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
    if not row:
        raise HTTPException(404, "没有找到这张巡礼地图。")
    if not user or row.owner_user_id != user.id:
        raise HTTPException(403, "只能编辑自己的巡礼地图。")
    return row


def _contributable_tour(db: Session, slug: str, request: Request) -> TourMap:
    """Public collections accept anyone's points; private ones only the owner's."""
    user = current_user(request)
    if not user:
        raise HTTPException(401, "请先登录。")
    row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
    if not row:
        raise HTTPException(404, "没有找到这个合集。")
    if row.visibility == "public" or row.owner_user_id == user.id:
        return row
    raise HTTPException(403, "这个合集未公开。")


def _editable_stop(db: Session, row: TourMap, sid: int, request: Request) -> TourStop:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "请先登录。")
    stop = db.query(TourStop).filter(TourStop.id == sid, TourStop.map_id == row.id).one_or_none()
    if not stop:
        raise HTTPException(404)
    if stop.user_id == user.id or row.owner_user_id == user.id:
        return stop
    raise HTTPException(403, "只能修改自己添加的地点。")


def _viewable_tour(db: Session, slug: str, request: Request) -> TourMap:
    row = db.query(TourMap).filter(TourMap.slug == slug, TourMap.deleted_at.is_(None)).one_or_none()
    if not row:
        raise HTTPException(404, "没有找到这张巡礼地图。")
    user = current_user(request)
    is_owner = bool(user and row.owner_user_id == user.id)
    if row.visibility != "public" and not is_owner:
        raise HTTPException(404, "没有找到这张巡礼地图。")
    return row


def _auto_category_id(db: Session, row: TourMap, country: str, admin1: str) -> Optional[int]:
    cats = (
        db.query(TourStopCategory)
        .filter(TourStopCategory.map_id == row.id, TourStopCategory.kind == "auto")
        .all()
    )
    if not cats:
        return None
    by_label = {c.label: c.id for c in cats}
    ctry = (country or "").strip()
    if ctry in ("中国", "China", "People's Republic of China"):
        continent = "Asia"
    else:
        continent = _country_continent().get(ctry.lower())
    if row.scope == "china":
        label = CHINA_PROVINCE_REGION.get((admin1 or "").strip(), "")
        if label not in by_label:
            label = CONTINENT_ZH.get(continent, "其他")
    else:
        label = CONTINENT_ZH.get(continent, "其他")
    return by_label.get(label) or by_label.get("其他") or cats[0].id


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (text or ""))


def _place_key(level: str, lat: float, lon: float) -> str:
    # Coordinate-based so the same spot merges regardless of language/name.
    return f"{level}|{round(float(lat), 2)}|{round(float(lon), 2)}"


def _spot_key(lat: float, lon: float) -> str:
    # Finer grid (~11 m) for user-added specific places.
    return f"spot|{round(float(lat), 4)}|{round(float(lon), 4)}"


_GARBAGE_RE = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")


def _looks_like_garbage(text: str) -> bool:
    """Detect mojibake / control chars / obvious spam."""
    if not text:
        return False
    if _GARBAGE_RE.search(text):
        return True
    if re.search(r"(.)\1{7,}", text):  # same char repeated 8+ times
        return True
    if len(text) >= 12 and len(set(text)) <= 3:  # near-constant string
        return True
    return False


def _looks_wrong_place(name, lat, lon) -> bool:
    """Sanity check: a name mentioning a polar region must sit in that region."""
    n = (name or "").strip().lower()
    checks = [
        (("南极", "south pole", "antarctic"), lambda la: la <= -60.0),
        (("北极", "north pole", "arctic"), lambda la: la >= 60.0),
    ]
    for keys, ok in checks:
        if any(k in n for k in keys):
            if not ok(float(lat)):
                return True
    return False


def _place_auto_ok(name, address, desc, source, photos, book_ids, lat=None, lon=None) -> tuple[bool, str]:
    """Very light auto-review (early stage): publish unless it clearly looks bad.

    Only blocks an empty name or obvious mojibake / spam. Everything else
    (address, books, description, source, coordinates) is optional.
    """
    if len(name) < 2:
        return False, "名称过短"
    for t in (name, address, desc, source):
        if _looks_like_garbage(t):
            return False, "疑似乱码或异常内容"
    return True, ""


def _get_or_create_place(db: Session, user_id, name, name_en, level, lat, lon, country, admin1) -> TourPlace:
    key = _place_key(level, lat, lon)
    place = db.query(TourPlace).filter(TourPlace.key == key).one_or_none()
    if place:
        if _has_cjk(name) and not _has_cjk(place.name):
            place.name = (name or "")[:120]
        return place
    # reuse a nearby place with a matching name (same or one containing the other)
    # so a city gets only one marker (e.g. 伦敦 / 伦敦城)
    nm = (name or "").strip()
    if nm:
        for cand in db.query(TourPlace).filter(TourPlace.level == level).all():
            cn = (cand.name or "").strip()
            if not cn or not (nm == cn or nm in cn or cn in nm):
                continue
            if abs((cand.lat or 0) - float(lat)) <= 0.2 and abs((cand.lon or 0) - float(lon)) <= 0.2:
                if len(nm) < len(cn):
                    cand.name = nm[:120]
                return cand
    place = TourPlace(
        key=key, name=(name or "")[:120], name_en=(name_en or "")[:160], level=level,
        lat=float(lat), lon=float(lon), country=(country or "")[:80], admin1=(admin1 or "")[:80],
        created_by=user_id,
    )
    db.add(place)
    db.flush()
    return place


def _place_pack(db: Session, p: TourPlace, user=None) -> dict:
    liked = False
    if user:
        liked = db.query(TourPlaceLike).filter(
            TourPlaceLike.place_id == p.id, TourPlaceLike.user_id == user.id
        ).first() is not None
    stop_count = db.query(TourStop).filter(TourStop.place_id == p.id).count()
    sample: list[str] = []
    for (note,) in db.query(TourStop.note).filter(TourStop.place_id == p.id, TourStop.note != "").limit(8).all():
        if note and note not in sample:
            sample.append(note)
    book_rows = db.query(TourPlaceBook).filter(TourPlaceBook.place_id == p.id).all()
    book_ids = [r.book_id for r in book_rows]
    books = []
    if book_ids:
        bmap = {b.id: b for b in db.query(Book).filter(Book.id.in_(book_ids)).all()}
        for bid in book_ids:
            b = bmap.get(bid)
            if b:
                books.append({"id": bid, "title": b.chinese_title or b.original_title or "", "slug": b.slug or ""})
    return {
        "id": p.id, "name": p.name, "name_en": p.name_en, "level": p.level,
        "lat": p.lat, "lon": p.lon, "country": p.country, "admin1": p.admin1,
        "footnote": p.footnote, "photos": _parse_photos(p.photos, ""),
        "view_count": p.view_count, "like_count": p.like_count, "stop_count": stop_count,
        "sample_notes": sample[:2],
        "created_by": p.created_by, "liked": liked,
        "is_creator": bool(user and p.created_by == user.id),
        "status": p.status or "published",
        "city_key": p.city_key or "",
        "address": p.address or "",
        "source_url": p.source_url or "",
        "merged_into_id": p.merged_into_id,
        "reject_reason": p.reject_reason or "",
        "delete_requested": bool(p.delete_requested),
        "auto_approved": bool(p.auto_approved),
        "books": books,
    }


def _parse_photos(raw: str, cover: str = "") -> list[str]:
    try:
        arr = json.loads(raw) if raw else []
        if not isinstance(arr, list):
            arr = []
    except (ValueError, TypeError):
        arr = []
    arr = [u for u in arr if isinstance(u, str) and u]
    if cover and cover not in arr:
        arr = [cover] + arr
    return arr


def _stop_book_ids(stop: TourStop) -> list[int]:
    """All linked book ids: JSON list, falling back to the legacy single book_id."""
    ids: list[int] = []
    try:
        arr = json.loads(stop.book_ids) if stop.book_ids else []
    except (ValueError, TypeError):
        arr = []
    if isinstance(arr, list):
        for v in arr:
            try:
                iv = int(v)
            except (ValueError, TypeError):
                continue
            if iv and iv not in ids:
                ids.append(iv)
    if not ids and stop.book_id:
        ids.append(int(stop.book_id))
    return ids


def _clean_ids(raw) -> list[int]:
    ids: list[int] = []
    for v in (raw or []):
        try:
            iv = int(v)
        except (ValueError, TypeError):
            continue
        if iv and iv not in ids:
            ids.append(iv)
    return ids


def _apply_draft_to_stop(stop: TourStop, d: dict) -> None:
    if "note" in d:
        stop.note = d["note"]
    if "author_id" in d:
        stop.author_id = d["author_id"]
    if "book_ids" in d:
        ids = _clean_ids(d.get("book_ids"))
        stop.book_ids = json.dumps(ids, ensure_ascii=False)
        stop.book_id = ids[0] if ids else None
    elif "book_id" in d:
        ids = _clean_ids([d.get("book_id")])
        stop.book_ids = json.dumps(ids, ensure_ascii=False)
        stop.book_id = ids[0] if ids else None
    if "photos" in d:
        stop.photos = json.dumps(d["photos"], ensure_ascii=False)
        if d["photos"]:
            stop.media_url = d["photos"][0]


def pack_tour(db: Session, row: TourMap, *, is_owner: bool = False, viewer_id: int | None = None) -> dict:
    cats = (
        db.query(TourStopCategory)
        .filter(TourStopCategory.map_id == row.id)
        .order_by(TourStopCategory.order_index.asc(), TourStopCategory.id.asc())
        .all()
    )
    stops = (
        db.query(TourStop)
        .filter(TourStop.map_id == row.id, TourStop.deleted_at.is_(None))
        .order_by(TourStop.order_index.asc(), TourStop.id.asc())
        .all()
    )
    book_ids: set[int] = set()
    for s in stops:
        book_ids.update(_stop_book_ids(s))
    books = {b.id: b for b in db.query(Book).filter(Book.id.in_(book_ids)).all()} if book_ids else {}
    author_ids = {s.author_id for s in stops if s.author_id}
    authors = {a.id: a for a in db.query(Author).filter(Author.id.in_(author_ids)).all()} if author_ids else {}
    place_ids = {s.place_id for s in stops if s.place_id}
    place_footnotes = {
        p.id: p.footnote for p in db.query(TourPlace).filter(TourPlace.id.in_(place_ids)).all()
    } if place_ids else {}
    owner = db.query(User).filter(User.id == row.owner_user_id).one_or_none()
    contrib_ids = {s.user_id for s in stops if s.user_id}
    contribs = {u.id: u for u in db.query(User).filter(User.id.in_(contrib_ids)).all()} if contrib_ids else {}

    def _who(uid):
        u = contribs.get(uid)
        if not u:
            return "", ""
        return (u.nickname or u.username or ""), (u.avatar_url or "")

    def _book_ref(bid):
        b = books.get(bid)
        if not b:
            return {"id": bid, "title": "", "slug": ""}
        return {"id": bid, "title": (b.chinese_title or b.original_title or ""), "slug": b.slug or ""}

    def _pack_stop(s):
        ids = _stop_book_ids(s)
        first = _book_ref(ids[0]) if ids else {"id": None, "title": "", "slug": ""}
        return {
            "id": s.id,
            "lat": s.lat,
            "lon": s.lon,
            "place_name": s.place_name,
            "country": s.country,
            "admin1": s.admin1,
            "city": s.city,
            "note": s.note,
            "period": s.period,
            "category_id": s.category_id,
            "tag_id": s.tag_id,
            "level": s.level or "city",
            "order_index": s.order_index,
            "book_id": first["id"],
            "book_title": first["title"],
            "book_slug": first["slug"],
            "books": [_book_ref(bid) for bid in ids],
            "author_id": s.author_id,
            "author_name": authors[s.author_id].name if s.author_id in authors else "",
            "place_id": s.place_id,
            "footnote": place_footnotes.get(s.place_id, ""),
            "contributor_name": _who(s.user_id)[0],
            "contributor_avatar": _who(s.user_id)[1],
            "is_contributor": bool(viewer_id and s.user_id == viewer_id),
            "media_url": s.media_url,
            "photos": _parse_photos(s.photos, s.media_url),
            "draft": (json.loads(s.draft) if s.draft else None),
            "has_draft": bool(s.draft),
            "pending_review": bool(s.draft and (json.loads(s.draft) or {}).get("_pending")),
        }

    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "subtitle": row.subtitle,
        "description": row.description,
        "scope": row.scope,
        "kind": row.kind or "custom",
        "ref_id": row.ref_id,
        "owner_user_id": row.owner_user_id,
        "base_style": row.base_style,
        "center": {"lat": row.center_lat, "lon": row.center_lon},
        "zoom": row.zoom,
        "visibility": row.visibility,
        "status": row.status,
        "cover_url": row.cover_url,
        "tags": [t for t in (row.tags or "").split(",") if t],
        "stop_count": row.stop_count,
        "view_count": row.view_count,
        "like_count": row.like_count,
        "is_owner": is_owner,
        "owner_name": (row.author_name or (owner.nickname or owner.username or "")) if owner else (row.author_name or ""),
        "owner_avatar": (owner.avatar_url or "") if owner else "",
        "categories": [
            {"id": c.id, "label": c.label, "color": c.color, "kind": c.kind or "auto", "order": c.order_index}
            for c in cats
        ],
        "stops": [_pack_stop(s) for s in stops],
    }


class StopIn(BaseModel):
    lat: float
    lon: float
    place_name: str = ""
    country: str = ""
    admin1: str = ""
    city: str = ""
    level: str = "city"
    note: str = ""
    period: str = ""
    tag_id: Optional[int] = None
    book_id: Optional[int] = None
    book_ids: list[int] = []
    author_id: Optional[int] = None
    csrf: str = ""


class StopPatch(BaseModel):
    place_name: Optional[str] = None
    note: Optional[str] = None
    period: Optional[str] = None
    tag_id: Optional[int] = None
    book_id: Optional[int] = None
    book_ids: Optional[list[int]] = None
    author_id: Optional[int] = None
    order_index: Optional[int] = None
    csrf: str = ""


class MetaIn(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    zoom: Optional[int] = None
    author_name: Optional[str] = None
    csrf: str = ""


class CategoryIn(BaseModel):
    label: str = ""
    color: str = "#9BB3C9"
    csrf: str = ""


class StopDraftIn(BaseModel):
    note: Optional[str] = None
    author_id: Optional[int] = None
    book_id: Optional[int] = None
    book_ids: Optional[list[int]] = None
    photos: Optional[list[str]] = None
    csrf: str = ""


class MediaBindIn(BaseModel):
    ids: list[int] = []
    csrf: str = ""


class QuickRecIn(BaseModel):
    title: str = ""
    authors: str = ""
    note: str = ""
    fuzzy: bool = False
    cover_url: str = ""
    csrf: str = ""


class NoteIn(BaseModel):
    body: str = ""
    csrf: str = ""


class NoteEditIn(BaseModel):
    body: Optional[str] = None
    is_private: Optional[bool] = None
    csrf: str = ""


class CollectionIn(BaseModel):
    kind: str = "custom"          # author | book | genre | custom
    ref_id: Optional[int] = None
    title: str = ""
    visibility: str = "public"    # public | private
    scope: str = "world"
    csrf: str = ""


class CollectionFromPlacesIn(BaseModel):
    title: str = ""
    place_ids: list[int] = []
    csrf: str = ""


class PlaceIn(BaseModel):
    name: str = ""
    level: str = "spot"          # spot (precise point) | city (city-level literary note)
    lat: Optional[float] = None
    lon: Optional[float] = None
    address: str = ""
    city_key: str = ""
    country: str = ""
    admin1: str = ""
    description: str = ""         # stored as footnote
    source_url: str = ""
    book_ids: list[int] = []
    author_id: Optional[int] = None
    photos: list[str] = []
    draft: bool = False
    csrf: str = ""


def _sniff_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise HTTPException(400, "仅支持 JPG、PNG 或 WebP 图片。")


def register(app, templates, base_ctx):
    @app.get("/tours")
    def tours_index(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        mine = []
        if user:
            rows = (
                db.query(TourMap)
                .filter(TourMap.owner_user_id == user.id)
                .order_by(TourMap.updated_at.desc())
                .limit(60)
                .all()
            )
            mine = [
                {"slug": r.slug, "title": r.title, "status": r.status, "scope": r.scope,
                 "stop_count": r.stop_count, "view_count": r.view_count}
                for r in rows
            ]
        return templates.TemplateResponse(
            request,
            "tours.html",
            base_ctx(
                request,
                title="地图巡礼｜FOLIO 折页",
                description="在地图上标记文学足迹，浏览所有人的巡礼。",
                body_class="page-tour-globe",
                boot={"mine": mine, "isAuthed": bool(user), "role": user_role(request)},
            ),
        )

    @app.get("/tours/new")
    def tour_new_page(request: Request, title: str = ""):
        user = current_user(request)
        if not user:
            return RedirectResponse("/login?next=/tours/new", status_code=303)
        return templates.TemplateResponse(
            request,
            "tour_new.html",
            base_ctx(
                request,
                title="创建巡礼地图｜FOLIO 折页",
                description="选择地图范围，创建属于你的文学巡礼。",
                scopes=SCOPES,
                error="",
                prefill=(title or "").strip()[:60],
            ),
        )

    @app.post("/tours/new")
    async def tour_new_post(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        form = await request.form()
        require_csrf(request, str(form.get("csrf") or ""))
        rate_limit(request, "tour-create")
        title = re.sub(r"\s+", " ", str(form.get("title") or "")).strip()[:160]
        scope = str(form.get("scope") or "world").strip().lower()
        if scope not in SCOPES:
            scope = "world"
        if len(title) < 2:
            return templates.TemplateResponse(
                request,
                "tour_new.html",
                base_ctx(request, title="创建巡礼地图｜FOLIO 折页", description="", scopes=SCOPES, error="请给巡礼地图起一个名字。"),
                status_code=400,
            )
        lat, lon, zoom = SCOPE_DEFAULT_VIEW[scope]
        row = TourMap(
            owner_user_id=user.id,
            slug=_unique_slug(db, title),
            title=title,
            scope=scope,
            center_lat=lat,
            center_lon=lon,
            zoom=zoom,
            visibility="private",
            status="draft",
        )
        db.add(row)
        db.flush()
        defaults = CHINA_CATEGORIES if scope == "china" else WORLD_CATEGORIES
        for i, (label, color) in enumerate(defaults):
            db.add(TourStopCategory(map_id=row.id, label=label, color=color, kind="auto", order_index=i))
        db.commit()
        return RedirectResponse(f"/tours/{row.slug}/edit", status_code=303)

    @app.get("/tours/{slug}/edit")
    def tour_edit_page(slug: str, request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        if not user:
            return RedirectResponse(f"/login?next=/tours/{slug}/edit", status_code=303)
        row = _own_tour(db, slug, request)
        return templates.TemplateResponse(
            request,
            "tour_edit.html",
            base_ctx(
                request,
                title=f"编辑《{row.title}》｜地图巡礼｜FOLIO 折页",
                description="在地图上标记你的文学足迹。",
                tour=pack_tour(db, row, is_owner=True, viewer_id=user.id),
            ),
        )

    @app.get("/tours/{slug}")
    def tour_detail_page(slug: str, request: Request, db: Session = Depends(get_db)):
        row = _viewable_tour(db, slug, request)
        user = current_user(request)
        is_owner = bool(user and row.owner_user_id == user.id)
        if row.visibility == "public" and not is_owner:
            row.view_count = (row.view_count or 0) + 1
            db.commit()
        return templates.TemplateResponse(
            request,
            "tour_detail.html",
            base_ctx(
                request,
                title=f"{row.title}｜地图巡礼｜FOLIO 折页",
                description=row.description or row.subtitle or "一张由读者创建的文学巡礼地图。",
                tour=pack_tour(db, row, is_owner=is_owner, viewer_id=user.id if user else None),
            ),
        )

    # ---- APIs -------------------------------------------------------------

    @app.get("/api/tours/globe")
    def api_globe(request: Request, db: Session = Depends(get_db)):
        tours = (
            db.query(TourMap)
            .filter(TourMap.visibility == "public", TourMap.status == "published", TourMap.deleted_at.is_(None))
            .order_by(TourMap.updated_at.desc())
            .limit(300)
            .all()
        )
        user = current_user(request)
        mine, published = [], []
        if user:
            for m in db.query(TourMap).filter(TourMap.owner_user_id == user.id, TourMap.deleted_at.is_(None)).order_by(TourMap.updated_at.desc()).all():
                item = {
                    "slug": m.slug, "title": m.title, "kind": m.kind or "custom", "scope": m.scope,
                    "stop_count": m.stop_count, "view_count": m.view_count,
                    "visibility": m.visibility, "status": m.status,
                }
                (published if m.visibility == "public" else mine).append(item)
        tour_ids = [t.id for t in tours]
        owner_ids = {t.owner_user_id for t in tours}
        owners = {u.id: u for u in db.query(User).filter(User.id.in_(owner_ids)).all()} if owner_ids else {}
        out_tours, points = [], []
        if tour_ids:
            cats_by_map: dict[int, list] = {}
            for c in db.query(TourStopCategory).filter(TourStopCategory.map_id.in_(tour_ids)).all():
                cats_by_map.setdefault(c.map_id, []).append(
                    {"id": c.id, "label": c.label, "color": c.color, "kind": c.kind or "auto"}
                )
            stops_by_map: dict[int, list] = {}
            for s in db.query(TourStop).filter(TourStop.map_id.in_(tour_ids)).all():
                stops_by_map.setdefault(s.map_id, []).append(s)
            for t in tours:
                out_tours.append({
                    "slug": t.slug, "title": t.title, "subtitle": t.subtitle, "scope": t.scope,
                    "kind": t.kind or "custom",
                    "stop_count": t.stop_count, "view_count": t.view_count,
                    "is_owner": bool(user and t.owner_user_id == user.id),
                    "owner_name": t.author_name or ((owners[t.owner_user_id].nickname or owners[t.owner_user_id].username)
                    if t.owner_user_id in owners else ""),
                    "owner_avatar": owners[t.owner_user_id].avatar_url if t.owner_user_id in owners else "",
                    "tags": [x for x in (t.tags or "").split(",") if x],
                    "categories": cats_by_map.get(t.id, []),
                })
                for s in stops_by_map.get(t.id, []):
                    points.append({
                        "tour": t.slug, "title": t.title, "lat": s.lat, "lon": s.lon,
                        "level": s.level or "city", "category_id": s.category_id, "tag_id": s.tag_id,
                        "place_name": s.place_name, "city": s.city, "country": s.country,
                        "note": s.note, "media_url": s.media_url, "book_id": s.book_id, "author_id": s.author_id, "id": s.id,
                    })
        return {"tours": out_tours, "points": points, "mine": mine, "published": published}

    @app.get("/api/tours/search")
    def api_search(q: str = "", db: Session = Depends(get_db)):
        keyword = (q or "").strip()
        if not keyword:
            return {"tours": [], "books": [], "authors": [], "genres": []}
        like = f"%{keyword}%"
        tours = (
            db.query(TourMap)
            .filter(
                TourMap.visibility == "public", TourMap.status == "published",
                or_(TourMap.title.ilike(like), TourMap.subtitle.ilike(like), TourMap.tags.ilike(like)),
            )
            .order_by(TourMap.updated_at.desc())
            .limit(10)
            .all()
        )
        books = (
            db.query(Book)
            .filter(or_(Book.original_title.ilike(like), Book.chinese_title.ilike(like), Book.isbn13.ilike(like)))
            .limit(8)
            .all()
        )
        authors = db.query(Author).filter(Author.name.ilike(like)).limit(8).all()
        genres = [g for g in GENRES if keyword in g][:8]

        linked: dict[int, list] = {}
        book_ids = [b.id for b in books]
        if book_ids:
            rows = (
                db.query(TourStop.book_id, TourMap.slug, TourMap.title)
                .join(TourMap, TourMap.id == TourStop.map_id)
                .filter(
                    TourStop.book_id.in_(book_ids),
                    TourMap.visibility == "public", TourMap.status == "published",
                )
                .all()
            )
            for bid, slug, title in rows:
                linked.setdefault(bid, []).append({"slug": slug, "title": title})

        author_ids = [a.id for a in authors]
        linked_authors: dict[int, list] = {}
        if author_ids:
            rows = (
                db.query(TourMap.ref_id, TourMap.slug, TourMap.title)
                .filter(TourMap.kind == "author", TourMap.ref_id.in_(author_ids), TourMap.visibility == "public")
                .all()
            )
            for rid, slug, title in rows:
                linked_authors.setdefault(rid, []).append({"slug": slug, "title": title})

        # entries (stops) matching by place / city / admin1 / country / note
        stop_rows = (
            db.query(TourStop, TourMap)
            .join(TourMap, TourMap.id == TourStop.map_id)
            .filter(
                TourStop.deleted_at.is_(None),
                TourMap.deleted_at.is_(None),
                TourMap.visibility == "public",
                TourMap.status == "published",
                or_(
                    TourStop.place_name.ilike(like),
                    TourStop.city.ilike(like),
                    TourStop.admin1.ilike(like),
                    TourStop.country.ilike(like),
                    TourStop.note.ilike(like),
                ),
            )
            .order_by(TourMap.updated_at.desc(), TourStop.order_index.asc())
            .limit(12)
            .all()
        )
        stop_cat_ids = {s.category_id for s, _ in stop_rows if s.category_id}
        stop_cats = {
            c.id: c.label
            for c in db.query(TourStopCategory).filter(TourStopCategory.id.in_(stop_cat_ids)).all()
        } if stop_cat_ids else {}
        stop_items = [
            {
                "map_slug": m.slug,
                "map_title": m.title,
                "stop_id": s.id,
                "place_name": s.place_name or s.city or "",
                "country": s.country or "",
                "admin1": s.admin1 or "",
                "region": stop_cats.get(s.category_id, ""),
                "snippet": (s.note or "").strip().replace("\n", " ")[:80],
                "lat": s.lat,
                "lon": s.lon,
            }
            for s, m in stop_rows
        ]

        # places (with their literary footnote) matching by name / city / country / footnote
        place_rows = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                or_(TourPlace.status == "published", TourPlace.status == "disputed"),
                or_(
                    TourPlace.name.ilike(like),
                    TourPlace.city_key.ilike(like),
                    TourPlace.country.ilike(like),
                    TourPlace.footnote.ilike(like),
                ),
            )
            .order_by((TourPlace.like_count * 3 + TourPlace.view_count).desc())
            .limit(12)
            .all()
        )
        place_items = [
            {
                "id": p.id, "name": p.name, "level": p.level,
                "city": p.city_key or "", "country": p.country or "",
                "snippet": (p.footnote or "").strip().replace("\n", " ")[:80],
                "lat": p.lat, "lon": p.lon,
            }
            for p in place_rows
        ]

        return {
            "tours": [{"slug": t.slug, "title": t.title, "scope": t.scope, "stop_count": t.stop_count} for t in tours],
            "stops": stop_items,
            "places": place_items,
            "books": [
                {"id": b.id, "slug": b.slug, "title": b.original_title, "chinese": b.chinese_title,
                 "linked_tours": linked.get(b.id, [])}
                for b in books
            ],
            "authors": [
                {"id": a.id, "name": a.name, "linked_tours": linked_authors.get(a.id, [])}
                for a in authors
            ],
            "genres": genres,
        }

    @app.post("/api/tours/collection")
    def api_create_collection(payload: CollectionIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "tour-create")
        kind = payload.kind if payload.kind in ("author", "book", "region", "genre", "custom") else "custom"
        visibility = "private" if payload.visibility == "private" else "public"
        scope = payload.scope if payload.scope in SCOPES else "world"
        title = (payload.title or "").strip()[:160]
        ref_id = payload.ref_id
        if kind == "author" and ref_id:
            author = db.query(Author).filter(Author.id == ref_id).one_or_none()
            if not author:
                raise HTTPException(404, "没有找到这位作者。")
            title = author.name
        elif kind == "book" and ref_id:
            book = db.query(Book).filter(Book.id == ref_id).one_or_none()
            if not book:
                raise HTTPException(404, "没有找到这本书。")
            title = (book.chinese_title or book.original_title)
        if len(title) < 1:
            raise HTTPException(400, "请填写巡礼名称。")
        # Public author/book collections are shared — join the existing one.
        if visibility == "public" and kind in ("author", "book") and ref_id:
            existing = (
                db.query(TourMap)
                .filter(TourMap.kind == kind, TourMap.ref_id == ref_id, TourMap.visibility == "public")
                .order_by(TourMap.id.asc())
                .first()
            )
            if existing:
                return pack_tour(db, existing, is_owner=(existing.owner_user_id == user.id))
        lat, lon, zoom = SCOPE_DEFAULT_VIEW[scope]
        row = TourMap(
            owner_user_id=user.id,
            slug=_unique_slug(db, title),
            title=title,
            scope=scope,
            kind=kind,
            ref_id=ref_id,
            center_lat=lat, center_lon=lon, zoom=zoom,
            visibility=visibility,
            status="published" if visibility == "public" else "draft",
            published_at=datetime.utcnow() if visibility == "public" else None,
        )
        db.add(row)
        db.flush()
        defaults = CHINA_CATEGORIES if scope == "china" else WORLD_CATEGORIES
        for i, (label, color) in enumerate(defaults):
            db.add(TourStopCategory(map_id=row.id, label=label, color=color, kind="auto", order_index=i))
        db.commit()
        return pack_tour(db, row, is_owner=True, viewer_id=user.id)

    @app.get("/api/tours/places")
    def api_places(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        rows = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                or_(TourPlace.status == "published", TourPlace.status == "disputed"),
            )
            .order_by((TourPlace.like_count * 3 + TourPlace.view_count).desc())
            .limit(400)
            .all()
        )
        return {"places": [_place_pack(db, p, user) for p in rows]}

    @app.post("/api/tours/collection-from-places")
    def api_collection_from_places(
        payload: CollectionFromPlacesIn, request: Request, db: Session = Depends(get_db)
    ):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "tour-create")
        title = (payload.title or "").strip()[:160]
        if not title:
            raise HTTPException(400, "请填写合集名称。")
        ids = _clean_ids(payload.place_ids)
        if not ids:
            raise HTTPException(400, "请先选择地点。")
        places = (
            db.query(TourPlace)
            .filter(TourPlace.id.in_(ids), TourPlace.deleted_at.is_(None))
            .all()
        )
        if not places:
            raise HTTPException(400, "没有可用的地点。")
        lats = [p.lat for p in places if p.lat is not None]
        lons = [p.lon for p in places if p.lon is not None]
        row = TourMap(
            owner_user_id=user.id, slug=_unique_slug(db, title), title=title,
            scope="world", kind="custom",
            center_lat=(sum(lats) / len(lats) if lats else 22.0),
            center_lon=(sum(lons) / len(lons) if lons else 8.0),
            zoom=3, visibility="private", status="draft",
        )
        db.add(row)
        db.flush()
        for i, p in enumerate(places):
            db.add(TourStop(
                map_id=row.id, user_id=user.id, place_id=p.id, lat=p.lat, lon=p.lon,
                level=p.level or "city", place_name=p.name, country=p.country or "",
                admin1=p.admin1 or "", city=p.city_key or "", note=p.footnote or "",
                order_index=i + 1,
            ))
        db.flush()
        row.stop_count = len(places)
        db.commit()
        return {"ok": True, "slug": row.slug, "title": row.title}

    @app.get("/api/tours/places/mine")
    def api_my_places(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        rows = (
            db.query(TourPlace)
            .filter(TourPlace.created_by == user.id, TourPlace.deleted_at.is_(None))
            .order_by(TourPlace.created_at.desc())
            .limit(200)
            .all()
        )
        return {"places": [_place_pack(db, p, user) for p in rows]}

    @app.get("/api/tours/places/pending")
    def api_places_pending(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                or_(TourPlace.status.in_(("pending", "disputed")), TourPlace.delete_requested.is_(True)),
            )
            .order_by(TourPlace.created_at.asc())
            .limit(200)
            .all()
        )
        return {"places": [_place_pack(db, p) for p in rows]}

    @app.get("/api/tours/places/auto")
    def api_places_auto(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                TourPlace.status == "published",
                TourPlace.auto_approved.is_(True),
            )
            .order_by(TourPlace.created_at.desc())
            .limit(200)
            .all()
        )
        return {"places": [_place_pack(db, p) for p in rows]}

    @app.get("/api/tours/places/reports")
    def api_place_reports(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = (
            db.query(TourPlaceReport)
            .filter(TourPlaceReport.status == "open")
            .order_by(TourPlaceReport.created_at.asc())
            .limit(200)
            .all()
        )
        out = []
        for r in rows:
            p = db.query(TourPlace).filter(TourPlace.id == r.place_id).one_or_none()
            out.append({
                "id": r.id, "place_id": r.place_id,
                "place_name": p.name if p else "", "reason": r.reason,
                "created_at": r.created_at.isoformat(),
            })
        return {"reports": out}

    @app.post("/api/tours/places/{pid}/review")
    async def api_place_review(pid: int, request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = current_user(request)
        place = db.query(TourPlace).filter(TourPlace.id == pid, TourPlace.deleted_at.is_(None)).one_or_none()
        if not place:
            raise HTTPException(404)
        action = body.get("action")
        reason = (body.get("reason") or "").strip()[:400]
        if action == "approve":
            place.status = "published"; place.reject_reason = ""; place.delete_requested = False
        elif action == "reject":
            place.status = "rejected"; place.reject_reason = reason; place.delete_requested = False
        elif action == "dispute":
            place.status = "disputed"; place.reject_reason = reason
        elif action == "delete":
            place.deleted_at = datetime.utcnow(); place.status = "deleted"; place.delete_requested = False
        else:
            raise HTTPException(400, "未知操作。")
        place.reviewed_by = user.id if user else None
        place.reviewed_at = datetime.utcnow()
        place.updated_at = datetime.utcnow()
        place.auto_approved = False  # any human review clears the auto flag
        db.add(TourPlaceReview(
            place_id=pid, reviewer_id=user.id if user else None, action=action, reason=reason
        ))
        if place.created_by and (not user or place.created_by != user.id):
            label = {"approve": "已通过", "reject": "被驳回", "dispute": "标记为待核实"}.get(action, action)
            db.add(Notification(
                user_id=place.created_by, type="place_review",
                actor_name="编辑部", title=f"你添加的地点「{place.name}」{label}",
                message=reason or "",
            ))
        db.commit()
        return {"ok": True, "status": place.status}

    @app.post("/api/tours/places/{pid}/merge")
    async def api_place_merge(pid: int, request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = current_user(request)
        src = db.query(TourPlace).filter(TourPlace.id == pid, TourPlace.deleted_at.is_(None)).one_or_none()
        dst = db.query(TourPlace).filter(
            TourPlace.id == body.get("target_id"), TourPlace.deleted_at.is_(None)
        ).one_or_none()
        if not src or not dst or src.id == dst.id:
            raise HTTPException(400, "合并目标无效。")
        db.query(TourStop).filter(TourStop.place_id == src.id).update(
            {TourStop.place_id: dst.id}, synchronize_session=False
        )
        existing_likes = {l.user_id for l in db.query(TourPlaceLike).filter(TourPlaceLike.place_id == dst.id).all()}
        for l in db.query(TourPlaceLike).filter(TourPlaceLike.place_id == src.id).all():
            if l.user_id in existing_likes:
                db.delete(l)
            else:
                l.place_id = dst.id; existing_likes.add(l.user_id)
        existing_books = {r.book_id for r in db.query(TourPlaceBook).filter(TourPlaceBook.place_id == dst.id).all()}
        for r in db.query(TourPlaceBook).filter(TourPlaceBook.place_id == src.id).all():
            if r.book_id in existing_books:
                db.delete(r)
            else:
                r.place_id = dst.id; existing_books.add(r.book_id)
        dst.view_count = (dst.view_count or 0) + (src.view_count or 0)
        dst.like_count = (dst.like_count or 0) + (src.like_count or 0)
        if not dst.footnote and src.footnote:
            dst.footnote = src.footnote
        src.merged_into_id = dst.id
        src.status = "rejected"
        src.reviewed_by = user.id if user else None
        src.reviewed_at = datetime.utcnow()
        db.add(TourPlaceReview(
            place_id=src.id, reviewer_id=user.id if user else None,
            action="merge", reason=f"merged into {dst.id}",
        ))
        db.commit()
        return {"ok": True, "merged_into": dst.id}

    @app.post("/api/tours/places/{pid}/delete")
    async def api_delete_place(pid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        place = db.query(TourPlace).filter(
            TourPlace.id == pid, TourPlace.deleted_at.is_(None)
        ).one_or_none()
        if not place:
            raise HTTPException(404)
        staff = user_role(request) in ("admin", "editor")
        if not (staff or place.created_by == user.id):
            raise HTTPException(403, "只能删除自己添加的地点。")
        if (place.status or "") == "published" and not staff:
            # deleting a published place needs review
            place.delete_requested = True
            place.updated_at = datetime.utcnow()
            db.add(TourPlaceReview(
                place_id=pid, reviewer_id=user.id, action="delete_request", reason="",
            ))
            db.commit()
            return {"ok": True, "pending": True}
        place.deleted_at = datetime.utcnow()
        place.status = "deleted"
        db.commit()
        return {"ok": True, "pending": False}

    @app.post("/api/tours/places/{pid}/report")
    async def api_place_report(pid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        rate_limit(request, "place-report")
        user = current_user(request)
        place = db.query(TourPlace).filter(TourPlace.id == pid, TourPlace.deleted_at.is_(None)).one_or_none()
        if not place:
            raise HTTPException(404)
        reason = (body.get("reason") or "").strip()[:500]
        if len(reason) < 3:
            raise HTTPException(400, "请填写举报原因。")
        db.add(TourPlaceReport(place_id=pid, user_id=user.id if user else None, reason=reason))
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/places")
    def api_create_place(payload: PlaceIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "place-create")
        name = (payload.name or "").strip()[:120]
        address = (payload.address or "").strip()[:240]
        desc = (payload.description or "").strip()[:2000]
        source = (payload.source_url or "").strip()[:400]
        photos = [u for u in (payload.photos or []) if isinstance(u, str) and u][:3]
        book_ids = _clean_ids(payload.book_ids)[:10]
        if payload.lat is None or payload.lon is None:
            raise HTTPException(400, "请在地图上选择精确坐标。")
        lat, lon = float(payload.lat), float(payload.lon)
        is_draft = bool(payload.draft)
        if is_draft:
            name = name or "未命名地点"
        else:
            if len(name) < 2:
                raise HTTPException(400, "请填写地点名称。")
            # duplicate check: same name within ~150 m
            for cand in db.query(TourPlace).filter(
                TourPlace.name == name, TourPlace.deleted_at.is_(None)
            ).all():
                if abs((cand.lat or 0) - lat) <= 0.0015 and abs((cand.lon or 0) - lon) <= 0.0015:
                    raise HTTPException(409, f"附近已有同名地点「{name}」，请确认是否重复。")
        staff = user_role(request) in ("admin", "editor")
        trusted = (getattr(user, "trust_level", 0) or 0) >= 1
        auto_ok, _auto_reason = _place_auto_ok(name, address, desc, source, photos, book_ids, lat, lon)
        if is_draft:
            status, auto_approved = "draft", False
        elif staff or trusted:
            status, auto_approved = "published", False
        elif auto_ok:
            status, auto_approved = "published", True  # auto-published, staff may re-check
        else:
            status, auto_approved = "pending", False
        level = payload.level if payload.level in ("city", "town", "street", "spot") else "spot"
        key = _spot_key(lat, lon) if level == "spot" else _place_key(level, lat, lon)
        place = db.query(TourPlace).filter(TourPlace.key == key).one_or_none()
        if place:
            place.name = name or place.name
            place.address = address or place.address
            place.footnote = desc or place.footnote
            place.source_url = source or place.source_url
            place.city_key = (payload.city_key or "").strip()[:200] or place.city_key
            if photos:
                place.photos = json.dumps(photos, ensure_ascii=False)
            place.status = status
            place.auto_approved = auto_approved
            place.reject_reason = ""
            place.updated_at = datetime.utcnow()
        else:
            place = TourPlace(
                key=key, name=name, level=level, lat=lat, lon=lon,
                country=(payload.country or "").strip()[:80],
                admin1=(payload.admin1 or "").strip()[:80],
                city_key=(payload.city_key or "").strip()[:200],
                address=address, source_url=source,
                footnote=desc, photos=json.dumps(photos, ensure_ascii=False),
                status=status, auto_approved=auto_approved,
                created_by=user.id,
            )
            db.add(place)
            db.flush()
        for bid in book_ids:
            if not db.query(TourPlaceBook).filter(
                TourPlaceBook.place_id == place.id, TourPlaceBook.book_id == bid
            ).first():
                db.add(TourPlaceBook(place_id=place.id, book_id=bid))
        db.commit()
        return {"ok": True, "place": _place_pack(db, place, user), "status": place.status}

    @app.post("/api/tours/places/{pid}/update")
    def api_update_place(pid: int, payload: PlaceIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "place-update")
        place = db.query(TourPlace).filter(
            TourPlace.id == pid, TourPlace.deleted_at.is_(None)
        ).one_or_none()
        if not place:
            raise HTTPException(404)
        is_owner = place.created_by == user.id
        staff = user_role(request) in ("admin", "editor")
        if not (is_owner or staff):
            raise HTTPException(403, "只能修改自己添加的地点。")
        name = (payload.name or "").strip()[:120]
        address = (payload.address or "").strip()[:240]
        desc = (payload.description or "").strip()[:2000]
        source = (payload.source_url or "").strip()[:400]
        photos = [u for u in (payload.photos or []) if isinstance(u, str) and u][:3]
        book_ids = _clean_ids(payload.book_ids)[:10]
        is_draft = bool(payload.draft)
        if not is_draft and len(name) < 2:
            raise HTTPException(400, "请填写地点名称。")
        place.name = name or place.name
        place.address = address or place.address
        place.footnote = desc or place.footnote
        place.source_url = source or place.source_url
        if payload.lat is not None and payload.lon is not None:
            place.lat = float(payload.lat)
            place.lon = float(payload.lon)
        if payload.city_key:
            place.city_key = payload.city_key.strip()[:200]
        if photos:
            place.photos = json.dumps(photos, ensure_ascii=False)
        place.updated_at = datetime.utcnow()
        db.query(TourPlaceBook).filter(TourPlaceBook.place_id == pid).delete(synchronize_session=False)
        for bid in book_ids:
            db.add(TourPlaceBook(place_id=pid, book_id=bid))
        was_published = (place.status or "") == "published"
        if is_draft:
            place.status = "draft"
            place.auto_approved = False
            place.reject_reason = ""
        elif staff:
            # staff (including the owner) always publish directly
            place.status = "published"
            place.auto_approved = False
            place.reject_reason = ""
            if not is_owner and place.created_by:
                db.add(Notification(
                    user_id=place.created_by, type="place_review", actor_name="编辑部",
                    title=f"你的地点「{place.name}」已被编辑部修改",
                    message=desc[:120],
                ))
        elif is_owner and was_published:
            # owner editing an already-published place needs review
            place.status = "pending"
            place.auto_approved = False
            place.reject_reason = ""
        else:
            auto_ok, _r = _place_auto_ok(name, address, desc, source, photos, book_ids, place.lat, place.lon)
            place.status = "published" if auto_ok else "pending"
            place.auto_approved = bool(auto_ok)
            place.reject_reason = ""
        place.reviewed_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": place.status, "place": _place_pack(db, place, user)}

    @app.get("/api/tours/places/{pid}/stops")
    def api_place_stops(pid: int, db: Session = Depends(get_db)):
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        rows = (
            db.query(TourStop, TourMap)
            .join(TourMap, TourMap.id == TourStop.map_id)
            .filter(
                TourStop.place_id == pid,
                TourStop.deleted_at.is_(None),
                TourMap.deleted_at.is_(None),
                TourMap.visibility == "public",
                TourMap.status == "published",
            )
            .order_by(TourMap.title.asc(), TourStop.order_index.asc())
            .all()
        )
        collections, stops, seen = [], [], set()
        for s, m in rows:
            if m.slug not in seen:
                seen.add(m.slug)
                collections.append({"slug": m.slug, "title": m.title})
            stops.append({
                "map_slug": m.slug, "map_title": m.title,
                "stop_id": s.id, "place_name": s.place_name or s.city or "",
            })
        return {"name": place.name, "collections": collections, "stops": stops}

    @app.get("/api/tours/places/{pid}")
    def api_place_detail(pid: int, request: Request, db: Session = Depends(get_db)):
        p = db.query(TourPlace).filter(TourPlace.id == pid, TourPlace.deleted_at.is_(None)).one_or_none()
        if not p:
            raise HTTPException(404)
        return _place_pack(db, p, current_user(request))

    @app.post("/api/tours/places/{pid}/view")
    def api_place_view(pid: int, db: Session = Depends(get_db)):
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        place.view_count = (place.view_count or 0) + 1
        db.commit()
        return {"ok": True, "view_count": place.view_count}

    @app.post("/api/tours/places/{pid}/like")
    async def api_place_like(pid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        existing = (
            db.query(TourPlaceLike)
            .filter(TourPlaceLike.place_id == pid, TourPlaceLike.user_id == user.id)
            .one_or_none()
        )
        if existing:
            db.delete(existing)
            place.like_count = max(0, (place.like_count or 0) - 1)
            liked = False
        else:
            db.add(TourPlaceLike(place_id=pid, user_id=user.id))
            place.like_count = (place.like_count or 0) + 1
            liked = True
        db.commit()
        return {"ok": True, "liked": liked, "like_count": place.like_count}

    @app.post("/api/tours/places/{pid}/footnote")
    async def api_place_footnote(pid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        require_user(request)
        rate_limit(request, "place-footnote")
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        place.footnote = (body.get("footnote") or "").strip()[:2000]
        place.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "footnote": place.footnote}

    @app.post("/api/tours/places/{pid}/photo")
    async def api_place_photo(
        pid: int, request: Request,
        file: UploadFile = File(...), csrf: str = Form(default=""),
        db: Session = Depends(get_db),
    ):
        require_csrf(request, csrf)
        user = require_user(request)
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        if place.created_by != user.id:
            raise HTTPException(403, "只有该地点的创建者可以上传照片。")
        arr = _parse_photos(place.photos, "")
        if len(arr) >= 3:
            raise HTTPException(400, "每个地点最多 3 张照片。")
        data = await file.read()
        if len(data) > PHOTO_MAX_BYTES:
            raise HTTPException(400, "照片请小于 8MB。")
        if len(data) < 24:
            raise HTTPException(400, "图片文件不完整。")
        ext = _sniff_ext(data)
        name = f"place{place.id}-{secrets.token_hex(8)}.{ext}"
        try:
            url = persist_user_upload(
                "tours", name, data, local_dir=TOUR_UPLOAD_DIR, content_type=content_type_for_ext(ext)
            )
        except Exception as exc:
            raise HTTPException(502, "照片上传失败，请稍后重试。") from exc
        arr.append(url)
        place.photos = json.dumps(arr)
        place.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "photos": arr}

    @app.post("/api/tours/places/{pid}/photo/delete")
    async def api_place_photo_delete(pid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        place = db.query(TourPlace).filter(TourPlace.id == pid).one_or_none()
        if not place:
            raise HTTPException(404)
        if place.created_by != user.id:
            raise HTTPException(403, "只有该地点的创建者可以删除照片。")
        url = (body.get("url") or "").strip()
        arr = [u for u in _parse_photos(place.photos, "") if u != url]
        place.photos = json.dumps(arr)
        db.commit()
        return {"ok": True, "photos": arr}

    @app.get("/api/tours/stops/{sid}/notes")
    def api_stop_notes(sid: int, request: Request, db: Session = Depends(get_db)):
        stop = db.query(TourStop).filter(TourStop.id == sid).one_or_none()
        if not stop:
            raise HTTPException(404)
        user = current_user(request)
        rows = [n for n in db.query(TourStopNote).filter(TourStopNote.stop_id == sid).all()
                if (not n.is_private) or (user and n.user_id == user.id)]

        def score(n):
            return (n.like_count or 0) * 3 + (n.view_count or 0)

        mine = [n for n in rows if user and n.user_id == user.id]
        others = sorted([n for n in rows if not (user and n.user_id == user.id)], key=score, reverse=True)
        liked = {
            l.note_id for l in db.query(TourStopNoteLike).filter(TourStopNoteLike.user_id == user.id).all()
        } if user else set()
        uids = {n.user_id for n in rows if n.user_id}
        users = {u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()} if uids else {}

        def pack(n):
            u = users.get(n.user_id)
            return {
                "id": n.id, "body": n.body,
                "author": (u.nickname or u.username) if u else (n.author_name or "访客"),
                "avatar": (u.avatar_url or "") if u else "",
                "like_count": n.like_count, "liked": n.id in liked,
                "mine": bool(user and n.user_id == user.id),
                "created_at": n.created_at.isoformat(),
            }

        intro_user = db.query(User).filter(User.id == stop.user_id).one_or_none() if stop.user_id else None
        return {
            "intro": {
                "body": stop.note or "",
                "author": (intro_user.nickname or intro_user.username) if intro_user else "",
                "is_creator": bool(user and stop.user_id == user.id),
            },
            "notes": [pack(n) for n in (mine + others)],
        }

    @app.post("/api/tours/stops/{sid}/notes")
    def api_add_stop_note(sid: int, payload: NoteIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "stop-note")
        stop = db.query(TourStop).filter(TourStop.id == sid).one_or_none()
        if not stop:
            raise HTTPException(404)
        body = (payload.body or "").strip()[:2000]
        if len(body) < 1:
            raise HTTPException(400, "请写点什么。")
        note = TourStopNote(
            stop_id=sid, user_id=user.id,
            author_name=(user.nickname or user.username or "")[:40], body=body,
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return {"ok": True, "note": {
            "id": note.id, "body": note.body, "author": note.author_name,
            "avatar": user.avatar_url or "", "like_count": 0, "liked": False, "mine": True,
            "created_at": note.created_at.isoformat(),
        }}

    @app.post("/api/tours/notes/{nid}/like")
    async def api_note_like(nid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        note = db.query(TourStopNote).filter(TourStopNote.id == nid).one_or_none()
        if not note:
            raise HTTPException(404)
        existing = db.query(TourStopNoteLike).filter(
            TourStopNoteLike.note_id == nid, TourStopNoteLike.user_id == user.id
        ).one_or_none()
        if existing:
            db.delete(existing)
            note.like_count = max(0, (note.like_count or 0) - 1)
            liked = False
        else:
            db.add(TourStopNoteLike(note_id=nid, user_id=user.id))
            note.like_count = (note.like_count or 0) + 1
            liked = True
        db.commit()
        return {"ok": True, "liked": liked, "like_count": note.like_count}

    @app.post("/api/tours/notes/{nid}/edit")
    def api_note_edit(nid: int, payload: NoteEditIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        note = db.query(TourStopNote).filter(TourStopNote.id == nid).one_or_none()
        if not note:
            raise HTTPException(404)
        if note.user_id != user.id:
            raise HTTPException(403, "只能修改自己的留言。")
        if payload.body is not None:
            body = payload.body.strip()[:2000]
            if body:
                note.body = body
        if payload.is_private is not None:
            note.is_private = bool(payload.is_private)
        note.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "body": note.body, "is_private": note.is_private}

    @app.post("/api/tours/notes/{nid}/delete")
    async def api_note_delete(nid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        note = db.query(TourStopNote).filter(TourStopNote.id == nid).one_or_none()
        if not note:
            raise HTTPException(404)
        if note.user_id != user.id:
            raise HTTPException(403, "只能删除自己的留言。")
        db.delete(note)
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/stops/{sid}/recommend")
    def api_stop_recommend(sid: int, payload: QuickRecIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        rate_limit(request, "tour-recommend")
        stop = db.query(TourStop).filter(TourStop.id == sid).one_or_none()
        if not stop:
            raise HTTPException(404)
        title = (payload.title or "").strip()[:150]
        if len(title) < 1:
            raise HTTPException(400, "请填写书名。")
        sub = BookSubmission(
            submission_number=next_number(db),
            visitor_id=getattr(request.state, "visitor_id", "") or "",
            user_id=user.id,
            nickname=(user.nickname or user.username or "")[:40],
            contact_email=(user.email or "")[:200],
            title=title, original_title=title,
            authors=(payload.authors or "").strip()[:100],
            introduction=(payload.note or "").strip()[:2000],
            recommendation_reason=(payload.note or "").strip()[:1000],
            cover_url=(payload.cover_url or "").strip()[:400],
            fuzzy=bool(payload.fuzzy),
            origin=f"地图巡礼 · {stop.place_name or stop.city or ''}"[:120],
            status="unassigned",
            submitted_at=datetime.utcnow(),
        )
        db.add(sub)
        db.commit()
        return {"ok": True, "submission": sub.submission_number, "fuzzy": sub.fuzzy}

    @app.get("/api/tours/pending")
    def api_pending(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = (
            db.query(TourMap)
            .filter(TourMap.status == "pending", TourMap.deleted_at.is_(None))
            .order_by(TourMap.updated_at.asc())
            .limit(200)
            .all()
        )
        stop_rows = (
            db.query(TourStop)
            .filter(TourStop.deleted_at.is_(None), TourStop.draft.isnot(None), TourStop.draft != "")
            .all()
        )
        stop_pending = []
        for s in stop_rows:
            try:
                d = json.loads(s.draft) if s.draft else {}
            except (ValueError, TypeError):
                d = {}
            if not d.get("_pending"):
                continue
            m = db.query(TourMap).filter(TourMap.id == s.map_id).one_or_none()
            stop_pending.append({
                "id": s.id,
                "map_slug": m.slug if m else "",
                "map_title": m.title if m else "",
                "place_name": s.place_name,
                "note": (d.get("note") or "")[:120],
                "book_count": len(_clean_ids(d.get("book_ids"))),
            })
        return {"pending": [
            {"slug": r.slug, "title": r.title, "kind": r.kind or "custom",
             "scope": r.scope, "stop_count": r.stop_count,
             "owner_name": r.author_name or ""}
            for r in rows
        ], "stop_pending": stop_pending}

    @app.post("/api/tours/stops/{sid}/review")
    async def api_stop_review(sid: int, request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        stop = db.query(TourStop).filter(TourStop.id == sid, TourStop.deleted_at.is_(None)).one_or_none()
        if not stop:
            raise HTTPException(404)
        d = json.loads(stop.draft) if stop.draft else {}
        if not d:
            raise HTTPException(400, "没有待审核的修改。")
        action = body.get("action")
        if action == "approve":
            editor = current_user(request)
            db.add(TourStopRevision(
                stop_id=sid, note=stop.note, author_id=stop.author_id,
                book_id=stop.book_id, book_ids=stop.book_ids, photos=stop.photos,
                editor_id=editor.id if editor else None,
            ))
            _apply_draft_to_stop(stop, d)
            stop.draft = ""
        elif action == "reject":
            stop.draft = ""
        else:
            raise HTTPException(400, "未知操作。")
        stop.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/{slug}/review")
    async def api_tour_review(slug: str, request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(TourMap).filter(TourMap.slug == slug, TourMap.deleted_at.is_(None)).one_or_none()
        if not row:
            raise HTTPException(404)
        action = body.get("action")
        if action == "approve":
            row.status = "published"
            row.visibility = "public"
            row.published_at = datetime.utcnow()
        elif action == "reject":
            row.status = "rejected"
            row.visibility = "private"
        else:
            raise HTTPException(400, "未知操作。")
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": row.status}

    @app.get("/api/tours/media/temp")
    def api_temp_media(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = (
            db.query(TourMedia)
            .filter(TourMedia.status == "temp")
            .order_by(TourMedia.created_at.asc())
            .limit(200)
            .all()
        )
        return {"media": [
            {"id": m.id, "url": m.url, "owner_id": m.owner_id, "created_at": m.created_at.isoformat()}
            for m in rows
        ]}

    @app.post("/api/tours/media/cleanup")
    async def api_media_cleanup(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        cutoff = datetime.utcnow() - timedelta(hours=24)
        rows = db.query(TourMedia).filter(TourMedia.status == "temp", TourMedia.created_at < cutoff).all()
        n = 0
        for m in rows:
            key = key_from_public_or_local_url(m.url, "tours")
            if key:
                delete_object(key)
            m.status = "deleted"
            n += 1
        db.commit()
        return {"ok": True, "cleaned": n}

    @app.get("/admin/tours")
    def admin_tours(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        pending = (
            db.query(TourMap)
            .filter(TourMap.status == "pending", TourMap.deleted_at.is_(None))
            .order_by(TourMap.updated_at.asc())
            .limit(100)
            .all()
        )
        temp = (
            db.query(TourMedia)
            .filter(TourMedia.status == "temp")
            .order_by(TourMedia.created_at.asc())
            .limit(100)
            .all()
        )
        stop_pending = []
        drafts = (
            db.query(TourStop)
            .filter(TourStop.deleted_at.is_(None), TourStop.draft.isnot(None), TourStop.draft != "")
            .order_by(TourStop.updated_at.asc())
            .limit(200)
            .all()
        )
        for s in drafts:
            try:
                d = json.loads(s.draft) if s.draft else {}
            except (ValueError, TypeError):
                d = {}
            if not d.get("_pending"):
                continue
            m = db.query(TourMap).filter(TourMap.id == s.map_id).one_or_none()
            stop_pending.append({
                "id": s.id,
                "map_slug": m.slug if m else "",
                "map_title": m.title if m else "",
                "place_name": s.place_name,
                "note": (d.get("note") or "")[:120],
                "book_count": len(_clean_ids(d.get("book_ids"))),
            })
        place_pending = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                or_(TourPlace.status.in_(("pending", "disputed")), TourPlace.delete_requested.is_(True)),
            )
            .order_by(TourPlace.created_at.asc())
            .limit(200)
            .all()
        )
        reports = (
            db.query(TourPlaceReport)
            .filter(TourPlaceReport.status == "open")
            .order_by(TourPlaceReport.created_at.asc())
            .limit(200)
            .all()
        )
        place_auto = (
            db.query(TourPlace)
            .filter(
                TourPlace.deleted_at.is_(None),
                TourPlace.merged_into_id.is_(None),
                TourPlace.status == "published",
                TourPlace.auto_approved.is_(True),
            )
            .order_by(TourPlace.created_at.desc())
            .limit(200)
            .all()
        )
        return templates.TemplateResponse(
            request,
            "admin_tours.html",
            base_ctx(
                request,
                title="巡礼审核｜FOLIO 折页",
                description="审核待审合集、待审地点、清理临时媒体。",
                pending=pending,
                stop_pending=stop_pending,
                place_pending=place_pending,
                place_auto=place_auto,
                reports=reports,
                temp=temp,
            ),
        )

    TRUST_LABELS = {
        0: "Lv0 · 新用户（需审核）", 1: "Lv1 · 可信（可直发）", 2: "Lv2 · 资深",
        3: "Lv3 · 版主", 4: "Lv4", 5: "Lv5", 6: "Lv6",
    }

    @app.get("/admin/users")
    def admin_users(request: Request, db: Session = Depends(get_db)):
        require_staff(request)
        rows = db.query(User).order_by(User.created_at.desc()).limit(500).all()
        return templates.TemplateResponse(
            request, "admin_users.html",
            base_ctx(
                request, title="用户信任等级｜FOLIO 折页",
                description="设置用户信任等级。", users=rows, trust_labels=TRUST_LABELS,
            ),
        )

    @app.post("/api/admin/users/{uid}/trust")
    async def api_set_trust(uid: int, request: Request, db: Session = Depends(get_db)):
        if user_role(request) != "admin":
            raise HTTPException(403, "仅管理员可设置信任等级。")
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = db.query(User).filter(User.id == uid).one_or_none()
        if not user:
            raise HTTPException(404)
        try:
            level = int(body.get("trust_level"))
        except (TypeError, ValueError):
            raise HTTPException(400, "等级无效。")
        user.trust_level = max(0, min(6, level))
        db.commit()
        return {"ok": True, "trust_level": user.trust_level}

    @app.get("/api/tours/trash")
    def api_trash(request: Request, db: Session = Depends(get_db)):
        user = require_user(request)
        staff = user_role(request) in ("admin", "editor")
        q = db.query(TourMap).filter(TourMap.deleted_at.isnot(None))
        if not staff:
            q = q.filter(TourMap.owner_user_id == user.id)
        rows = q.order_by(TourMap.deleted_at.desc()).limit(200).all()
        return {"trash": [
            {"slug": r.slug, "title": r.title, "kind": r.kind or "custom",
             "stop_count": r.stop_count, "deleted_at": r.deleted_at.isoformat() if r.deleted_at else ""}
            for r in rows
        ]}

    @app.post("/api/tours/{slug}/restore")
    async def api_restore(slug: str, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        row = db.query(TourMap).filter(TourMap.slug == slug, TourMap.deleted_at.isnot(None)).one_or_none()
        if not row:
            raise HTTPException(404)
        staff = user_role(request) in ("admin", "editor")
        if not (staff or row.owner_user_id == user.id):
            raise HTTPException(403, "只能恢复自己的合集。")
        row.deleted_at = None
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/media")
    async def api_media_upload(
        request: Request, file: UploadFile = File(...),
        csrf: str = Form(default=""), db: Session = Depends(get_db),
    ):
        require_csrf(request, csrf)
        user = require_user(request)
        rate_limit(request, "tour-media")
        data = await file.read()
        if len(data) > PHOTO_MAX_BYTES:
            raise HTTPException(400, "照片请小于 8MB。")
        if len(data) < 24:
            raise HTTPException(400, "图片文件不完整。")
        ext = _sniff_ext(data)
        name = f"m{user.id}-{secrets.token_hex(8)}.{ext}"
        try:
            url = persist_user_upload(
                "tours", name, data, local_dir=TOUR_UPLOAD_DIR, content_type=content_type_for_ext(ext)
            )
        except Exception as exc:
            raise HTTPException(502, "照片上传失败。") from exc
        media = TourMedia(owner_id=user.id, url=url, status="temp")
        db.add(media)
        db.commit()
        return {"ok": True, "id": media.id, "url": url}

    @app.post("/api/tours/{slug}/stops/{sid}/bind-media")
    def api_bind_media(slug: str, sid: int, payload: MediaBindIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        user = require_user(request)
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        media = db.query(TourMedia).filter(TourMedia.id.in_(payload.ids or [])).all()
        arr = _parse_photos(stop.photos, "")
        for m in media:
            if m.owner_id not in (None, user.id):
                continue
            if m.url not in arr:
                arr.append(m.url)
            m.stop_id = sid
            m.status = "attached"
        stop.photos = json.dumps(arr)
        if not stop.media_url and arr:
            stop.media_url = arr[0]
        stop.updated_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "photos": arr}

    @app.post("/api/tours/{slug}/stops/{sid}/draft")
    def api_stop_draft(slug: str, sid: int, payload: StopDraftIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        d = json.loads(stop.draft) if stop.draft else {}
        if payload.note is not None:
            d["note"] = (payload.note or "").strip()[:2000]
        if payload.author_id is not None:
            d["author_id"] = payload.author_id or None
        if payload.book_ids is not None:
            d["book_ids"] = _clean_ids(payload.book_ids)
            d.pop("book_id", None)
        elif payload.book_id is not None:
            d["book_ids"] = _clean_ids([payload.book_id])
            d.pop("book_id", None)
        if payload.photos is not None:
            d["photos"] = payload.photos
        d.pop("_pending", None)
        stop.draft = json.dumps(d, ensure_ascii=False)
        stop.updated_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "draft": d}

    @app.post("/api/tours/{slug}/stops/{sid}/submit")
    async def api_stop_submit(slug: str, sid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        d = json.loads(stop.draft) if stop.draft else {}
        if not d:
            raise HTTPException(400, "没有待提交的草稿。")
        staff = user_role(request) in ("admin", "editor")
        needs_review = row.visibility == "public" and not staff and row.owner_user_id != user.id
        if needs_review:
            d["_pending"] = True
            stop.draft = json.dumps(d, ensure_ascii=False)
            stop.updated_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            db.commit()
            return {"ok": True, "pending": True}
        db.add(TourStopRevision(
            stop_id=sid, note=stop.note, author_id=stop.author_id,
            book_id=stop.book_id, book_ids=stop.book_ids, photos=stop.photos, editor_id=user.id,
        ))
        _apply_draft_to_stop(stop, d)
        stop.draft = ""
        stop.updated_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "pending": False}

    @app.get("/api/tours/stops/{sid}/revisions")
    def api_stop_revisions(sid: int, request: Request, db: Session = Depends(get_db)):
        rows = (
            db.query(TourStopRevision)
            .filter(TourStopRevision.stop_id == sid)
            .order_by(TourStopRevision.created_at.desc())
            .limit(20)
            .all()
        )
        return {"revisions": [
            {"id": r.id, "note": r.note, "created_at": r.created_at.isoformat()}
            for r in rows
        ]}

    @app.post("/api/tours/stops/{sid}/rollback")
    async def api_stop_rollback(sid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        rev = db.query(TourStopRevision).filter(
            TourStopRevision.id == body.get("rev_id"), TourStopRevision.stop_id == sid
        ).one_or_none()
        if not rev:
            raise HTTPException(404)
        stop = db.query(TourStop).filter(TourStop.id == sid).one_or_none()
        if not stop:
            raise HTTPException(404)
        row = db.query(TourMap).filter(TourMap.id == stop.map_id).one_or_none()
        staff = user_role(request) in ("admin", "editor")
        allowed = (
            staff
            or (row and row.owner_user_id == user.id)
            or (row and row.visibility != "public" and stop.user_id == user.id)
        )
        if not allowed:
            raise HTTPException(403, "已公开合集的版本回滚需由合集创建者或编辑/管理员操作。")
        db.add(TourStopRevision(
            stop_id=sid, note=stop.note, author_id=stop.author_id,
            book_id=stop.book_id, book_ids=stop.book_ids, photos=stop.photos, editor_id=user.id,
        ))
        stop.note = rev.note
        stop.author_id = rev.author_id
        stop.book_id = rev.book_id
        stop.book_ids = rev.book_ids or (json.dumps([rev.book_id]) if rev.book_id else "")
        stop.photos = rev.photos
        arr = _parse_photos(rev.photos, "")
        if arr:
            stop.media_url = arr[0]
        stop.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}

    @app.get("/api/tours/{slug}")
    def api_tour(slug: str, request: Request, db: Session = Depends(get_db)):
        row = _viewable_tour(db, slug, request)
        user = current_user(request)
        return pack_tour(db, row, is_owner=bool(user and row.owner_user_id == user.id), viewer_id=user.id if user else None)

    @app.post("/api/tours/{slug}/stops")
    def api_add_stop(slug: str, payload: StopIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        rate_limit(request, "tour-stop")
        row = _contributable_tour(db, slug, request)
        if db.query(TourStop).filter(TourStop.map_id == row.id).count() >= MAX_STOPS:
            raise HTTPException(400, f"一个合集最多标记 {MAX_STOPS} 个地点。")
        order = (db.query(TourStop).filter(TourStop.map_id == row.id).count()) + 1
        country = (payload.country or "").strip()[:80]
        admin1 = (payload.admin1 or "").strip()[:80]
        level = payload.level if payload.level in ("country", "region", "city") else "city"
        stop = TourStop(
            map_id=row.id,
            user_id=current_user(request).id,
            category_id=_auto_category_id(db, row, country, admin1),
            tag_id=payload.tag_id,
            lat=float(payload.lat),
            lon=float(payload.lon),
            level=level,
            book_id=(_clean_ids(payload.book_ids or ([payload.book_id] if payload.book_id else [])) or [None])[0],
            book_ids=json.dumps(_clean_ids(payload.book_ids or ([payload.book_id] if payload.book_id else [])), ensure_ascii=False),
            author_id=payload.author_id,
            place_name=(payload.place_name or "").strip()[:120],
            country=country,
            admin1=admin1,
            city=(payload.city or "").strip()[:80],
            note=(payload.note or "").strip()[:2000],
            period=(payload.period or "").strip()[:40],
            order_index=order,
        )
        db.add(stop)
        place = _get_or_create_place(
            db, current_user(request).id, stop.place_name, payload.city, level,
            stop.lat, stop.lon, country, admin1,
        )
        stop.place_id = place.id
        # author/book collections auto-associate their subject
        if row.kind == "author" and row.ref_id and not stop.author_id:
            stop.author_id = row.ref_id
        elif row.kind == "book" and row.ref_id and not stop.book_id:
            stop.book_id = row.ref_id
            stop.book_ids = json.dumps([row.ref_id])
        row.updated_at = datetime.utcnow()
        db.flush()
        row.stop_count = db.query(TourStop).filter(TourStop.map_id == row.id).count()
        db.commit()
        return {"ok": True, "stop": pack_tour(db, row, viewer_id=current_user(request).id)["stops"][-1], "stop_count": row.stop_count}

    @app.post("/api/tours/{slug}/stops/{sid}")
    def api_update_stop(slug: str, sid: int, payload: StopPatch, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        if payload.place_name is not None:
            stop.place_name = payload.place_name.strip()[:120]
        if payload.note is not None:
            stop.note = payload.note.strip()[:2000]
        if payload.period is not None:
            stop.period = payload.period.strip()[:40]
        if payload.tag_id is not None:
            stop.tag_id = payload.tag_id or None
        if payload.book_ids is not None:
            ids = _clean_ids(payload.book_ids)
            stop.book_ids = json.dumps(ids, ensure_ascii=False)
            stop.book_id = ids[0] if ids else None
        elif payload.book_id is not None:
            ids = _clean_ids([payload.book_id])
            stop.book_ids = json.dumps(ids, ensure_ascii=False)
            stop.book_id = ids[0] if ids else None
        if payload.author_id is not None:
            stop.author_id = payload.author_id or None
        if payload.order_index is not None:
            stop.order_index = int(payload.order_index)
        stop.updated_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/{slug}/stops/{sid}/delete")
    async def api_delete_stop(slug: str, sid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        user = current_user(request)
        if not user:
            raise HTTPException(401, "请先登录。")
        stop = db.query(TourStop).filter(TourStop.id == sid, TourStop.map_id == row.id).one_or_none()
        if not stop:
            raise HTTPException(404)
        staff = user_role(request) in ("admin", "editor")
        allowed = staff or row.owner_user_id == user.id or (row.visibility != "public" and stop.user_id == user.id)
        if not allowed:
            raise HTTPException(403, "已公开合集的地点需由合集创建者或编辑/管理员删除。")
        stop.deleted_at = datetime.utcnow()
        db.flush()
        row.stop_count = db.query(TourStop).filter(TourStop.map_id == row.id).count()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "stop_count": row.stop_count}

    @app.post("/api/tours/{slug}/stops/{sid}/photo")
    async def api_stop_photo(
        slug: str,
        sid: int,
        request: Request,
        file: UploadFile = File(...),
        csrf: str = Form(default=""),
        db: Session = Depends(get_db),
    ):
        require_csrf(request, csrf)
        rate_limit(request, "tour-photo")
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        data = await file.read()
        if len(data) > PHOTO_MAX_BYTES:
            raise HTTPException(400, "照片请小于 8MB。")
        if len(data) < 24:
            raise HTTPException(400, "图片文件不完整。")
        ext = _sniff_ext(data)
        name = f"t{row.id}-{secrets.token_hex(8)}.{ext}"
        try:
            url = persist_user_upload(
                "tours", name, data, local_dir=TOUR_UPLOAD_DIR, content_type=content_type_for_ext(ext)
            )
        except Exception as exc:
            raise HTTPException(502, "照片上传失败，请稍后重试。") from exc
        arr = _parse_photos(stop.photos, "")
        arr.append(url)
        stop.photos = json.dumps(arr)
        if not stop.media_url:
            stop.media_url = url
        stop.updated_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "media_url": url, "photos": arr}

    @app.post("/api/tours/{slug}/stops/{sid}/photos/delete")
    async def api_delete_photo(slug: str, sid: int, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        stop = _editable_stop(db, row, sid, request)
        url = (body.get("url") or "").strip()
        arr = [u for u in _parse_photos(stop.photos, "") if u != url]
        stop.photos = json.dumps(arr)
        stop.media_url = arr[0] if arr else ""
        stop.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "photos": arr}

    @app.post("/api/tours/{slug}/categories")
    def api_add_category(slug: str, payload: CategoryIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        row = _own_tour(db, slug, request)
        label = (payload.label or "").strip()[:40]
        if not label:
            raise HTTPException(400, "请填写标签名称。")
        color = (payload.color or "#9BB3C9").strip()[:16]
        order = db.query(TourStopCategory).filter(TourStopCategory.map_id == row.id).count()
        cat = TourStopCategory(map_id=row.id, label=label, color=color, kind="custom", order_index=order)
        db.add(cat)
        db.flush()
        db.commit()
        return {"ok": True, "category": {"id": cat.id, "label": cat.label, "color": cat.color, "kind": "custom", "order": cat.order_index}}

    @app.post("/api/tours/{slug}/meta")
    def api_meta(slug: str, payload: MetaIn, request: Request, db: Session = Depends(get_db)):
        require_csrf(request, payload.csrf)
        row = _own_tour(db, slug, request)
        if payload.title is not None and payload.title.strip():
            row.title = payload.title.strip()[:160]
        if payload.subtitle is not None:
            row.subtitle = payload.subtitle.strip()[:240]
        if payload.description is not None:
            row.description = payload.description.strip()[:4000]
        if payload.center_lat is not None:
            row.center_lat = float(payload.center_lat)
        if payload.center_lon is not None:
            row.center_lon = float(payload.center_lon)
        if payload.zoom is not None:
            row.zoom = int(payload.zoom)
        if payload.author_name is not None:
            row.author_name = payload.author_name.strip()[:60]
        if payload.visibility in ("private", "unlisted", "public"):
            row.visibility = payload.visibility
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}

    @app.post("/api/tours/{slug}/delete")
    async def api_delete_tour(slug: str, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        user = require_user(request)
        row = db.query(TourMap).filter(TourMap.slug == slug).one_or_none()
        if not row:
            raise HTTPException(404)
        staff = user_role(request) in ("admin", "editor")
        if not (staff or (row.owner_user_id == user.id and row.visibility != "public")):
            raise HTTPException(403, "已公开的合集需由编辑/管理员删除。")
        row.deleted_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "soft": True}

    @app.post("/api/tours/{slug}/publish")
    async def api_publish(slug: str, request: Request, db: Session = Depends(get_db)):
        body = await request.json()
        require_csrf(request, body.get("csrf") or "")
        row = _own_tour(db, slug, request)
        if (row.stop_count or 0) < 1:
            raise HTTPException(400, "至少标记一个地点后再发布。")
        staff = user_role(request) in ("admin", "editor")
        row.visibility = "public"
        row.status = "published" if staff else "pending"
        row.published_at = datetime.utcnow() if staff else row.published_at
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "slug": row.slug, "status": row.status}
