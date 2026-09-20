#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Expand English original-library XLSX to 1000+ popular Goodreads titles.

Collects short bibliographic fields (title, author, year, publisher, ISBN,
rating, genre). Detailed Chinese synopsis / author bio columns are left blank
for later editorial fill. Covers are downloaded into covers/incoming-en/ for
one-click upload later.
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
INSPIRATION = ROOT.parent
# Expansion artifacts live outside the git repo to keep the project lean.
OFFLINE = INSPIRATION / "folio-covers-offline"
DATA = OFFLINE / "data-en"
COVER_DIR = OFFLINE / "covers-en"
XLSX_OUT = INSPIRATION / "英文原版书籍" / "2026藏书待购清单.xlsx"
XLSX_BACKUP = DATA / "2026藏书待购清单.backup.xlsx"
CAND_DIR = OFFLINE / "covers-en-candidates"
UA = "FOLIO-en-expand/1.0 (catalog research; no commerce)"

HEADER = [
    "序号",
    "主类型",
    "子类型",
    "热度标签",
    "优先级",
    "原文书名",
    "中文常用译名",
    "作者",
    "作者国家/地区",
    "首次出版年",
    "原版代表出版社",
    "ISBN-13（代表版，下单请再核）",
    "Goodreads评分",
    "Goodreads评分人数",
    "一句话简介",
    "故事梗概",
    "作者介绍",
    "适合谁",
    "入选理由",
    "建议正版渠道",
    "购入状态",
    "本地文件名",
    "封面文件",
    "slug",
    "备注",
]

GENRE_COLORS = {
    "氛围悬疑": "C7D4C9",
    "推理犯罪": "D4C7C0",
    "休闲日常": "E6DCC8",
    "爱情": "E4C9D0",
    "文学": "C9D0DC",
    "恐怖": "C9B8B4",
    "科幻": "B8C9D4",
    "奇幻": "D4C9B8",
    "剧情历史": "D0C9C0",
    "其他": "F4EFE6",
}

SUBJECT_TO_GENRE = [
    (r"horror|ghost|vampire|zombie|gothic|haunting|witch", ("恐怖", "恐怖")),
    (r"mystery|crime|detective|thriller|suspense|noir|murder|killer", ("推理犯罪", "悬疑")),
    (r"romance|love stor|wedding|boyfriend|girlfriend", ("爱情", "爱情")),
    (r"fantasy|magic|dragon|fairy|wizard|witch|elf|faerie|throne", ("奇幻", "奇幻")),
    (r"science fiction|sci-fi|dystopia|space|cyberpunk|martian|android|robot", ("科幻", "科幻")),
    (r"historical fiction|world war|civil war|tudor|victorian|wwii|ww2", ("剧情历史", "历史")),
    (r"young adult|juvenile|children|hunger games|potter|narnia|percy jackson", ("休闲日常", "成长")),
    (r"\bliterary fiction\b|\bclassic fiction\b", ("文学", "文学")),
]

# Title/author keyword fallback when subjects are missing (Goodreads Best Ever etc.)
TITLE_GENRE_HINTS = [
    (r"\b(potter|narnia|tolkien|hobbit|mistborn|wheel of time|stormlight|acotar|fourth wing|name of the wind|priory|sanderson|rothfuss|maas|yarros|brandon|american gods|good omens|discworld|earthsea|grisha|shadow and bone)\b", ("奇幻", "奇幻")),
    (r"\b(dune|foundation|neuromancer|ender|hail mary|martian|hyperion|left hand of darkness|kindred|three-body|ready player|dark matter|recursion|station eleven|children of time|androids?|blade runner|hunger games|divergent|maze runner)\b", ("科幻", "科幻")),
    (r"\b(shining|dracula|frankenstein|it\b|pet sematary|carrie|salem|hill house|mexican gothic|bird box|only good indians|haunting|interview with the vampire)\b", ("恐怖", "恐怖")),
    (r"\b(gone girl|silent patient|girl with the dragon|davinci|da vinci|sherlock|poirot|christie|murder of|and then there were|verity|housemaid|guest list|big sleep|girl on the train)\b", ("推理犯罪", "悬疑")),
    (r"\b(pride and prejudice|jane eyre|notebook|outlander|beach read|normal people|it ends with us|love hypothesis|bridgerton|romeo and juliet|persuasion|sense and sensibility)\b", ("爱情", "爱情")),
    (r"\b(book thief|nightingale|pachinko|crawdads|all the light|the help\b|homegoing|vanishing half|wolf hall|pillars of the earth|gone with the wind|memoirs of a geisha)\b", ("剧情历史", "历史")),
    (r"\b(alchemist|midnight library|lessons in chemistry|eleanor oliphant|cerulean|remarkably bright|gentleman in moscow|ove\b|fault in our stars|perks of being|giving tree|charlotte.?s web|little prince)\b", ("休闲日常", "日常")),
]


