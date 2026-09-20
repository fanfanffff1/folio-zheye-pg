"""World-literature tour regions: preview copy + detail content.

Schematic (not survey-accurate) literary regions for the 世界文学巡礼 map.
Kept deliberately data-only so the map SVG / pages can be regenerated.
"""

from __future__ import annotations

from typing import Any

WORLD_FILTER_PILLS: list[dict[str, str]] = [
    {"id": "all", "label": "全部"},
    {"id": "europe", "label": "欧洲"},
    {"id": "americas", "label": "美洲"},
    {"id": "asia", "label": "亚洲"},
    {"id": "middleeast", "label": "中东"},
    {"id": "africa", "label": "非洲"},
    {"id": "oceania", "label": "大洋洲"},
]


def _region(
    region_id: str,
    name: str,
    short_name: str,
    style: str,
    scope: str,
    keywords: list[str],
    writers: list[dict[str, str]],
    works: list[dict[str, str]],
    filter_id: str,
    *,
    quote: str = "",
    quote_by: str = "",
    detail_path: str | None = None,
) -> dict[str, Any]:
    return {
        "id": region_id,
        "map_type": "world",
        "name": name,
        "short_name": short_name,
        "style": style,
        "scope": scope,
        "brief": f"{style}{scope}",
        "subtitle": style,
        "keywords": keywords,
        "writers": writers,
        "representative_authors": [w["name"] for w in writers],
        "representative_works": works,
        "starter_books": [
            {"title": w["title"], "author": w.get("author", ""), "note": ""} for w in works
        ],
        "quote": quote,
        "quote_by": quote_by,
        "collection_id": f"world-{region_id}",
        "detail_path": detail_path or f"/literary-map/world/{region_id}",
        "collection_path": f"/literary-map/world/{region_id}/collection",
        "filter": filter_id,
        "book_count": len(works),
    }


WORLD_REGIONS: dict[str, dict[str, Any]] = {}


def _add(region: dict[str, Any]) -> None:
    WORLD_REGIONS[region["id"]] = region


_add(_region(
    "britain_ireland",
    "英国与爱尔兰文学",
    "英国与爱尔兰",
    "经验主义与道德讽喻、心理现实主义、哥特与荒诞、帝国之后的身份反思。",
    "从伦敦的剧场到都柏林的街巷，英语世界最深的心理与讽刺传统。",
    ["心理现实", "社会讽刺", "哥特", "现代主义"],
    [
        {"name": "简·奥斯汀", "blurb": "以婚姻与阶层写尽英式反讽与体面。"},
        {"name": "查尔斯·狄更斯", "blurb": "工业都市里的孤儿、债务与温情。"},
        {"name": "弗吉尼亚·伍尔夫", "blurb": "意识流中的时间、性别与战争。"},
        {"name": "詹姆斯·乔伊斯", "blurb": "都柏林一日，现代小说的分水岭。"},
        {"name": "艾米莉·勃朗特", "blurb": "荒原上的爱与复仇，哥特的顶点。"},
    ],
    [
        {"title": "傲慢与偏见", "author": "简·奥斯汀"},
        {"title": "远大前程", "author": "查尔斯·狄更斯"},
        {"title": "达洛维夫人", "author": "弗吉尼亚·伍尔夫"},
        {"title": "尤利西斯", "author": "詹姆斯·乔伊斯"},
        {"title": "呼啸山庄", "author": "艾米莉·勃朗特"},
        {"title": "一九八四", "author": "乔治·奥威尔"},
    ],
    "europe",
    quote="我们都在阴沟里，但仍有人仰望星空。",
    quote_by="奥斯卡·王尔德",
))

