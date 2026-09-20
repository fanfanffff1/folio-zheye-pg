#!/usr/bin/env python3
"""Generate list/detail WebP + AVIF variants from static/covers/*.jpg|png.

Outputs (next to source):
  {stem}-240.webp|.avif  — mobile list (~240×360)
  {stem}-320.webp|.avif  — list thumbnail (~320×480)
  {stem}-600.webp|.avif  — detail cover (~600×900)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COVER_DIR = ROOT / "static" / "covers"
SRC_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SKIP_SUFFIXES = ("-240", "-320", "-600")
WIDTHS = (240, 320, 600)
SPECS = {
    240: (240, 360, 72, 45),
    320: (320, 480, 78, 50),
    600: (600, 900, 82, 55),
}

sys.path.insert(0, str(ROOT / "scripts"))
from trim_cover_borders import trim_dark_borders  # noqa: E402


def is_source(path: Path) -> bool:
    if path.suffix.lower() not in SRC_EXT:
        return False
    return not any(path.stem.endswith(s) for s in SKIP_SUFFIXES)


def resize_cover(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    im = im.convert("RGB")
    w, h = im.size
    scale = min(max_w / w, max_h / h, 1.0)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    return im


def needs_write(path: Path, src_mtime: float, force: bool) -> bool:
    return force or not path.exists() or path.stat().st_mtime < src_mtime


def process_one(src: Path, force: bool) -> dict:
    stem = src.stem
    result = {"src": src.name, "wrote": False}
    src_mtime = src.stat().st_mtime
    targets: list[tuple[Path, int, str, int]] = []
    for width, (mw, mh, webp_q, avif_q) in SPECS.items():
        webp = COVER_DIR / f"{stem}-{width}.webp"
        avif = COVER_DIR / f"{stem}-{width}.avif"
        if needs_write(webp, src_mtime, force):
            targets.append((webp, width, "WEBP", webp_q))
        if needs_write(avif, src_mtime, force):
            targets.append((avif, width, "AVIF", avif_q))
    if not targets:
        return result

    with Image.open(src) as im:
        rgb, _box = trim_dark_borders(im)
        rgb = rgb.convert("RGB")
        resized: dict[int, Image.Image] = {}
        for path, width, fmt, quality in targets:
            mw, mh, _, _ = SPECS[width]
            if width not in resized:
                resized[width] = resize_cover(rgb, mw, mh)
            resized[width].save(path, format=fmt, quality=quality, method=6 if fmt == "WEBP" else 4)
            result["wrote"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize FOLIO book covers to WebP+AVIF")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Cover directory (default: static/covers; use folio-covers-offline/covers-en for EN expansion)",
    )
    args = parser.parse_args()
    global COVER_DIR
    if args.dir is not None:
        COVER_DIR = args.dir.expanduser().resolve()

    sources = sorted(p for p in COVER_DIR.iterdir() if p.is_file() and is_source(p))
    if args.limit:
        sources = sources[: args.limit]
    if not sources:
        print("No source covers found.", file=sys.stderr)
        return 1

    wrote = skipped = 0
    for src in sources:
        try:
            info = process_one(src, force=args.force)
        except Exception as exc:
            print(f"FAIL {src.name}: {exc}", file=sys.stderr)
            continue
        if info["wrote"]:
            wrote += 1
            print(f"OK {src.name}")
        else:
            skipped += 1

    def avg(glob: str) -> int:
        xs = [p.stat().st_size for p in COVER_DIR.glob(glob)]
        return int(sum(xs) / len(xs)) if xs else 0

    print(
        f"done sources={len(sources)} wrote={wrote} skipped={skipped} "
        f"avg240.webp={avg('*-240.webp')}B avg240.avif={avg('*-240.avif')}B "
        f"avg320.webp={avg('*-320.webp')}B avg320.avif={avg('*-320.avif')}B"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