def guess_genre(subjects: list[str], title: str, author: str = "") -> tuple[str, str]:
    blob = " ".join(subjects + [title, author]).lower()
    for pat, pair in SUBJECT_TO_GENRE:
        if re.search(pat, blob):
            return pair
    for pat, pair in TITLE_GENRE_HINTS:
        if re.search(pat, blob):
            return pair
    return ("文学", "文学")

BUY = "Amazon / Bookshop.org / Kobo（Kindle 或 EPUB）"
ASCII_SLUG_RE = re.compile(r"[^a-z0-9]+")


def curl_json(url: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                ["curl", "-4", "-sSL", "--max-time", "22", "-A", UA, url],
                capture_output=True,
                timeout=28,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
            continue
        if proc.returncode != 0 or not proc.stdout:
            last = proc.stderr
            time.sleep(0.4 * (attempt + 1))
            continue
        try:
            return json.loads(proc.stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            last = "bad json"
            time.sleep(0.3)
            continue
    return None


def curl_bytes(url: str, retries: int = 3) -> bytes | None:
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                ["curl", "-4", "-sSL", "--max-time", "25", "-A", UA, url],
                capture_output=True,
                timeout=32,
            )
        except (subprocess.TimeoutExpired, OSError):
            time.sleep(0.5 * (attempt + 1))
            continue
        if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 4000:
            return proc.stdout
        time.sleep(0.35 * (attempt + 1))
    return None


def norm_key(title: str) -> str:
    t = re.sub(r"\s*\([^)]*#[0-9]+[^)]*\)\s*", "", title or "")
    t = t.lower().strip()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def clean_title(title: str) -> str:
    t = (title or "").strip()
    t = re.sub(r"\s*\(Goodreads Author\)", "", t)
    # keep series marker but drop boxed-set noise later
    return re.sub(r"\s+", " ", t).strip()


def make_slug(title: str, author: str, isbn: str = "") -> str:
    ascii_part = ASCII_SLUG_RE.sub("-", title.lower()).strip("-")
    if ascii_part and re.fullmatch(r"[a-z0-9-]{3,70}", ascii_part):
        base = f"en-{ascii_part}"[:80]
    elif isbn:
        base = f"en-{isbn}"
    else:
        digest = hashlib.sha1(f"en|{title}|{author}".encode("utf-8")).hexdigest()[:10]
        base = f"en-{digest}"
    return base


def parse_year(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int) and 1400 <= raw <= 2030:
        return raw
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(raw))
    return int(m.group(1)) if m else None


