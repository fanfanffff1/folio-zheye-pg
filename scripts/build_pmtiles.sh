#!/usr/bin/env bash
#
# Build a self-hosted PMTiles basemap (Protomaps schema) for the regions that
# actually have collections, then upload it to R2. The frontend renders it with
# protomaps-leaflet (already vendored) when MAP_PMTILES_URL is set.
#
# Requires one of:
#   - planetiler (Java 17+)  : https://github.com/onthegomap/planetiler
#   - a prebuilt Protomaps basemap download
#
# Tip: only tile the regions you need (China / Europe / specific countries)
# instead of the whole planet, to keep the file small and generation fast.
#
set -euo pipefail

# ---- config -----------------------------------------------------------------
AREA="${AREA:-china}"                 # planetiler --area (e.g. china, japan, ...)
OUT="${OUT:-build/pmtiles/$AREA.pmtiles}"
PLANETILER_JAR="${PLANETILER_JAR:-build/planetiler.jar}"
KEY="${KEY:-tour-map/$AREA.pmtiles}"  # R2 object key

mkdir -p "$(dirname "$OUT")" build

# ---- 1) get planetiler ------------------------------------------------------
if [ ! -f "$PLANETILER_JAR" ]; then
  echo "Downloading planetiler.jar ..."
  curl -fL -o "$PLANETILER_JAR" \
    https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar
fi

# ---- 2) build PMTiles (Protomaps basemap profile) ---------------------------
# Planetiler downloads the OSM extract for --area automatically.
# For a custom/partial area, replace --area with --osm-path=<region.osm.pbf>.
echo "Building $OUT for area=$AREA ..."
java -Xmx8g -jar "$PLANETILER_JAR" \
  --osm-path="${OSM_PBF:-}" \
  --area="$AREA" \
  --output="$OUT" \
  --force

# Alternative (no Java): download a prebuilt Protomaps basemap and skip to step 3:
#   curl -fL -o "$OUT" "https://build.protomaps.com/<YYYYMMDD>.pmtiles"

# ---- 3) upload to R2 --------------------------------------------------------
echo "Uploading $OUT -> $KEY ..."
python3 scripts/upload_r2.py "$OUT" "$KEY"

echo
echo "Done. Set these on Render:"
echo "  MAP_PMTILES_URL=https://<your-cdn-domain>/$KEY"
echo "  MAP_CDN_BASE=https://<your-cdn-domain>"
