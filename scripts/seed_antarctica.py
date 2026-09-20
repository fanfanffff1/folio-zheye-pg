#!/usr/bin/env python3
"""Seed Antarctica places with literary footnotes so the polar region has content.

OSM tiles over Antarctica are mostly blank ice; these curated places give the
map something to show (research stations, the South Pole, expedition huts) and
tie them to the literature of polar exploration.

Usage:
    python3 scripts/seed_antarctica.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.models import SessionLocal, TourPlace, User  # noqa: E402

DATA = ROOT / "static" / "data" / "tour-map" / "world" / "antarctica-places.json"

NOTES = {
    "南极点": "1911–1912 年，阿蒙森与斯科特展开南极点竞赛。斯科特一行 1912 年 1 月 17 日抵达，"
            "却发现阿蒙森的挪威国旗已先期插上；归途中五人全部遇难。茨威格在《人类群星闪耀时》的"
            "《争夺南极点》里，写下这场以失败告终、却照亮人类探险精神的远征。",
    "阿蒙森-斯科特站": "建在南极点上的常年科考站，以两位极地先驱阿蒙森与斯科特命名。",
    "斯科特小屋": "斯科特 1910–1913 年『特拉诺瓦号』探险队的基地小屋（埃文斯角），"
              "至今仍留存着当年的补给与笔记。",
    "沙克尔顿小屋": "沙克尔顿 1907–1909 年『尼姆罗德号』探险队基地（罗伊兹角）。"
                "他此行抵达距南极点约 180 公里处后折返，留下《南极之心》。",
    "鲸湾": "阿蒙森 1911 年在此建立『前进号营地』(Framheim)，由此出发，"
          "于 1911 年 12 月 14 日成为第一个抵达南极点的人。",
    "麦克默多站": "美国南极科考站、南极最大的聚居地；罗斯岛一带是南极探险史的核心区域。",
    "斯科特基地": "新西兰南极科考站，紧邻麦克默多站，1957 年为纪念斯科特而建。",
    "罗斯冰架": "世界最大的冰架，斯科特与阿蒙森的远征都以此为起点。",
    "沃斯托克站": "俄罗斯科考站，曾记录到地球最低气温约 −89.2°C。",
    "康宏站": "法/意联合科考站，位于南极高原『冰穹 C』，以极端低温与孤立著称。",
    "南极半岛": "最早被人类接近的南极区域，如今是科考与探险的门户。",
    "南磁极": "地磁南极，随年代漂移；早期探险家曾为抵达它付出巨大代价。",
}


def place_key(level: str, lat: float, lon: float) -> str:
    return f"{level}|{round(float(lat), 2)}|{round(float(lon), 2)}"


def main() -> None:
    sites = json.loads(DATA.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        owner = (
            db.query(User).filter(User.role == "admin").order_by(User.id.asc()).first()
            or db.query(User).order_by(User.id.asc()).first()
        )
        created = updated = 0
        for s in sites:
            name = s.get("nameZh") or s.get("name") or ""
            lat, lon = float(s["lat"]), float(s["lon"])
            key = place_key("city", lat, lon)
            place = db.query(TourPlace).filter(TourPlace.key == key).one_or_none()
            note = NOTES.get(name, "")
            if place:
                if note and not place.footnote:
                    place.footnote = note
                    updated += 1
                continue
            db.add(TourPlace(
                key=key, name=name, name_en=(s.get("nameEn") or "")[:160], level="city",
                lat=lat, lon=lon, country="南极洲", admin1="", footnote=note,
                created_by=owner.id if owner else None,
            ))
            created += 1
        db.commit()
        print(f"antarctica places: created {created}, updated {updated} (owner={owner.id if owner else None})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
