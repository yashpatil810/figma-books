"""Text measurement with the real macOS fonts (Avenir / DIN Condensed) so pagination matches Figma."""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

AVENIR = "/System/Library/Fonts/Avenir.ttc"
DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
_IDX = {"medium": 8, "heavy": 4, "black": 2}
SCALE = 10


@lru_cache(maxsize=64)
def _font(kind: str, size: float):
    px = int(round(size * SCALE))
    try:
        if kind == "din":
            return ImageFont.truetype(DIN, px)
        return ImageFont.truetype(AVENIR, px, index=_IDX[kind])
    except Exception:
        return None


@lru_cache(maxsize=20000)
def _w(kind: str, size: float, s: str) -> float:
    f = _font(kind, size)
    if f is None:  # fonts missing: rough average-width fallback
        return len(s) * size * (0.42 if kind == "din" else 0.52)
    return f.getlength(s) / SCALE


def fonts_available() -> dict:
    return {"avenir": os.path.exists(AVENIR), "din_condensed": os.path.exists(DIN)}


def count_lines(runs: list[dict], width: float, size: float = 11, base: str = "medium") -> int:
    """Greedy word wrap over styled runs; bold runs use the Black face, like the plugin does."""
    words: list[tuple[str, str]] = []
    for r in runs:
        kind = "black" if r.get("b") else base
        parts = r["t"].replace("\t", "    ").split("\n")
        for pi, part in enumerate(parts):
            if pi > 0:
                words.append(("\n", kind))
            toks = part.split(" ")
            for ti, tok in enumerate(toks):
                words.append((tok + (" " if ti < len(toks) - 1 else ""), kind))
    lines, cur = 1, 0.0
    for tok, kind in words:
        if tok == "\n":
            lines += 1
            cur = 0.0
            continue
        w = _w(kind, size, tok)
        wt = _w(kind, size, tok.rstrip())
        if cur + wt > width and cur > 0:
            lines += 1
            cur = 0.0
        cur += w
    return lines


def text_lines(text: str, width: float, size: float, kind: str) -> int:
    return count_lines([{"t": text}], width, size, kind)
