#!/usr/bin/env python3
"""Fetch self-hosted base-map data for the tour-map creator (Option B).

Two independent, internally-consistent stacks (never mix their coordinates):

World  — Natural Earth (public domain, WGS-84)
  countries 50m, admin-1 50m, populated places 10m (trimmed), lakes 50m

China  — DataV Aliyun areas_v3 (GCJ-02)
  country→province polygons + province→city polygons + a flat city index
  (city boundaries are lazy-loaded per province in the UI)

Usage:
  python3 scripts/fetch_tour_map_data.py                 # world + china
  python3 scripts/fetch_tour_map_data.py --world-only
  python3 scripts/fetch_tour_map_data.py --china-only
  python3 scripts/fetch_tour_map_data.py --with-districts  # + city→district (big)
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "data" / "tour-map"

NE_MIRRORS = [
    "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/{name}",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{name}",
]
DATAV = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json"

# name -> (filename, kept property keys)
WORLD = {
    "countries": ("ne_50m_admin_0_countries.geojson", (
        "ADMIN", "NAME", "NAME_ZH", "ISO_A3", "CONTINENT",
        "LABEL_X", "LABEL_Y", "LABELRANK", "MIN_ZOOM", "MAX_LABEL",
    )),
    "admin1": ("ne_50m_admin_1_states_provinces.geojson", ("name", "admin", "iso_a2", "postal")),
    "places": ("ne_10m_populated_places.geojson", (
        "NAME", "NAME_ZH", "POP_MAX", "LATITUDE", "LONGITUDE", "ADM0NAME", "ADM1NAME",
    )),
    "lakes": ("ne_50m_lakes.geojson", ("name",)),
}
MIN_POP = 5000  # drop tiny villages from the world city layer

# Natural Earth 10m admin-1 (shapefile) — comprehensive regions with Chinese names.
NE_ADMIN1_ZIP = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"

# Colloquial / alternate region names that are not first-class admin-1 features.
REGION_ALIASES = [
    {"name": "Canary Islands", "nameZh": "加纳利群岛", "admin": "Spain", "lat": 28.10, "lon": -15.40,
     "aliases": ["加纳利群岛", "加那利群岛", "Canary Islands", "Canarias", "Canary Is."]},
    {"name": "Balearic Islands", "nameZh": "巴利阿里群岛", "admin": "Spain", "lat": 39.62, "lon": 2.99,
     "aliases": ["巴利阿里群岛", "Balearic Islands", "Baleares"]},
]

# --- One-China normalization -------------------------------------------------
# Natural Earth is a foreign dataset: it gives Taiwan a non-PRC Chinese label
# and lists Taiwan / Hong Kong / Macao as separate "countries". We override the
# label to 台湾 and treat them (and China's islands) as parts of China.
NAME_ZH_OVERRIDES = {
    "Taiwan": "台湾",
    "China": "中国",
}
# These ISO_A3 are shown as parts of China, never as separate countries.
CHINA_PARTS_ISO = {"TWN", "HKG", "MAC"}
# Disputed entities China does NOT recognize as independent states are folded
# into their sovereign state (China's position). Taiwan / HK / Macao → China.
COUNTRY_NORMALIZE = {
    "taiwan": "China",
    "hong kong": "China", "hong kong s.a.r.": "China", "hong kong s.a.r": "China",
    "macao": "China", "macao s.a.r.": "China", "macao s.a.r": "China", "macau": "China",
    "spratly is.": "China", "spratly islands": "China",
    "paracel is.": "China", "paracel islands": "China",
    "kosovo": "Serbia",
    "northern cyprus": "Cyprus", "n. cyprus": "Cyprus",
    "somaliland": "Somalia",
    "western sahara": "Morocco", "w. sahara": "Morocco",
}
# NE region entries for these disputed admin-1 units are dropped (covered by CHINA_PLACES).
EXCLUDE_REGION_ADMINS = {"spratly is.", "paracel is."}
# Country labels not shown (China does not recognize them as separate states).
HIDDEN_COUNTRY_LABELS = {"Kosovo", "N. Cyprus", "Somaliland", "W. Sahara"}
EXCLUDE_COUNTRY_NAMES = {"Taiwan", "Hong Kong", "Macao", "Kosovo", "N. Cyprus", "Somaliland", "W. Sahara"}
# China's Taiwan / SARs and islands (searchable + markable as regions of China).
CHINA_PLACES = [
    {"name": "Taiwan", "nameZh": "台湾", "admin": "China", "lat": 23.70, "lon": 120.96,
     "aliases": ["台湾", "台灣", "台湾省", "台湾地区"]},
    {"name": "Hong Kong", "nameZh": "香港", "admin": "China", "lat": 22.32, "lon": 114.17,
     "aliases": ["香港", "香港特别行政区"]},
    {"name": "Macao", "nameZh": "澳门", "admin": "China", "lat": 22.20, "lon": 113.54,
     "aliases": ["澳门", "澳門", "澳门特别行政区"]},
    {"name": "Diaoyu Islands", "nameZh": "钓鱼岛", "admin": "China", "lat": 25.74, "lon": 123.48,
     "aliases": ["钓鱼岛", "釣魚島", "钓鱼岛及其附属岛屿", "Diaoyu Islands"]},
    {"name": "Chiwei Islet", "nameZh": "赤尾屿", "admin": "China", "lat": 25.92, "lon": 124.55,
     "aliases": ["赤尾屿", "赤尾嶼"]},
    {"name": "Dongsha Islands", "nameZh": "东沙群岛", "admin": "China", "lat": 20.70, "lon": 116.72,
     "aliases": ["东沙群岛", "東沙群島"]},
    {"name": "Xisha Islands", "nameZh": "西沙群岛", "admin": "China", "lat": 16.50, "lon": 112.00,
     "aliases": ["西沙群岛", "西沙群島"]},
    {"name": "Zhongsha Islands", "nameZh": "中沙群岛", "admin": "China", "lat": 15.50, "lon": 114.00,
     "aliases": ["中沙群岛", "中沙群島"]},
    {"name": "Nansha Islands", "nameZh": "南沙群岛", "admin": "China", "lat": 10.00, "lon": 114.00,
     "aliases": ["南沙群岛", "南沙群島"]},
]


def _normalize_country(name: str) -> str:
    return COUNTRY_NORMALIZE.get((name or "").strip().lower(), name or "")


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "folio-tour-map/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download(name: str, filename: str) -> bytes:
    last = None
    for tpl in NE_MIRRORS:
        url = tpl.format(name=filename)
        try:
            return http_get(url)
        except Exception as exc:  # try next mirror
            last = exc
            print(f"    mirror failed: {url} ({exc})", file=sys.stderr)
    raise RuntimeError(f"all mirrors failed for {filename}: {last}")


def write_json(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def fetch_world() -> None:
    dest = OUT / "world"
    print("== World (Natural Earth, WGS-84) ==")
    for key, (filename, keep) in WORLD.items():
        raw = download(key, filename)
        data = json.loads(raw)
        feats = data.get("features", [])
        kept = []
        for ft in feats:
            props = ft.get("properties") or {}
            if key == "places":
                pop = props.get("POP_MAX") or 0
                try:
                    pop = int(pop)
                except (TypeError, ValueError):
                    pop = 0
                if pop < MIN_POP:
                    continue
            slim = {k: props.get(k) for k in keep if props.get(k) is not None}
            if key == "countries":
                override = NAME_ZH_OVERRIDES.get(slim.get("NAME"))
                if override:
                    slim["NAME_ZH"] = override
                if slim.get("NAME") in HIDDEN_COUNTRY_LABELS:
                    slim["LABEL_HIDDEN"] = True
            elif key == "places":
                slim["ADM0NAME"] = _normalize_country(slim.get("ADM0NAME"))
            kept.append({"type": "Feature", "properties": slim, "geometry": ft.get("geometry")})
        out = {"type": "FeatureCollection", "features": kept}
        size = write_json(dest / f"{key}.geojson", out)
        print(f"  {key:10} features={len(kept):6} -> {size/1024/1024:.2f} MB")

    build_country_index(dest)
    build_region_index(dest)
    write_json(dest / "region-aliases.json", REGION_ALIASES)
    write_json(dest / "china-places.json", CHINA_PLACES)
    print(f"  region aliases: {len(REGION_ALIASES)} | china places: {len(CHINA_PLACES)}")


def build_country_index(dest: Path) -> None:
    data = json.loads((dest / "countries.geojson").read_text(encoding="utf-8"))
    idx = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        if p.get("LABEL_X") is None or p.get("LABEL_Y") is None:
            continue
        if p.get("ISO_A3") in CHINA_PARTS_ISO:
            continue  # Taiwan / HK / Macao are parts of China, not countries
        name = p.get("NAME") or ""
        if name in EXCLUDE_COUNTRY_NAMES:
            continue  # disputed entities China does not recognize as states
        idx.append({
            "name": name, "nameZh": NAME_ZH_OVERRIDES.get(name, p.get("NAME_ZH") or ""),
            "lat": p.get("LABEL_Y"), "lon": p.get("LABEL_X"),
            "continent": p.get("CONTINENT") or "", "iso": p.get("ISO_A3") or "",
        })
    size = write_json(dest / "country-index.json", idx)
    print(f"  country-index entries={len(idx)} -> {size/1024:.0f} KB")


def build_region_index(dest: Path) -> None:
    try:
        import shapefile  # pyshp
    except ImportError:
        raise SystemExit("Install pyshp first: python3 -m pip install pyshp") from None
    print("  downloading ne_10m_admin_1_states_provinces.zip …")
    raw = http_get(NE_ADMIN1_ZIP, timeout=300)
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            z.extractall(td)
        reader = shapefile.Reader(str(Path(td) / "ne_10m_admin_1_states_provinces.shp"))
        idx = []
        for rec in reader.iterShapeRecords():
            p = rec.record.as_dict()
            lat, lon = p.get("latitude"), p.get("longitude")
            if lat is None or lon is None:
                continue
            if str(p.get("admin") or "").strip().lower() in EXCLUDE_REGION_ADMINS:
                continue
            idx.append({
                "name": p.get("name") or "", "nameZh": p.get("name_zh") or "",
                "nameEn": p.get("name_en") or "", "admin": _normalize_country(p.get("admin")),
                "iso": p.get("iso_a2") or "", "type": p.get("type_en") or "",
                "lat": lat, "lon": lon,
            })
    size = write_json(dest / "region-index.json", idx)
    print(f"  region-index entries={len(idx)} -> {size/1024:.0f} KB")


def datav(adcode: int) -> dict:
    url = DATAV.format(adcode=adcode)
    return json.loads(http_get(url, timeout=60))


def fetch_china(with_districts: bool = False) -> None:
    dest = OUT / "china"
    print("== China (DataV, GCJ-02) ==")
    country = datav(100000)
    provinces = country.get("features", [])
    write_json(dest / "provinces.geojson", country)
    print(f"  provinces  features={len(provinces)}")

    city_index = []
    cities_dir = dest / "cities"
    for i, prov in enumerate(provinces, 1):
        p = prov.get("properties") or {}
        adcode = p.get("adcode")
        if not adcode:
            continue
        try:
            province_full = datav(int(adcode))
        except Exception as exc:
            print(f"  WARN province {p.get('name')} ({adcode}) failed: {exc}", file=sys.stderr)
            continue
        feats = province_full.get("features", [])
        # Keep only city-level features (or all if already districts)
        slim_feats = []
        for ft in feats:
            cp = ft.get("properties") or {}
            slim_feats.append({
                "type": "Feature",
                "properties": {
                    "adcode": cp.get("adcode"),
                    "name": cp.get("name"),
                    "level": cp.get("level"),
                    "center": cp.get("center"),
                    "centroid": cp.get("centroid"),
                    "parent": cp.get("parent") or adcode,
                },
                "geometry": ft.get("geometry"),
            })
            city_index.append({
                "name": cp.get("name"),
                "adcode": cp.get("adcode"),
                "level": cp.get("level"),
                "province": p.get("name"),
                "provinceAdcode": adcode,
                "center": cp.get("center") or cp.get("centroid"),
            })
        write_json(cities_dir / f"{adcode}.geojson",
                   {"type": "FeatureCollection", "features": slim_feats})
        print(f"  [{i:02}/{len(provinces)}] {p.get('name'):8} {len(slim_feats):4} cities")
        time.sleep(0.15)

    idx_size = write_json(dest / "city-index.json", city_index)
    print(f"  city index  entries={len(city_index)} -> {idx_size/1024:.0f} KB")

    if with_districts:
        print("  -- districts (opt-in) --")
        districts_dir = dest / "districts"
        for city in city_index:
            if city.get("level") != "city" or not city.get("adcode"):
                continue
            try:
                full = datav(int(city["adcode"]))
            except Exception:
                continue
            feats = full.get("features", [])
            if not feats:
                continue
            write_json(districts_dir / f"{city['adcode']}.geojson", full)
            time.sleep(0.12)
        print("  districts done")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch tour-map base data (Option B)")
    ap.add_argument("--world-only", action="store_true")
    ap.add_argument("--china-only", action="store_true")
    ap.add_argument("--with-districts", action="store_true")
    args = ap.parse_args()

    if not args.china_only:
        fetch_world()
    if not args.world_only:
        fetch_china(with_districts=args.with_districts)
    print(f"\nDone. Output: {OUT}")
    print("Note: world=WGS-84, china=GCJ-02 — keep each stack on its own map, never mix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
