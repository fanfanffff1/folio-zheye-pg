#!/usr/bin/env python3
"""Enrich Chinese books (language_code="zh") from Douban.

Design (per editorial guidance):
- SEARCH and FETCH are separate phases. Search resolves a Douban subject id and
  caches it in the state file; fetch then only opens /subject/{id}/ (one request,
  no search) and pulls just 出版社/出版年/版次/ISBN/页数/简介/封面.
- If an ISBN or Douban id is already known (from 国图/微信读书/OpenLibrary/…),
  it is used directly and the search is skipped entirely.
- Random 3-8s delay between requests + exponential backoff on throttle
  (60s → 120s → 240s …, not a fixed cooldown).
- Cached + resumable; progress log at data/reports/zh-enrich.log

Usage:
    python3 scripts/enrich_zh_douban.py --phase search --limit 100
    python3 scripts/enrich_zh_douban.py --phase fetch  --limit 100
    python3 scripts/enrich_zh_douban.py --phase all    --limit 50
    python3 scripts/enrich_zh_douban.py --phase fetch --sleep-min 3 --sleep-max 8
"""
from __future__ import annotations

import argparse
import gzip
import html as htmllib
import io as _io
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.cover_urls import derive_cover_urls  # noqa: E402
from folio.models import Book, SessionLocal, init_db  # noqa: E402

COVERS_DIR = ROOT / "static" / "covers"
REPORT_DIR = ROOT / "data" / "reports"
STATE_PATH = REPORT_DIR / "zh-enrich-state.json"
LOG_PATH = REPORT_DIR / "zh-enrich.log"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_opener = None


def opener():
    global _opener
    if _opener is None:
        cj = CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        _opener.addheaders = [
            ("User-Agent", UA),
            ("Accept-Language", "zh-CN,zh;q=0.9"),
            ("Referer", "https://book.douban.com/"),
        ]
    return _opener


class Throttled(Exception):
    pass


def get(url: str, binary: bool = False, retries: int = 3, timeout: int = 30):
    last = None
    for i in range(retries):
        try:
            r = opener().open(url, timeout=timeout)
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data if binary else data.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.5 * (i + 1))
    raise last


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return re.sub(r"[\s《》〈〉「」『』·,，.。:：;；!！?？\-—_/\\()（）\[\]【】\"'’‘“”]+", "", text)


def clean_html(frag: str) -> str:
    frag = re.sub(r"<br\s*/?>", "\n", frag or "")
    frag = re.sub(r"<[^>]+>", "", frag)
    return htmllib.unescape(frag).strip()


# ---------------------------------------------------------------- search ----
def douban_search(title: str, author: str):
    q = urllib.parse.quote(title)
    html = get(f"https://search.douban.com/book/subject_search?search_text={q}&cat=1001")
    m = re.search(r"window\.__DATA__\s*=\s*", html)
    if not m:
        return None
    start = m.end()
    depth = 0
    i = start
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    try:
        data = json.loads(html[start:i + 1])
    except Exception:
        return None
    err = (data.get("error_info") or "").strip()
    if err:
        raise Throttled(err)
    items = data.get("items") or []
    nt, na = norm(title), norm(author)
    matches = []
    for it in items:
        if norm(it.get("title")) != nt:
            continue
        if na and na not in norm(it.get("abstract") or ""):
            continue
        matches.append(it)
    if not matches:
        return None

    def popularity(it):
        r = it.get("rating") or {}
        return (r.get("count") or 0, r.get("value") or 0)

    matches.sort(key=popularity, reverse=True)
    return matches[0]


# ----------------------------------------------------------------- fetch ----
def parse_subject(html: str) -> dict:
    out: dict = {}

    def after(label: str) -> str:
        m = re.search(re.escape(label) + r"\s*:?\s*</span>\s*(.*?)<br\s*/?>", html, re.S)
        if not m:
            m = re.search(re.escape(label) + r"\s*:?\s*</span>\s*(.*?)(?:<br|</div>)", html, re.S)
        return clean_html(m.group(1)) if m else ""

    m = re.search(r'property="v:itemreviewed">(.*?)</span>', html)
    out["title"] = clean_html(m.group(1)) if m else ""
    out["author"] = after("作者")
    out["translator"] = after("译者")
    out["publisher"] = after("出版社")
    out["pubdate"] = after("出版年")
    out["isbn"] = after("ISBN")
    out["pages"] = after("页数")
    out["binding"] = after("装帧")
    out["subtitle"] = after("副标题")
    out["original_title"] = after("原作名")
    m = re.search(r'id="mainpic".*?<img[^>]+src="([^"]+)"', html, re.S)
    out["cover"] = m.group(1) if m else ""
    intros = re.findall(r'<div class="intro">(.*?)</div>', html, re.S)
    out["intro"] = max((clean_html(x) for x in intros), key=len, default="")
    return out


def big_cover(url: str) -> str:
    return re.sub(r"/view/subject/[a-z]/", "/view/subject/l/", url or "")


