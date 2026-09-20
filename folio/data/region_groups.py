"""Province → literary region dissolve groups for the Chinese literature map.

Source GeoJSON: DataV Aliyun `100000_full.json`
(https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json) — China
province/municipality boundaries including 台湾 / 香港 / 澳门.
"""

from __future__ import annotations

# Province names as they appear in DataV properties.name
REGION_GROUPS: dict[str, dict] = {
    "dongbei": {
        "id": "dongbei",
        "name": "东北",
        "filter": "mainland",
        "fill": "#c5d4c8",
        "provinces": ["辽宁省", "吉林省", "黑龙江省"],
    },
    "caoyuan": {
        "id": "caoyuan",
        "name": "草原",
        "filter": "mainland",
        "fill": "#d4c9a8",
        "provinces": ["内蒙古自治区"],
    },
    "huabei": {
        "id": "huabei",
        "name": "华北·京津",
        "filter": "mainland",
        "fill": "#c8d0d8",
        "provinces": ["北京市", "天津市", "河北省", "山西省"],
    },
    "zhongyuan": {
        "id": "zhongyuan",
        "name": "中原",
        "filter": "mainland",
        "fill": "#d8cfc0",
        "provinces": ["河南省", "山东省", "湖北省", "湖南省"],
    },
    "xibei": {
        "id": "xibei",
        "name": "西北",
        "filter": "mainland",
        "fill": "#d9d0b8",
        "provinces": ["陕西省", "甘肃省", "宁夏回族自治区", "青海省", "新疆维吾尔自治区"],
    },
    "zangdi": {
        "id": "zangdi",
        "name": "藏地",
        "filter": "mainland",
        "fill": "#c9c4d4",
        "provinces": ["西藏自治区"],
    },
    "xinan": {
        "id": "xinan",
        "name": "西南",
        "filter": "mainland",
        "fill": "#c4d4c0",
        "provinces": ["四川省", "重庆市", "云南省", "贵州省"],
    },
    "jiangnan": {
        "id": "jiangnan",
        "name": "江南",
        "filter": "mainland",
        "fill": "#c0d4d0",
        "provinces": ["江苏省", "浙江省", "上海市", "安徽省"],
    },
    "lingnan": {
        "id": "lingnan",
        "name": "岭南",
        "filter": "mainland",
        "fill": "#d0d8c4",
        "provinces": ["广东省", "广西壮族自治区", "海南省"],
    },
    "dongnan": {
        "id": "dongnan",
        "name": "东南",
        "filter": "mainland",
        "fill": "#c8d8d4",
        "provinces": ["福建省", "江西省"],
    },
    "taiwan": {
        "id": "taiwan",
        "name": "台湾",
        "filter": "gat",
        "fill": "#d4d0c8",
        "provinces": ["台湾省"],
    },
    "hongkong": {
        "id": "hongkong",
        "name": "香港",
        "filter": "gat",
        "fill": "#d8d4cc",
        "provinces": ["香港特别行政区"],
    },
    "macau": {
        "id": "macau",
        "name": "澳门",
        "filter": "gat",
        "fill": "#d0ccc4",
        "provinces": ["澳门特别行政区"],
    },
}

# Abstract overseas / Nanyang islands (not dissolved from admin borders)
OVERSEAS_ISLANDS: list[dict] = [
    {
        "id": "mahua",
        "name": "马华",
        "filter": "nanyang",
        "fill": "#d2c8b8",
        "cx": 620,
        "cy": 735,
        "rx": 48,
        "ry": 28,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (620, 510),
        "curve_bend": 0.2,
        "curve_side": 1,
    },
    {
        "id": "singapore",
        "name": "新加坡华文",
        "filter": "nanyang",
        "fill": "#d0c4b4",
        "cx": 820,
        "cy": 740,
        "rx": 42,
        "ry": 24,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (650, 515),
        "curve_bend": 0.22,
        "curve_side": 1,
    },
    {
        "id": "seasia",
        "name": "东南亚华语",
        "filter": "nanyang",
        "fill": "#ccc0b0",
        "cx": 420,
        "cy": 730,
        "rx": 56,
        "ry": 30,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (560, 520),
        "curve_bend": 0.2,
        "curve_side": -1,
    },
    {
        "id": "japankorea",
        "name": "日韩华语",
        "filter": "overseas",
        "fill": "#c8c4d0",
        "cx": 1080,
        "cy": 260,
        "rx": 44,
        "ry": 26,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (760, 300),
        "curve_bend": 0.24,
        "curve_side": 1,
    },
    {
        "id": "northamerica",
        "name": "北美华语",
        "filter": "overseas",
        "fill": "#c4ccd4",
        "cx": 95,
        "cy": 280,
        "rx": 52,
        "ry": 28,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (300, 280),
        "curve_bend": 0.28,
        "curve_side": 1,
    },
    {
        "id": "europe",
        "name": "欧洲华语",
        "filter": "overseas",
        "fill": "#c8c8d0",
        "cx": 85,
        "cy": 430,
        "rx": 48,
        "ry": 26,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (270, 400),
        "curve_bend": 0.26,
        "curve_side": -1,
    },
    {
        "id": "oceania",
        "name": "大洋洲华语",
        "filter": "overseas",
        "fill": "#c4d0c8",
        "cx": 1020,
        "cy": 745,
        "rx": 50,
        "ry": 28,
        "label_dx": 0,
        "label_dy": 4,
        "connect_to": (700, 520),
        "curve_bend": 0.24,
        "curve_side": 1,
    },
]

FILTER_PILLS: list[dict] = [
    {"id": "all", "label": "全部"},
    {"id": "mainland", "label": "大陆地区"},
    {"id": "gat", "label": "港澳台"},
    {"id": "nanyang", "label": "南洋"},
    {"id": "overseas", "label": "海外"},
]

# SVG canvas (mainland projected into upper area; islands below/around)
SVG_WIDTH = 1280
SVG_HEIGHT = 820
MAINLAND_VIEW = {
    # lon/lat bounds for China proper (+ Taiwan)
    "lon_min": 73.0,
    "lon_max": 135.0,
    "lat_min": 17.5,
    "lat_max": 54.0,
    # pixel box for mainland drawing
    "x0": 220,
    "y0": 40,
    "w": 620,
    "h": 520,
}
