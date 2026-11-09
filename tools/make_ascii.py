"""Turn a portrait photo into the ASCII art used on the profile card.

Run this once, by hand, whenever the photo changes:

    pip install pillow numpy
    python tools/make_ascii.py path/to/photo.png

It writes two files that build_card.py reads:

    assets/ascii-dark.txt   bright parts of the photo -> dense characters
    assets/ascii-light.txt  dark parts of the photo   -> dense characters

The photo itself is not committed; only the text art is.

The background is dropped by colour (the portrait sits on a saturated blue
backdrop), so the figure stands out as a silhouette instead of a filled
rectangle. Tune BG_BLUE_MARGIN if a new photo has a different backdrop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent

COLS = 80                   # characters per line
CELL_ASPECT = 1.85          # line height / character advance; must match build_card.py
CROP = (180, 30, 844, 840)  # left, top, right, bottom in the 1024x1024 photo
BG_BLUE_MARGIN = 19         # a pixel is backdrop when blue exceeds red by this much
GAMMA = 1.2                 # >1 keeps the brightest skin from all becoming '@'

# Light-to-dense ramp. Index 0 (a space) is reserved for the backdrop.
RAMP = " .:-=+*#%@"


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    img = Image.open(path).convert("RGB").crop(CROP)
    w, h = img.size
    rows = round(h / (w / COLS) / CELL_ASPECT)

    rgb = np.asarray(img).astype(np.int16)
    backdrop = (rgb[..., 2] - rgb[..., 0]) > BG_BLUE_MARGIN
    mask = Image.fromarray(np.where(backdrop, 0, 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MedianFilter(9))

    grey = img.convert("L")
    grey = grey.filter(ImageFilter.UnsharpMask(radius=25, percent=120, threshold=0))  # local contrast
    grey = grey.filter(ImageFilter.UnsharpMask(radius=2, percent=250, threshold=0))   # edges: glasses, eyes
    grey = ImageOps.autocontrast(grey, cutoff=1, mask=mask)

    size = (COLS, rows)
    lum = np.asarray(grey.resize(size, Image.Resampling.BOX)).astype(float) / 255
    fig = np.asarray(mask.resize(size, Image.Resampling.BOX)) > 127
    return lum, fig


def render(lum: np.ndarray, fig: np.ndarray, invert: bool) -> list[str]:
    tone = (1 - lum) ** (1 / GAMMA) if invert else lum ** GAMMA
    levels = len(RAMP) - 1
    lines = []
    for r in range(lum.shape[0]):
        row = []
        for c in range(lum.shape[1]):
            if not fig[r, c]:
                row.append(" ")
                continue
            # The figure never vanishes: its faintest pixel still gets the
            # lightest mark, which keeps dark hair and shirt readable.
            row.append(RAMP[min(levels, 1 + int(round(tone[r, c] * (levels - 1))))])
        lines.append("".join(row).rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/make_ascii.py PHOTO")
    lum, fig = load(Path(sys.argv[1]))
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    (out / "ascii-dark.txt").write_text("\n".join(render(lum, fig, invert=False)) + "\n")
    (out / "ascii-light.txt").write_text("\n".join(render(lum, fig, invert=True)) + "\n")
    print(f"wrote {lum.shape[0]} rows x {lum.shape[1]} cols to {out}")


if __name__ == "__main__":
    main()
