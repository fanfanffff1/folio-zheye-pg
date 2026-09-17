#!/usr/bin/env python3
"""Replace featured book copy from data/FOLIO_书籍详情页润色文案.md."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "data" / "FOLIO_书籍详情页润色文案.md"
FEAT = ROOT / "folio" / "featured.py"

HEAD = re.compile(r"^### \d+\. (.+?)｜", re.M)
BLOCK = re.compile(
    r"\*\*内容简介\*\*  \n(?P<synopsis>.+?)\n\n"
    r"\*\*为什么推荐\*\*  \n(?P<reason>.+?)\n\n"
    r"\*\*谁会喜欢\*\*  \n(?P<audience>.+?)\n\n"
    r"\*\*作者介绍\*\*  \n(?P<bio>.+?)(?=\n### |\n---\n|\n## |\Z)",
    re.S,
)
STR_FIELD = re.compile(r'("{key}": )("(?:\\.|[^"\\])*")')


def parse_md() -> dict[str, dict[str, str]]:
    text = MD.read_text(encoding="utf-8")
    titles = HEAD.findall(text)
    bodies = list(BLOCK.finditer(text))
    if len(titles) != 48 or len(bodies) != 48:
        raise SystemExit(f"parsed titles={len(titles)} bodies={len(bodies)}, expected 48")
    out = {}
    for title, m in zip(titles, bodies):
        out[title.strip()] = {
            "fullDescriptionZh": m.group("synopsis").strip(),
            "recommendationZh": m.group("reason").strip(),
            "audienceZh": m.group("audience").strip(),
            "biographyZh": m.group("bio").strip(),
        }
    return out


def replace_field(chunk: str, key: str, value: str) -> str:
    pat = re.compile(rf'("{key}": )("(?:\\.|[^"\\])*")')
    new = json.dumps(value, ensure_ascii=False)
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        return m.group(1) + new

    updated, count = pat.subn(sub, chunk, count=1)
    if count != 1:
        raise SystemExit(f"could not replace {key} in chunk starting {chunk[:80]!r}")
    return updated


def main() -> None:
    copies = parse_md()
    src = FEAT.read_text(encoding="utf-8")
    parts = re.split(r'(?=        "matchTitle": )', src)
    used = set()
    out = [parts[0]]
    for part in parts[1:]:
        m = re.search(r'"matchTitle": "((?:\\.|[^"\\])*)"', part)
        if not m:
            out.append(part)
            continue
        title = m.group(1)
        if title not in copies:
            raise SystemExit(f"no polished copy for {title!r}")
        copy = copies[title]
        used.add(title)
        part = replace_field(part, "fullDescriptionZh", copy["fullDescriptionZh"])
        part = replace_field(part, "recommendationZh", copy["recommendationZh"])
        part = replace_field(part, "audienceZh", copy["audienceZh"])
        part = replace_field(part, "biographyZh", copy["biographyZh"])
        out.append(part)
    missing = set(copies) - used
    if missing:
        raise SystemExit(f"unused copy for {sorted(missing)}")
    FEAT.write_text("".join(out), encoding="utf-8")
    print(f"updated {len(used)} books in {FEAT}")


if __name__ == "__main__":
    main()
