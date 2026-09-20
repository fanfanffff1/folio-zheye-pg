"""Country → world-literary-region dissolve groups.

Source GeoJSON: Natural Earth 1:110m Admin 0 Countries (public domain)
  https://www.naturalearthdata.com/
  mirror used: https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/
               geojson/ne_110m_admin_0_countries.geojson

Regions are literary/cultural groupings (not political). Boundaries always come
from this one GeoJSON + this dissolve map — never hand-drawn.
"""

from __future__ import annotations

# ISO_A3 codes as they appear in Natural Earth properties.
# Note: a few features carry ISO_A3 = "-99"; they are matched via ADM0_A3 below
# (FRA, NOR, KOS, CYN, SOL).
WORLD_REGION_GROUPS: dict[str, dict] = {
    "britain_ireland": {
        "id": "britain_ireland",
        "name": "英国与爱尔兰",
        "filter": "europe",
        "fill": "#9BB3C9",
        "countries": ["GBR", "IRL"],
        "label_offset": (-92, -20),
    },
    "usa_canada": {
        "id": "usa_canada",
        "name": "美国与加拿大",
        "filter": "americas",
        "fill": "#9DAFC7",
        "countries": ["USA", "CAN"],
    },
    "latin_america": {
        "id": "latin_america",
        "name": "拉丁美洲",
        "filter": "americas",
        "fill": "#D2956E",
        "countries": [
            "MEX", "GTM", "BLZ", "SLV", "HND", "NIC", "CRI", "PAN",
            "CUB", "JAM", "HTI", "DOM", "PRI", "TTO", "BHS",
            "COL", "VEN", "ECU", "PER", "BRA", "BOL", "PRY", "URY",
            "ARG", "CHL", "GUY", "SUR",
        ],
    },
    "france": {
        "id": "france",
        "name": "法国与法语文学",
        "filter": "europe",
        "fill": "#9CBE9A",
        "countries": ["FRA", "BEL", "CHE", "LUX"],
        "label_offset": (-150, -14),
    },
    "spain": {
        "id": "spain",
        "name": "西班牙",
        "filter": "europe",
        "fill": "#E0B65C",
        "countries": ["ESP"],
        "label_offset": (-128, -10),
    },
    "portugal": {
        "id": "portugal",
        "name": "葡萄牙",
        "filter": "europe",
        "fill": "#DDB07F",
        "countries": ["PRT"],
        "label_offset": (-110, 20),
    },
    "italy": {
        "id": "italy",
        "name": "意大利",
        "filter": "europe",
        "fill": "#B9BE74",
        "countries": ["ITA"],
        "label_offset": (86, -16),
    },
    "germany_central": {
        "id": "germany_central",
        "name": "德国与中欧",
        "filter": "europe",
        "fill": "#9DBC8E",
        "countries": ["DEU", "AUT", "POL", "CZE", "SVK", "HUN", "SVN", "HRV"],
        "label_offset": (66, -34),
    },
    "russia_east_europe": {
        "id": "russia_east_europe",
        "name": "俄罗斯与东欧",
        "filter": "europe",
        "fill": "#9BA8C8",
        "countries": [
            "RUS", "UKR", "BLR", "MDA", "ROU", "BGR", "SRB", "BIH",
            "MNE", "MKD", "ALB", "GRC", "LTU", "LVA", "EST",
            "KOS", "GEO", "ARM", "AZE", "MNG",
        ],
        "label_offset": (-30, -16),
    },
    "nordics": {
        "id": "nordics",
        "name": "北欧",
        "filter": "europe",
        "fill": "#86BCBB",
        "countries": ["NOR", "SWE", "FIN", "DNK", "ISL"],
        "label_offset": (12, -24),
    },
    "arabia": {
        "id": "arabia",
        "name": "阿拉伯·波斯·土耳其",
        "filter": "middleeast",
        "fill": "#E2C77E",
        "countries": [
            "TUR", "SYR", "LBN", "ISR", "PSE", "JOR", "IRQ", "IRN",
            "SAU", "YEM", "OMN", "ARE", "QAT", "CYP", "CYN",
            "KAZ", "UZB", "TKM", "TJK", "KGZ",
        ],
        "label_offset": (-12, -16),
    },
    "south_asia": {
        "id": "south_asia",
        "name": "南亚",
        "filter": "asia",
        "fill": "#BACB7C",
        "countries": ["IND", "PAK", "BGD", "NPL", "BTN", "LKA", "AFG"],
    },
    "southeast_asia": {
        "id": "southeast_asia",
        "name": "东南亚",
        "filter": "asia",
        "fill": "#86C3A2",
        "countries": [
            "MMR", "THA", "LAO", "KHM", "VNM", "MYS", "IDN",
            "PHL", "BRN", "TLS",
        ],
    },
    "chinese": {
        "id": "chinese",
        "name": "华语文学",
        "filter": "asia",
        "fill": "#A6C88E",
        "countries": ["CHN", "TWN"],
    },
    "japan": {
        "id": "japan",
        "name": "日本",
        "filter": "asia",
        "fill": "#DEA5AB",
        "countries": ["JPN"],
        "label_offset": (34, 6),
    },
    "korea": {
        "id": "korea",
        "name": "韩国",
        "filter": "asia",
        "fill": "#BBA4CE",
        "countries": ["KOR", "PRK"],
        "label_offset": (18, -16),
    },
    "africa": {
        "id": "africa",
        "name": "非洲",
        "filter": "africa",
        "fill": "#D0A87A",
        "countries": [
            "DZA", "MAR", "ESH", "TUN", "LBY", "EGY", "ERI", "SDN", "SSD",
            "ETH", "SOM", "SOL", "DJI", "KEN", "UGA", "RWA", "BDI", "TZA",
            "MOZ", "ZWE", "ZMB", "MWI", "AGO", "COD", "COG", "GAB", "GNQ",
            "CMR", "CAF", "TCD", "NER", "NGA", "BEN", "TGO", "GHA", "CIV",
            "LBR", "SLE", "GIN", "GNB", "SEN", "GMB", "MRT", "MLI", "BFA",
            "BWA", "NAM", "ZAF", "LSO", "SWZ", "MDG",
        ],
    },
    "oceania": {
        "id": "oceania",
        "name": "澳大利亚·新西兰·太平洋",
        "filter": "oceania",
        "fill": "#86C9BE",
        "countries": ["AUS", "NZL", "PNG", "FJI", "SLB", "VUT", "NCL"],
    },
}

# Natural Earth has ISO_A3 = "-99" for these; match by ADM0_A3 instead.
ADM0_FALLBACK: dict[str, str] = {
    "FRA": "france",
    "NOR": "nordics",
    "KOS": "russia_east_europe",
    "CYN": "arabia",
    "SOL": "africa",
}

# Equirectangular canvas. Antarctica + a few unclaimed islands are intentionally
# excluded from the literary regions.
WORLD_SVG_WIDTH = 1280
WORLD_SVG_HEIGHT = 520
WORLD_VIEW = {
    "lon_min": -180.0,
    "lon_max": 180.0,
    "lat_min": -58.0,
    "lat_max": 84.0,
    "x0": 0.0,
    "y0": 0.0,
    "w": float(WORLD_SVG_WIDTH),
    "h": float(WORLD_SVG_HEIGHT),
}