_add(_region(
    "usa_canada",
    "美国与加拿大文学",
    "美国与加拿大",
    "边疆与移民经验、个人主义与清教遗产、南方哥特、后现代实验。",
    "从新英格兰到密西西比，从草原到北方森林，多元而辽阔的北美叙事。",
    ["边疆", "移民", "南方哥特", "后现代"],
    [
        {"name": "赫尔曼·梅尔维尔", "blurb": "以海洋与执念写美国的形而上学。"},
        {"name": "马克·吐温", "blurb": "密西西比河上的口语与自由。"},
        {"name": "威廉·福克纳", "blurb": "南方家族的衰败与时间迷宫。"},
        {"name": "托妮·莫里森", "blurb": "以记忆与创伤写非裔美国经验。"},
        {"name": "艾丽丝·门罗", "blurb": "加拿大小镇里女性的隐秘人生。"},
    ],
    [
        {"title": "白鲸", "author": "赫尔曼·梅尔维尔"},
        {"title": "哈克贝利·费恩历险记", "author": "马克·吐温"},
        {"title": "喧哗与骚动", "author": "威廉·福克纳"},
        {"title": "宠儿", "author": "托妮·莫里森"},
        {"title": "老人与海", "author": "欧内斯特·海明威"},
        {"title": "逃离", "author": "艾丽丝·门罗"},
    ],
    "americas",
    quote="河流知道一切，只是从不说话。",
    quote_by="马克·吐温",
))

_add(_region(
    "latin_america",
    "拉丁美洲文学",
    "拉丁美洲",
    "魔幻现实、殖民与混血记忆、政治暴力、热带与巴洛克。",
    "在现实与幻想的交汇处，书写土地、记忆与人，让日常生活长出魔幻的枝叶。",
    ["魔幻现实", "殖民记忆", "政治", "巴洛克"],
    [
        {"name": "豪尔赫·路易斯·博尔赫斯", "blurb": "以迷宫、镜子与无限写短篇的宇宙。"},
        {"name": "加西亚·马尔克斯", "blurb": "马孔多的百年孤独与拉美史诗。"},
        {"name": "马里奥·巴尔加斯·略萨", "blurb": "结构现实主义里的权力与欲望。"},
        {"name": "胡里奥·科塔萨尔", "blurb": "跳房子式的语言实验与都市幻想。"},
        {"name": "巴勃罗·聂鲁达", "blurb": "情诗与政治诗并行的拉美声音。"},
    ],
    [
        {"title": "百年孤独", "author": "加西亚·马尔克斯"},
        {"title": "小径分岔的花园", "author": "博尔赫斯"},
        {"title": "绿房子", "author": "巴尔加斯·略萨"},
        {"title": "跳房子", "author": "科塔萨尔"},
        {"title": "佩德罗·巴拉莫", "author": "胡安·鲁尔福"},
        {"title": "二十首情诗与绝望的歌", "author": "聂鲁达"},
    ],
    "americas",
    quote="在那里，记忆没有尽头，遗忘也没有。",
    quote_by="加西亚·马尔克斯",
))

_add(_region(
    "france",
    "法国与法语文学",
    "法国与法语",
    "理性与启蒙、存在主义、新小说实验、法语世界的流散。",
    "从沙龙与百科全书到塞纳河畔的咖啡馆，法语文学不断重写自由与荒诞。",
    ["启蒙", "存在主义", "新小说", "流散"],
    [
        {"name": "奥诺雷·德·巴尔扎克", "blurb": "人间喜剧，写尽一个时代的风俗。"},
        {"name": "居斯塔夫·福楼拜", "blurb": "精确文体与平凡生活的悲剧。"},
        {"name": "马塞尔·普鲁斯特", "blurb": "追忆中重建时间与感官。"},
        {"name": "阿尔贝·加缪", "blurb": "荒诞、反抗与地中海的阳光。"},
        {"name": "玛格丽特·杜拉斯", "blurb": "以破碎的语句写爱、记忆与殖民。"},
    ],
    [
        {"title": "包法利夫人", "author": "居斯塔夫·福楼拜"},
        {"title": "追忆似水年华", "author": "马塞尔·普鲁斯特"},
        {"title": "局外人", "author": "阿尔贝·加缪"},
        {"title": "情人", "author": "玛格丽特·杜拉斯"},
        {"title": "悲惨世界", "author": "维克多·雨果"},
        {"title": "高老头", "author": "奥诺雷·德·巴尔扎克"},
    ],
    "europe",
    quote="真正的发现之旅，不在于看见新风景，而在于拥有新眼光。",
    quote_by="马塞尔·普鲁斯特",
))

