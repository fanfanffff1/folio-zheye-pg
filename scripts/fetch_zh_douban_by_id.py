#!/usr/bin/env python3
"""Phase 1 backbone: fetch 豆瓣 book details by subject id (no search).

The 豆瓣 search endpoint throttles hard, but the *detail* endpoint is tolerant
(10/10 at 3s). We already have ~46k subject ids in
    ~/Desktop/inspiration/douban_ids.tsv   (douban_id, title, rating, votes)

This pulls 出版社 / 出版年 / 版次 / ISBN / 页数 / 简介 / 封面 for each id and
caches everything, so it is resumable and safe to run in batches (1k → 10k → …).

Layout (outside the repo, mirrors the English pipeline):
    folio-covers-offline/data-zh/douban-cache.json     parsed fields per id
    folio-covers-offline/data-zh/zh-books.tsv          flat result table
    folio-covers-offline/covers-zh-candidates/<id>.jpg covers
    folio-covers-offline/data-zh/fetch-zh.log          progress log

Usage:
    python3 scripts/fetch_zh_douban_by_id.py --limit 1000 --workers 3
    python3 scripts/fetch_zh_douban_by_id.py --limit 200  --no-cover
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPIRATION = ROOT.parent
IDS_TSV = INSPIRATION / "douban_ids.tsv"
OFFLINE = INSPIRATION / "folio-covers-offline"
DATA = OFFLINE / "data-zh"
COVERS = OFFLINE / "covers-zh-candidates"
CACHE = DATA / "douban-cache.json"
OUT_TSV = DATA / "zh-books.tsv"
LOG = DATA / "fetch-zh.log"
COOKIE_JAR = DATA / "cookies.txt"
# Safari UA + a persistent cookie jar (a `bid` cookie from the homepage) keeps
# Douban happy far longer than the plain Chrome UA (20/20 vs blocking at ~200).
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

_lock = threading.Lock()


def log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _lock:
        print(f"{ts} {line}", flush=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} {line}\n")


def warmup() -> None:
    """Visit the homepage so the cookie jar gets a `bid` cookie."""
    DATA.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-4", "-sSL", "-c", str(COOKIE_JAR), "-o", "/dev/null", "--max-time", "20",
         "-A", UA, "https://book.douban.com/"],
        capture_output=True, timeout=26,
    )


def curl(url: str, binary: bool = False, max_time: int = 25):
    try:
        proc = subprocess.run(
            ["curl", "-4", "-sSL", "--max-time", str(max_time), "-A", UA,
             "-b", str(COOKIE_JAR), "-c", str(COOKIE_JAR),
             "-H", "Accept-Language: zh-CN,zh;q=0.9", "-H", "Referer: https://book.douban.com/", url],
            capture_output=True, timeout=max_time + 6,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    if binary:
        return proc.stdout
    return proc.stdout.decode("utf-8", "ignore")


def clean_html(frag: str) -> str:
    frag = re.sub(r"<br\s*/?>", "\n", frag or "")
    frag = re.sub(r"<[^>]+>", "", frag)
    return htmllib.unescape(frag).strip()


def parse_subject(html: str) -> dict:
    out: dict = {}

    def after(label: str) -> str:
        m = re.search(re.escape(label) + r"\s*:?\s*</span>\s*(.*?)<br\s*/?>", html, re.S)
        if not m:
            m = re.search(re.escape(label) + r"\s*:?\s*</span>\s*(.*?)(?:<br|</div>)", html, re.S)
        # fields are single-line: collapse the markup whitespace/newlines
        return re.sub(r"\s+", " ", clean_html(m.group(1))).strip() if m else ""

    m = re.search(r'property="v:itemreviewed">(.*?)</span>', html)
    out["title"] = re.sub(r"\s+", " ", clean_html(m.group(1))).strip() if m else ""
    out["author"] = after("作者")
    out["translator"] = after("译者")
    out["publisher"] = after("出版社")
    out["pubdate"] = after("出版年")
    out["isbn"] = after("ISBN")
    out["pages"] = after("页数")
    out["binding"] = after("装帧")
    out["original_title"] = after("原作名")
    m = re.search(r'id="mainpic".*?<img[^>]+src="([^"]+)"', html, re.S)
    out["cover"] = m.group(1) if m else ""
    intros = re.findall(r'<div class="intro">(.*?)</div>', html, re.S)
    out["intro"] = max((clean_html(x) for x in intros), key=len, default="")
    m = re.search(r'<span class="pl">\s*评分', html)
    out["ok"] = bool(out["title"]) and ("ISBN" in html or bool(out["publisher"]))
    return out


def big_cover(url: str) -> str:
    return re.sub(r"/view/subject/[a-z]/", "/view/subject/l/", url or "")


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def read_ids() -> list[tuple[str, str]]:
    rows = []
    with open(IDS_TSV, encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            c = line.rstrip("\n").split("\t")
            if c and c[0].strip().isdigit():
                rows.append((c[0].strip(), c[1].strip() if len(c) > 1 else ""))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--sleep-min", type=float, default=5.0)
    ap.add_argument("--sleep-max", type=float, default=10.0)
    ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--max-fail", type=int, default=8, help="consecutive failures before pausing (blocked)")
    ap.add_argument("--cooldown", type=float, default=1800, help="seconds to wait after a block")
    ap.add_argument("--loop", action="store_true", help="keep running batches, cooling down when blocked")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    COVERS.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    all_ids = read_ids()
    if args.retry_errors:
        todo = [(i, t) for i, t in all_ids if cache.get(i, {}).get("_err")]
    else:
        todo = [(i, t) for i, t in all_ids if i not in cache]
    todo = todo[: args.limit]
    warmup()
    log(f"=== fetch start | ids_total={len(all_ids)} cached={len(cache)} todo={len(todo)} workers={args.workers} ===")

    def work(item):
        sid, title = item
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))
        html = curl(f"https://book.douban.com/subject/{sid}/")
        if not html or 'property="v:itemreviewed"' not in html:
            return sid, {"_err": "blocked", "_title_hint": title, "_at": time.time()}
        d = parse_subject(html)
        d["_title_hint"] = title
        d["_at"] = time.time()
        if not args.no_cover and d.get("cover"):
            data = curl(big_cover(d["cover"]), binary=True, max_time=20)
            if data and len(data) > 3000:
                (COVERS / f"{sid}.jpg").write_bytes(data)
                d["_cover_saved"] = True
        return sid, d

    def run_batch(items):
        """Returns (done, ok, cov, blocked). Circuit-breaks after --max-fail misses."""
        done = ok = cov = fails = 0
        blocked = False
        t0 = time.time()

        def consume(sid, d):
            nonlocal done, ok, cov, fails
            cache[sid] = d
            done += 1
            if d.get("ok"):
                ok += 1
                fails = 0
            else:
                fails += 1
            if d.get("_cover_saved"):
                cov += 1
            if done % 10 == 0:
                save_cache(cache)
                log(f"[{done}/{len(items)}] ok={ok} cover={cov} fails={fails} | "
                    f"{done / max(1e-6, time.time() - t0):.2f}/s | last={d.get('title') or d.get('_title_hint')}")
            return fails >= args.max_fail

        if args.workers <= 1:
            for it in items:
                sid, d = work(it)
                if consume(sid, d):
                    blocked = True
                    break
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futs = [ex.submit(work, it) for it in items]
                for fut in as_completed(futs):
                    sid, d = fut.result()
                    if consume(sid, d):
                        blocked = True
                        for f in futs:
                            f.cancel()
                        break
        save_cache(cache)
        return done, ok, cov, blocked

    total_ok = total_cov = 0
    while True:
        batch = [it for it in todo if it[0] not in cache]
        if not batch:
            break
        done, ok, cov, blocked = run_batch(batch)
        total_ok += ok
        total_cov += cov
        if blocked:
            log(f"!! blocked after {done} in this batch; cooling down {int(args.cooldown)}s")
            if not args.loop:
                break
            time.sleep(args.cooldown)
            warmup()  # refresh cookies before the next batch
        elif not args.loop:
            break
    ok, cov = total_ok, total_cov
    # flat table
    with open(OUT_TSV, "w", encoding="utf-8") as fh:
        fh.write("douban_id\ttitle\tauthor\tpublisher\tpubdate\tisbn\tpages\tbinding\tintro_len\tcover\n")
        for sid, _ in all_ids:
            d = cache.get(sid)
            if not d:
                continue
            fh.write("\t".join([
                sid, (d.get("title") or d.get("_title_hint") or "").replace("\t", " "),
                (d.get("author") or "").replace("\t", " "), (d.get("publisher") or "").replace("\t", " "),
                d.get("pubdate") or "", d.get("isbn") or "", d.get("pages") or "",
                d.get("binding") or "", str(len(d.get("intro") or "")),
                "Y" if d.get("_cover_saved") else "",
            ]) + "\n")
    log(f"=== fetch done | done={done} ok={ok} cover={cov} | cache={len(cache)} -> {OUT_TSV} ===")


if __name__ == "__main__":
    main()
