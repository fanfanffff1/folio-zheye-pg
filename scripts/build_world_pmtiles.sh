#!/usr/bin/env bash
# Download a GLOBAL Protomaps basemap PMTiles and upload it to R2.
#
# It takes a cutout of the official daily planet build with `pmtiles extract`,
# which only fetches the z0..MAXZOOM sub-pyramid (no need to download the whole
# 138GB planet first). Vector tiles are already gzip-compressed inside the
# archive, so nothing else needs compressing.
#
# Storage (approx, the whole planet at z15 is ~138GB; each extra zoom ~doubles):
#   MAXZOOM=12 ~17GB   MAXZOOM=13 ~35GB   MAXZOOM=14 ~69GB   MAXZOOM=15 ~138GB
#
# After it finishes, set on the server (Render env):
#   MAP_PMTILES_URL = <printed url>
#
# Usage:
#   MAXZOOM=14 ./scripts/build_world_pmtiles.sh     # ~69GB, recommended
#   MAXZOOM=15 ./scripts/build_world_pmtiles.sh     # full detail, ~138GB
set -euo pipefail

MAXZOOM="${MAXZOOM:-14}"
THREADS="${THREADS:-8}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$(cd "$ROOT/.." && pwd)/folio-map-data}"   # Desktop/inspiration/folio-map-data (outside the repo)
OUT="$WORK/world.pmtiles"
KEY="tour-map/world.pmtiles"

command -v pmtiles >/dev/null 2>&1 || { echo ">> installing pmtiles CLI ..."; brew install pmtiles; }
command -v curl    >/dev/null 2>&1 || { echo "!! need curl"; exit 1; }

mkdir -p "$WORK"
echo ">> work dir: $WORK  (kept outside the repo; delete it to reclaim space)"

SRC="${SRC:-}"
if [ -n "$SRC" ]; then
  echo ">> using build from SRC: $SRC"
else
  echo ">> finding the latest Protomaps planet build ..."
  for i in $(seq 0 14); do
    if d="$(date -u -v-"${i}"d +%Y%m%d 2>/dev/null)"; then :; else d="$(date -u -d "-${i} days" +%Y%m%d)"; fi
    url="https://build.protomaps.com/${d}.pmtiles"
    if curl -sfI --max-time 25 "$url" >/dev/null 2>&1; then SRC="$url"; break; fi
  done
fi
if [ -z "$SRC" ]; then
  echo "!! could not find a recent planet build."
  echo "   This is usually a network/proxy problem — check with:"
  echo "     curl -sSI https://build.protomaps.com/20260919.pmtiles | head -1"
  echo "   then either fix the proxy, or pass a known build directly:"
  echo "     SRC=https://build.protomaps.com/20260919.pmtiles MAXZOOM=15 $0"
  exit 1
fi
echo "   $SRC"

if [ -f "$OUT" ]; then
  echo ">> $OUT already exists, skipping download (delete it to re-download)"
else
  echo ">> extracting world (z0-$MAXZOOM) -> $OUT"
  echo "   this downloads only the needed tile ranges; can take a long time"
  # write to a .part file so an interrupted run is not mistaken for a good archive
  rm -f "$OUT.part"
  pmtiles extract "$SRC" "$OUT.part" --maxzoom="$MAXZOOM" --download-threads="$THREADS"
  mv "$OUT.part" "$OUT"
fi
pmtiles verify "$OUT"
ls -lh "$OUT"

echo ">> uploading to R2 as $KEY (streamed) ..."
cd "$ROOT"
python3 scripts/upload_r2.py "$OUT" "$KEY"

echo
echo "done. Set this on the server:"
python3 - <<PY
from folio.object_store import public_object_url
try:
    print("  MAP_PMTILES_URL=" + public_object_url("$KEY"))
except Exception as e:
    print("  MAP_PMTILES_URL=<your-cdn>/$KEY  (", e, ")")
PY