_add(_region(
    "spain",
    "西班牙文学",
    "西班牙",
    "黄金世纪与流浪汉小说、地域与多元、内战记忆、魔幻与日常。",
    "从拉曼查的风车到安达卢西亚的深歌，西班牙语文学的发源地。",
    ["黄金世纪", "流浪汉", "内战记忆", "地域"],
    [
        {"name": "米格尔·德·塞万提斯", "blurb": "现代小说的开端，理想与现实的喜剧。"},
        {"name": "费德里科·加西亚·洛尔迦", "blurb": "安达卢西亚的诗歌与悲剧。"},
        {"name": "米格尔·德·乌纳穆诺", "blurb": "以迷雾与哲思写存在的焦虑。"},
        {"name": "贝尼托·佩雷斯·加尔多斯", "blurb": "以民族轶事写西班牙社会。"},
        {"name": "哈维尔·马里亚斯", "blurb": "以悬念与沉思写当代西班牙。"},
    ],
    [
        {"title": "堂吉诃德", "author": "塞万提斯"},
        {"title": "洛尔迦诗选", "author": "费德里科·加西亚·洛尔迦"},
        {"title": "迷雾", "author": "乌纳穆诺"},
        {"title": "羊泉村", "author": "洛佩·德·维加"},
        {"title": "时间里的痴人", "author": "哈维尔·马里亚斯"},
    ],
    "europe",
    quote="绿啊，我多么爱你这绿色。",
    quote_by="费德里科·加西亚·洛尔迦",
))

_add(_region(
    "portugal",
    "葡萄牙文学",
    "葡萄牙",
    "海洋与乡愁、saudade 情结、现代主义、殖民与后殖民。",
    "从卡蒙斯的航海史诗到佩索阿的里斯本，葡语世界的起点。",
    ["海洋", "saudade", "现代主义", "后殖民"],
    [
        {"name": "路易斯·德·卡蒙斯", "blurb": "以卢济塔尼亚人之歌写航海与帝国。"},
        {"name": "费尔南多·佩索阿", "blurb": "以无数异名写里斯本的忧郁。"},
        {"name": "若泽·萨拉马戈", "blurb": "以寓言拷问理性与人性。"},
        {"name": "埃萨·德·凯罗斯", "blurb": "以讽刺写里斯本的社会百态。"},
        {"name": "安东尼奥·洛博·安图内斯", "blurb": "以意识流写殖民战争的创伤。"},
    ],
    [
        {"title": "卢济塔尼亚人之歌", "author": "路易斯·德·卡蒙斯"},
        {"title": "佩索阿诗选", "author": "费尔南多·佩索阿"},
        {"title": "失明症漫记", "author": "若泽·萨拉马戈"},
        {"title": "马亚一家", "author": "埃萨·德·凯罗斯"},
        {"title": "大象旅行记", "author": "若泽·萨拉马戈"},
    ],
    "europe",
    quote="我什么都不是，也永远不会成为什么。",
    quote_by="费尔南多·佩索阿",
))

_add(_region(
    "germany_central",
    "德国与中欧文学",
    "德国与中欧",
    "浪漫主义与哲思、成长小说、卡夫卡式荒诞、战后记忆。",
    "从歌德的浮士德到卡夫卡的办公室，德语与中欧世界在思想与荒诞之间。",
    ["浪漫主义", "成长小说", "荒诞", "战后记忆"],
    [
        {"name": "约翰·沃尔夫冈·冯·歌德", "blurb": "以浮士德写近代人的求索。"},
        {"name": "弗兰茨·卡夫卡", "blurb": "官僚、罪责与变形中的现代焦虑。"},
        {"name": "托马斯·曼", "blurb": "以魔山写欧洲的精神危机。"},
        {"name": "莱纳·玛利亚·里尔克", "blurb": "在物与天使之间写现代诗。"},
        {"name": "米兰·昆德拉", "blurb": "以反讽写政治与存在的轻与重。"},
    ],
    [
        {"title": "浮士德", "author": "歌德"},
        {"title": "变形记", "author": "弗兰茨·卡夫卡"},
        {"title": "魔山", "author": "托马斯·曼"},
        {"title": "不能承受的生命之轻", "author": "米兰·昆德拉"},
        {"title": "给青年诗人的信", "author": "里尔克"},
    ],
    "europe",
    quote="一切伟大的作品都诞生于对世界的陌生感。",
    quote_by="弗兰茨·卡夫卡",
))

