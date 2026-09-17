#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import language XLSX catalogs into a cleaned JSON dataset.

Idempotent: re-running overwrites data/cleaned-books.json and reports,
but does not invent bibliographic facts. Buy-channel columns are dropped.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:
    print("Need openpyxl", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
INSPIRATION = ROOT.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = DATA_DIR / "reports"

LANG_FOLDERS = {
    "en": ("英文原版书籍", "英语", "English"),
    "es": ("西班牙语原版书籍", "西班牙语", "Español"),
    "ja": ("日语原版书籍", "日语", "日本語"),
    "ko": ("韩语原版书籍", "韩语", "한국어"),
    "fr": ("法语原版书籍", "法语", "Français"),
    "it": ("意大利语原版书籍", "意大利语", "Italiano"),
}

HEADER_ALIASES = {
    "原文书名": "originalTitle",
    "title": "originalTitle",
    "书名": "originalTitle",
    "中文常用译名": "chineseTitle",
    "中文译名": "chineseTitle",
    "作者": "author",
    "author": "author",
    "作者国家/地区": "nationality",
    "首次出版年": "yearRaw",
    "出版日期": "yearRaw",
    "publication date": "yearRaw",
    "原版代表出版社": "publisher",
    "出版社": "publisher",
    "publisher": "publisher",
    "isbn-13（代表版，下单请再核）": "isbn",
    "isbn-13（代表版,下单请再核）": "isbn",
    "isbn13": "isbn",
    "isbn-13": "isbn",
    "isbn": "isbn",
    "主类型": "genreRaw",
    "类型": "genreRaw",
    "genre": "genreRaw",
    "子类型": "subgenre",
    "热度标签": "heat",
    "一句话简介": "blurb",
    "简介": "blurb",
    "description": "blurb",
    "适合谁": "audience",
    "入选理由": "why",
    "优先级": "priority",
    "序号": "rowNo",
    "语言": "languageHint",
    "language": "languageHint",
    "封面": "cover",
    "cover": "cover",
}

GENRE_MAP = {
    "氛围悬疑": ("悬疑", ["悬疑", "惊悚"]),
    "推理犯罪": ("推理", ["推理", "悬疑"]),
    "休闲日常": ("家庭", ["家庭", "成长"]),
    "爱情": ("爱情", ["爱情"]),
    "文学": ("文学小说", ["文学小说"]),
    "恐怖": ("惊悚", ["惊悚", "悬疑"]),
    "科幻": ("科幻", ["科幻"]),
    "奇幻": ("奇幻", ["奇幻"]),
    "剧情历史": ("历史", ["历史", "社会议题"]),
}

ASCII_SLUG_RE = re.compile(r"[^a-z0-9]+")


def norm_header(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def map_headers(cells) -> dict:
    mapping = {}
    aliases = {k.lower(): v for k, v in HEADER_ALIASES.items()}
    for idx, cell in enumerate(cells):
        key = aliases.get(norm_header(cell))
        if key:
            mapping[key] = idx
    return mapping


def normalize_isbn(raw) -> str:
    if raw is None:
        return ""
    s = re.sub(r"[^0-9Xx]", "", str(raw).strip())
    if len(s) in (10, 13):
        return s.upper()
    return ""


def parse_year(raw):
    if raw is None:
        return None, "missing"
    if isinstance(raw, int) and 1400 <= raw <= 2030:
        return raw, "ok"
    if isinstance(raw, float) and raw == int(raw) and 1400 <= int(raw) <= 2030:
        return int(raw), "ok"
    text = str(raw).strip()
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", text)
    if m:
        return int(m.group(1)), "parsed"
    return None, "invalid"


def make_slug(lang: str, title: str, author: str, isbn: str, seq: int) -> str:
    ascii_part = ASCII_SLUG_RE.sub("-", title.lower()).strip("-")
    if ascii_part and re.fullmatch(r"[a-z0-9-]{3,80}", ascii_part):
        base = f"{lang}-{ascii_part}"[:80]
    elif isbn:
        base = f"{lang}-{isbn}"
    else:
        digest = hashlib.sha1(f"{lang}|{title}|{author}".encode("utf-8")).hexdigest()[:10]
        base = f"{lang}-{digest}"
    return f"{base}" if seq == 0 else f"{base}-{seq}"


def pad_short(blurb: str, audience: str, genre: str) -> str:
    text = (blurb or "").strip()
    if len(text) < 80 and audience:
        extra = audience.strip().rstrip("。")
        text = f"{text}{'。' if text and not text.endswith('。') else ''}适合{extra}。"
    if len(text) < 80:
        text = (
            f"{text}{'。' if text and not text.endswith('。') else ''}"
            f"本书属{genre}类原版读物，宜按原作语言阅读，感知句法与节奏。"
            "本站只提供中文导读与交流，不提供购买服务。"
            "封面与出版信息如有出入，以原书版权页为准。"
        )
    if len(text) > 150:
        text = text[:147].rstrip("，、； ") + "…"
    return text


def iter_tabular(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        wb = load_workbook(path, data_only=True)
        for sheet in wb.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            yield sheet.title, rows
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = [tuple(r) for r in csv.reader(fh)]
        yield path.stem, rows


def collect_source_files() -> list[tuple[str, Path]]:
    found = []
    for code, (folder, _zh, _native) in LANG_FOLDERS.items():
        directory = INSPIRATION / folder
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.xlsx")) + sorted(directory.glob("*.xls")) + sorted(directory.glob("*.csv")):
            if path.name.startswith("~$"):
                continue
            found.append((code, path))
    extra = INSPIRATION / "书籍推荐" / "incoming"
    if extra.exists():
        for path in sorted(extra.glob("*.xlsx")) + sorted(extra.glob("*.xls")) + sorted(extra.glob("*.csv")):
            found.append(("und", path))
    return found


def import_all(dry_run: bool = False) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    books = []
    warnings = []
    skipped = []
    failed = []
    seen_isbn = {}
    seen_key = {}
    slug_count = Counter()
    stats = Counter()

    sources = collect_source_files()
    if not sources:
        raise SystemExit("No XLSX/CSV catalogs found.")

    for lang_code, path in sources:
        lang_name = LANG_FOLDERS.get(lang_code, (None, lang_code, lang_code))[1]
        try:
            sheets = list(iter_tabular(path))
        except Exception as exc:
            failed.append({"file": str(path), "error": str(exc)})
            continue
        for sheet_name, rows in sheets:
            if not rows:
                continue
            header_map = map_headers(rows[0])
            if "originalTitle" not in header_map:
                skipped.append({"file": path.name, "sheet": sheet_name, "reason": "no title column"})
                continue
            for i, row in enumerate(rows[1:], start=2):
                stats["rows_seen"] += 1
                try:
                    title = str(row[header_map["originalTitle"]] or "").strip()
                except Exception:
                    failed.append({"file": path.name, "sheet": sheet_name, "row": i, "reason": "row read error"})
                    continue
                if not title or title.startswith("—"):
                    skipped.append({"file": path.name, "row": i, "reason": "empty title"})
                    continue
                why = ""
                if "why" in header_map:
                    why = str(row[header_map["why"]] or "")
                if "占位" in why or "跳过" in why or "重复" in why:
                    skipped.append({"file": path.name, "row": i, "title": title, "reason": "placeholder/duplicate flag"})
                    continue

                def col(name, default=""):
                    if name not in header_map:
                        return default
                    value = row[header_map[name]]
                    return default if value is None else value

                isbn = normalize_isbn(col("isbn"))
                year, year_status = parse_year(col("yearRaw"))
                author = str(col("author")).strip()
                publisher = str(col("publisher")).strip()
                chinese = str(col("chineseTitle")).strip()
                genre_raw = str(col("genreRaw")).strip()
                primary, tags = GENRE_MAP.get(genre_raw, ("其他", ["其他"]))
                sub = str(col("subgenre")).strip()
                if sub:
                    tags = list(dict.fromkeys(tags + [sub]))
                blurb = str(col("blurb")).strip()
                audience = str(col("audience")).strip()
                nationality = str(col("nationality")).strip()
                heat = str(col("heat")).strip()
                cover = str(col("cover")).strip()

                if year_status != "ok":
                    warnings.append({
                        "file": path.name, "row": i, "title": title,
                        "field": "year", "value": str(col("yearRaw")), "status": year_status,
                    })
                if not isbn:
                    warnings.append({"file": path.name, "row": i, "title": title, "field": "isbn", "status": "missing"})
                if year_status == "invalid":
                    failed.append({"file": path.name, "row": i, "title": title, "reason": f"bad year {col('yearRaw')}"})
                    # keep the book, mark pending
                dup_isbn = isbn and isbn in seen_isbn
                key = f"{lang_code}|{title.lower()}|{author.lower()}"
                dup_key = key in seen_key
                if dup_isbn or dup_key:
                    skipped.append({
                        "file": path.name, "row": i, "title": title,
                        "reason": "duplicate",
                        "match": seen_isbn.get(isbn) or seen_key.get(key),
                    })
                    stats["skipped_dup"] += 1
                    continue

                slug_base = make_slug(lang_code, title, author, isbn, 0)
                slug_count[slug_base] += 1
                slug = slug_base if slug_count[slug_base] == 1 else f"{slug_base}-{slug_count[slug_base]}"

                verification = "verified" if (year and publisher and author and title) else "pending"
                if not year or year_status != "ok":
                    verification = "pending"
                if not isbn:
                    # ISBN missing is common in this catalog; keep verified if year/publisher known
                    pass

                pub_date = f"{year}-01-01" if year else None
                record = {
                    "slug": slug,
                    "originalTitle": title,
                    "chineseTitle": chinese if chinese and chinese != "—" else "",
                    "authorName": author,
                    "nationality": nationality,
                    "languageCode": lang_code,
                    "languageName": lang_name,
                    "publisher": publisher if publisher != "—" else "",
                    "publicationYear": year,
                    "publicationDate": pub_date,
                    "isbn13": isbn if len(isbn) == 13 else "",
                    "isbn10": isbn if len(isbn) == 10 else "",
                    "primaryGenre": primary,
                    "genres": [primary],
                    "tags": tags,
                    "heat": heat,
                    "shortDescriptionZh": pad_short(blurb, audience, primary),
                    "audienceHintZh": audience,
                    "whyHintZh": why,
                    "coverImage": cover,
                    "isFeatured": False,
                    "isRecommended": False,
                    "issueId": None,
                    "verificationStatus": verification,
                    "sourceFile": path.name,
                    "sourceSheet": sheet_name,
                    "sourceRow": i,
                    "selectionReason": "",
                    "sourceName": "inspiration catalog xlsx",
                    "sourceUrl": "",
                }
                books.append(record)
                if isbn:
                    seen_isbn[isbn] = slug
                seen_key[key] = slug
                stats["imported"] += 1

    payload = {
        "generatedAt": date.today().isoformat(),
        "bookCount": len(books),
        "languages": sorted({b["languageCode"] for b in books}),
        "books": books,
    }
    if not dry_run:
        (DATA_DIR / "cleaned-books.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (REPORT_DIR / "import-summary.json").write_text(
            json.dumps({
                "imported": stats["imported"],
                "skipped": len(skipped),
                "warnings": len(warnings),
                "failed": len(failed),
                "byLanguage": dict(Counter(b["languageCode"] for b in books)),
                "missingIsbn": sum(1 for b in books if not b["isbn13"] and not b["isbn10"]),
                "pendingYear": sum(1 for b in books if b["verificationStatus"] == "pending"),
                "year2026": sum(1 for b in books if b["publicationYear"] == 2026),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (REPORT_DIR / "warnings.json").write_text(json.dumps(warnings, ensure_ascii=False, indent=2), encoding="utf-8")
        (REPORT_DIR / "skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")
        (REPORT_DIR / "failed.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        pending = [b for b in books if b["verificationStatus"] == "pending" or not (b["isbn13"] or b["isbn10"])]
        (REPORT_DIR / "pending-verification.json").write_text(
            json.dumps([
                {
                    "slug": b["slug"],
                    "title": b["originalTitle"],
                    "author": b["authorName"],
                    "year": b["publicationYear"],
                    "isbn": b["isbn13"] or b["isbn10"],
                    "language": b["languageCode"],
                    "status": b["verificationStatus"],
                }
                for b in pending
            ], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        f"imported={stats['imported']} skipped={len(skipped)} "
        f"warnings={len(warnings)} failed={len(failed)} dry_run={dry_run}"
    )
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_all(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
