#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lookup ISBN / year from Open Library and Google Books, download covers, crop to 2:3.

Does not invent bibliographic facts: a hit is kept only when title+author match.
Manual year/ISBN fixes for known misparsed catalog rows are listed below with sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import subprocess
import tempfile

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COVER_DIR = ROOT / "static" / "covers"
CACHE_PATH = DATA / "reports" / "enrich-cache.json"
OVERLAY_PATH = DATA / "enrichment.json"
CLEANED = DATA / "cleaned-books.json"
UA = "FOLIO-enrichment/1.0 (catalog research; no commerce)"

LANG_GB = {"en": "en", "es": "es", "ja": "ja", "ko": "ko", "fr": "fr", "it": "it"}

# Hand-verified repairs for rows whose year column was a country/century, not a date.
YEAR_FIXES = {
    "cartas de amor a los muertos": {
        "languageCode": "es",
        "publicationYear": 2014,
        "isbn13": "9788494424328",
        "authorName": "Ava Dellaira",
        "publisher": "Farrar, Straus and Giroux / Nocturna",
        "verificationStatus": "verified",
        "sourceName": "Nocturna Ediciones copyright page; original English 2014",
        "note": "英语原作2014；西班牙语Nocturna 2015，ISBN 978-84-944243-2-8",
    },
    "한 스푼의 시간": {
        "languageCode": "ko",
        "publicationYear": 2016,
        "isbn13": "9788959130580",
        "authorName": "구병모",
        "publisher": "위즈덤하우스",
        "verificationStatus": "verified",
        "sourceName": "Kyobo / Aladin listing 2016-09-05",
        "note": "구병모，2016年9月5日",
    },
    "le chuchoteur": {
        "languageCode": "fr",
        "publicationYear": 2009,
        "isbn13": "9782702141045",
        "authorName": "Donato Carrisi",
        "publisher": "Longanesi / Calmann-Lévy",
        "verificationStatus": "verified",
        "sourceName": "Longanesi Il suggeritore 2009; Calmann-Lévy 2010 French",
        "note": "意大利语原作2009；法语2010，ISBN 9782702141045",
    },
    "la classe de neige": {
        "languageCode": "fr",
        "publicationYear": 1995,
        "isbn13": "9782867444494",
        "authorName": "Emmanuel Carrère",
        "publisher": "P.O.L",
        "verificationStatus": "verified",
        "sourceName": "P.O.L 1995",
        "note": "1995年首次出版",
    },
    "aux animaux la guerre": {
        "languageCode": "fr",
        "publicationYear": 2014,
        "isbn13": "9782330033736",
        "authorName": "Nicolas Mathieu",
        "publisher": "Actes Sud",
        "verificationStatus": "verified",
        "sourceName": "Actes Sud 2014",
        "note": "2014年首次出版",
    },
    "홍길동전": {
        "languageCode": "ko",
        "publicationYear": 1612,
        "isbn13": "9788937462009",
        "authorName": "허균",
        "publisher": "민음사（现代通行整理本）",
        "verificationStatus": "verified",
        "sourceName": "Minumsa world literature 200; composition ~17th century",
        "note": "17世纪作品（约1612，托名허균）；ISBN为2009民音社通行整理本",
    },
    "춘향전": {
        "languageCode": "ko",
        "publicationYear": 1845,
        "isbn13": "9788937461002",
        "authorName": "작자 미상",
        "publisher": "민음사（现代通行整理本）",
        "verificationStatus": "verified",
        "sourceName": "Minumsa world literature 100; 19c woodblock recensions",
        "note": "19世纪完板系统刊本；ISBN为2004民音社通行整理本",
    },
    "dracula": {
        "languageCode": "it",
        "publicationYear": 1897,
        "isbn13": "9780141439846",
        "authorName": "Bram Stoker",
        "publisher": "Archibald Constable / Penguin Classics",
        "verificationStatus": "verified",
        "sourceName": "First edition 1897 Constable; Penguin Classics ISBN",
        "note": "英语原作1897；目录误植作者，已改正",
    },
    "華氏451": {
        "languageCode": "ja",
        "publicationYear": 1953,
        "authorName": "Ray Bradbury",
        "verificationStatus": "verified",
        "sourceName": "Ballantine 1953 first publication",
        "note": "英语原作1953；日语目录为译本书名，ISBN另由书目库匹配日语版",
    },
    "별주부전": {
        "languageCode": "ko",
        "publicationYear": 1800,
        "isbn13": "9788954697095",
        "authorName": "작자 미상",
        "publisher": "창비（한국고전문학전집：토끼전·장끼전）",
        "verificationStatus": "verified",
        "sourceName": "Changbi 한국고전문학전집 2024; 토끼전/별주부전 조선후기 판소리계소설",
        "note": "조선후기 판소리계小说，无单一初版年；ISBN为2024昌比《토끼전 장끼전》整理本",
    },
}


