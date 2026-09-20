#!/usr/bin/env python3
"""Dissolve Natural Earth country GeoJSON into literary regions and emit one SVG.

Single authoritative source:
  static/data/literary-map/world-countries.raw.json
  (Natural Earth 1:110m Admin 0 Countries, public domain)

Region membership lives in folio/data/world_region_groups.py — never hand-draw
adjacent borders. Regenerate with:

  python3 scripts/build_world_literature_map.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.data.world_region_groups import (  # noqa: E402
    ADM0_FALLBACK,
    WORLD_REGION_GROUPS,
    WORLD_SVG_HEIGHT,
    WORLD_SVG_WIDTH,
    WORLD_VIEW,
)

RAW_GEOJSON = ROOT / "static" / "data" / "literary-map" / "world-countries.raw.json"
MERGED_GEOJSON = ROOT / "static" / "data" / "literary-map" / "world-regions.geojson"
OUT_SVG = ROOT / "static" / "img" / "literary-map" / "world-literature-map.svg"


def project(lon: float, lat: float) -> tuple[float, float]:
    v = WORLD_VIEW
    x = v["x0"] + (lon - v["lon_min"]) / (v["lon_max"] - v["lon_min"]) * v["w"]
    y = v["y0"] + (v["lat_max"] - lat) / (v["lat_max"] - v["lat_min"]) * v["h"]
    return x, y


def ring_to_path(ring: list) -> str:
    if not ring:
        return ""
    parts = []
    for i, pt in enumerate(ring):
        x, y = project(pt[0], pt[1])
        parts.append(("M" if i == 0 else "L") + f"{x:.2f},{y:.2f}")
    parts.append("Z")
    return "".join(parts)


def geom_to_path(geom) -> str:
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        polys = []
        for g in geom.geoms:
            if isinstance(g, Polygon):
                polys.append(g)
            elif isinstance(g, MultiPolygon):
                polys.extend(list(g.geoms))
    else:
        return ""

    chunks = []
    for poly in polys:
        chunks.append(ring_to_path(list(poly.exterior.coords)))
        for interior in poly.interiors:
            chunks.append(ring_to_path(list(interior.coords)))
    return "".join(chunks)


def load_countries(path: Path) -> tuple[dict, dict]:
    from shapely.geometry import shape

    data = json.loads(path.read_text(encoding="utf-8"))
    by_iso: dict[str, object] = {}
    by_adm0: dict[str, object] = {}
    for ft in data.get("features", []):
        props = ft.get("properties") or {}
        geom = shape(ft["geometry"])
        iso = str(props.get("ISO_A3") or "").strip()
        if iso and iso != "-99":
            by_iso[iso] = geom
        adm0 = str(props.get("ADM0_A3") or "").strip()
        if adm0:
            by_adm0[adm0] = geom
    return by_iso, by_adm0


def dissolve_regions(by_iso: dict, by_adm0: dict) -> dict:
    from shapely.ops import unary_union

    dissolved = {}
    for rid, meta in WORLD_REGION_GROUPS.items():
        geoms, missing = [], []
        for code in meta["countries"]:
            g = by_iso.get(code) or by_adm0.get(code)
            if g is None:
                missing.append(code)
            else:
                geoms.append(g)
        if missing:
            print(f"WARN {rid}: missing countries {missing}", file=sys.stderr)
        if not geoms:
            continue
        cleaned = []
        for g in geoms:
            try:
                if not g.is_valid:
                    g = g.buffer(0)
            except Exception:
                g = g.buffer(0)
            cleaned.append(g)
        dissolved[rid] = unary_union(cleaned).buffer(0)
    return dissolved


def simplify(geom, tol: float = 0.06):
    try:
        return geom.simplify(tol, preserve_topology=True)
    except Exception:
        return geom


def label_xy(geom) -> tuple[float, float]:
    c = geom.representative_point()
    return project(c.x, c.y)


def projected_bbox(geom) -> tuple[float, float, float, float]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    geoms = getattr(geom, "geoms", [geom])
    for g in geoms:
        xs, ys = g.exterior.xy if hasattr(g, "exterior") else ([], [])
        for lon, lat in zip(xs, ys):
            x, y = project(lon, lat)
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
    return minx, miny, maxx, maxy


def write_merged_geojson(dissolved: dict) -> None:
    from shapely.geometry import mapping

    features = []
    for rid, geom in dissolved.items():
        meta = WORLD_REGION_GROUPS[rid]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": rid,
                    "name": meta["name"],
                    "filter": meta["filter"],
                    "fill": meta["fill"],
                },
                "geometry": mapping(geom),
            }
        )
    MERGED_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    MERGED_GEOJSON.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def build_svg(dissolved: dict) -> str:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WORLD_SVG_WIDTH} {WORLD_SVG_HEIGHT}" '
        'role="img" aria-label="世界文学巡礼地图" class="clm-svg" data-map="world">',
        "  <title>世界文学巡礼地图</title>",
        "  <desc>按文学传统划分的世界文学区域。可用键盘 Tab 选择区域。</desc>",
        "  <defs>",
        '    <filter id="clm-glow" x="-40%" y="-40%" width="180%" height="180%">',
        '      <feDropShadow dx="0" dy="0" stdDeviation="3.5" flood-color="#e5bb52" flood-opacity="0.75"/>',
        "    </filter>",
        "  </defs>",
        '  <g class="clm-world" data-layer="world">',
    ]
    region_lines: list[str] = []
    # Labels + leader lines go in a top overlay so no later region paints over them.
    overlay_lines: list[str] = []

    for rid, geom in dissolved.items():
        meta = WORLD_REGION_GROUPS[rid]
        g = simplify(geom)
        d = geom_to_path(g)
        if not d:
            continue
        lx, ly = label_xy(g)
        label = meta["name"]
        dx, dy = meta.get("label_offset", (0, 0))
        tx, ty = lx + dx, ly + dy
        region_lines.append(
            f'    <g class="clm-region" id="region-{rid}" data-region="{rid}" '
            f'data-filter="{meta["filter"]}" tabindex="0" role="button" '
            f'aria-label="{label}文学">'
        )
        region_lines.append(
            f'      <path class="clm-shape" d="{d}" fill="{meta["fill"]}" '
            f'stroke="#f3efe6" stroke-width="1.1" />'
        )
        minx, miny, maxx, maxy = projected_bbox(g)
        if max(maxx - minx, maxy - miny) < 16:
            hit_r = max(14.0, (maxx - minx) / 2, (maxy - miny) / 2)
            region_lines.append(
                f'      <circle class="clm-hit" cx="{lx:.1f}" cy="{ly:.1f}" r="{hit_r:.1f}" '
                f'fill="transparent" stroke="none" />'
            )
        region_lines.append("    </g>")

        if abs(dx) + abs(dy) >= 18:
            overlay_lines.append(
                f'    <path class="clm-label-leader" d="M{lx:.1f},{ly:.1f} L{tx:.1f},{ty:.1f}" '
                f'fill="none" stroke="#7a6a4a" stroke-width="0.8" stroke-dasharray="2 2.5" '
                f'opacity="0.7" pointer-events="none" />'
            )
            overlay_lines.append(
                f'    <circle class="clm-label-dot" cx="{lx:.1f}" cy="{ly:.1f}" r="1.6" '
                f'fill="#c5a35a" opacity="0.9" pointer-events="none" />'
            )
        overlay_lines.append(
            f'    <text class="clm-label" x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="11" fill="#3a4a40" pointer-events="none">{label}</text>'
        )

    lines = head + region_lines + ["  </g>", '  <g class="clm-labels-overlay" aria-hidden="true">']
    lines += overlay_lines
    lines += ["  </g>", "</svg>"]
    return "\n".join(lines) + "\n"


def main() -> int:
    if not RAW_GEOJSON.exists():
        print(f"Missing {RAW_GEOJSON}", file=sys.stderr)
        print(
            "Download Natural Earth ne_110m_admin_0_countries.geojson into that path.",
            file=sys.stderr,
        )
        return 1
    by_iso, by_adm0 = load_countries(RAW_GEOJSON)
    print(f"Loaded {len(by_iso)} ISO-indexed countries (+{len(by_adm0)} ADM0)")
    dissolved = dissolve_regions(by_iso, by_adm0)
    print(f"Dissolved {len(dissolved)} regions")
    write_merged_geojson(dissolved)
    print(f"Wrote {MERGED_GEOJSON}")
    svg = build_svg(dissolved)
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUT_SVG} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
