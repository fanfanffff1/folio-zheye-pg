#!/usr/bin/env python3
"""Seed the named literary tours from the reference maps the user provided.

Sources: user-supplied images (苏格兰文学地图 / 北欧书单 / 台湾省文学圣地巡礼地图 /
德国文学哲学圣地巡礼地图 / 三毛文学地图截图). Works + authors are taken from those
images; nothing is invented here.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.auth import hash_password  # noqa: E402
from folio.models import SessionLocal, TourMap, TourStop, TourStopCategory, User  # noqa: E402
from folio.tours import (  # noqa: E402
    SCOPE_DEFAULT_VIEW, WORLD_CATEGORIES, _auto_category_id, _get_or_create_place, _unique_slug,
)

SRC = "（据用户提供的巡礼图）"

# (place, lat, lon, level, country, admin1, work/author footnote)
SCOTLAND = [
    ("刘易斯岛", 58.20, -6.40, "region", "United Kingdom", "Scotland", "凯文·麦克尼尔《通往斯托诺韦之路》(The Stornoway Way)" + SRC),
    ("斯凯岛", 57.40, -6.20, "region", "United Kingdom", "Scotland", "弗吉尼亚·伍尔夫《到灯塔去》(To the Lighthouse)" + SRC),
    ("西部高地", 57.00, -5.00, "region", "United Kingdom", "Scotland", "伊恩·班克斯《乌鸦之路》(The Crow Road)" + SRC),
    ("爱丁堡", 55.95, -3.19, "city", "United Kingdom", "Scotland", "欧文·威尔士《猜火车》(Trainspotting)" + SRC),
    ("格拉斯哥", 55.86, -4.25, "city", "United Kingdom", "Scotland", "詹姆斯·凯尔曼《多晚了，多晚》(How Late It Was, How Late)" + SRC),
    ("埃特里克", 55.40, -3.00, "region", "United Kingdom", "Scotland", "罗伯特·路易斯·史蒂文森《绑架》(Kidnapped)" + SRC),
]

NORDIC = [
    ("奥斯陆", 59.91, 10.75, "city", "Norway", "Oslo", "易卜生《玩偶之家》；约恩·福瑟《有人在此》；达格·索尔斯塔《安德森教授的夜晚》；克瑙斯高《我的奋斗》" + SRC),
    ("卑尔根", 60.39, 5.32, "city", "Norway", "Vestland", "托尔·海尔达尔《孤筏重洋》(Kon-Tiki)" + SRC),
    ("斯德哥尔摩", 59.33, 18.06, "city", "Sweden", "Stockholm", "托马斯·特朗斯特罗姆《沉石与火舌》；弗雷德里克·巴克曼《一个叫欧维的男人决定去死》" + SRC),
    ("哥德堡", 57.71, 11.97, "city", "Sweden", "Västra Götaland", "阿斯特丽德·林格伦《长袜子皮皮》" + SRC),
    ("赫尔辛基", 60.17, 24.94, "city", "Finland", "Uusimaa", "西伦佩《夏夜的人们》《神圣的贫困》；阿托·帕西林纳《遇见野兔的那一年》" + SRC),
    ("哥本哈根", 55.68, 12.57, "city", "Denmark", "Hovedstaden", "安徒生《安徒生童话》；克尔凯郭尔《恐惧与颤栗》《非此即彼》" + SRC),
    ("奥登塞", 55.40, 10.39, "city", "Denmark", "Syddanmark", "安徒生出生地《安徒生童话》" + SRC),
    ("雷克雅未克", 64.15, -21.94, "city", "Iceland", "Capital Region", "《萨迦》；约恩·卡尔曼·斯特凡松《鱼没有脚》；奥杜·阿娃·奥拉夫斯多蒂《种玫瑰的男人》" + SRC),
]

TAIWAN = [
    ("台北", 25.03, 121.56, "city", "China", "台湾", "白先勇《孽子》《台北人》；林海音《城南旧事》" + SRC),
    ("新竹", 24.80, 120.97, "city", "China", "台湾", "吴浊流《亚细亚的孤儿》" + SRC),
    ("宜兰", 24.75, 121.75, "city", "China", "台湾", "黄春明《儿子的大玩偶》《看海的日子》" + SRC),
    ("花莲", 23.98, 121.60, "city", "China", "台湾", "杨牧《奇来前书》《水之湄》" + SRC),
    ("台东", 22.76, 121.14, "city", "China", "台湾", "《最后的猎人》《兰屿行医记》" + SRC),
    ("云林", 23.71, 120.43, "city", "China", "台湾", "宋泽莱《打牛湳村》" + SRC),
    ("彰化", 24.08, 120.54, "city", "China", "台湾", "赖和（台湾新文学之父）" + SRC),
    ("台南", 22.99, 120.21, "city", "China", "台湾", "叶石涛（府城书写）" + SRC),
    ("屏东", 22.67, 120.49, "city", "China", "台湾", "《傀儡花》" + SRC),
    ("澎湖", 23.57, 119.58, "city", "China", "台湾", "《外婆的澎湖湾》" + SRC),
]

GERMANY = [
    ("法兰克福", 50.11, 8.68, "city", "Germany", "Hesse", "歌德《少年维特之烦恼》《浮士德》" + SRC),
    ("魏玛", 50.98, 11.33, "city", "Germany", "Thuringia", "歌德与席勒；席勒《华伦斯坦》《威廉·退尔》" + SRC),
    ("耶拿", 50.93, 11.59, "city", "Germany", "Thuringia", "黑格尔《精神现象学》" + SRC),
    ("海德堡", 49.40, 8.67, "city", "Germany", "Baden-Württemberg", "荷尔德林《颂歌集》；德国浪漫主义" + SRC),
    ("柏林", 52.52, 13.40, "city", "Germany", "Berlin", "本雅明《单行道》；布莱希特" + SRC),
    ("慕尼黑", 48.14, 11.58, "city", "Germany", "Bavaria", "托马斯·曼《布登勃洛克一家》" + SRC),
    ("弗莱堡", 47.99, 7.85, "city", "Germany", "Baden-Württemberg", "海德格尔《存在与时间》" + SRC),
    ("柯尼斯堡", 54.71, 20.51, "city", "Russia", "Kaliningrad", "康德（纯粹理性批判）" + SRC),
    ("特里尔", 49.75, 6.64, "city", "Germany", "Rhineland-Palatinate", "马克思《资本论》" + SRC),
    ("莱比锡", 51.34, 12.37, "city", "Germany", "Saxony", "歌德《浮士德》；莱布尼茨《单子论》" + SRC),
    ("维也纳", 48.21, 16.37, "city", "Austria", "Wien", "弗洛伊德；维特根斯坦" + SRC),
    ("布拉格", 50.08, 14.44, "city", "Czechia", "Praha", "卡夫卡《城堡》《变形记》" + SRC),
    ("苏黎世", 47.38, 8.54, "city", "Switzerland", "Zürich", "黑塞《荒原狼》；荣格" + SRC),
]

SANMAO = [
    ("台北", 25.03, 121.56, "city", "China", "台湾", "三毛出生与成长之地。" + SRC),
    ("马德里", 40.42, -3.70, "city", "Spain", "Madrid", "青年三毛留学西班牙，《雨季不再来》。" + SRC),
    ("阿尤恩（撒哈拉）", 27.15, -13.20, "city", "Morocco", "Laayoune", "《撒哈拉的故事》故事发生地。" + SRC),
    ("加纳利群岛", 28.10, -15.40, "region", "Spain", "Canary Islands", "三毛与荷西在西属加那利群岛的家。" + SRC),
    ("拉帕尔马岛", 28.68, -17.85, "region", "Spain", "Canary Islands", "荷西长眠之地，《梦里花落知多少》。" + SRC),
    ("墨西哥城", 19.43, -99.13, "city", "Mexico", "Ciudad de México", "《万水千山走遍》中南美之行。" + SRC),
    ("马丘比丘", -13.16, -72.55, "city", "Peru", "Cusco", "《万水千山走遍》：“我们还在古斯各，等待着去马丘比丘的火车。”" + SRC),
    ("加德满都", 27.72, 85.32, "city", "Nepal", "Bagmati", "三毛 1989 年尼泊尔之行（地图截图）。" + SRC),
]

NAMED = [
    ("苏格兰文学地图", SCOTLAND),
    ("北欧文学巡礼", NORDIC),
    ("台湾文学圣地巡礼", TAIWAN),
    ("德国文学哲学巡礼", GERMANY),
    ("三毛文学巡礼", SANMAO),
]


def ensure_user(db) -> User:
    user = db.query(User).filter(User.username == "folio_seed").one_or_none()
    if user:
        return user
    user = User(username="folio_seed", email="seed@folio.local",
                password_hash=hash_password(secrets.token_urlsafe(24)),
                nickname="FOLIO 编辑部", role="user", status="active")
    db.add(user)
    db.flush()
    return user


def get_or_create_collection(db, user, title, scope="world"):
    row = db.query(TourMap).filter(TourMap.title == title, TourMap.kind == "custom").first()
    if row:
        return row
    lat, lon, zoom = SCOPE_DEFAULT_VIEW.get(scope, SCOPE_DEFAULT_VIEW["world"])
    row = TourMap(owner_user_id=user.id, slug=_unique_slug(db, title), title=title,
                  scope=scope, kind="custom", visibility="public", status="published",
                  center_lat=lat, center_lon=lon, zoom=zoom, published_at=datetime.utcnow())
    db.add(row)
    db.flush()
    for i, (label, color) in enumerate(WORLD_CATEGORIES):
        db.add(TourStopCategory(map_id=row.id, label=label, color=color, kind="auto", order_index=i))
    return row


def add_point(db, user, collection, name, lat, lon, level, country, admin1, footnote):
    place = _get_or_create_place(db, user.id, name, "", level, lat, lon, country, admin1)
    if footnote:
        place.footnote = footnote
    if db.query(TourStop).filter(TourStop.map_id == collection.id, TourStop.place_id == place.id).first():
        return 0
    order = db.query(TourStop).filter(TourStop.map_id == collection.id).count() + 1
    db.add(TourStop(map_id=collection.id, user_id=user.id, place_id=place.id,
                    category_id=_auto_category_id(db, collection, country, admin1),
                    lat=lat, lon=lon, level=level, place_name=name, country=country,
                    admin1=admin1, order_index=order))
    collection.stop_count = order
    return 1


def main() -> int:
    db = SessionLocal()
    try:
        user = ensure_user(db)
        total = 0
        for title, points in NAMED:
            col = get_or_create_collection(db, user, title)
            n = sum(add_point(db, user, col, *p) for p in points)
            total += n
            print(f"  {title}: +{n} (共 {col.stop_count})")
        db.commit()
        print(f"seeded {total} stops")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
