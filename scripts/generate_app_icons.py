#!/usr/bin/env python3

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image


ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def square_icon(base_image: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted = base_image.copy()
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    offset_x = (size - fitted.width) // 2
    offset_y = (size - fitted.height) // 2
    canvas.paste(fitted, (offset_x, offset_y), fitted)
    return canvas


def build_icons(logo_path: Path, build_assets_dir: Path) -> None:
    build_assets_dir.mkdir(parents=True, exist_ok=True)
    iconset_dir = build_assets_dir / "KeepOrNah.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True)

    with Image.open(logo_path) as image:
        base = image.convert("RGBA")
        largest = square_icon(base, 1024)
        largest.save(build_assets_dir / "KeepOrNah.ico", format="ICO", sizes=ICO_SIZES)
        for filename, size in ICONSET_SIZES.items():
            square_icon(base, size).save(iconset_dir / filename, format="PNG")


def build_icns(build_assets_dir: Path) -> None:
    with Image.open(build_assets_dir / "KeepOrNah.iconset" / "icon_512x512@2x.png") as image:
        image.save(build_assets_dir / "KeepOrNah.icns")


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: generate_app_icons.py <logo.png> <build-assets-dir> [--icns]")

    logo_path = Path(sys.argv[1]).resolve()
    build_assets_dir = Path(sys.argv[2]).resolve()
    generate_icns = "--icns" in sys.argv[3:]

    if not logo_path.is_file():
        raise SystemExit(f"Logo file not found: {logo_path}")

    build_icons(logo_path, build_assets_dir)
    if generate_icns:
        build_icns(build_assets_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
