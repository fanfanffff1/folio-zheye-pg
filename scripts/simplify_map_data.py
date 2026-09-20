#!/usr/bin/env python3
"""Shrink the big map GeoJSON with a topology-preserving simplification pass.

The world basemap (countries / admin1 / lakes) and china/provinces ship a lot of
coordinate detail that is invisible at the zooms we use (z2-9). This applies a
Douglas-Peucker simplify + a coordinate grid snap, in place.

Revert anytime with:  git checkout static/data/tour-map

Usage:
    python3 scripts/simplify_map_data.py --dry-run
    python3 scripts/simplify_map_data.py --tol 0.02 --decimals 3
    python3 scripts/simplify_map_data.py --tol 0.05 --decimals 2   # aggressive
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import shapely
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "static" / "data" / "tour-map"
TARGETS = [
    "world/countries.geojson",
    "world/admin1.geojson",
    "world/lakes.geojson",
    "china/provinces.geojson",
]


def grid_for(decimals: int) -> float:
    return 10 ** (-decimals)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=0.02, help="simplify tolerance in degrees (default 0.02)")
    ap.add_argument("--decimals", type=int, default=3, help="coordinate decimals to keep (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    grid = grid_for(args.decimals)
    for rel in TARGETS:
        path = BASE / rel
        if not path.is_file():
            print("skip (missing)", rel)
            continue
        raw = path.read_bytes()
        data = json.loads(raw)
        features = data.get("features") or []
        out = []
        for f in features:
            geom = f.get("geometry")
            if not geom:
                out.append(f)
                continue
            try:
                g = shape(geom).simplify(args.tol, preserve_topology=True)
                g = shapely.set_precision(g, grid)
                if g.is_empty:
                    g = shape(geom)
            except Exception:
                g = shape(geom)
            nf = dict(f)
            nf["geometry"] = mapping(g)
            out.append(nf)
        data["features"] = out
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        pct = (1 - len(blob) / max(1, len(raw))) * 100
        print(f"{rel}: {len(raw)/1e6:.2f}MB -> {len(blob)/1e6:.2f}MB  (-{pct:.0f}%)  {len(features)} features")
        if not args.dry_run:
            path.write_bytes(blob)


if __name__ == "__main__":
    main()