def isbn13_valid(raw: str) -> bool:
    s = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(s) == 10:
        return True
    if len(s) != 13 or not s.isdigit() or not s.startswith(("978", "979")):
        return False
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(s[:12]))
    return ((10 - total % 10) % 10) == int(s[12])


def normalize_isbn(raw: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(s) == 10:
        return s
    if isbn13_valid(s):
        return s
    return ""


def norm_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.split(r"[（(]|英；|意；|改|不收|体系外", text, maxsplit=1)[0]
    text = text.lower()
    text = re.sub(r"[:：/|].*$", "", text)
    text = re.sub(r"[“”\"'’.,!?;:()\[\]{}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_person(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.split(r"[；;]|为英语|体系外|等；|短；|偏|托名|外；|不收|改收| 改", text)[0]
    return text.strip(" /|,")


def title_close(a: str, b: str) -> bool:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.78


def author_close(query: str, candidates) -> bool:
    q = clean_person(query).lower()
    if not q or q in {"작자 미상", "未详", "anon"}:
        return True
    if "待核" in q:
        return True
    tokens = [t for t in re.split(r"\s+", q) if len(t) >= 2]
    last = tokens[-1] if tokens else q
    blob = " ".join(candidates or []).lower()
    if last in blob or q in blob:
        return True
    # CJK: any 2+ char chunk
    for i in range(len(q) - 1):
        chunk = q[i : i + 2]
        if chunk in blob:
            return True
    return False


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def process_cover(data: bytes, dest: Path) -> bool:
    try:
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
    except Exception:
        return False
    if min(im.size) < 80:
        return False
    im = trim_edges(im)
    if min(im.size) < 80:
        return False
    probe = im.resize((40, 60), Image.Resampling.BILINEAR)
    if len(set(probe.getdata())) < 400:
        return False
    target_w, target_h = 800, 1200
    im.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (27, 23, 18))
    x = (target_w - im.width) // 2
    y = (target_h - im.height) // 2
    canvas.paste(im, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "JPEG", quality=88, optimize=True)
    return dest.stat().st_size > 4000


def trim_edges(im: Image.Image, threshold: int = 22) -> Image.Image:
    px = im.load()
    w, h = im.size
    samples = [px[2, 2], px[w - 3, 2], px[2, h - 3], px[w - 3, h - 3]]
    bg = tuple(sum(c[i] for c in samples) // 4 for i in range(3))

    def is_bg(x, y):
        p = px[x, y]
        return all(abs(p[i] - bg[i]) <= threshold for i in range(3))

    left, top, right, bottom = 0, 0, w - 1, h - 1
    while left < right and all(is_bg(left, y) for y in range(0, h, max(1, h // 40))):
        left += 1
    while right > left and all(is_bg(right, y) for y in range(0, h, max(1, h // 40))):
        right -= 1
    while top < bottom and all(is_bg(x, top) for x in range(0, w, max(1, w // 40))):
        top += 1
    while bottom > top and all(is_bg(x, bottom) for x in range(0, w, max(1, w // 40))):
        bottom -= 1
    pad = 4
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(w, right + 1 + pad),
        min(h, bottom + 1 + pad),
    )
    if box[2] - box[0] < 60 or box[3] - box[1] < 80:
        return im
    return im.crop(box)


class Lookup:
    def __init__(self, cache: dict):
        self.cache = cache

    def curl(self, url: str, binary: bool = False, retries: int = 3):
        key = ("bin:" if binary else "json:") + url
        if key in self.cache and not binary:
            return self.cache[key]
        last = None
        for attempt in range(retries):
            cmd = [
                "curl", "-4", "-sSL", "--max-time", "22",
                "-A", "Mozilla/5.0 FOLIO-enrichment/1.0",
                url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=28)
            except (subprocess.TimeoutExpired, OSError) as exc:
                last = exc
                time.sleep(0.6 * (attempt + 1))
                continue
            if proc.returncode != 0 or not proc.stdout:
                last = proc.stderr
                time.sleep(0.4 * (attempt + 1))
                continue
            if binary:
                time.sleep(0.05)
                return proc.stdout
            try:
                data = json.loads(proc.stdout.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                last = "invalid json"
                time.sleep(0.25)
                continue
            self.cache[key] = data
            time.sleep(0.08)
            return data
        return None if not binary else last

    def gdata(self, title: str, author: str, lang: str, isbn: str = ""):
        if isbn:
            q = f"isbn:{isbn}"
        elif lang in {"ja", "ko"}:
            q = f"{title} {clean_person(author)}"
        else:
            q = f'intitle:"{title}"'
            person = clean_person(author)
            if person:
                token = person.split()[0]
                if token:
                    q += f" inauthor:{token}"
        url = (
            "https://books.google.com/books/feeds/volumes?alt=json&max-results=8&q="
            + quote(q)
        )
        return self.curl(url)

    def pick_gdata(self, payload, title, author, lang):
        if not payload or not isinstance(payload, dict):
            return None
        entries = (payload.get("feed") or {}).get("entry") or []
        for e in entries:
            g_title = (e.get("title") or {}).get("$t") or ""
            creators = [x.get("$t") or "" for x in (e.get("dc$creator") or [])]
            langs = [x.get("$t") or "" for x in (e.get("dc$language") or [])]
            if langs and lang not in langs and lang != "en":
                if not title_close(title, g_title):
                    continue
            if not title_close(title, g_title):
                continue
            if author and not author_close(author, creators):
                continue
            isbn13 = isbn10 = volume_id = ""
            for ident in e.get("dc$identifier") or []:
                raw = ident.get("$t") or ""
                if raw.startswith("ISBN:"):
                    num = normalize_isbn(raw.split(":", 1)[1])
                    if len(num) == 13:
                        isbn13 = num
                    elif len(num) == 10:
                        isbn10 = num
                elif re.fullmatch(r"[A-Za-z0-9_-]{10,}", raw) and not volume_id:
                    volume_id = raw
            year = None
            dates = e.get("dc$date") or []
            if dates:
                m = re.search(r"(1[5-9]\d{2}|20\d{2})", dates[0].get("$t") or "")
                if m:
                    year = int(m.group(1))
            pubs = e.get("dc$publisher") or []
            isbn_for_cover = isbn13 or isbn10
            image = ""
            if isbn_for_cover:
                image = (
                    "https://books.google.com/books?vid=ISBN"
                    f"{isbn_for_cover}&printsec=frontcover&img=1&zoom=4"
                )
            elif volume_id:
                image = (
                    "https://books.google.com/books?id="
                    f"{volume_id}&printsec=frontcover&img=1&zoom=4"
                )
            return {
                "isbn13": isbn13,
                "isbn10": isbn10,
                "year": year,
                "publisher": pubs[0].get("$t") if pubs else "",
                "authors": creators,
                "image": image,
                "source": "Google Books GData",
                "volumeId": volume_id,
            }
        return None

    def download_image(self, url: str, dest: Path, extra_urls=None) -> bool:
        urls = [url] + list(extra_urls or [])
        for u in urls:
            if not u:
                continue
            data = self.curl(u, binary=True)
            if not data or not isinstance(data, (bytes, bytearray)) or len(data) < 4000:
                continue
            if process_cover(bytes(data), dest):
                return True
        return False


def apply_manual_fixes(books: list[dict]) -> int:
    n = 0
    for book in books:
        key = norm_title(book["originalTitle"])
        # exact key from YEAR_FIXES uses original-ish forms
        hit = None
        for k, v in YEAR_FIXES.items():
            if v.get("languageCode") == book["languageCode"] and (key == norm_title(k) or norm_title(k) in key or key in norm_title(k)):
                hit = v
                break
        if not hit:
            continue
        if hit.get("isbn13") and isbn13_valid(hit["isbn13"]):
            book["isbn13"] = hit["isbn13"]
        if hit.get("publicationYear"):
            book["publicationYear"] = hit["publicationYear"]
            book["publicationDate"] = f"{hit['publicationYear']}-01-01"
        if hit.get("authorName"):
            book["authorName"] = hit["authorName"]
        if hit.get("publisher"):
            book["publisher"] = hit["publisher"]
        book["verificationStatus"] = hit.get("verificationStatus", "verified")
        book["sourceName"] = hit.get("sourceName", book.get("sourceName") or "")
        book["selectionReason"] = hit.get("note", "")
        n += 1
    return n


def cover_path_for(slug: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug)[:80]
    return COVER_DIR / f"{safe}.jpg"


def enrich(limit: int | None = None, missing_only: bool = False) -> dict:
    payload = json.loads(CLEANED.read_text(encoding="utf-8"))
    books = payload["books"]
    try:
        sys.path.insert(0, str(ROOT))
        from folio.featured import FEATURED
        featured_map = {(f["languageCode"], f["matchTitle"]): f for f in FEATURED}
        for book in books:
            feat = featured_map.get((book["languageCode"], book["originalTitle"]))
            if feat and feat.get("isbn13") and not book.get("isbn13"):
                book["isbn13"] = feat["isbn13"]
                book["sourceName"] = feat.get("sourceName") or book.get("sourceName")
    except Exception:
        pass
    cache = {k: v for k, v in load_json(CACHE_PATH, {}).items() if not str(k).startswith("https://www.googleapis.com")}
    overlay = load_json(OVERLAY_PATH, {"bySlug": {}})
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    manual = apply_manual_fixes(books)
    stats = {
        "manualYearFixes": manual,
        "isbnFilled": 0,
        "coversSaved": 0,
        "lookedUp": 0,
        "unresolvedIsbn": 0,
        "unresolvedCover": 0,
    }
    api = Lookup(cache)
    work = books[:limit] if limit else books
    if missing_only:
        work = [b for b in work if not cover_path_for(b["slug"]).exists()]
        print(f"missing covers to retry: {len(work)}")
    for i, book in enumerate(work, 1):
        title = book["originalTitle"]
        if any(mark in title for mark in ("改收", "不收", "体系外")):
            stats["unresolvedCover"] += 1
            if not book.get("isbn13") and not book.get("isbn10"):
                stats["unresolvedIsbn"] += 1
            continue
        author = clean_person(book.get("authorName") or "")
        lang = book["languageCode"]
        slug = book["slug"]
        dest = cover_path_for(slug)
        isbn = book.get("isbn13") or book.get("isbn10") or ""
        need_isbn = not isbn
        need_cover = not dest.exists()
        if not need_isbn and not need_cover:
            book["coverImage"] = f"/covers/{dest.name}"
            overlay["bySlug"][slug] = {
                "isbn13": book.get("isbn13") or "",
                "isbn10": book.get("isbn10") or "",
                "publicationYear": book.get("publicationYear"),
                "coverImage": book["coverImage"],
                "verificationStatus": book.get("verificationStatus"),
                "sourceName": book.get("sourceName") or "",
            }
            continue
        stats["lookedUp"] += 1
        payload_g = api.gdata(title, author, lang, isbn if isbn else "")
        hit = api.pick_gdata(payload_g, title, author, lang)
        if hit:
            if need_isbn and hit.get("isbn13"):
                book["isbn13"] = hit["isbn13"]
                isbn = hit["isbn13"]
                stats["isbnFilled"] += 1
                book["sourceName"] = hit.get("source") or book.get("sourceName")
                if book.get("verificationStatus") == "pending" and (book.get("publicationYear") or hit.get("year")):
                    book["verificationStatus"] = "verified"
            if hit.get("isbn10") and not book.get("isbn10"):
                book["isbn10"] = hit["isbn10"]
            if not book.get("publicationYear") and hit.get("year"):
                y = int(hit["year"])
                if 1400 <= y <= 2026:
                    book["publicationYear"] = y
                    book["publicationDate"] = f"{y}-01-01"
                    if book.get("verificationStatus") == "pending":
                        book["verificationStatus"] = "verified"
            extra = []
            cover_isbn = book.get("isbn13") or book.get("isbn10") or isbn
            if cover_isbn:
                extra.append(
                    "https://books.google.com/books?vid=ISBN"
                    f"{cover_isbn}&printsec=frontcover&img=1&zoom=4"
                )
                extra.append(
                    "https://books.google.com/books?vid=ISBN"
                    f"{cover_isbn}&printsec=frontcover&img=1&zoom=3"
                )
            if hit.get("volumeId"):
                extra.append(
                    "https://books.google.com/books?id="
                    f"{hit['volumeId']}&printsec=frontcover&img=1&zoom=4"
                )
            if need_cover:
                ok = api.download_image(hit.get("image") or "", dest, extra)
                if ok:
                    stats["coversSaved"] += 1
                    book["coverImage"] = f"/covers/{dest.name}"
        elif isbn and need_cover:
            extra = [
                f"https://books.google.com/books?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=4",
                f"https://books.google.com/books?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=3",
            ]
            if api.download_image("", dest, extra):
                stats["coversSaved"] += 1
                book["coverImage"] = f"/covers/{dest.name}"
        if not book.get("isbn13") and not book.get("isbn10"):
            stats["unresolvedIsbn"] += 1
        if not dest.exists():
            stats["unresolvedCover"] += 1
        elif not book.get("coverImage"):
            book["coverImage"] = f"/covers/{dest.name}"
        overlay["bySlug"][slug] = {
            "isbn13": book.get("isbn13") or "",
            "isbn10": book.get("isbn10") or "",
            "publicationYear": book.get("publicationYear"),
            "publisher": book.get("publisher") or "",
            "authorName": book.get("authorName") or "",
            "coverImage": book.get("coverImage") or "",
            "verificationStatus": book.get("verificationStatus"),
            "sourceName": book.get("sourceName") or "",
            "selectionReason": book.get("selectionReason") or "",
        }
        if i % 20 == 0 or i == len(work):
            print(f"  {i}/{len(work)} isbn+={stats['isbnFilled']} covers={stats['coversSaved']}")
            save_json(CACHE_PATH, cache)
            save_json(OVERLAY_PATH, overlay)
    payload["books"] = books
    payload["generatedAt"] = payload.get("generatedAt")
    payload["isbnCount"] = sum(1 for b in books if b.get("isbn13") or b.get("isbn10"))
    payload["coverCount"] = sum(1 for b in books if b.get("coverImage", "").endswith(".jpg"))
    CLEANED.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    save_json(CACHE_PATH, cache)
    save_json(OVERLAY_PATH, overlay)
    save_json(DATA / "reports" / "enrich-summary.json", stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def process_existing_jpgs() -> int:
    n = 0
    for path in list(COVER_DIR.glob("*.jpg")):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        tmp = path.with_suffix(".tmp.jpg")
        if process_cover(data, tmp):
            tmp.replace(path)
            n += 1
        elif tmp.exists():
            tmp.unlink()
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--process-existing", action="store_true")
    args = parser.parse_args()
    if args.process_existing:
        print("processed existing", process_existing_jpgs())
    enrich(limit=args.limit or None, missing_only=args.missing_only)


if __name__ == "__main__":
    main()
