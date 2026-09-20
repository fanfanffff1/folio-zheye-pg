"""Data-driven copy for Chinese literary map regions (preview + detail)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .region_groups import FILTER_PILLS, OVERSEAS_ISLANDS, REGION_GROUPS

MapType = str  # "chinese"

# Table-driven region copy generated from 中国地域与世界华文文学百年书单.xlsx
# via scripts/build_literary_region_data.py
_BOOK_DATA_PATH = Path(__file__).resolve().parent / "literary_region_books.json"


def _load_book_data() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_BOOK_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload.get("regions") or {}


BOOK_DATA: dict[str, dict[str, Any]] = _load_book_data()

_ERA_RULES: list[tuple[int, int, str]] = [
    (1900, 1949, "现代·流亡与启蒙"),
    (1950, 1979, "新中国叙事"),
    (1980, 1999, "新时期转向"),
    (2000, 2100, "当代新声音"),
]


def _start_year(years: str) -> int:
    match = re.search(r"(18|19|20)\d{2}", years or "")
    return int(match.group(0)) if match else 0


def _era_label(years: str) -> str:
    start = _start_year(years)
    for lo, hi, label in _ERA_RULES:
        if lo <= start <= hi:
            return label
    return "发展脉络"


def _style_keywords(style: str, limit: int = 5) -> list[str]:
    parts = [p.strip("。；;，, ") for p in re.split(r"[、，,；;]", style or "") if p.strip("。；;，, ")]
    return parts[:limit]


def _writer_blurb(author: dict[str, Any], period: str) -> str:
    works = author.get("works") or []
    label = "历史/先驱作者" if period == "historical" else "当代作者"
    if works:
        quoted = "》《".join(works[:2])
        return f"{label}，代表作《{quoted}》。"
    return f"{label}。"


def _ordered_authors(authors: dict[str, list[dict]], limit: int = 0) -> list[tuple[dict, str]]:
    rows: list[tuple[dict, str]] = []
    for period in ("historical", "contemporary"):
        for author in authors.get(period, []):
            rows.append((author, period))
    return rows[:limit] if limit else rows


def _phase_authors(authors: dict[str, list[dict]], index: int, total: int) -> list[str]:
    period = "historical" if index < max(1, (total + 1) // 2) else "contemporary"
    pool = authors.get(period, [])
    if not pool:
        pool = authors.get("contemporary" if period == "historical" else "historical", [])
    return [a["name"] for a in pool[:4]]


def _merge_book_data(regions: dict[str, dict[str, Any]]) -> None:
    for rid, region in regions.items():
        data = BOOK_DATA.get(rid)
        if not data:
            continue
        authors = data.get("authors") or {"historical": [], "contemporary": []}
        representative = data.get("representative_authors") or [
            a["name"] for a, _ in _ordered_authors(authors, 4)
        ]
        works = data.get("representative_works") or [
            {"title": w, "author": a["name"]}
            for a, _ in _ordered_authors(authors)
            for w in (a.get("works") or [])[:1]
        ][:6]
        phases = data.get("phases") or []

        region["style"] = data.get("style") or region.get("subtitle", "")
        region["scope"] = data.get("scope") or ""
        region["context"] = data.get("context") or ""
        if region["scope"]:
            region["brief"] = f"{region['style']}{region['scope']}"
        else:
            region["brief"] = region["style"]
        region["image"] = data.get("image") or f"/static/img/literary-map/region-{rid}.jpg"
        region["authors"] = authors
        region["representative_authors"] = representative
        region["representative_works"] = works

        by_name = {a["name"]: (a, period) for a, period in _ordered_authors(authors)}
        region["writers"] = [
            {"name": name, "blurb": _writer_blurb(*by_name[name])}
            for name in representative
            if name in by_name
        ]
        region["starter_books"] = [
            {"title": w["title"], "author": w.get("author", ""), "note": ""}
            for w in works
        ]
        region["timeline"] = [
            {
                "id": p.get("id") or f"p{i + 1}",
                "era": _era_label(p.get("years", "")),
                "years": p.get("years", ""),
                "summary": p.get("text", ""),
                "authors": _phase_authors(authors, i, len(phases)),
            }
            for i, p in enumerate(phases)
        ]
        region["book_count"] = len(authors.get("historical", [])) + len(authors.get("contemporary", []))

        if not region.get("how_to_enter"):
            labels = ["第一本", "再读一本", "当代声音"]
            region["how_to_enter"] = [
                {
                    "label": labels[i] if i < len(labels) else "延伸阅读",
                    "title": w["title"],
                    "author": w.get("author", ""),
                    "blurb": f"{region['short_name']}文学代表作品之一。",
                }
                for i, w in enumerate(works[:3])
            ]
        if not region.get("themes"):
            region["themes"] = [
                {"id": f"t{i + 1}", "title": kw, "blurb": f"{region['short_name']}文学反复书写的主题。"}
                for i, kw in enumerate(_style_keywords(region["style"]))
            ]
        region["keywords"] = _style_keywords(region["style"])
        region["subtitle"] = region.get("subtitle") or region["style"]


def _stub(
    region_id: str,
    name: str,
    short_name: str,
    subtitle: str,
    brief: str,
    keywords: list[str],
    writers: list[dict[str, str]],
    starter_books: list[dict[str, str]],
    filter_id: str,
    *,
    timeline: list[dict[str, Any]] | None = None,
    themes: list[dict[str, str]] | None = None,
    how_to_enter: list[dict[str, str]] | None = None,
    quote: str = "",
    quote_by: str = "",
) -> dict[str, Any]:
    return {
        "id": region_id,
        "map_type": "chinese",
        "name": name,
        "short_name": short_name,
        "subtitle": subtitle,
        "brief": brief,
        "keywords": keywords,
        "writers": writers,
        "starter_books": starter_books,
        "timeline": timeline or [],
        "themes": themes or [],
        "how_to_enter": how_to_enter or [],
        "quote": quote,
        "quote_by": quote_by,
        "collection_id": f"chinese-{region_id}",
        "detail_path": f"/literary-map/chinese/{region_id}",
        "filter": filter_id,
        "book_count": 0,
    }


DONGBEI = {
    "id": "dongbei",
    "map_type": "chinese",
    "name": "东北文学",
    "short_name": "东北",
    "subtitle": "在漫长冬季、黑土地与时代变迁之间，书写人的坚韧、失落与重新生活。",
    "brief": (
        "东北文学从呼兰河的童年记忆，走到铁轨与工厂熄灯后的城市夜色。"
        "它写寒冷与边地，也写普通人如何把日子重新过成诗。"
        "故乡、工业与女性经验在这里交织成一条漫长的河。"
    ),
    "keywords": ["故乡", "工业", "边地", "女性经验", "黑土地"],
    "writers": [
        {"name": "萧红", "blurb": "以呼兰河的童年与流亡岁月，写下东北现代文学的起点。"},
        {"name": "迟子建", "blurb": "以北国的雪、河与人情，写冷地里仍温热的生命。"},
        {"name": "班宇", "blurb": "以沈阳街巷与下岗年代的语气，写当代东北的日常与幽默。"},
        {"name": "双雪涛", "blurb": "以悬疑外壳包裹工业城市的记忆与少年心事。"},
    ],
    "starter_books": [
        {"title": "呼兰河传", "author": "萧红", "note": "从一座小城的四季，看见东北现代文学的源头。"},
        {"title": "额尔古纳河右岸", "author": "迟子建", "note": "鄂温克族的迁徙与哀歌，边地生命的长卷。"},
        {"title": "冬泳", "author": "班宇", "note": "短篇里的沈阳夜色、玩笑与心酸。"},
    ],
    "how_to_enter": [
        {
            "label": "第一本",
            "title": "呼兰河传",
            "author": "萧红",
            "blurb": "从童年至流亡，东北现代文学最清晰的入口。",
        },
        {
            "label": "再读一本",
            "title": "额尔古纳河右岸",
            "author": "迟子建",
            "blurb": "把视野拉向边地与民族记忆，看见更辽阔的北方。",
        },
        {
            "label": "当代声音",
            "title": "冬泳",
            "author": "班宇",
            "blurb": "用当代口语走进后工业城市的日常与幽默。",
        },
    ],
    "timeline": [
        {
            "id": "sprout",
            "era": "现代萌芽",
            "years": "1900s–1930s",
            "summary": "乡土与启蒙交织，东北现代文学开始发出自己的声音。",
            "authors": ["萧红", "端木蕻良", "骆宾基"],
        },
        {
            "id": "war",
            "era": "战争与流亡",
            "years": "1930s–1949",
            "summary": "沦陷与流亡迫使书写者带着故乡上路，家国与个人命运缠绕。",
            "authors": ["萧军", "舒群", "罗烽"],
        },
        {
            "id": "newchina",
            "era": "新中国叙事",
            "years": "1949–1978",
            "summary": "建设、土地与集体生活进入叙事中心，东北成为时代写作的重要现场。",
            "authors": ["梁晓声", "曲波"],
        },
        {
            "id": "reform",
            "era": "新时期转向",
            "years": "1978–2000",
            "summary": "改革与工业转型改变城市肌理，文学开始回望与反思。",
            "authors": ["迟子建", "阿成"],
        },
        {
            "id": "now",
            "era": "当代新声音",
            "years": "2000–今",
            "summary": "“东北文艺复兴”等讨论里，短篇、口语与城市记忆重新聚光。",
            "authors": ["班宇", "双雪涛", "郑执"],
        },
    ],
    "themes": [
        {"id": "land", "title": "土地与故乡", "blurb": "黑土、河流与返乡的执念。"},
        {"id": "industry", "title": "工业与城市", "blurb": "工厂、铁轨与熄灯后的街巷。"},
        {"id": "women", "title": "女性写作", "blurb": "从呼兰河到当代女性经验。"},
        {"id": "border", "title": "边地经验", "blurb": "国界、民族与北方的边缘位置。"},
        {"id": "memory", "title": "历史记忆", "blurb": "时代褶皱里的个人命运。"},
    ],
    "quote": "东北的冷，是地理的，也是人心的；但在最冷的地方，也有最热的生命。",
    "quote_by": "迟子建",
    "collection_id": "chinese-dongbei",
    "detail_path": "/literary-map/chinese/dongbei",
    "filter": "mainland",
    "book_count": 0,
}


def _build_regions() -> dict[str, dict[str, Any]]:
    regions: dict[str, dict[str, Any]] = {"dongbei": DONGBEI}

    stubs: list[tuple] = [
        (
            "caoyuan",
            "草原文学",
            "草原",
            "风、马与游牧记忆里的汉语写作。",
            "从辽阔牧场到城市边缘，草原文学写迁徙、边界与人的去留。短篇与长河小说都在这里寻找地平线。",
            ["游牧", "边地", "风土", "迁徙"],
            [{"name": "玛拉沁夫", "blurb": "草原生活的经典书写者。"}, {"name": "邓一光", "blurb": "当代草原与军旅记忆。"}, {"name": "鲍尔吉·原野", "blurb": "散文里的草原气息。"}],
            [{"title": "茫茫的草原", "author": "玛拉沁夫"}, {"title": "我是我的神", "author": "邓一光"}],
            "mainland",
        ),
        (
            "huabei",
            "华北·京津文学",
            "华北·京津",
            "京城街巷与华北平原上的世情与先锋。",
            "从京味小说到华北乡土，这里汇聚宫廷余韵、胡同烟火与当代都市的实验写作。",
            ["京味", "市井", "先锋", "乡土"],
            [{"name": "老舍", "blurb": "京味文学的坐标。"}, {"name": "林斤澜", "blurb": "短篇里的华北气质。"}, {"name": "刘震云", "blurb": "乡土与官场之间的汉语节奏。"}],
            [{"title": "骆驼祥子", "author": "老舍"}, {"title": "一句顶一万句", "author": "刘震云"}],
            "mainland",
        ),
        (
            "zhongyuan",
            "中原文学",
            "中原",
            "厚土、方言与历史深处的叙事力量。",
            "中原文学扎根厚土与方言，既有历史长河，也有当代乡村与城镇的艰难与幽默。",
            ["厚土", "方言", "历史", "乡镇"],
            [{"name": "阎连科", "blurb": "神实主义与中原乡村。"}, {"name": "李佩甫", "blurb": "平原上的权力与人情。"}, {"name": "乔叶", "blurb": "当代中原女性声音。"}],
            [{"title": "受活", "author": "阎连科"}, {"title": "羊的门", "author": "李佩甫"}],
            "mainland",
        ),
        (
            "xibei",
            "西北文学",
            "西北",
            "黄土、荒漠与信念之间的长音。",
            "西北文学写黄土高原、河西走廊与边疆的信仰、饥饿与沉默的力量。",
            ["黄土", "边塞", "信仰", "沉默"],
            [{"name": "路遥", "blurb": "平凡世界里的西北青年。"}, {"name": "陈忠实", "blurb": "白鹿原上的家族史诗。"}, {"name": "红柯", "blurb": "新疆与西海固的诗性叙事。"}],
            [{"title": "平凡的世界", "author": "路遥"}, {"title": "白鹿原", "author": "陈忠实"}],
            "mainland",
        ),
        (
            "zangdi",
            "藏地文学",
            "藏地",
            "高原、信仰与汉语中的藏地经验。",
            "藏地文学以高原光线与信仰为底色，连接汉语写作与地方知识、神话与当代生活。",
            ["高原", "信仰", "神话", "边地"],
            [{"name": "阿来", "blurb": "尘埃与嘉绒大地。"}, {"name": "次仁罗布", "blurb": "藏地当代汉语小说。"}, {"name": "范稳", "blurb": "藏地历史长卷。"}],
            [{"title": "尘埃落定", "author": "阿来"}, {"title": "放生羊", "author": "次仁罗布"}],
            "mainland",
        ),
        (
            "xinan",
            "西南文学",
            "西南",
            "山地、方言与魔幻现实的交汇。",
            "西南文学有山城雾气、民族志与先锋实验，也有乡镇与边境的复杂声音。",
            ["山地", "方言", "先锋", "民族"],
            [{"name": "阿城", "blurb": "棋王与文化寻根。"}, {"name": "残雪", "blurb": "先锋与幽微内心。"}, {"name": "东西", "blurb": "广西叙事的当代面孔。"}],
            [{"title": "棋王", "author": "阿城"}, {"title": "后悔录", "author": "东西"}],
            "mainland",
        ),
        (
            "jiangnan",
            "江南文学",
            "江南",
            "水网、园林与精致的汉语感官。",
            "江南文学以水乡、市镇与文人传统为底，从现代海派到当代细腻的感官写作。",
            ["水乡", "市镇", "海派", "感官"],
            [{"name": "郁达夫", "blurb": "现代抒情的江南气质。"}, {"name": "王安忆", "blurb": "上海与江南的长篇世界。"}, {"name": "苏童", "blurb": "香椿树街与南方意象。"}],
            [{"title": "长恨歌", "author": "王安忆"}, {"title": "米", "author": "苏童"}],
            "mainland",
        ),
        (
            "lingnan",
            "岭南文学",
            "岭南",
            "湿热气候、商埠与南来北往的故事。",
            "岭南文学连接广州、广西与海南，写商埠、移民、方言与改革开放的潮汐。",
            ["商埠", "移民", "方言", "潮汐"],
            [{"name": "欧阳山", "blurb": "一代风流与岭南社会。"}, {"name": "张欣", "blurb": "都市岭南的情感图谱。"}, {"name": "林白", "blurb": "女性写作与南方经验。"}],
            [{"title": "三家巷", "author": "欧阳山"}, {"title": "一个人的战争", "author": "林白"}],
            "mainland",
        ),
        (
            "dongnan",
            "东南文学",
            "东南",
            "海岸线、侨乡与闽地的声音。",
            "东南文学面向海峡与南洋，写侨乡、家族与沿海城镇的开合。",
            ["侨乡", "海岸", "家族", "海峡"],
            [{"name": "冰心", "blurb": "闽籍现代文学先声。"}, {"name": "林语堂", "blurb": "跨语际的东南智识。"}, {"name": "北北", "blurb": "当代福建叙事。"}],
            [{"title": "寄小读者", "author": "冰心"}, {"title": "京华烟云", "author": "林语堂"}],
            "mainland",
        ),
        (
            "taiwan",
            "台湾文学",
            "台湾",
            "岛屿、母语与多重现代性。",
            "台湾文学在日治、战后与当代之间展开，写乡土、现代主义与岛屿身份。",
            ["岛屿", "乡土", "现代主义", "身份"],
            [{"name": "白先勇", "blurb": "台北人与华丽缘。"}, {"name": "黄春明", "blurb": "乡土文学代表。"}, {"name": "朱天心", "blurb": "当代台湾的锐利声音。"}],
            [{"title": "台北人", "author": "白先勇"}, {"title": "儿子的大玩偶", "author": "黄春明"}],
            "gat",
        ),
        (
            "hongkong",
            "香港文学",
            "香港",
            "城邦节奏与双语夹缝中的汉语。",
            "香港文学写都市节奏、流行文化与历史转折里的个人，也写武侠与严肃文学的并置。",
            ["都市", "城邦", "流行", "夹缝"],
            [{"name": "也斯", "blurb": "香港都市诗学。"}, {"name": "西西", "blurb": "童话与城市实验。"}, {"name": "董启章", "blurb": "长篇里的香港宇宙。"}],
            [{"title": "我城", "author": "西西"}, {"title": "天工开物·栩栩如真", "author": "董启章"}],
            "gat",
        ),
        (
            "macau",
            "澳门文学",
            "澳门",
            "小城、口岸与跨文化的低语。",
            "澳门文学体量小而独特，写口岸历史、中葡交汇与小城日常。",
            ["口岸", "小城", "跨文化"],
            [{"name": "鲁茂", "blurb": "澳门报章与小说传统。"}, {"name": "李观鼎", "blurb": "澳门文学评论与创作。"}, {"name": "汤祯兆", "blurb": "当代澳门观察。"}],
            [{"title": "澳门故事", "author": "鲁茂"}, {"title": "澳门文学评述", "author": "李观鼎"}],
            "gat",
        ),
        (
            "mahua",
            "马华文学",
            "马华",
            "热带、多语社会与离散的汉语。",
            "马华文学在马来西亚多语环境中坚持汉语写作，写雨林、城镇与身份政治。",
            ["雨林", "多语", "离散", "身份"],
            [{"name": "黎紫书", "blurb": "马华小说的重要当代声音。"}, {"name": "黄锦树", "blurb": "理论与创作并重。"}, {"name": "李永平", "blurb": "南洋与中国想象。"}],
            [{"title": "告别的年代", "author": "黎紫书"}, {"title": "吉陵春秋", "author": "李永平"}],
            "nanyang",
        ),
        (
            "singapore",
            "新加坡华文文学",
            "新加坡华文",
            "城邦、政策语言与华文位置。",
            "新加坡华文文学在英语主导的城邦里守护华文，写移民史、家庭与都市治理下的情感。",
            ["城邦", "移民", "家庭", "双语"],
            [{"name": "英培安", "blurb": "新加坡华文长篇重镇。"}, {"name": "希尼尔", "blurb": "微型小说与都市速写。"}, {"name": "吴耀宗", "blurb": "当代诗与小说。"}],
            [{"title": "画室", "author": "英培安"}, {"title": "轻信莫疑", "author": "希尼尔"}],
            "nanyang",
        ),
        (
            "seasia",
            "东南亚华语文学",
            "东南亚华语",
            "海路、侨批与多国华文网络。",
            "东南亚华语文学跨越泰、印尼、越、菲等地，写海路贸易、侨乡纽带与冷战遗痕。",
            ["海路", "侨批", "冷战", "网络"],
            [{"name": "黄锦树", "blurb": "区域华文的重要参照。"}, {"name": "张贵兴", "blurb": "婆罗洲雨林叙事。"}, {"name": "小黑", "blurb": "马华与区域短篇。"}],
            [{"title": "猴杯", "author": "张贵兴"}, {"title": "土与火", "author": "小黑"}],
            "nanyang",
        ),
        (
            "japankorea",
            "日韩华语文学",
            "日韩华语",
            "留学、侨居与东亚城市中的汉语。",
            "日韩华语写作常与留学、侨居和翻译相关，写东亚都市里的疏离与亲密。",
            ["留学", "侨居", "翻译", "都市"],
            [{"name": "张承志", "blurb": "与日本经验相关的汉语写作。"}, {"name": "李长声", "blurb": "日本观察随笔。"}, {"name": "多和田叶子", "blurb": "跨语写作的参照（日德）。"}],
            [{"title": "敬重与惜别", "author": "李长声"}, {"title": "北方的河", "author": "张承志"}],
            "overseas",
        ),
        (
            "northamerica",
            "北美华语文学",
            "北美华语",
            "移民、校园与双语生活中的汉语。",
            "北美华语文学写留学、移民家庭、种族政治与双语夹缝中的自我发明。",
            ["移民", "校园", "双语", "身份"],
            [{"name": "严歌苓", "blurb": "北美华人经验的小说家。"}, {"name": "哈金", "blurb": "英语写作中的中国经验（参照）。"}, {"name": "张翎", "blurb": "移民故事与历史回声。"}],
            [{"title": "扶桑", "author": "严歌苓"}, {"title": "金山", "author": "张翎"}],
            "overseas",
        ),
        (
            "europe",
            "欧洲华语文学",
            "欧洲华语",
            "旅欧、流亡与思想交汇中的汉语。",
            "欧洲华语写作连接留学、流亡与思想史，写异乡的孤独与回望。",
            ["旅欧", "流亡", "思想", "回望"],
            [{"name": "高行健", "blurb": "法语与汉语之间的剧作与小说。"}, {"name": "虹影", "blurb": "旅英写作与女性叙事。"}, {"name": "赵毅衡", "blurb": "符号学与散文随笔。"}],
            [{"title": "灵山", "author": "高行健"}, {"title": "饥饿的女儿", "author": "虹影"}],
            "overseas",
        ),
        (
            "oceania",
            "大洋洲华语文学",
            "大洋洲华语",
            "南半球城市与华人社群的汉语。",
            "大洋洲华语文学写澳新等地的华人社群、自然与疏离，以及跨太平洋的家书。",
            ["社群", "自然", "疏离", "家书"],
            [{"name": "欧阳昱", "blurb": "澳华诗歌与翻译。"}, {"name": "张奥列", "blurb": "澳华小说。"}, {"name": "萧虹", "blurb": "澳华文学整理与创作。"}],
            [{"title": "独自上升", "author": "欧阳昱"}, {"title": "澳洲的中国人", "author": "张奥列"}],
            "overseas",
        ),
    ]

    for args in stubs:
        rid = args[0]
        regions[rid] = _stub(*args)

    # Ensure every dissolve / island id has a region entry
    for rid in REGION_GROUPS:
        assert rid in regions, rid
    for island in OVERSEAS_ISLANDS:
        assert island["id"] in regions, island["id"]

    # Overlay table-driven style / authors / works / timeline.
    _merge_book_data(regions)
    return regions


LITERARY_REGIONS: dict[str, dict[str, Any]] = _build_regions()


def get_region(region_id: str) -> dict[str, Any] | None:
    return LITERARY_REGIONS.get(region_id)


def regions_for_filter(filter_id: str | None = None) -> list[dict[str, Any]]:
    items = list(LITERARY_REGIONS.values())
    if filter_id:
        items = [r for r in items if r.get("filter") == filter_id]
    # Stable order: mainland groups order, then gat, nanyang, overseas
    order = list(REGION_GROUPS.keys()) + [i["id"] for i in OVERSEAS_ISLANDS]
    rank = {rid: i for i, rid in enumerate(order)}
    return sorted(items, key=lambda r: rank.get(r["id"], 999))


def regions_json_payload() -> list[dict[str, Any]]:
    """Compact payload for map preview JS (no hard-coded copy in components)."""
    out = []
    for r in regions_for_filter():
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "short_name": r["short_name"],
                "brief": r["brief"],
                "style": r.get("style", ""),
                "scope": r.get("scope", ""),
                "keywords": r["keywords"][:5],
                "writers": [w["name"] for w in r["writers"][:4]],
                "starter_books": [
                    {"title": b["title"], "author": b.get("author", "")}
                    for b in r["starter_books"][:4]
                ],
                "image": r.get("image", ""),
                "detail_path": r["detail_path"],
                "filter": r["filter"],
            }
        )
    return out


FILTER_PILL_META = FILTER_PILLS