_add(_region(
    "italy",
    "意大利文学",
    "意大利",
    "古典人文、但丁传统、新现实主义、后现代迷宫。",
    "从神曲的三界到战后街巷，意大利文学始终在古典与日常之间穿行。",
    ["人文主义", "新现实主义", "后现代", "城市"],
    [
        {"name": "但丁·阿利吉耶里", "blurb": "以神曲奠定意大利语的文学传统。"},
        {"name": "伊塔洛·卡尔维诺", "blurb": "以幻想与结构写现代寓言。"},
        {"name": "翁贝托·埃科", "blurb": "符号学与历史悬疑的迷宫。"},
        {"name": "阿尔贝托·莫拉维亚", "blurb": "以冷漠写战后中产的道德。"},
        {"name": "埃莱娜·费兰特", "blurb": "那不勒斯四部曲里的女性与城市。"},
    ],
    [
        {"title": "神曲", "author": "但丁"},
        {"title": "看不见的城市", "author": "伊塔洛·卡尔维诺"},
        {"title": "玫瑰的名字", "author": "翁贝托·埃科"},
        {"title": "我的天才女友", "author": "埃莱娜·费兰特"},
        {"title": "冷漠的人们", "author": "阿尔贝托·莫拉维亚"},
    ],
    "europe",
    quote="地狱最炽热之处，留给在道德危机中保持中立的人。",
    quote_by="但丁",
))

_add(_region(
    "russia_east_europe",
    "俄罗斯与东欧文学",
    "俄罗斯与东欧",
    "灵魂与苦难、现实主义史诗、讽刺与荒诞、流亡书写。",
    "从伏尔加河到多瑙河，沉重的历史与不驯的想象力在文字里彼此拉扯。",
    ["苦难", "史诗", "讽刺", "流亡"],
    [
        {"name": "费奥多尔·陀思妥耶夫斯基", "blurb": "在罪与信仰之间拷问灵魂。"},
        {"name": "列夫·托尔斯泰", "blurb": "以史诗写战争、家族与道德。"},
        {"name": "安东·契诃夫", "blurb": "在短篇与戏剧里写日常的悲悯。"},
        {"name": "米哈伊尔·布尔加科夫", "blurb": "以魔幻讽刺写莫斯科与信仰。"},
        {"name": "切斯瓦夫·米沃什", "blurb": "流亡中为历史作证的诗。"},
    ],
    [
        {"title": "罪与罚", "author": "陀思妥耶夫斯基"},
        {"title": "战争与和平", "author": "列夫·托尔斯泰"},
        {"title": "大师与玛格丽特", "author": "布尔加科夫"},
        {"title": "契诃夫短篇小说选", "author": "安东·契诃夫"},
        {"title": "被禁锢的头脑", "author": "切斯瓦夫·米沃什"},
    ],
    "europe",
    quote="美是一种可怕而恐怖的东西。",
    quote_by="陀思妥耶夫斯基",
))