def normalize_isbn(raw: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(s) in (10, 13):
        return s
    return ""


def heat_tag(rating: float, count: int, year: int | None) -> str:
    if year and year >= 2026:
        return "2026新书"
    if count >= 500_000 and rating >= 4.0:
        return "经典常销"
    if count >= 100_000:
        return "近年现象级"
    if rating >= 4.2:
        return "经典常销"
    return "近年现象级"


def priority(rating: float, count: int) -> str:
    if count >= 200_000 or rating >= 4.3:
        return "A"
    if count >= 30_000 or rating >= 4.0:
        return "B"
    return "C"


def should_skip(title: str, author: str) -> str:
    t = title.lower()
    if not title or not author:
        return "missing title/author"
    if "boxed set" in t or "box set" in t or "omnibus" in t:
        return "box set"
    if re.search(r"[\u0400-\u04FF\u0600-\u06FF]", title):
        return "non-latin title"
    if author.startswith("score:") or len(author) > 120:
        return "bad author"
    return ""


def gdata_lookup(title: str, author: str, cache: dict) -> dict | None:
    cache_key = f"{norm_key(title)}|{author.lower().strip()}"
    if cache_key in cache:
        return cache[cache_key]
    q = f'intitle:"{title.split("(")[0].strip()}"'
    token = (author.split(",")[0].split("&")[0].split(" and ")[0]).strip().split()
    if token:
        q += f" inauthor:{token[-1]}"
    url = (
        "https://books.google.com/books/feeds/volumes?alt=json&max-results=5&q="
        + quote(q)
    )
    payload = curl_json(url)
    hit = None
    if payload and isinstance(payload, dict):
        entries = (payload.get("feed") or {}).get("entry") or []
        want = norm_key(title.split("(")[0])
        for e in entries:
            g_title = (e.get("title") or {}).get("$t") or ""
            if want and want not in norm_key(g_title) and norm_key(g_title) not in want:
                # soft accept if author token matches and title ratio-ish
                if SequenceMatcher_ratio(want, norm_key(g_title)) < 0.55:
                    continue
            langs = [x.get("$t") or "" for x in (e.get("dc$language") or [])]
            if langs and "en" not in langs and "eng" not in langs:
                continue
            isbn13 = isbn10 = ""
            for ident in e.get("dc$identifier") or []:
                raw = ident.get("$t") or ""
                if raw.startswith("ISBN:"):
                    num = normalize_isbn(raw.split(":", 1)[1])
                    if len(num) == 13:
                        isbn13 = num
                    elif len(num) == 10 and not isbn10:
                        isbn10 = num
            year = None
            for d in e.get("dc$date") or []:
                year = parse_year(d.get("$t"))
                if year:
                    break
            pubs = e.get("dc$publisher") or []
            creators = [x.get("$t") or "" for x in (e.get("dc$creator") or [])]
            subjects = [x.get("$t") or "" for x in (e.get("dc$subject") or [])]
            desc = ""
            for d in e.get("dc$description") or []:
                desc = (d.get("$t") or "").strip()
                if desc:
                    break
            hit = {
                "isbn13": isbn13,
                "isbn10": isbn10,
                "year": year,
                "publisher": (pubs[0].get("$t") if pubs else "") or "",
                "authors": creators,
                "subjects": subjects,
                "description": desc,
                "gTitle": g_title,
            }
            break
    cache[cache_key] = hit
    time.sleep(0.08)
    return hit


def SequenceMatcher_ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()



def is_bad_cover_image(im: Image.Image) -> bool:
    """Reject empty placeholders, solid colors, interior text pages, UI junk."""
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im = im.convert("RGB")
    w, h = im.size
    if min(w, h) < 100:
        return True
    ratio = h / max(w, 1)
    if ratio < 0.85 or ratio > 2.6:
        return True

    small = im.resize((80, 120), Image.Resampling.BILINEAR)
    arr = small.load()
    px = [arr[x, y] for y in range(small.size[1]) for x in range(small.size[0])]
    n = len(px)
    if n < 100:
        return True

    # brightness / color stats
    means = [sum(c[i] for c in px) / n for i in range(3)]
    vars_ = [sum((c[i] - means[i]) ** 2 for c in px) / n for i in range(3)]
    avg_var = sum(vars_) / 3
    # near-solid black / white / gray
    if avg_var < 180:
        return True

    white = sum(1 for r, g, b in px if r > 242 and g > 242 and b > 242) / n
    black = sum(1 for r, g, b in px if r < 18 and g < 18 and b < 18) / n
    if white > 0.82 or black > 0.82:
        return True

    # low color diversity (placeholder / hatch / template)
    quantized = {((r // 24) << 10) | ((g // 24) << 5) | (b // 24) for r, g, b in px}
    if len(quantized) < 18 and avg_var < 1200:
        return True

    # text-heavy interior page: mostly bright paper + many dark ink pixels
    dark = sum(1 for r, g, b in px if (r + g + b) / 3 < 90) / n
    mid = sum(1 for r, g, b in px if 90 <= (r + g + b) / 3 <= 200) / n
    if white > 0.55 and dark > 0.08 and mid < 0.35:
        # further: ink concentrated in bands (rows with many dark pixels)
        band_hits = 0
        for y in range(0, 120, 4):
            row = px[y * 80 : (y + 1) * 80]
            if not row:
                continue
            d = sum(1 for r, g, b in row if (r + g + b) / 3 < 100) / len(row)
            if d > 0.12:
                band_hits += 1
        if band_hits >= 8:
            return True

    # optional OCR for known junk phrases
    try:
        import pytesseract

        sample = im.copy()
        sample.thumbnail((600, 900), Image.Resampling.BILINEAR)
        txt = (pytesseract.image_to_string(sample, lang="eng+chi_sim") or "").lower()
        junk = (
            "image not available",
            "not available",
            "praise for",
            "table of contents",
            "copyright",
            "前言",
            "目录",
            "isbn",
            "publisher",
        )
        # "isbn" alone on a UI screenshot page is common; require combo
        if any(j in txt for j in ("image not available", "not available", "praise for", "前言", "目录")):
            return True
        if "isbn" in txt and ("author" in txt or "publisher" in txt or "出版社" in txt):
            return True
    except Exception:
        pass
    return False


def cover_file_is_bad(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 5000:
            return True
        with Image.open(path) as im:
            return is_bad_cover_image(im)
    except Exception:
        return True


def save_cover(data: bytes, dest: Path) -> bool:
    try:
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
    except Exception:
        return False
    if is_bad_cover_image(im):
        return False
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    # re-check after flatten
    if is_bad_cover_image(im):
        return False
    im.thumbnail((900, 1350), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.jpg")
    im.save(tmp, format="JPEG", quality=90, optimize=True)
    if not tmp.is_file() or tmp.stat().st_size < 5000:
        tmp.unlink(missing_ok=True)
        return False
    # final gate on written file
    if cover_file_is_bad(tmp):
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def download_cover(isbn: str, slug: str) -> str:
    dest = COVER_DIR / f"{slug}.jpg"
    if dest.exists():
        if not cover_file_is_bad(dest):
            return dest.name
        # bad existing file: delete and refetch
        try:
            dest.unlink()
        except OSError:
            pass
        cand = CAND_DIR / dest.name
        if cand.exists():
            try:
                cand.unlink()
            except OSError:
                pass
    urls = []
    if isbn:
        urls.append(
            f"https://books.google.com/books?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=4"
        )
        urls.append(
            f"https://books.google.com/books?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=3"
        )
        urls.append(f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg")
        urls.append(f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg")
    # offline mirror reuse only if it passes quality gate
    offline = INSPIRATION / "folio-covers-offline" / "covers" / f"{slug}.jpg"
    if offline.exists() and offline.stat().st_size > 5000:
        try:
            data = offline.read_bytes()
            if save_cover(data, dest):
                return dest.name
        except OSError:
            pass
    for url in urls:
        data = curl_bytes(url)
        if data and save_cover(data, dest):
            try:
                CAND_DIR.mkdir(parents=True, exist_ok=True)
                (CAND_DIR / dest.name).write_bytes(dest.read_bytes())
            except OSError:
                pass
            return dest.name
        # remove partial
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        time.sleep(0.05)
    return ""


def load_existing_map() -> dict[str, dict]:
    path = XLSX_OUT
    if not path.exists():
        return {}
    wb = load_workbook(path, data_only=True)
    ws = wb["全部书目"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    idx = {h: i for i, h in enumerate(header)}
    out = {}
    for row in rows[1:]:
        if not row or not row[idx.get("原文书名", 5)]:
            continue
        title = str(row[idx["原文书名"]]).strip()
        out[norm_key(title)] = {
            "title": title,
            "author": str(row[idx.get("作者", 7)] or "").strip(),
            "genre": str(row[idx.get("主类型", 1)] or "").strip(),
            "sub": str(row[idx.get("子类型", 2)] or "").strip(),
            "heat": str(row[idx.get("热度标签", 3)] or "").strip(),
            "pri": str(row[idx.get("优先级", 4)] or "B").strip(),
            "zh": str(row[idx.get("中文常用译名", 6)] or "").strip(),
            "country": str(row[idx.get("作者国家/地区", 8)] or "").strip(),
            "year": row[idx.get("首次出版年", 9)],
            "pub": str(row[idx.get("原版代表出版社", 10)] or "").strip(),
            "isbn": str(row[idx.get("ISBN-13（代表版，下单请再核）", 11)] or "").strip()
            if row[idx.get("ISBN-13（代表版，下单请再核）", 11)]
            else "",
            "blurb": str(row[idx.get("一句话简介", 12)] or "").strip(),
            "who": str(row[idx.get("适合谁", 13)] or "").strip() if "适合谁" in idx else "",
            "why": str(row[idx.get("入选理由", 14)] or "").strip() if "入选理由" in idx else "",
        }
    return out


def load_enrichment_isbn() -> dict[str, dict]:
    path = ROOT / "data" / "enrichment.json"
    if not path.exists():
        return {}
    by = (json.loads(path.read_text(encoding="utf-8")).get("bySlug") or {})
    # also map by cleaned title from cleaned-books
    cleaned = ROOT / "data" / "cleaned-books.json"
    out = {}
    if cleaned.exists():
        for b in json.loads(cleaned.read_text(encoding="utf-8")).get("books") or []:
            if b.get("languageCode") != "en":
                continue
            extra = by.get(b["slug"]) or {}
            out[norm_key(b["originalTitle"])] = {
                "isbn13": extra.get("isbn13") or b.get("isbn13") or "",
                "publisher": extra.get("publisher") or b.get("publisher") or "",
                "year": extra.get("publicationYear") or b.get("publicationYear"),
                "author": extra.get("authorName") or b.get("authorName") or "",
                "zh": b.get("chineseTitle") or "",
                "blurb": b.get("shortDescriptionZh") or "",
                "country": b.get("nationality") or "",
                "genre_raw": b.get("primaryGenre") or "",
                "slug": b.get("slug") or "",
            }
    return out


def style_header(ws):
    fill = PatternFill("solid", fgColor="1B1712")
    font = Font(name="Calibri", bold=True, color="F4EFE6", size=11)
    side = Border(
        left=Side(style="thin", color="C4A574"),
        right=Side(style="thin", color="C4A574"),
        top=Side(style="thin", color="C4A574"),
        bottom=Side(style="thin", color="C4A574"),
    )
    for col, name in enumerate(HEADER, 1):
        cell = ws.cell(1, col, name)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = side
    ws.row_dimensions[1].height = 36
    ws.freeze_panes = "A2"
    widths = {
        "A": 6,
        "B": 12,
        "C": 12,
        "D": 12,
        "E": 8,
        "F": 36,
        "G": 18,
        "H": 22,
        "I": 14,
        "J": 10,
        "K": 20,
        "L": 18,
        "M": 12,
        "N": 14,
        "O": 36,
        "P": 40,
        "Q": 28,
        "R": 18,
        "S": 22,
        "T": 28,
        "U": 10,
        "V": 16,
        "W": 28,
        "X": 28,
        "Y": 20,
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def write_guide(ws, n: int, with_isbn: int, with_cover: int):
    ws["A1"] = "英文原版藏书 · Goodreads 高人气扩容清单"
    ws["A1"].font = Font(name="Calibri", size=18, bold=True, color="1B1712")
    ws.merge_cells("A1:F1")
    lines = [
        "",
        f"本表共收录 {n} 本英语原版大众读物（Goodreads 评分 ≥ 3.9 为主，并入原有待购书目）。",
        "收录原则：参考 Goodreads Listopia / 高人气书单；优先高评分 + 高评分人数。",
        "短字段优先：书名、作者、类型、评分、出版年、出版社、ISBN、封面文件。",
        "「故事梗概」「作者介绍」可先空着，后续再补详细中文导读。",
        "ISBN / 封面来自 Google Books / Open Library 公开书目接口，下单与上架前请再核。",
        f"当前已补 ISBN：{with_isbn} 本；已下封面：{with_cover} 本（见项目 covers/incoming-en/）。",
        f"建议购买渠道：{BUY}",
        "优先级：A 先看 / B 按类型补 / C 下单前再核。",
        "封面路径：项目内 covers/incoming-en/{slug}.jpg ，并同步到 英文原版书籍/封面搜集/候选/。",
    ]
    for i, line in enumerate(lines, 2):
        ws[f"A{i}"] = line
        ws[f"A{i}"].font = Font(name="Calibri", size=12, color="1B1712")
        ws[f"A{i}"].alignment = Alignment(wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)
        ws.row_dimensions[i].height = 22
    ws.column_dimensions["A"].width = 28
    ws.row_dimensions[1].height = 28


def write_stats(ws, rows: list[dict]):
    g = Counter(r["genre"] for r in rows)
    h = Counter(r["heat"] for r in rows)
    ws["A1"] = "按主类型"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A3"] = "主类型"
    ws["B3"] = "册数"
    for i, (k, v) in enumerate(sorted(g.items()), 4):
        ws[f"A{i}"] = k
        ws[f"B{i}"] = v
        ws[f"A{i}"].fill = PatternFill("solid", fgColor=GENRE_COLORS.get(k, "F4EFE6"))
    ws["D1"] = "按热度"
    ws["D1"].font = Font(bold=True, size=14)
    ws["D3"] = "热度标签"
    ws["E3"] = "册数"
    for i, (k, v) in enumerate(sorted(h.items()), 4):
        ws[f"D{i}"] = k
        ws[f"E{i}"] = v
    ws["A16"] = f"合计 {len(rows)} 册"
    ws["A16"].font = Font(bold=True)
    ws["A17"] = f"有 ISBN：{sum(1 for r in rows if r.get('isbn'))}"
    ws["A18"] = f"有封面：{sum(1 for r in rows if r.get('cover'))}"
    ws["A19"] = f"故事梗概已填：{sum(1 for r in rows if r.get('synopsis'))}（可后续补）"
    for col, w in {"A": 16, "B": 10, "D": 16, "E": 10}.items():
        ws.column_dimensions[col].width = w


def write_catalog(ws, rows: list[dict]):
    style_header(ws)
    side = Border(
        left=Side(style="thin", color="E6DCC8"),
        right=Side(style="thin", color="E6DCC8"),
        top=Side(style="thin", color="E6DCC8"),
        bottom=Side(style="thin", color="E6DCC8"),
    )
    wrap = Alignment(vertical="center", wrap_text=True)
    body = Font(name="Calibri", size=11, color="1B1712")
    for i, r in enumerate(rows, 1):
        values = [
            i,
            r["genre"],
            r["sub"],
            r["heat"],
            r["pri"],
            r["title"],
            r.get("zh") or "",
            r["author"],
            r.get("country") or "",
            r.get("year") or "",
            r.get("publisher") or "",
            r.get("isbn") or "",
            r.get("rating") or "",
            r.get("ratingsCount") or "",
            r.get("blurb") or "",
            r.get("synopsis") or "",  # intentionally often blank
            r.get("authorBio") or "",  # intentionally often blank
            r.get("who") or "",
            r.get("why")
            or f"Goodreads {r.get('rating')}★ / {r.get('ratingsCount') or 0:,} ratings",
            BUY,
            "待购",
            "",
            r.get("cover") or "",
            r.get("slug") or "",
            r.get("note") or "",
        ]
        fill = PatternFill("solid", fgColor=GENRE_COLORS.get(r["genre"], "F4EFE6"))
        for c, v in enumerate(values, 1):
            cell = ws.cell(i + 1, c, v)
            cell.font = body
            cell.alignment = wrap
            cell.border = side
            if c == 2:
                cell.fill = fill
            elif i % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="FBF7F0")
        ws.row_dimensions[i + 1].height = 42
    last = len(rows) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADER))}{last}"
    dv = DataValidation(type="list", formula1='"待购,已购,已入库,暂不买"', allow_blank=False)
    dv.add(f"U2:U{last}")
    ws.add_data_validation(dv)
    dv2 = DataValidation(type="list", formula1='"A,B,C"', allow_blank=False)
    dv2.add(f"E2:E{last}")
    ws.add_data_validation(dv2)


def build_rows(
    limit: int = 0,
    skip_covers: bool = False,
    skip_lookup: bool = False,
    fast: bool = False,
) -> list[dict]:
    if fast:
        skip_covers = True
        skip_lookup = True
    DATA.mkdir(parents=True, exist_ok=True)
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    seed_path = DATA / "seed_merged.json"
    if not seed_path.exists():
        raise SystemExit(f"Missing {seed_path}; regenerate seed first.")
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    existing = load_existing_map()
    enrich = load_enrichment_isbn()
    cache_path = DATA / "gdata-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    rows: list[dict] = []
    seen_keys = set()
    seen_isbn = set()
    skipped = []

    work = seeds[:limit] if limit else seeds
    for i, seed in enumerate(work, 1):
        title = clean_title(seed["title"])
        author = (seed.get("author") or "").strip()
        rating = float(seed.get("rating") or 0)
        count = int(seed.get("ratingsCount") or 0)
        reason = should_skip(title, author)
        if reason:
            skipped.append({"title": title, "reason": reason})
            continue
        k = norm_key(title)
        if k in seen_keys:
            skipped.append({"title": title, "reason": "dup key"})
            continue
        seen_keys.add(k)

        prev = existing.get(k) or {}
        meta = enrich.get(k) or {}
        isbn = normalize_isbn(prev.get("isbn") or meta.get("isbn13") or "")
        year = parse_year(prev.get("year") or meta.get("year"))
        publisher = prev.get("pub") or meta.get("publisher") or ""
        zh = prev.get("zh") or meta.get("zh") or ""
        country = prev.get("country") or meta.get("country") or ""
        blurb = prev.get("blurb") or meta.get("blurb") or ""
        who = prev.get("who") or ""
        why = prev.get("why") or ""
        genre = prev.get("genre") or ""
        sub = prev.get("sub") or ""
        subjects: list[str] = []
        note = ""

        # Reuse prior GData cache even in fast mode
        cache_hit = None
        cache_key = f"{k}|{author.lower().strip()}"
        if cache_key in cache:
            cache_hit = cache[cache_key]
        elif any(ck.startswith(k + "|") for ck in cache):
            for ck, cv in cache.items():
                if ck.startswith(k + "|") and cv:
                    cache_hit = cv
                    break
        if cache_hit:
            if not isbn:
                isbn = cache_hit.get("isbn13") or cache_hit.get("isbn10") or ""
            if not year and cache_hit.get("year"):
                year = cache_hit["year"]
            if not publisher and cache_hit.get("publisher"):
                publisher = cache_hit["publisher"]
            subjects = cache_hit.get("subjects") or subjects
            if not blurb and cache_hit.get("description"):
                eng = re.sub(r"<[^>]+>", "", cache_hit["description"])
                eng = re.sub(r"\s+", " ", eng).strip()
                if eng:
                    blurb = eng[:120].rstrip(" ,.;:") + ("…" if len(eng) > 120 else "")
                    note = "一句话简介暂用英文书讯摘要，故事梗概待补中文"

        if not skip_lookup and (not isbn or not year or not publisher or not genre):
            hit = gdata_lookup(title, author, cache)
            if hit:
                if not isbn:
                    isbn = hit.get("isbn13") or hit.get("isbn10") or ""
                if not year and hit.get("year"):
                    year = hit["year"]
                if not publisher and hit.get("publisher"):
                    publisher = hit["publisher"]
                subjects = hit.get("subjects") or []
                if not blurb and hit.get("description"):
                    # keep a short English blurb as placeholder; Chinese synopsis stays empty
                    eng = re.sub(r"<[^>]+>", "", hit["description"])
                    eng = re.sub(r"\s+", " ", eng).strip()
                    if eng:
                        blurb = eng[:120].rstrip(" ,.;:") + ("…" if len(eng) > 120 else "")
                        note = "一句话简介暂用英文书讯摘要，故事梗概待补中文"
                if hit.get("authors") and (not author or "待核" in author):
                    author = hit["authors"][0]

        if isbn and isbn in seen_isbn:
            skipped.append({"title": title, "reason": f"dup isbn {isbn}"})
            continue
        if isbn:
            seen_isbn.add(isbn)

        if not genre:
            genre, sub = guess_genre(subjects, title, author)
        elif not sub:
            sub = genre
        # Re-classify “文学” dumping-ground when we only have weak default
        if genre == "文学" and not prev.get("genre"):
            guessed, g_sub = guess_genre(subjects, title, author)
            if guessed != "文学":
                genre, sub = guessed, g_sub

        heat = prev.get("heat") or heat_tag(rating, count, year)
        pri = prev.get("pri") or priority(rating, count)
        slug = meta.get("slug") or make_slug(title.split("(")[0].strip(), author, isbn)
        cover = ""
        local_cover = COVER_DIR / f"{slug}.jpg"
        if local_cover.exists() and local_cover.stat().st_size > 5000:
            cover = local_cover.name
        elif not skip_covers:
            cover = download_cover(isbn, slug)

        rows.append(
            {
                "title": title,
                "author": author,
                "genre": genre,
                "sub": sub,
                "heat": heat,
                "pri": pri,
                "zh": zh if zh != "—" else "",
                "country": country,
                "year": year,
                "publisher": publisher if publisher != "—" else "",
                "isbn": isbn if len(isbn) == 13 else (isbn if len(isbn) == 10 else ""),
                "rating": rating,
                "ratingsCount": count,
                "blurb": blurb,
                "synopsis": "",
                "authorBio": "",
                "who": who,
                "why": why,
                "cover": cover,
                "slug": slug,
                "note": note,
            }
        )
        if i % 25 == 0 or i == len(work):
            print(
                f"  [{i}/{len(work)}] kept={len(rows)} isbn={sum(1 for r in rows if r['isbn'])} "
                f"cover={sum(1 for r in rows if r['cover'])}",
                flush=True,
            )
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    (DATA / "expand-skipped.json").write_text(
        json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # sort: rating count desc, then rating
    rows.sort(key=lambda r: (-(r.get("ratingsCount") or 0), -(r.get("rating") or 0), r["title"]))
    return rows


def save_xlsx(rows: list[dict]) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    if XLSX_OUT.exists():
        XLSX_BACKUP.write_bytes(XLSX_OUT.read_bytes())
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "使用说明"
    write_guide(
        ws0,
        len(rows),
        sum(1 for r in rows if r.get("isbn")),
        sum(1 for r in rows if r.get("cover")),
    )
    ws1 = wb.create_sheet("全部书目")
    write_catalog(ws1, rows)
    ws2 = wb.create_sheet("类型统计")
    write_stats(ws2, rows)
    XLSX_OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX_OUT)
    # project mirror
    mirror = DATA / "英文原版书籍-扩容书目.xlsx"
    wb.save(mirror)
    summary = {
        "total": len(rows),
        "withIsbn": sum(1 for r in rows if r.get("isbn")),
        "withCover": sum(1 for r in rows if r.get("cover")),
        "withBlurb": sum(1 for r in rows if r.get("blurb")),
        "withSynopsis": sum(1 for r in rows if r.get("synopsis")),
        "genres": dict(Counter(r["genre"] for r in rows)),
        "xlsx": str(XLSX_OUT),
        "coversDir": str(COVER_DIR),
    }
    (DATA / "expand-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return XLSX_OUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-covers", action="store_true")
    parser.add_argument("--skip-lookup", action="store_true")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip live GData/cover downloads; use seed + cache + enrichment only",
    )
    parser.add_argument(
        "--covers-only",
        action="store_true",
        help="Download missing covers for rows already listed in expand-summary / xlsx",
    )
    args = parser.parse_args()
    if args.covers_only:
        download_missing_covers()
        return
    rows = build_rows(
        limit=args.limit,
        skip_covers=args.skip_covers,
        skip_lookup=args.skip_lookup,
        fast=args.fast,
    )
    if len(rows) < 1000 and not args.limit:
        print(f"WARNING: only {len(rows)} rows (<1000)", flush=True)
    save_xlsx(rows)
    print(f"wrote {len(rows)} -> {XLSX_OUT}", flush=True)


def download_missing_covers(limit: int = 0) -> None:
    """Second pass: fill covers for xlsx rows that have ISBN but no local jpg."""
    if not XLSX_OUT.exists():
        raise SystemExit("Run expand first")
    wb = load_workbook(XLSX_OUT)
    ws = wb["全部书目"]
    headers = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(headers)}
    need = []
    for row in range(2, ws.max_row + 1):
        slug = ws.cell(row, col["slug"]).value or ""
        isbn = str(ws.cell(row, col["ISBN-13（代表版，下单请再核）"]).value or "")
        cover = ws.cell(row, col["封面文件"]).value or ""
        dest = COVER_DIR / f"{slug}.jpg"
        if cover and dest.exists():
            continue
        if not slug:
            continue
        need.append((row, slug, normalize_isbn(isbn)))
    if limit:
        need = need[:limit]
    print(f"covers to fetch: {len(need)}", flush=True)
    ok = 0
    for i, (row, slug, isbn) in enumerate(need, 1):
        name = download_cover(isbn, slug)
        if name:
            ws.cell(row, col["封面文件"], name)
            ok += 1
        if i % 20 == 0 or i == len(need):
            print(f"  [{i}/{len(need)}] ok={ok}", flush=True)
            wb.save(XLSX_OUT)
    wb.save(XLSX_OUT)
    # mirror
    mirror = DATA / "英文原版书籍-扩容书目.xlsx"
    wb.save(mirror)
    print(f"covers done ok={ok}/{len(need)}", flush=True)


if __name__ == "__main__":
    main()
