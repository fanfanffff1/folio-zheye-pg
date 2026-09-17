#!/bin/sh
set -e
DATA_DIR="${FOLIO_DATA_DIR:-/app/data}"
CATALOG_DIR="${FOLIO_CATALOG_DIR:-/app/catalog}"
mkdir -p "$DATA_DIR/uploads/avatars" "$DATA_DIR/uploads/submissions"
# 书目随发布更新；用户写在 DATABASE_URL 指向的 Postgres，部署不会清空账号。
if [ -f "$CATALOG_DIR/cleaned-books.json" ] || [ -f /app/data/cleaned-books.json ]; then
  python3 -m folio.seed
fi
exec python3 run.py
