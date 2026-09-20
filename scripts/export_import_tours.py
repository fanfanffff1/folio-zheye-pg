#!/usr/bin/env python3
"""Copy local (SQLite) map-pilgrimage data into the target database (DATABASE_URL).

Imported collections / stops / places are all assigned to the `fan` admin account.
Books and authors are matched by slug / name (ids may differ between databases).

Usage:
    DATABASE_URL="<neon-url>" python3 scripts/export_import_tours.py --dry-run
    DATABASE_URL="<neon-url>" python3 scripts/export_import_tours.py

Notes:
- Idempotent: an existing collection slug / place key is reused, not duplicated.
- Copies: collections, categories, stops, places, place-book links.
- Does NOT copy: user notes, revisions, media temp rows, likes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from folio.config import database_url  # noqa: E402
from folio.models import (  # noqa: E402
    Author, Book, SessionLocal, TourMap, TourPlace, TourPlaceBook, TourStop,
    TourStopCategory, User, init_db,
)

LOCAL_DB = ROOT / "data" / "folio.db"


def _as_dict(obj, fields):
    return {f: getattr(obj, f) for f in fields if hasattr(obj, f)}


MAP_FIELDS = ["slug", "title", "author_name", "subtitle", "description", "scope", "kind",
              "base_style", "center_lat", "center_lon", "zoom", "visibility", "status",
              "cover_url", "tags", "view_count", "like_count", "stop_count", "published_at"]
CAT_FIELDS = ["label", "color", "kind", "order_index"]
STOP_FIELDS = ["lat", "lon", "level", "place_name", "country", "admin1", "city", "note",
               "period", "order_index", "media_url", "photos"]
PLACE_FIELDS = ["key", "name", "name_en", "level", "lat", "lon", "country", "admin1",
                "footnote", "photos", "view_count", "like_count", "status", "city_key",
                "address", "source_url", "reject_reason", "auto_approved"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--owner", default="fan")
    ap.add_argument("--places-only", action="store_true",
                    help="only import places (+ place-book links), skip collections/stops")
    args = ap.parse_args()

    target_url = database_url()
    if target_url.startswith("sqlite") and "data/folio.db" in target_url:
        raise SystemExit(
            "DATABASE_URL 现在指向本地 SQLite。请设为生产库，例如：\n"
            "  DATABASE_URL=\"postgresql://...\" python3 scripts/export_import_tours.py"
        )

    local_engine = create_engine("sqlite:///" + str(LOCAL_DB))
    Local = sessionmaker(bind=local_engine)
    src = Local()
    dst = SessionLocal()  # bound to DATABASE_URL (target)

    try:
        init_db()  # make sure the target has all tables
        owner = dst.query(User).filter(User.username == args.owner).one_or_none()
        if not owner:
            raise SystemExit(f"目标库没有用户 {args.owner}（管理员），请先注册/创建该账号。")
        print(f"target owner: {owner.username} (id={owner.id})")

        # ---- id maps: books by slug, authors by name ----
        book_map: dict[int, int] = {}
        dst_books = {b.slug: b.id for b in dst.query(Book).all()}
        missing_books = 0
        for b in src.query(Book).all():
            tid = dst_books.get(b.slug)
            if tid:
                book_map[b.id] = tid
            else:
                missing_books += 1
        author_map: dict[int, int] = {}
        dst_authors = {a.name: a.id for a in dst.query(Author).all()}
        missing_authors = 0
        for a in src.query(Author).all():
            tid = dst_authors.get(a.name)
            if tid:
                author_map[a.id] = tid
            else:
                missing_authors += 1
        print(f"book map: {len(book_map)} (missing {missing_books}) | "
              f"author map: {len(author_map)} (missing {missing_authors})")

        # ---- places ----
        place_map: dict[int, int] = {}
        new_places = 0
        for p in src.query(TourPlace).all():
            tgt = dst.query(TourPlace).filter(TourPlace.key == p.key).one_or_none()
            if tgt:
                place_map[p.id] = tgt.id
                continue
            new_places += 1
            if args.dry_run:
                place_map[p.id] = -1
                continue
            row = TourPlace(created_by=owner.id, **_as_dict(p, PLACE_FIELDS))
            dst.add(row)
            dst.flush()
            place_map[p.id] = row.id
        print(f"places: {new_places} new / {len(place_map)} total")

        # ---- place -> book links ----
        new_pb = 0
        for pb in src.query(TourPlaceBook).all():
            tpid = place_map.get(pb.place_id)
            tbid = book_map.get(pb.book_id)
            if not tpid or tpid < 0 or not tbid:
                continue
            if dst.query(TourPlaceBook).filter(
                TourPlaceBook.place_id == tpid, TourPlaceBook.book_id == tbid
            ).first():
                continue
            new_pb += 1
            if not args.dry_run:
                dst.add(TourPlaceBook(place_id=tpid, book_id=tbid, note=pb.note or ""))
        print(f"place-book links: {new_pb} new")

        if args.places_only:
            if args.dry_run:
                dst.rollback(); print("dry-run: nothing written.")
            else:
                dst.commit(); print("done: places imported (collections skipped).")
            return

        # ---- collections + categories + stops ----
        new_maps = new_stops = new_cats = 0
        for m in src.query(TourMap).all():
            exists = dst.query(TourMap).filter(TourMap.slug == m.slug).one_or_none()
            if exists:
                continue
            new_maps += 1
            if args.dry_run:
                continue
            row = TourMap(owner_user_id=owner.id, **_as_dict(m, MAP_FIELDS))
            if row.ref_id:
                row.ref_id = book_map.get(row.ref_id) or author_map.get(row.ref_id) or None
            dst.add(row)
            dst.flush()
            cat_map: dict[int, int] = {}
            for c in src.query(TourStopCategory).filter(TourStopCategory.map_id == m.id).all():
                new_cats += 1
                nc = TourStopCategory(map_id=row.id, **_as_dict(c, CAT_FIELDS))
                dst.add(nc)
                dst.flush()
                cat_map[c.id] = nc.id
            for s in src.query(TourStop).filter(TourStop.map_id == m.id).all():
                new_stops += 1
                ns = TourStop(
                    map_id=row.id, user_id=owner.id,
                    place_id=place_map.get(s.place_id),
                    author_id=author_map.get(s.author_id),
                    category_id=cat_map.get(s.category_id),
                    **_as_dict(s, STOP_FIELDS),
                )
                # map book ids (legacy single + list)
                if s.book_id:
                    ns.book_id = book_map.get(s.book_id)
                ids = []
                try:
                    import json as _json
                    for bid in (_json.loads(s.book_ids) if s.book_ids else []):
                        if book_map.get(bid):
                            ids.append(book_map[bid])
                except Exception:
                    pass
                if ns.book_id and ns.book_id not in ids:
                    ids.insert(0, ns.book_id)
                ns.book_id = ids[0] if ids else None
                import json as _json
                ns.book_ids = _json.dumps(ids, ensure_ascii=False)
                dst.add(ns)
        print(f"collections: {new_maps} new | categories: {new_cats} new | stops: {new_stops} new")

        if args.dry_run:
            dst.rollback()
            print("dry-run: nothing written.")
        else:
            dst.commit()
            print("done: imported to target.")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
