#!/usr/bin/env python3
"""Ikona Imprezja Playlist Pro ze znaku na logo-stacked-dark.png.

Źródło ma 196×243 i napis pod spodem. Na ikonę idzie sam złoty znak,
na płaskim tle jak w logo. Powstają PNG, ICNS (Mac) i ICO (Windows).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "editor" / "static" / "brand" / "logo-stacked-dark.png"
OUT = ROOT / "editor" / "static" / "brand"
# Znak (fala + aparat), z zapasem na antyaliasing. Napis zostaje poza kadrem.
CROP = (40, 22, 154, 132)
BG = (26, 26, 26)
MARK_RATIO = 0.78


def _mark() -> Image.Image:
    src = Image.open(SRC).convert("RGB")
    crop = src.crop(CROP)
    bg = src.getpixel((2, 2))
    rgba = crop.convert("RGBA")
    pix = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pix[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) < 42:
                pix[x, y] = (0, 0, 0, 0)
    return rgba


def _square(size: int, mark: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (size, size), BG)
    target = max(1, int(size * MARK_RATIO))
    fitted = mark.resize((target, target), Image.Resampling.LANCZOS)
    if size >= 128:
        fitted = fitted.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=2))
    pos = ((size - target) // 2, (size - target) // 2)
    canvas.paste(fitted, pos, fitted)
    return canvas


def _icns(master: Image.Image) -> None:
    iconset = OUT / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    sizes = {
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
    for name, size in sizes.items():
        _square(size, master).save(iconset / name, "PNG")
    dest = OUT / "app-icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)
    shutil.rmtree(iconset)


def main() -> None:
    if not SRC.is_file():
        sys.exit(f"Brak logo: {SRC}")
    mark = _mark()
    png = OUT / "app-icon.png"
    _square(1024, mark).save(png, "PNG")
    ico_sizes = [256, 128, 64, 48, 32, 24, 16]
    images = [_square(size, mark) for size in ico_sizes]
    images[0].save(
        OUT / "app-icon.ico",
        format="ICO",
        sizes=[(size, size) for size in ico_sizes],
        append_images=images[1:],
    )
    if sys.platform == "darwin":
        _icns(mark)
    print(png)


if __name__ == "__main__":
    main()
