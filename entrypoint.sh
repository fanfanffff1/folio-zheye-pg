#!/bin/sh
set -e
DATA_DIR="${FOLIO_DATA_DIR:-/app/data}"
CATALOG_DIR="${FOLIO_CATALOG_DIR:-/app/catalog}"
mkdir -p "$DATA_DIR/uploads/avatars" "$DATA_DIR/uploads/submissions"
# 书目随发布更新；用户写在 DATABASE_URL 指向的 Postgres，部署不会清空账号。
# 库里已有书时 seed 会走轻量模式（不重导 600+ 本），冷启动更快。
# 需要强制全量重导时设 FOLIO_FORCE_SEED=1。
if [ -f "$CATALOG_DIR/cleaned-books.json" ] || [ -f /app/data/cleaned-books.json ]; then
  python3 -m folio.seed
fi
exec python3 run.py
