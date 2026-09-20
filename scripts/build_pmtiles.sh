#!/usr/bin/env bash
# Build a Protomaps basemap PMTiles for a named area and upload it to R2.
#
# The frontend already prefers a self-hosted PMTiles file when MAP_PMTILES_URL
# is set (single file + HTTP Range + edge cache => fast & stable, no per-tile
# requests to a foreign tile server). This produces a file in the Protomaps
# basemap schema, which is what the site renders (flavor: "light", pale).
#
# Requirements: Java 21+ and Maven  ->  brew install openjdk maven
#
# Usage:
#   ./scripts/build_pmtiles.sh                       # china, maxzoom 14
#   AREA=monaco MAXZOOM=14 ./scripts/build_pmtiles.sh   # tiny smoke test
#   AREA=china MAXZOOM=15 ./scripts/build_pmtiles.sh
#
# After it finishes, set on the server (Render env):
#   MAP_PMTILES_URL = https://<your-cdn>/tour-map/<area>.pmtiles
set -euo pipefail

AREA="${AREA:-china}"
MAXZOOM="${MAXZOOM:-14}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$(cd "$ROOT/.." && pwd)/folio-map-data}"   # Desktop/inspiration/folio-map-data (outside the repo)
KEY="tour-map/${AREA}.pmtiles"
OUT="$WORK/${AREA}.pmtiles"

command -v java >/dev/null 2>&1 || { echo "!! need Java 21+  ->  brew install openjdk"; exit 1; }
command -v mvn  >/dev/null 2>&1 || { echo "!! need Maven     ->  brew install maven"; exit 1; }
command -v git  >/dev/null 2>&1 || { echo "!! need git"; exit 1; }

mkdir -p "$WORK"
echo ">> work dir: $WORK  (kept outside the repo; delete it to reclaim space)"
if [ ! -d "$WORK/basemaps" ]; then
  echo ">> cloning protomaps/basemaps ..."
  git clone --depth 1 https://github.com/protomaps/basemaps.git "$WORK/basemaps"
fi

cd "$WORK/basemaps/tiles"
echo ">> building planetiler jar (first run downloads deps) ..."
mvn -q clean package
JAR="$(ls target/*-with-deps.jar 2>/dev/null | head -1)"
[ -n "$JAR" ] || { echo "!! build failed"; exit 1; }

echo ">> generating $AREA.pmtiles (maxzoom $MAXZOOM) — this can take a while ..."
java -Xmx4g -jar "$JAR" --download --force --area="$AREA" --maxzoom="$MAXZOOM" --output="$OUT"
ls -lh "$OUT"

echo ">> uploading to R2 as $KEY ..."
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
