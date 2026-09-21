#!/usr/bin/env python3
"""Backbone crawler: zhihailib.com book pages → Chinese book metadata + covers.

zhihailib exposes ~174k book pages (see ../zhihailib_ids.txt, built from its
sitemap). Each /book/<id> page carries og:title / og:image / og:description with
《书名》, 作者, 出版社, 出版日期, 语言 — enough for a bibliography + cover.

The author string usually starts with a nationality tag (`[英]莎士比亚`,
`（美）杰夫·沃克`, `[清]陈球`). We use it to flag 外文译作 vs 中文原作 so the
catalog can keep Chinese originals only.

Layout (outside the repo, mirrors the English pipeline):
    folio-covers-offline/data-zh/zhihailib-cache.json
    folio-covers-offline/data-zh/zhihailib-books.tsv
    folio-covers-offline/covers-zh-candidates/<id>.jpg
    folio-covers-offline/data-zh/zhihailib.log

Usage:
    python3 scripts/fetch_zhihailib.py --limit 1000 --workers 6
    python3 scripts/fetch_zhihailib.py --limit 1000 --workers 6 --no-cover
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
IDS_TXT = INSPIRATION / "zhihailib_ids.txt"
OFFLINE = INSPIRATION / "folio-covers-offline"
DATA = OFFLINE / "data-zh"
COVERS = OFFLINE / "covers-zh-candidates"
CACHE = DATA / "zhihailib-cache.json"
OUT_TSV = DATA / "zhihailib-books.tsv"
LOG = DATA / "zhihailib.log"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

FOREIGN = ("英", "美", "法", "德", "日", "俄", "苏", "意", "西班牙", "韩", "爱尔兰", "加拿大", "澳",
           "奥地利", "瑞典", "挪威", "丹麦", "荷兰", "波兰", "印度", "巴西", "哥伦比亚", "阿根廷",
           "以色列", "土耳其", "希腊", "瑞士", "比利时", "葡萄牙", "南非", "埃及", "尼日利亚", "智利",
           "秘鲁", "捷克", "匈牙利", "罗马尼亚", "芬兰", "冰岛", "乌克兰", "伊朗", "伊拉克", "越南",
           "泰国", "马来西亚", "新西兰", "墨西哥", "古巴", "乌拉圭", "塞尔维亚", "保加利亚", "克罗地亚")
DYNASTY = ("先秦", "春秋", "战国", "西周", "东周", "秦", "汉", "三国", "魏晋", "南北朝", "隋", "唐",
           "五代", "宋", "辽", "金", "元", "明", "清", "民国", "近代", "现代", "当代")
_lock = threading.Lock()


def log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _lock:
        print(f"{ts} {line}", flush=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} {line}\n")


def curl(url: str, binary: bool = False, max_time: int = 25):
    try:
        proc = subprocess.run(
            ["curl", "-4", "-sSL", "--max-time", str(max_time), "-A", UA, url],
            capture_output=True, timeout=max_time + 6,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout if binary else proc.stdout.decode("utf-8", "ignore")


def meta(html: str, prop: str) -> str:
    m = re.search(r'property="' + re.escape(prop) + r'"\s+content="([^"]*)"', html)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def classify_author(author: str) -> str:
    """'zh' (Chinese original) | 'translation' | 'unknown'."""
    a = (author or "").strip()
    if not a:
        return "unknown"
    m = re.match(r"^\s*[\[【(（]\s*([^\]】)）]{1,8})\s*[\]】)）]", a)
    if m:
        tag = m.group(1)
        if any(f in tag for f in FOREIGN):
            return "translation"
        if any(d in tag for d in DYNASTY):
            return "zh"
        return "unknown"
    return "zh"  # plain Chinese name, no nationality tag


def parse_page(html: str) -> dict:
    """Handles both page shapes:
    new  og:title=书名 ; og:desc='…《书名》, 作者: X, 出版社: Y, 出版日期: Z …'
    old  og:title='《书名》作者：X' ; og:desc='TXT / X / 校对版全本 / 完本 / 简介…'
    """
    desc = meta(html, "og:description")
    title = meta(html, "og:title")
    cover = meta(html, "og:image")
    author = publisher = pubdate = language = fmt = intro = ""
    full_title = ""

    def f(label: str) -> str:
        m = re.search(re.escape(label) + r"\s*[:：]\s*([^,，]+)", desc)
        return m.group(1).strip() if m else ""

    if "免费下载这本书" in desc or re.search(r"作者\s*[:：]", desc):
        # new structured format
        t = re.search(r"《(.*?)》", desc)
        full_title = t.group(1).strip() if t else title
        author, publisher, pubdate, language, fmt = (
            f("作者"), f("出版社"), f("出版日期"), f("语言"), f("文件格式"))
    else:
        # old format (web novels): title carries 作者, desc is slash-separated
        m = re.match(r"《(.*?)》\s*作者\s*[:：]\s*(.+)", title)
        if m:
            full_title, author = m.group(1).strip(), m.group(2).strip()
        else:
            full_title = title
        parts = [p.strip() for p in desc.split("/") if p.strip()]
        if parts:
            fmt = parts[0]
            if not author and len(parts) > 1:
                author = parts[1]
            tail = [p for p in parts[2:] if len(p) > 30]
            if tail:
                intro = max(tail, key=len)

    clean = re.sub(r"[（(][^）)]*[）)]\s*$", "", full_title).strip() or full_title
    return {
        "title": full_title,
        "title_clean": clean,
        "author": author,
        "publisher": publisher,
        "pubdate": pubdate,
        "language": language,
        "format": fmt,
        "intro": intro,
        "cover_url": cover,
        "origin": classify_author(author),
        "ok": bool(full_title) and bool(author),
    }


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sleep-min", type=float, default=0.2)
    ap.add_argument("--sleep-max", type=float, default=0.6)
    ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--max-fail", type=int, default=25)
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    COVERS.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    all_ids = [l.strip() for l in IDS_TXT.read_text(encoding="utf-8").splitlines() if l.strip().isdigit()]
    todo = [i for i in all_ids if i not in cache][: args.limit]
    log(f"=== zhihailib start | ids_total={len(all_ids)} cached={len(cache)} todo={len(todo)} workers={args.workers} ===")

    def work(sid: str):
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))
        html = curl(f"https://www.zhihailib.com/book/{sid}")
        if html and ("Page not found" in html or "页面不存在" in html):
            return sid, {"_err": "notfound", "_at": time.time()}
        if not html or 'property="og:title"' not in html:
            return sid, {"_err": "fetch", "_at": time.time()}
        d = parse_page(html)
        d["_at"] = time.time()
        if not args.no_cover and d.get("cover_url"):
            data = curl(d["cover_url"], binary=True, max_time=25)
            if data and len(data) > 2500:
                (COVERS / f"{sid}.jpg").write_bytes(data)
                d["_cover_saved"] = True
        return sid, d

    done = ok = cov = zh = 0
    fails = 0
    t0 = time.time()

    def consume(sid, d):
        nonlocal done, ok, cov, zh, fails
        cache[sid] = d
        done += 1
        if d.get("ok"):
            ok += 1
            fails = 0
        elif d.get("_err") == "notfound":
            pass  # dead sitemap entry — not a real failure
        else:
            fails += 1
        if d.get("_cover_saved"):
            cov += 1
        if d.get("origin") == "zh":
            zh += 1
        if done % 25 == 0:
            save_cache(cache)
            log(f"[{done}/{len(todo)}] ok={ok} cover={cov} zh原作={zh} fails={fails} | "
                f"{done / max(1e-6, time.time() - t0):.2f}/s")
        return fails >= args.max_fail

    blocked = False
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, s) for s in todo]
        for fut in as_completed(futs):
            sid, d = fut.result()
            if consume(sid, d):
                blocked = True
                for f in futs:
                    f.cancel()
                break
    save_cache(cache)

    with open(OUT_TSV, "w", encoding="utf-8") as fh:
        fh.write("id\ttitle\ttitle_clean\tauthor\tpublisher\tpubdate\torigin\tcover\n")
        for sid in all_ids:
            d = cache.get(sid)
            if not d:
                continue
            fh.write("\t".join([
                sid, (d.get("title") or "").replace("\t", " "), (d.get("title_clean") or "").replace("\t", " "),
                (d.get("author") or "").replace("\t", " "), (d.get("publisher") or "").replace("\t", " "),
                d.get("pubdate") or "", d.get("origin") or "", "Y" if d.get("_cover_saved") else "",
            ]) + "\n")
    log(f"=== zhihailib done | done={done} ok={ok} cover={cov} zh原作={zh} blocked={blocked} -> {OUT_TSV} ===")


if __name__ == "__main__":
    main()
