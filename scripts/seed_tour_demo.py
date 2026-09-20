#!/usr/bin/env python3
"""Seed demo tour collections (shared, public) with points + literary footnotes.

  python3 scripts/seed_tour_demo.py
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.auth import hash_password  # noqa: E402
from folio.models import SessionLocal, TourMap, TourStop, TourStopCategory, TourPlace, User  # noqa: E402
from folio.tours import (  # noqa: E402
    SCOPE_DEFAULT_VIEW, WORLD_CATEGORIES, _auto_category_id, _get_or_create_place, _unique_slug,
)

# (name, lat, lon, level, country, admin1, footnote)
SANMAO = [
    ("台北", 25.03, 121.56, "city", "China", "台湾", "三毛出生、成长与写作的起点，也是她一次次远行后回望的地方。"),
    ("马德里", 40.42, -3.70, "city", "Spain", "Madrid", "青年三毛在此求学，欧洲流浪的落脚点；《雨季不再来》里的青春与迷惘。"),
    ("拉帕尔马岛", 28.68, -17.85, "region", "Spain", "Canary Islands", "荷西在此潜水、遇难；《梦里花落知多少》写下最深的告别。"),
    ("加纳利群岛", 28.10, -15.40, "region", "Spain", "Canary Islands", "三毛与荷西在西属加那利群岛的家，《撒哈拉的故事》之后的岁月。"),
    ("阿尤恩（撒哈拉）", 27.15, -13.20, "city", "Morocco", "Laayoune", "《撒哈拉的故事》的发生地：沙漠、邻居与异乡人的日常。"),
    ("墨西哥城", 19.43, -99.13, "city", "Mexico", "Ciudad de México", "《万水千山走遍》中南美的第一站，玛雅与殖民记忆交织。"),
    ("马丘比丘", -13.16, -72.55, "city", "Peru", "Cusco", "“我们还在古斯各，等待着去马丘比丘的火车。”——《万水千山走遍》。"),
    ("的的喀喀湖", -15.84, -69.33, "region", "Peru", "Puno", "秘鲁高原上的湖泊，三毛笔下的印第安与辽阔。"),
    ("布宜诺斯艾利斯", -34.60, -58.38, "city", "Argentina", "Buenos Aires", "南美大陆的南端，探戈与乡愁。"),
    ("加德满都", 27.72, 85.32, "city", "Nepal", "Bagmati", "“我亲爱的尼泊尔啊”——三毛写给尼泊尔的一封情书。"),
    ("敦煌", 40.14, 94.66, "city", "China", "甘肃", "《敦煌记》里，她把大漠与壁画写进汉语的想象。"),
    ("重庆", 29.56, 106.55, "city", "China", "重庆", "《雨季不再来》中的战时陪都记忆与少年岁月。"),
]

GERMANY = [
    ("法兰克福", 50.11, 8.68, "city", "Germany", "Hesse", "歌德出生地，德国文学与“世界文学”概念的源头。"),
    ("魏玛", 50.98, 11.33, "city", "Germany", "Thuringia", "歌德与席勒的古典魏玛，德语文学的圣地。"),
    ("耶拿", 50.93, 11.59, "city", "Germany", "Thuringia", "黑格尔在此完成《精神现象学》，浪漫派与观念论的现场。"),
    ("图宾根", 48.52, 9.06, "city", "Germany", "Baden-Württemberg", "荷尔德林与黑格尔的图宾根神学院；《在轮下》的黑森林边缘。"),
    ("海德堡", 49.40, 8.67, "city", "Germany", "Baden-Württemberg", "德国浪漫主义的核心，荷尔德林与艾兴多夫的大学城。"),
    ("柏林", 52.52, 13.40, "city", "Germany", "Berlin", "本雅明、布莱希特与现代都市经验的现场；《单行道》。"),
    ("慕尼黑", 48.14, 11.58, "city", "Germany", "Bavaria", "托马斯·曼与《威尼斯之死》的起点；《布登勃洛克一家》的吕贝克近旁。"),
    ("弗莱堡", 47.99, 7.85, "city", "Germany", "Baden-Württemberg", "海德格尔讲学之地，《存在与时间》的语境。"),
    ("柯尼斯堡", 54.71, 20.51, "city", "Russia", "Kaliningrad", "康德一生未远行的城市，纯粹理性批判的故乡。"),
    ("特里尔", 49.75, 6.64, "city", "Germany", "Rhineland-Palatinate", "马克思出生地，《资本论》与政治经济学的起点。"),
    ("莱比锡", 51.34, 12.37, "city", "Germany", "Saxony", "歌德求学、巴赫与出版业的城市；《浮士德》的奥尔巴赫地窖。"),
    ("维也纳", 48.21, 16.37, "city", "Austria", "Wien", "弗洛伊德与维特根斯坦，德语世界的现代思想心脏。"),
    ("布拉格", 50.08, 14.44, "city", "Czechia", "Praha", "卡夫卡的布拉格，《城堡》《变形记》的官僚与荒诞。"),
    ("苏黎世", 47.38, 8.54, "city", "Switzerland", "Zürich", "荣格与《荒原狼》的黑塞在此交会，达达主义诞生地。"),
]

NORDIC = [
    ("奥斯陆", 59.91, 10.75, "city", "Norway", "Oslo", "易卜生《玩偶之家》《培尔·金特》的现代剧场。"),
    ("卑尔根", 60.39, 5.32, "city", "Norway", "Vestland", "易卜生早年的剧院岁月，峡湾与《人民公敌》。"),
    ("斯德哥尔摩", 59.33, 18.06, "city", "Sweden", "Stockholm", "斯特林堡《红房间》的都市与北欧现代性。"),
    ("乌普萨拉", 59.86, 17.64, "city", "Sweden", "Uppsala", "拉格洛夫《尼尔斯骑鹅旅行记》的瑞典天空。"),
    ("哥本哈根", 55.68, 12.57, "city", "Denmark", "Hovedstaden", "安徒生与克尔凯郭尔的城市，童话与存在主义并存。"),
    ("奥登塞", 55.40, 10.39, "city", "Denmark", "Syddanmark", "安徒生出生地，小美人鱼与丑小鸭的原点。"),
    ("赫尔辛基", 60.17, 24.94, "city", "Finland", "Uusimaa", "芬兰文学与《夏夜的人们》；西贝柳斯的北国。"),
    ("图尔库", 60.45, 22.27, "city", "Finland", "Varsinais-Suomi", "芬兰旧都，扬松笔下的姆明谷想象。"),
    ("雷克雅未克", 64.15, -21.94, "city", "Iceland", "Capital Region", "冰岛萨迦与《独立的人们》，火山与冰川之间的叙事。"),
    ("特罗姆瑟", 69.65, 18.96, "city", "Norway", "Troms", "北极圈内的城市，极夜与北欧犯罪小说。"),
]

SCOTLAND = [
    ("刘易斯岛", 58.20, -6.40, "region", "United Kingdom", "Scotland", "凯文·麦克尼尔《通往斯托诺韦之路》——盖尔语与岛民记忆。"),
    ("斯凯岛", 57.40, -6.20, "region", "United Kingdom", "Scotland", "弗吉尼亚·伍尔夫《到灯塔去》的灯塔远眺，内赫布里底群岛。"),
    ("西部高地", 57.00, -5.00, "region", "United Kingdom", "Scotland", "伊恩·班克斯《乌鸦之路》——荒凉高地与家族史。"),
    ("爱丁堡", 55.95, -3.19, "city", "United Kingdom", "Scotland", "欧文·威尔士《猜火车》与司各特、史蒂文森的旧城。"),
    ("格拉斯哥", 55.86, -4.25, "city", "United Kingdom", "Scotland", "詹姆斯·凯尔曼《多晚了，多晚》——工人阶级的城市。"),
    ("埃特里克", 55.40, -3.00, "region", "United Kingdom", "Scotland", "史蒂文森《绑架》的苏格兰边区与高地荒原。"),
    ("阿伯丁", 57.15, -2.09, "city", "United Kingdom", "Scotland", "花岗岩之城，麦克迪尔米德的苏格兰文艺复兴。"),
    ("因弗内斯", 57.48, -4.22, "city", "United Kingdom", "Scotland", "高地的门户，《麦克白》式的荒野与雾。"),
]

TAIWAN = [
    ("台北", 25.03, 121.56, "city", "China", "台湾", "白先勇《台北人》、林海音《城南旧事》——迁台者的都市与旧梦。"),
    ("新北", 25.01, 121.46, "city", "China", "台湾", "《艋舺》《枯木》等，淡水河畔的市井与青春。"),
    ("桃园", 24.99, 121.30, "city", "China", "台湾", "眷村与《儿子的大玩偶》式的底层日常。"),
    ("新竹", 24.80, 120.97, "city", "China", "台湾", "吴浊流《亚细亚的孤儿》的殖民记忆与客庄。"),
    ("台中", 24.15, 120.68, "city", "China", "台湾", "《桂花巷》里的中部市镇与女性命运。"),
    ("彰化", 24.08, 120.54, "city", "China", "台湾", "赖和的乡土书写，台湾新文学的先声。"),
    ("云林", 23.71, 120.43, "city", "China", "台湾", "宋泽莱《打牛湳村》——农村与现代化的撕裂。"),
    ("台南", 22.99, 120.21, "city", "China", "台湾", "叶石涛的府城记忆，最早的汉人聚落与文学传统。"),
    ("高雄", 22.63, 120.30, "city", "China", "台湾", "《盐埕区长》与港都的工人阶级书写。"),
    ("屏东", 22.67, 120.49, "city", "China", "台湾", "《傀儡花》里的原汉冲突与恒春半岛。"),
    ("台东", 22.76, 121.14, "city", "China", "台湾", "《最后的猎人》与山海之间的原住民叙事。"),
    ("花莲", 23.98, 121.60, "city", "China", "台湾", "杨牧《奇来前书》——东海岸的抒情与离散。"),
    ("宜兰", 24.75, 121.75, "city", "China", "台湾", "黄春明《看海的日子》——兰阳平原的小人物。"),
    ("澎湖", 23.57, 119.58, "city", "China", "台湾", "《外婆的澎湖湾》与岛屿的离乡记忆。"),
]

NAMED = [
    ("三毛文学巡礼", SANMAO),
    ("德国文学哲学巡礼", GERMANY),
    ("北欧文学巡礼", NORDIC),
    ("苏格兰文学地图", SCOTLAND),
    ("台湾文学圣地巡礼", TAIWAN),
]

# region id -> (collection title, scope, [(city, lat, lon, country, admin1)])
REGION_TOURS = {
    "dongbei": ("东北文学巡礼", "china", [("哈尔滨", 45.80, 126.53, "China", "黑龙江省"), ("沈阳", 41.80, 123.43, "China", "辽宁省"), ("呼兰", 45.98, 126.60, "China", "黑龙江省")]),
    "xibei": ("西北文学巡礼", "china", [("西安", 34.34, 108.94, "China", "陕西省"), ("延安", 36.59, 109.49, "China", "陕西省"), ("兰州", 36.06, 103.83, "China", "甘肃省")]),
    "zangdi": ("藏地文学巡礼", "china", [("拉萨", 29.65, 91.14, "China", "西藏自治区"), ("日喀则", 29.27, 88.88, "China", "西藏自治区"), ("马尔康", 31.90, 102.21, "China", "四川省")]),
    "xinan": ("西南文学巡礼", "china", [("成都", 30.57, 104.07, "China", "四川省"), ("重庆", 29.56, 106.55, "China", "重庆"), ("昆明", 25.04, 102.71, "China", "云南省")]),
    "zhongyuan": ("中原文学巡礼", "china", [("郑州", 34.75, 113.63, "China", "河南省"), ("洛阳", 34.62, 112.45, "China", "河南省"), ("开封", 34.80, 114.31, "China", "河南省")]),
    "huabei": ("华北京津文学巡礼", "china", [("北京", 39.90, 116.40, "China", "北京市"), ("天津", 39.13, 117.20, "China", "天津市"), ("保定", 38.87, 115.46, "China", "河北省")]),
    "jiangnan": ("江南文学巡礼", "china", [("上海", 31.23, 121.47, "China", "上海市"), ("苏州", 31.30, 120.58, "China", "江苏省"), ("杭州", 30.27, 120.15, "China", "浙江省"), ("南京", 32.06, 118.80, "China", "江苏省")]),
    "dongnan": ("东南文学巡礼", "china", [("福州", 26.07, 119.30, "China", "福建省"), ("厦门", 24.48, 118.09, "China", "福建省"), ("泉州", 24.87, 118.68, "China", "福建省")]),
    "lingnan": ("岭南文学巡礼", "china", [("广州", 23.13, 113.26, "China", "广东省"), ("桂林", 25.27, 110.29, "China", "广西壮族自治区"), ("海口", 20.04, 110.32, "China", "海南省")]),
    "caoyuan": ("草原文学巡礼", "china", [("呼和浩特", 40.84, 111.75, "China", "内蒙古自治区"), ("锡林浩特", 43.93, 116.09, "China", "内蒙古自治区"), ("呼伦贝尔", 49.21, 119.77, "China", "内蒙古自治区")]),
    "hongkong": ("香港文学巡礼", "china", [("香港", 22.32, 114.17, "China", "香港特别行政区")]),
    "macau": ("澳门文学巡礼", "china", [("澳门", 22.20, 113.54, "China", "澳门特别行政区")]),
    "taiwan": ("台湾文学巡礼", "china", [("台北", 25.03, 121.56, "China", "台湾省"), ("台南", 22.99, 120.21, "China", "台湾省"), ("高雄", 22.63, 120.30, "China", "台湾省")]),
    "northamerica": ("北美华语文学巡礼", "world", [("旧金山", 37.77, -122.42, "United States of America", "California"), ("纽约", 40.71, -74.01, "United States of America", "New York"), ("温哥华", 49.28, -123.12, "Canada", "British Columbia")]),
    "europe": ("欧洲华语文学巡礼", "world", [("巴黎", 48.86, 2.35, "France", "Île-de-France"), ("伦敦", 51.51, -0.13, "United Kingdom", "England"), ("柏林", 52.52, 13.40, "Germany", "Berlin")]),
    "japankorea": ("日韩华语文学巡礼", "world", [("东京", 35.68, 139.69, "Japan", "Tokyo"), ("大阪", 34.69, 135.50, "Japan", "Osaka"), ("首尔", 37.57, 126.98, "South Korea", "Seoul")]),
    "seasia": ("东南亚华语文学巡礼", "world", [("曼谷", 13.76, 100.50, "Thailand", "Bangkok"), ("雅加达", -6.21, 106.85, "Indonesia", "Jakarta"), ("马尼拉", 14.60, 120.98, "Philippines", "Metro Manila")]),
    "mahua": ("马华文学巡礼", "world", [("吉隆坡", 3.14, 101.69, "Malaysia", "Kuala Lumpur"), ("槟城", 5.41, 100.34, "Malaysia", "Penang"), ("怡保", 4.60, 101.07, "Malaysia", "Perak")]),
    "singapore": ("新加坡华文文学巡礼", "world", [("新加坡", 1.35, 103.82, "Singapore", "Singapore")]),
    "oceania": ("大洋洲华语文学巡礼", "world", [("悉尼", -33.87, 151.21, "Australia", "New South Wales"), ("墨尔本", -37.81, 144.96, "Australia", "Victoria"), ("奥克兰", -36.85, 174.76, "New Zealand", "Auckland")]),
}


def ensure_user(db) -> User:
    user = db.query(User).filter(User.username == "folio_seed").one_or_none()
    if user:
        return user
    user = User(
        username="folio_seed", email="seed@folio.local",
        password_hash=hash_password(secrets.token_urlsafe(24)),
        nickname="FOLIO 编辑部", role="user", status="active",
    )
    db.add(user)
    db.flush()
    return user


def get_or_create_collection(db, user, title, scope):
    row = db.query(TourMap).filter(TourMap.title == title, TourMap.kind == "custom").first()
    if row:
        return row
    lat, lon, zoom = SCOPE_DEFAULT_VIEW.get(scope, SCOPE_DEFAULT_VIEW["world"])
    row = TourMap(
        owner_user_id=user.id, slug=_unique_slug(db, title), title=title,
        scope=scope, kind="custom", visibility="public", status="published",
        center_lat=lat, center_lon=lon, zoom=zoom, published_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    defaults = WORLD_CATEGORIES
    for i, (label, color) in enumerate(defaults):
        db.add(TourStopCategory(map_id=row.id, label=label, color=color, kind="auto", order_index=i))
    return row


def add_point(db, user, collection, name, lat, lon, level, country, admin1, footnote):
    place = _get_or_create_place(db, user.id, name, "", level, lat, lon, country, admin1)
    if footnote and not place.footnote:
        place.footnote = footnote
    exists = db.query(TourStop).filter(TourStop.map_id == collection.id, TourStop.place_id == place.id).first()
    if exists:
        return False
    order = db.query(TourStop).filter(TourStop.map_id == collection.id).count() + 1
    db.add(TourStop(
        map_id=collection.id, user_id=user.id, place_id=place.id,
        category_id=_auto_category_id(db, collection, country, admin1),
        lat=lat, lon=lon, level=level, place_name=name, country=country, admin1=admin1,
        order_index=order,
    ))
    collection.stop_count = order
    return True


def main() -> int:
    db = SessionLocal()
    try:
        user = ensure_user(db)
        total = 0
        for title, points in NAMED:
            col = get_or_create_collection(db, user, title, "world")
            n = sum(add_point(db, user, col, *p) for p in points)
            total += n
            print(f"  {title}: +{n} (共 {col.stop_count})")
        # region collections, footnote from representative works
        data_path = ROOT / "folio" / "data" / "literary_region_books.json"
        book_data = json.loads(data_path.read_text(encoding="utf-8")).get("regions", {}) if data_path.exists() else {}
        for rid, (title, scope, cities) in REGION_TOURS.items():
            col = get_or_create_collection(db, user, title, scope)
            info = book_data.get(rid) or {}
            works = info.get("representative_works") or []
            note = "代表作品：" + "、".join(f"《{w['title']}》({w['author']})" for w in works[:3]) if works else ""
            n = 0
            for (city, lat, lon, country, admin1) in cities:
                n += add_point(db, user, col, city, lat, lon, "city", country, admin1, note)
            total += n
            print(f"  {title}: +{n}")
        db.commit()
        print(f"seeded {total} new stops across {len(NAMED) + len(REGION_TOURS)} collections")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