def download_cover(url: str, dest: Path) -> bool:
    try:
        data = get(big_cover(url), binary=True)
    except Exception:
        return False
    if len(data) < 3000:
        return False
    try:
        from PIL import Image
        im = Image.open(_io.BytesIO(data)).convert("RGB")
        if min(im.size) < 120:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=92)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ main ----
def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=0), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["search", "fetch", "all"], default="all")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--sleep-min", type=float, default=3.0)
    ap.add_argument("--sleep-max", type=float, default=8.0)
    ap.add_argument("--backoff-base", type=float, default=60, help="throttle wait = base * 2^attempt")
    ap.add_argument("--backoff-max", type=float, default=900)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(LOG_PATH, "a", encoding="utf-8")

    def log(line: str) -> None:
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    def pause() -> None:
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    if not args.dry_run:
        init_db()
    db = SessionLocal()
    state = load_state()

    books = db.query(Book).filter(Book.language_code == "zh").order_by(Book.id).all()
    if not args.force:
        if args.phase == "search":
            books = [b for b in books if b.slug not in state]
        elif args.phase == "fetch":
            books = [b for b in books if state.get(b.slug, {}).get("douban_id")
                     and not state.get(b.slug, {}).get("fetched_at")]
        else:
            books = [b for b in books if state.get(b.slug, {}).get("status") != "ok"]
    todo = books[: args.limit]
    log(f"=== {args.phase} start {time.strftime('%Y-%m-%d %H:%M:%S')} | todo={len(todo)} dry={args.dry_run} ===")

    ok = miss = 0
    for i, b in enumerate(todo, 1):
        title = (b.chinese_title or b.original_title or "").strip()
        author = b.author.name if b.author else ""
        st = state.setdefault(b.slug, {})

        def cooldown(fn):
            for attempt in range(6):
                try:
                    return fn()
                except Throttled as te:
                    wait = min(args.backoff_max, args.backoff_base * (2 ** attempt))
                    log(f"[{i}/{len(todo)}] THROTTLE {te} -> sleep {int(wait)}s")
                    time.sleep(wait)
            return None

        try:
            # 1) resolve a Douban id (skip if we already have one)
            if args.phase in ("search", "all") and not st.get("douban_id"):
                hit = cooldown(lambda: douban_search(title, author))
                pause()
                if not hit:
                    if st.get("status") != "ok":
                        st.update(status="no_match", at=time.time())
                    log(f"[{i}/{len(todo)}] MISS  {b.slug} | {title} / {author}")
                    miss += 1
                    continue
                st["douban_id"] = str(hit["id"])
                st["searched_at"] = time.time()
                save_state(state)
            sid = st.get("douban_id")
            if not sid:
                miss += 1
                continue

            if args.phase == "search":
                log(f"[{i}/{len(todo)}] FOUND {b.slug} | {title} -> douban/{sid}")
                ok += 1
                continue

            # 2) fetch the subject page and fill fields
            html = cooldown(lambda: get(f"https://book.douban.com/subject/{sid}/"))
            pause()
            if not html:
                log(f"[{i}/{len(todo)}] SKIP  {b.slug} | {title} (throttled)")
                continue
            sub = parse_subject(html)
            isbn = re.sub(r"[^0-9Xx]", "", sub.get("isbn") or "")
            cover_ok = False
            cover_rel = b.cover_image
            if sub.get("cover") and not args.dry_run:
                dest = COVERS_DIR / (b.slug + ".jpg")
                cover_ok = download_cover(sub["cover"], dest)
                if cover_ok:
                    cover_rel = "/covers/" + dest.name
            if not args.dry_run:
                b.publisher = sub.get("publisher") or b.publisher
                y = (sub.get("pubdate") or "")[:4]
                if y.isdigit():
                    b.publication_year = int(y)
                if sub.get("binding"):
                    b.edition = sub["binding"]
                if len(isbn) == 13:
                    b.isbn13 = isbn
                elif len(isbn) == 10:
                    b.isbn10 = isbn
                if sub.get("intro"):
                    b.full_description_zh = sub["intro"]
                    if not b.short_description_zh:
                        b.short_description_zh = sub["intro"][:80]
                if cover_ok:
                    b.cover_image = cover_rel
                    b.cover_thumbnail_url, b.cover_full_url = derive_cover_urls(cover_rel)
                b.source_name = "豆瓣"
                b.source_url = f"https://book.douban.com/subject/{sid}/"
                b.verification_status = "verified"
                db.commit()
            st.update(status="ok", fetched_at=time.time(), isbn=isbn, cover=cover_ok)
            save_state(state)
            ok += 1
            log(f"[{i}/{len(todo)}] OK    {b.slug} | {title} | isbn={isbn or '-'} cover={'Y' if cover_ok else 'n'} pub={sub.get('publisher','')}")
        except Exception as e:  # noqa: BLE001
            st.update(status="error", err=str(e)[:120], at=time.time())
            log(f"[{i}/{len(todo)}] ERR   {b.slug} | {title} | {e}")
        if not args.dry_run and i % 10 == 0:
            save_state(state)

    if not args.dry_run:
        save_state(state)
    log(f"=== {args.phase} done | ok={ok} miss={miss} ===")
    db.close()
    logf.close()


if __name__ == "__main__":
    main()
