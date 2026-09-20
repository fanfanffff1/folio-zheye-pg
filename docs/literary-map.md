# 文学地图（华语文学 / 世界文学巡礼）

> 边界只有一个权威来源：GeoJSON → 按地区 dissolve → 单一主 SVG。
> 禁止手绘相邻边界，禁止多张 PNG 拼接地图，禁止 AI 生成行政轮廓。

## 世界文学巡礼（World）

| Path | Page |
|------|------|
| `/literary-map/world` | Interactive world map |
| `/literary-map/world/<region_id>` | Region detail (e.g. `latin_america`) |
| `/literary-map/world/<region_id>/collection` | Region reading list |
| `/api/literary-map/world/regions` | JSON for preview cards |

### Data & generation (single source)

| File | Role |
|------|------|
| `static/data/literary-map/world-countries.raw.json` | Raw Natural Earth 1:110m Admin 0 Countries GeoJSON (public domain) |
| `folio/data/world_region_groups.py` | Country (ISO_A3) → literary region dissolve map + projection |
| `scripts/build_world_literature_map.py` | Dissolve + project + emit SVG |
| `static/data/literary-map/world-regions.geojson` | Dissolved region geometries |
| `static/img/literary-map/world-literature-map.svg` | **Master interactive SVG** |
| `folio/data/world_regions.py` | Region content (style / writers / works) |

Backgrounds (bottom layer only): `world-desktop.png` / `world-tablet.png` / `world-mobile.png`.

```bash
python3 -m pip install shapely
python3 scripts/build_world_literature_map.py
```

The script never draws borders: it loads the raw GeoJSON, unions each region's
countries with shapely, simplifies, projects equirectangular, and writes one SVG
whose `<path class="clm-shape">` elements share edges exactly.

## Routes（华语文学）

| Path | Page |
|------|------|
| `/literary-map` | Redirect → `/literary-map/chinese` |
| `/literary-map/chinese` | Interactive Chinese literature map |
| `/literary-map/chinese/<region_id>` | Region detail (e.g. `dongbei`) |
| `/literary-map/chinese/<region_id>/collection` | Collection stub (empty OK) |
| `/literary-map/world` | World map stub |
| `/api/literary-map/chinese/regions` | JSON for preview cards |

Homepage entry: first card in「跨越语言，遇见故事」→ `/literary-map/chinese` (special card; does **not** add `zh` to `LANGS`).

## Assets

| File | Role |
|------|------|
| `static/img/literary-map/chinese-desktop.png` | Map page background (desktop) |
| `static/img/literary-map/chinese-tablet.png` | Background (tablet) |
| `static/img/literary-map/chinese-mobile.png` | Background (mobile) |
| `static/img/literary-map/chinese-literature-map.svg` | **Master interactive SVG** (regions) |
| `static/data/literary-map/china-provinces.raw.json` | Raw province GeoJSON |
| `static/data/literary-map/chinese-regions.geojson` | Dissolved literary regions |
| `static/css/literary-map.css` | Map + detail styles |
| `static/js/literary-map-chinese.js` | Map interactions |
| `static/js/literary-map-detail.js` | Detail timeline |

Backgrounds are bottom layer only (`background-size: cover; background-position: center`). Regions are SVG paths/islands — not a non-interactive bitmap map.

## Data

- `folio/data/region_groups.py` — province → region dissolve groups, overseas islands, filter pills
- `folio/data/literary_regions.py` — preview + detail copy (`dongbei` rich; others stubs)

## Regenerate SVG

GeoJSON source: **DataV Aliyun** China full boundary

```text
https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json
```

Saved as `static/data/literary-map/china-provinces.raw.json`.

```bash
# from repo root
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt shapely
# (re)download if missing:
curl -fsSL -o static/data/literary-map/china-provinces.raw.json \
  "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
.venv/bin/python scripts/build_chinese_literature_map.py
```

The script:

1. Loads province GeoJSON
2. Dissolves provinces per `REGION_GROUPS` (shapely `unary_union`)
3. Writes merged GeoJSON + master SVG with `id` / `data-region` / `aria-label` / `tabindex="0"`
4. Appends overseas abstract islands (马华、新加坡华文、东南亚华语、日韩华语、北美华语、欧洲华语、大洋洲华语) with soft dotted connectors

HK / Macau / Taiwan are separate regions (港澳台 filter).

## Interaction notes

- **Desktop:** gold hover `#e5bb52` + glow; right preview; click → detail
- **Tablet:** fixed/below preview panel; tap selects; CTA → detail
- **Mobile:** zoom/pan viewport; bottom drawer;「按列表浏览地区」for small targets
- Keyboard: Tab, Enter/Space, Esc

## Phase-1 styling

Soft low-saturation fills, thin ivory separators (`#f3efe6`), no thick black borders, no permanent heavy shadows on all regions.