_add(_region(
    "nordics",
    "北欧文学",
    "北欧",
    "冷峻自然、社会民主与孤独、犯罪小说、神话重述。",
    "漫长冬夜与极昼之间，北欧写作在自然、福利社会与孤独里寻找光。",
    ["自然", "孤独", "犯罪", "神话"],
    [
        {"name": "亨里克·易卜生", "blurb": "以社会问题剧撕开体面的表象。"},
        {"name": "奥古斯特·斯特林堡", "blurb": "自然主义与心理冲突的先锋。"},
        {"name": "克努特·汉姆生", "blurb": "以饥饿写现代人的精神漂泊。"},
        {"name": "塞尔玛·拉格洛夫", "blurb": "以童话重述北欧的土地与传说。"},
        {"name": "约恩·福瑟", "blurb": "极简语言中的沉默与等待。"},
    ],
    [
        {"title": "玩偶之家", "author": "亨里克·易卜生"},
        {"title": "饥饿", "author": "克努特·汉姆生"},
        {"title": "尼尔斯骑鹅旅行记", "author": "塞尔玛·拉格洛夫"},
        {"title": "龙纹身的女孩", "author": "斯蒂格·拉尔森"},
        {"title": "晨与夜", "author": "约恩·福瑟"},
    ],
    "europe",
    quote="在最长夜里，人最清楚自己需要什么光。",
    quote_by="北欧谚语",
))

_add(_region(
    "arabia",
    "阿拉伯·波斯·土耳其文学",
    "阿拉伯·波斯·土耳其",
    "口传史诗与诗歌传统、一千零一夜、苏菲神秘、现代流亡。",
    "从巴格达到伊斯坦布尔，诗歌、故事与信仰织成中东文学的锦缎。",
    ["诗歌", "一千零一夜", "神秘主义", "流亡"],
    [
        {"name": "鲁米", "blurb": "苏菲诗歌中的爱与合一。"},
        {"name": "哈菲兹", "blurb": "波斯抒情诗里的酒、爱与神。"},
        {"name": "纳吉布·马哈福兹", "blurb": "以开罗三部曲写埃及社会。"},
        {"name": "奥尔罕·帕慕克", "blurb": "在东西方之间写伊斯坦布尔的呼愁。"},
        {"name": "阿多尼斯", "blurb": "以诗歌反思阿拉伯的现代命运。"},
    ],
    [
        {"title": "一千零一夜", "author": "民间故事集"},
        {"title": "我的名字叫红", "author": "奥尔罕·帕慕克"},
        {"title": "开罗三部曲", "author": "纳吉布·马哈福兹"},
        {"title": "鲁米诗选", "author": "鲁米"},
        {"title": "我的孤独是一座花园", "author": "阿多尼斯"},
    ],
    "middleeast",
    quote="伤口是光进入你内心的地方。",
    quote_by="鲁米",
))

_add(_region(
    "south_asia",
    "南亚文学",
    "南亚",
    "史诗与神话、殖民与后殖民、英语写作、魔幻与都市。",
    "从恒河平原到孟买街头，多语并存的南亚以英语与母语同时讲述现代。",
    ["史诗", "后殖民", "英语写作", "魔幻"],
    [
        {"name": "拉宾德拉纳特·泰戈尔", "blurb": "以诗歌连接孟加拉与世界。"},
        {"name": "萨尔曼·鲁西迪", "blurb": "以魔幻写后殖民印度的诞生。"},
        {"name": "V.S.奈保尔", "blurb": "在流散与故乡之间写作。"},
        {"name": "阿兰达蒂·洛伊", "blurb": "以微小之物写种姓与性别。"},
        {"name": "裘帕·拉希莉", "blurb": "以短篇写移民的身份与乡愁。"},
    ],
    [
        {"title": "吉檀迦利", "author": "泰戈尔"},
        {"title": "午夜之子", "author": "萨尔曼·鲁西迪"},
        {"title": "微物之神", "author": "阿兰达蒂·洛伊"},
        {"title": "同名人", "author": "裘帕·拉希莉"},
        {"title": "印度：受伤的文明", "author": "V.S.奈保尔"},
    ],
    "asia",
    quote="让生如夏花之绚烂，死如秋叶之静美。",
    quote_by="泰戈尔",
))

