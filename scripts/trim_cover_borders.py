#!/usr/bin/env python3
"""Trim near-black letterbox borders from book covers, then rebuild WebP variants.

Edits source JPG/PNG in static/covers (and optional covers/), then regenerates
*-240/320/600 .webp|.avif so list and detail images stay in sync.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COVER_DIR = ROOT / "static" / "covers"
PROVIDED_DIR = ROOT / "covers"
SRC_EXT = {".jpg", ".jpeg", ".png"}
SKIP_SUFFIXES = ("-240", "-320", "-600")


def is_source(path: Path) -> bool:
    if path.suffix.lower() not in SRC_EXT:
        return False
    return not any(path.stem.endswith(s) for s in SKIP_SUFFIXES)


def trim_dark_borders(
    im: Image.Image,
    *,
    luma_max: int = 48,
    tol: int = 14,
    dark_ratio: float = 0.96,
    max_frac: float = 0.42,
    min_trim: int = 4,
    min_area_ratio: float = 0.35,
) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    """Crop uniform near-black frames from the image edges."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    frame = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    if max(frame) > luma_max:
        return rgb, None

    def is_frame(c: tuple[int, int, int]) -> bool:
        return all(abs(c[i] - frame[i]) <= tol for i in range(3)) and max(c) <= luma_max + 8

    def row_border(y: int) -> bool:
        step = max(1, w // 500)
        vals = [px[x, y] for x in range(0, w, step)]
        return sum(1 for c in vals if is_frame(c)) / len(vals) >= dark_ratio

    def col_border(x: int) -> bool:
        step = max(1, h // 500)
        vals = [px[x, y] for y in range(0, h, step)]
        return sum(1 for c in vals if is_frame(c)) / len(vals) >= dark_ratio

    top = 0
    while top < int(h * max_frac) and row_border(top):
        top += 1
    bottom = h - 1
    while bottom > top and (h - 1 - bottom) < int(h * max_frac) and row_border(bottom):
        bottom -= 1
    left = 0
    while left < int(w * max_frac) and col_border(left):
        left += 1
    right = w - 1
    while right > left and (w - 1 - right) < int(w * max_frac) and col_border(right):
        right -= 1

    if top + (h - 1 - bottom) < min_trim and left + (w - 1 - right) < min_trim:
        return rgb, None

    box = (left, top, right + 1, bottom + 1)
    cropped = rgb.crop(box)
    if cropped.size[0] * cropped.size[1] < min_area_ratio * w * h:
        return rgb, None
    return cropped, box


def resize_cover(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    im = im.convert("RGB")
    w, h = im.size
    scale = min(max_w / w, max_h / h, 1.0)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    return im


def save_jpeg(im: Image.Image, path: Path) -> None:
    im.convert("RGB").save(path, format="JPEG", quality=90, optimize=True)


def process_source(path: Path, dry_run: bool) -> tuple[str, tuple[int, int, int, int] | None]:
    with Image.open(path) as im:
        cropped, box = trim_dark_borders(im)
        rgb = cropped.convert("RGB")
        if box and not dry_run:
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                save_jpeg(rgb, path)
            else:
                rgb.save(path)
        # always refresh webp from (possibly trimmed) pixels
        if not dry_run:
            stem = path.stem
            for width, (mw, mh, webp_q, avif_q) in (
                (240, (240, 360, 72, 45)),
                (320, (320, 480, 78, 50)),
                (600, (600, 900, 82, 55)),
            ):
                sized = resize_cover(rgb, mw, mh)
                sized.save(
                    COVER_DIR / f"{stem}-{width}.webp",
                    format="WEBP",
                    quality=webp_q,
                    method=6,
                )
                sized.save(
                    COVER_DIR / f"{stem}-{width}.avif",
                    format="AVIF",
                    quality=avif_q,
                )
    return ("trim" if box else "keep"), box


def iter_sources(extra_dirs: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for directory in [COVER_DIR, *extra_dirs]:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or not is_source(path):
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim black cover borders and rebuild WebP")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--also-provided",
        action="store_true",
        help=f"Also trim originals in {PROVIDED_DIR}",
    )
    args = parser.parse_args()

    extras = [PROVIDED_DIR] if args.also_provided else []
    sources = iter_sources(extras)
    # Prefer static/covers path when same name exists in both
    sources = [p for p in sources if p.parent == COVER_DIR] + [
        p for p in sources if p.parent != COVER_DIR
    ]
    # Deduplicate by name preferring COVER_DIR
    by_name: dict[str, Path] = {}
    for p in sources:
        by_name.setdefault(p.name, p)
        if p.parent == COVER_DIR:
            by_name[p.name] = p
    sources = sorted(by_name.values(), key=lambda p: p.name)
    if args.also_provided:
        # process provided copies that share names after static, for disk sync
        provided = [p for p in PROVIDED_DIR.iterdir() if p.is_file() and is_source(p)] if PROVIDED_DIR.is_dir() else []
    else:
        provided = []

    if args.limit:
        sources = sources[: args.limit]

    trimmed = kept = 0
    for path in sources:
        try:
            action, box = process_source(path, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            continue
        if action == "trim":
            trimmed += 1
            print(f"TRIM {path.name} {box}")
        else:
            kept += 1

    # Mirror trim onto provided/ covers with same filenames (seed copy source)
    for path in provided:
        static_twin = COVER_DIR / path.name
        if not static_twin.exists():
            continue
        try:
            with Image.open(static_twin) as im:
                if not args.dry_run:
                    save_jpeg(im.convert("RGB"), path) if path.suffix.lower() in {".jpg", ".jpeg"} else im.save(path)
        except Exception as exc:
            print(f"FAIL mirror {path.name}: {exc}", file=sys.stderr)

    print(f"done sources={len(sources)} trimmed={trimmed} kept={kept} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
