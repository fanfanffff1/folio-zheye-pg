#!/usr/bin/env python3
"""Phase 1 seed: import the 中国地域与世界华文文学百年书单 (author → works) list.

Reads the "作者作品库" sheet (地区 / 时期层 / 作者 / 代表作1-3 / 重要作4-5 /
纳入理由 / 交叉地区) and creates the authors + their works as Chinese books
(language_code="zh"). This is the ~1000-book pilot for the 10万中文书库 project.

Idempotent: books are matched by slug, and by (normalized title, author).

Usage:
    python3 scripts/import_zh_seed.py --dry-run
    python3 scripts/import_zh_seed.py
    DATABASE_URL="<neon>" python3 scripts/import_zh_seed.py    # production
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
INSPIRATION = ROOT.parent
XLSX = INSPIRATION / "中国地域与世界华文文学百年书单.xlsx"
SHEET = "作者作品库"
SOURCE_NAME = "中国地域与世界华文文学百年书单"

sys.path.insert(0, str(ROOT))

from folio.models import Author, Book, SessionLocal, init_db  # noqa: E402

try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return re.sub(r"[\s《》〈〉「」『』·,，.。:：;；!！?？\-—_/\\()（）\[\]【】\"'’‘“”]+", "", text)


def trunc(value, n: int) -> str:
    s = value if isinstance(value, str) else ("" if value is None else str(value))
    return s[:n]


def slug_base(title: str) -> str:
    if lazy_pinyin:
        py = "-".join(p for p in lazy_pinyin(title) if p.strip())
        py = re.sub(r"[^a-z0-9]+", "-", py.lower()).strip("-")
        if py:
            return "zh-" + py[:80]
    import hashlib
    return "zh-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not XLSX.exists():
        raise SystemExit(f"找不到表格：{XLSX}")
    wb = load_workbook(XLSX, read_only=True)
    if SHEET not in wb.sheetnames:
        raise SystemExit(f"缺少工作表：{SHEET}")
    ws = wb[SHEET]
    it = ws.iter_rows(values_only=True)
    # the header may not be the first row (title/blank rows above it)
    hdr, col = [], {}
    for _ in range(8):
        row = next(it, None)
        if row is None:
            break
        cand = [str(h).strip() if h is not None else "" for h in row]
        if "作者" in cand and any(c.startswith("代表作") for c in cand):
            hdr = cand
            col = {h: i for i, h in enumerate(hdr)}
            break
    if not col:
        raise SystemExit(f"在 {SHEET} 前 8 行找不到表头（需含 作者 / 代表作…）")
    need = ["地区", "时期层", "作者", "代表作1", "代表作2", "代表作3", "重要作4", "重要作5", "纳入理由", "交叉地区"]
    for k in need:
        if k not in col:
            raise SystemExit(f"缺少列：{k}（表头：{hdr}）")

    def cell(row, key):
        i = col[key]
        v = row[i] if i < len(row) else None
        return str(v).strip() if v is not None else ""

    if not args.dry_run:
        init_db()
    db = SessionLocal() if not args.dry_run else None
    authors_n = books_n = 0
    seen_slugs: set[str] = set()
    try:
        for row in it:
            author_name = cell(row, "作者")
            if not author_name:
                continue
            works = [cell(row, f"代表作{i}") for i in (1, 2, 3)] + [cell(row, f"重要作{i}") for i in (4, 5)]
            works = [w for w in works if w]
            if not works:
                continue
            region = cell(row, "地区")
            period = cell(row, "时期层")
            cross = cell(row, "交叉地区")
            reason = cell(row, "纳入理由")
            tags = [t for t in [region, period, cross] if t]

            author = None
            if not args.dry_run:
                author = db.query(Author).filter(Author.name == author_name).one_or_none()
                if not author:
                    author = Author(name=trunc(author_name, 200), localized_name=trunc(author_name, 200))
                    db.add(author)
                    db.flush()
            authors_n += 1

            for work in works:
                if args.limit and books_n >= args.limit:
                    break
                # dedup within this run and against the DB
                if not args.dry_run:
                    existing = (
                        db.query(Book)
                        .filter(Book.author_id == author.id, Book.language_code == "zh")
                        .all()
                    )
                    hit = next((b for b in existing if norm(b.chinese_title) == norm(work)), None)
                else:
                    hit = None
                if hit:
                    hit.tags = ",".join(dict.fromkeys([t for t in (hit.tags or "").split(",") if t] + tags))
                    continue

                base = slug_base(work)
                slug = base
                n = 2
                while slug in seen_slugs or (not args.dry_run and db.query(Book).filter(Book.slug == slug).first()):
                    slug = f"{base}-{n}"
                    n += 1
                seen_slugs.add(slug)

                if not args.dry_run:
                    book = Book(
                        slug=slug,
                        original_title=trunc(work, 400),
                        chinese_title=trunc(work, 400),
                        author_id=author.id,
                        language_code="zh",
                        language_name="中文",
                        primary_genre="文学",
                        tags=trunc(",".join(tags), 400),
                        short_description_zh="",
                        cover_image="/covers/placeholder.svg",
                        verification_status="pending",
                        source_name=SOURCE_NAME,
                        source_file=XLSX.name,
                        source_row=row[0] if row and isinstance(row[0], int) else 0,
                        selection_reason=reason,
                    )
                    db.add(book)
                books_n += 1
            if args.limit and books_n >= args.limit:
                break
        if not args.dry_run:
            db.commit()
        print(f"{'[dry-run] ' if args.dry_run else ''}authors={authors_n} books={books_n}")
    finally:
        if db:
            db.close()
        wb.close()


if __name__ == "__main__":
    main()