_add(_region(
    "southeast_asia",
    "东南亚文学",
    "东南亚",
    "热带风土、殖民与民族国家、多语社会、雨林与海洋。",
    "在雨林、海峡与群岛之间，东南亚写作以多语讲述殖民、迁徙与本土。",
    ["热带", "殖民", "多语", "海洋"],
    [
        {"name": "普拉姆迪亚·阿南达·杜尔", "blurb": "以布鲁岛四部曲写印尼的觉醒。"},
        {"name": "黄锦树", "blurb": "以雨林与马共写马华的记忆。"},
        {"name": "黎紫书", "blurb": "以怡保的市井写马华当代生活。"},
        {"name": "张贵兴", "blurb": "以婆罗洲雨林写欲望与暴力。"},
        {"name": "尤索夫", "blurb": "新加坡马来文学的现代声音。"},
    ],
    [
        {"title": "人世间", "author": "普拉姆迪亚"},
        {"title": "告别的年代", "author": "黎紫书"},
        {"title": "猴杯", "author": "张贵兴"},
        {"title": "雨", "author": "黄锦树"},
        {"title": "我城", "author": "西西"},
    ],
    "asia",
    quote="雨落在雨林里，也落在所有想回家的路上。",
    quote_by="黄锦树",
))

_add(_region(
    "chinese",
    "华语文学",
    "华语",
    "方言与山川、乡土与现代性、离散与迁徙、网络与都市。",
    "沿着方言、山川与迁徙，寻找汉语写作的不同故乡。",
    ["乡土", "现代性", "离散", "都市"],
    [
        {"name": "鲁迅", "blurb": "以呐喊奠定现代汉语小说的批判传统。"},
        {"name": "沈从文", "blurb": "以边城写湘西的温情与挽歌。"},
        {"name": "张爱玲", "blurb": "以都市男女写乱世里的人性。"},
        {"name": "莫言", "blurb": "以高密东北乡写乡土中国的野性。"},
        {"name": "白先勇", "blurb": "以台北人写迁徙与旧梦。"},
    ],
    [
        {"title": "呐喊", "author": "鲁迅"},
        {"title": "边城", "author": "沈从文"},
        {"title": "倾城之恋", "author": "张爱玲"},
        {"title": "活着", "author": "余华"},
        {"title": "台北人", "author": "白先勇"},
    ],
    "asia",
    detail_path="/literary-map/chinese",
    quote="山川异域，风月同天。",
    quote_by="汉语古谚",
))

_add(_region(
    "japan",
    "日本文学",
    "日本",
    "物哀与幽玄、私小说、战后与都市、推理与幻想。",
    "在季节的细微变化里，日本文学写孤独、美与无常，也写都市的疏离。",
    ["物哀", "私小说", "都市", "推理"],
    [
        {"name": "夏目漱石", "blurb": "以心与猫写近代日本的自我。"},
        {"name": "川端康成", "blurb": "以雪国写美与虚无。"},
        {"name": "三岛由纪夫", "blurb": "以极致的文体写美与毁灭。"},
        {"name": "村上春树", "blurb": "以都市孤独与隐喻写当代日本。"},
        {"name": "吉本芭娜娜", "blurb": "以轻巧的语句写丧失与疗愈。"},
    ],
    [
        {"title": "心", "author": "夏目漱石"},
        {"title": "雪国", "author": "川端康成"},
        {"title": "金阁寺", "author": "三岛由纪夫"},
        {"title": "挪威的森林", "author": "村上春树"},
        {"title": "厨房", "author": "吉本芭娜娜"},
    ],
    "asia",
    quote="穿过县界长长的隧道，便是雪国。",
    quote_by="川端康成",
))

_add(_region(
    "korea",
    "韩国文学",
    "韩国",
    "儒家传统与近代创伤、分断与记忆、女性书写、都市孤独。",
    "在分断与高速现代化之间，韩国文学写记忆、女性与个体的抵抗。",
    ["分断", "记忆", "女性", "都市"],
    [
        {"name": "朴景利", "blurb": "以土地写近代韩国的苦难与坚韧。"},
        {"name": "黄顺元", "blurb": "以抒情写战争与人的尊严。"},
        {"name": "申京淑", "blurb": "以请照顾好我妈妈写家庭与女性。"},
        {"name": "韩江", "blurb": "以素食者写暴力、身体与抵抗。"},
        {"name": "金英夏", "blurb": "以都市与历史写当代韩国。"},
    ],
    [
        {"title": "请照顾好我妈妈", "author": "申京淑"},
        {"title": "素食者", "author": "韩江"},
        {"title": "光之帝国", "author": "金英夏"},
        {"title": "土地", "author": "朴景利"},
        {"title": "少年来了", "author": "韩江"},
    ],
    "asia",
    quote="我想成为一棵树，把根扎进土地里。",
    quote_by="韩江",
))

