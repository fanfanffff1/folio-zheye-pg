#!/usr/bin/env python3
"""Dissolve China province GeoJSON into literary regions and emit one master SVG.

Data source (documented in docs/literary-map.md):
  DataV Aliyun areas_v3 bound 100000_full.json
  https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json

Usage (from repo root, with shapely available):
  .venv/bin/python scripts/build_chinese_literature_map.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.data.region_groups import (  # noqa: E402
    MAINLAND_VIEW,
    OVERSEAS_ISLANDS,
    REGION_GROUPS,
    SVG_HEIGHT,
    SVG_WIDTH,
)

RAW_GEOJSON = ROOT / "static" / "data" / "literary-map" / "china-provinces.raw.json"
MERGED_GEOJSON = ROOT / "static" / "data" / "literary-map" / "chinese-regions.geojson"
OUT_SVG = ROOT / "static" / "img" / "literary-map" / "chinese-literature-map.svg"


def project(lon: float, lat: float) -> tuple[float, float]:
    v = MAINLAND_VIEW
    x = v["x0"] + (lon - v["lon_min"]) / (v["lon_max"] - v["lon_min"]) * v["w"]
    y = v["y0"] + (v["lat_max"] - lat) / (v["lat_max"] - v["lat_min"]) * v["h"]
    return x, y


def ring_to_path(ring: list) -> str:
    if not ring:
        return ""
    parts = []
    for i, pt in enumerate(ring):
        lon, lat = pt[0], pt[1]
        x, y = project(lon, lat)
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd}{x:.2f},{y:.2f}")
    parts.append("Z")
    return "".join(parts)


def geom_to_path(geom) -> str:
    """Convert shapely geometry to SVG path d."""
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    polys = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
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


def load_features(path: Path) -> dict[str, object]:
    from shapely.geometry import shape

    data = json.loads(path.read_text(encoding="utf-8"))
    by_name = {}
    for ft in data.get("features", []):
        props = ft.get("properties") or {}
        name = props.get("name")
        if not name:
            continue
        by_name[name] = shape(ft["geometry"])
    return by_name


def dissolve_regions(by_name: dict) -> dict[str, object]:
    from shapely.ops import unary_union

    dissolved = {}
    for rid, meta in REGION_GROUPS.items():
        geoms = []
        missing = []
        for pname in meta["provinces"]:
            g = by_name.get(pname)
            if g is None:
                missing.append(pname)
            else:
                geoms.append(g)
        if missing:
            print(f"WARN {rid}: missing provinces {missing}", file=sys.stderr)
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


def simplify(geom, tol=0.08):
    try:
        return geom.simplify(tol, preserve_topology=True)
    except Exception:
        return geom


def centroid_label_xy(geom) -> tuple[float, float]:
    c = geom.representative_point()
    return project(c.x, c.y)


def write_merged_geojson(dissolved: dict) -> None:
    from shapely.geometry import mapping

    features = []
    for rid, geom in dissolved.items():
        meta = REGION_GROUPS[rid]
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
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" '
        f'role="img" aria-label="华语文学地图" class="clm-svg" data-map="chinese">',
        "  <title>华语文学地图</title>",
        "  <desc>按文学地理划分的中国与海外华语写作区域。可用键盘 Tab 选择区域。</desc>",
        '  <defs>',
        '    <filter id="clm-glow" x="-40%" y="-40%" width="180%" height="180%">',
        '      <feDropShadow dx="0" dy="0" stdDeviation="3.5" flood-color="#e5bb52" flood-opacity="0.75"/>',
        "    </filter>",
        "  </defs>",
        '  <g class="clm-connections" aria-hidden="true">',
    ]

    # Soft cubic dashes + constellation stars (coast → overseas islands)
    import math as _math

    def _cubic(x1, y1, x2, y2, bend=0.22, side=1.0):
        dx, dy = x2 - x1, y2 - y1
        nx, ny = -dy, dx
        nlen = _math.hypot(nx, ny) or 1.0
        nx, ny = nx / nlen * side, ny / nlen * side
        off = _math.hypot(dx, dy) * bend
        c1x = x1 + dx * 0.28 + nx * off * 0.55
        c1y = y1 + dy * 0.28 + ny * off * 0.55
        c2x = x1 + dx * 0.72 + nx * off
        c2y = y1 + dy * 0.72 + ny * off
        return f"M{x1:.1f},{y1:.1f} C{c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {x2:.1f},{y2:.1f}"

    def _star(cx, cy, r=2.8):
        return (
            f'    <path class="clm-connection-star" d="M{cx:.1f},{cy-r:.1f} L{cx+r*0.38:.1f},{cy-r*0.38:.1f} '
            f'L{cx+r:.1f},{cy:.1f} L{cx+r*0.38:.1f},{cy+r*0.38:.1f} L{cx:.1f},{cy+r:.1f} '
            f'L{cx-r*0.38:.1f},{cy+r*0.38:.1f} L{cx-r:.1f},{cy:.1f} L{cx-r*0.38:.1f},{cy-r*0.38:.1f} Z" />'
        )

    for island in OVERSEAS_ISLANDS:
        x1, y1 = island["connect_to"]
        x2, y2 = island["cx"], island["cy"]
        bend = float(island.get("curve_bend", 0.22))
        side = float(island.get("curve_side", 1))
        lines.append(f'    <path data-to="{island["id"]}" d="{_cubic(x1, y1, x2, y2, bend, side)}" />')
        dx, dy = x2 - x1, y2 - y1
        nx, ny = -dy, dx
        nlen = _math.hypot(nx, ny) or 1.0
        nx, ny = nx / nlen * side, ny / nlen * side
        off = _math.hypot(dx, dy) * bend * 0.65
        s1x, s1y = x1 + dx * 0.35 + nx * off * 0.5, y1 + dy * 0.35 + ny * off * 0.5
        s2x, s2y = x1 + dx * 0.68 + nx * off * 0.85, y1 + dy * 0.68 + ny * off * 0.85
        lines.append(_star(s1x, s1y, 2.8))
        lines.append(_star(s2x, s2y, 2.4))
    lines.append("  </g>")

    lines.append('  <g class="clm-mainland" data-layer="mainland">')
    for rid, geom in dissolved.items():
        meta = REGION_GROUPS[rid]
        g = simplify(geom)
        d = geom_to_path(g)
        if not d:
            continue
        lx, ly = centroid_label_xy(g)
        label = meta["name"]
        lines.append(
            f'    <g class="clm-region" id="region-{rid}" data-region="{rid}" '
            f'data-filter="{meta["filter"]}" tabindex="0" role="button" '
            f'aria-label="{label}文学">'
        )
        lines.append(
            f'      <path class="clm-shape" d="{d}" fill="{meta["fill"]}" '
            f'stroke="#f3efe6" stroke-width="1.1" />'
        )
        # Invisible min hit area for tiny regions (HK / Macau)
        if rid in {"hongkong", "macau"}:
            lines.append(
                f'      <circle class="clm-hit" cx="{lx:.1f}" cy="{ly:.1f}" r="14" '
                f'fill="transparent" stroke="none" />'
            )
            # Offset callout labels so 香港/澳门 do not overlap
            if rid == "hongkong":
                tx, ty = lx + 36.0, ly + 37.0
            else:
                tx, ty = lx - 36.0, ly + 38.0
            mx, my = (lx + tx) / 2, (ly + ty) / 2 + 6
            lines.append(
                f'      <path class="clm-label-leader" d="M{lx:.1f},{ly:.1f} Q{mx:.1f},{my:.1f} {tx:.1f},{ty - 8:.1f}" '
                f'fill="none" stroke="#7a6a4a" stroke-width="0.9" stroke-dasharray="2 2.5" opacity="0.75" pointer-events="none" />'
            )
            lines.append(
                f'      <circle class="clm-label-dot" cx="{lx:.1f}" cy="{ly:.1f}" r="1.8" fill="#c5a35a" opacity="0.9" pointer-events="none" />'
            )
            lines.append(
                f'      <text class="clm-label clm-label-callout" x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
                f'dominant-baseline="middle" font-size="11" fill="#3a4a40" pointer-events="none">{label}</text>'
            )
        else:
            lines.append(
                f'      <text class="clm-label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="middle" font-size="11" fill="#3a4a40" pointer-events="none">{label}</text>'
            )
        lines.append("    </g>")
    lines.append("  </g>")

    lines.append('  <g class="clm-overseas" data-layer="overseas">')
    for island in OVERSEAS_ISLANDS:
        rid = island["id"]
        label = island["name"]
        cx, cy, rx, ry = island["cx"], island["cy"], island["rx"], island["ry"]
        # Soft organic island (ellipse + slight wobble via path)
        lines.append(
            f'    <g class="clm-region" id="region-{rid}" data-region="{rid}" '
            f'data-filter="{island["filter"]}" tabindex="0" role="button" '
            f'aria-label="{label}文学">'
        )
        # Min 44x44 hit target
        hit_r = max(rx, ry, 22)
        lines.append(
            f'      <ellipse class="clm-hit" cx="{cx}" cy="{cy}" rx="{hit_r}" ry="{hit_r}" '
            f'fill="transparent" />'
        )
        lines.append(
            f'      <ellipse class="clm-shape" cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
            f'fill="{island["fill"]}" stroke="#f3efe6" stroke-width="1.1" />'
        )
        lines.append(
            f'      <text class="clm-label" x="{cx}" y="{cy + island["label_dy"]}" '
            f'text-anchor="middle" dominant-baseline="middle" font-size="10" '
            f'fill="#3a4a40" pointer-events="none">{label}</text>'
        )
        lines.append("    </g>")
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    if not RAW_GEOJSON.exists():
        print(f"Missing {RAW_GEOJSON}", file=sys.stderr)
        print("Download DataV 100000_full.json into that path, then re-run.", file=sys.stderr)
        return 1
    by_name = load_features(RAW_GEOJSON)
    print(f"Loaded {len(by_name)} province features")
    dissolved = dissolve_regions(by_name)
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