_add(_region(
    "africa",
    "非洲文学",
    "非洲",
    "口传传统、殖民与独立、后殖民批判、离散与身份。",
    "从尼日尔河到开普敦，非洲写作在口传与现代之间重述被改写的历史。",
    ["口传", "后殖民", "离散", "身份"],
    [
        {"name": "钦努阿·阿契贝", "blurb": "以瓦解写伊博社会与殖民入侵。"},
        {"name": "沃莱·索因卡", "blurb": "以戏剧与小说写约鲁巴世界。"},
        {"name": "恩古吉·瓦·提安戈", "blurb": "以母语写作抵抗殖民语言。"},
        {"name": "纳丁·戈迪默", "blurb": "以南非写种族隔离下的人。"},
        {"name": "奇玛曼达·恩戈兹·阿迪契", "blurb": "以当代视角写性别与移民。"},
    ],
    [
        {"title": "瓦解", "author": "钦努阿·阿契贝"},
        {"title": "耻", "author": "J.M.库切"},
        {"title": "半轮黄日", "author": "奇玛曼达·恩戈兹·阿迪契"},
        {"title": "死亡与国王的侍从", "author": "沃莱·索因卡"},
        {"title": "十字架上的魔鬼", "author": "恩古吉"},
    ],
    "africa",
    quote="直到狮子有了自己的历史学家，狩猎的故事才不再只属于猎人。",
    quote_by="非洲谚语",
))

_add(_region(
    "oceania",
    "澳大利亚·新西兰·太平洋文学",
    "大洋洲",
    "移民与拓荒、原住民叙事、海洋与岛屿、当代多元。",
    "在南半球的海洋与岛屿之间，大洋洲文学写迁徙、原住民记忆与多元当代。",
    ["移民", "原住民", "海洋", "多元"],
    [
        {"name": "帕特里克·怀特", "blurb": "以人树写澳洲大陆与人的孤独。"},
        {"name": "彼得·凯里", "blurb": "以凯利帮真史重写民族神话。"},
        {"name": "蒂姆·温顿", "blurb": "以云街写西澳的海与成长。"},
        {"name": "凯莉·赫尔姆", "blurb": "以女性视角写边地与记忆。"},
        {"name": "帕特里夏·格雷斯", "blurb": "以毛利视角写新西兰的家族史。"},
    ],
    [
        {"title": "人树", "author": "帕特里克·怀特"},
        {"title": "凯利帮真史", "author": "彼得·凯里"},
        {"title": "云街", "author": "蒂姆·温顿"},
        {"title": "骨人", "author": "克丽·休姆"},
        {"title": "鲸骑士", "author": "威提·伊希玛埃拉"},
    ],
    "oceania",
    quote="海从不属于任何人，它只记得所有经过的人。",
    quote_by="太平洋谚语",
))


def get_world_region(region_id: str) -> dict[str, Any] | None:
    return WORLD_REGIONS.get(region_id)


def world_regions_for_filter(filter_id: str | None = None) -> list[dict[str, Any]]:
    items = list(WORLD_REGIONS.values())
    if filter_id:
        items = [r for r in items if r.get("filter") == filter_id]
    return items


def world_regions_json_payload() -> list[dict[str, Any]]:
    """Compact payload for the map preview JS."""
    out = []
    for r in world_regions_for_filter():
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "short_name": r["short_name"],
                "brief": r["brief"],
                "style": r["style"],
                "scope": r["scope"],
                "keywords": r["keywords"][:5],
                "writers": [w["name"] for w in r["writers"][:4]],
                "starter_books": [
                    {"title": w["title"], "author": w.get("author", "")}
                    for w in r["representative_works"][:4]
                ],
                "detail_path": r["detail_path"],
                "filter": r["filter"],
            }
        )
    return out
