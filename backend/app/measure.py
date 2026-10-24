"""Text measurement with the real fonts so pagination matches Figma.

Default: the macOS fonts Avenir / DIN Condensed. A style can name other fonts (theme["fonts"]); Google Fonts are
downloaded once into data/fonts and measured exactly. If a font cannot be found, the default metrics are used instead
and the page lengths are approximate (see `warnings`).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import httpx
from PIL import ImageFont

from . import config

AVENIR = "/System/Library/Fonts/Avenir.ttc"
DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
_IDX = {"medium": 8, "heavy": 4, "black": 2}
SCALE = 10


_cfg: dict | None = None
warnings: list[str] = []
_found: dict[str, Path | None] = {}
DEFAULT_WEIGHTS = {"medium": 500, "heavy": 800, "black": 900, "din": 700}
WEIGHT_STYLES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}
SYSTEM_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]


def configure(fonts: dict | None):
    """Use these fonts for measuring (None = the defaults). Safe to call before every layout."""
    global _cfg
    new = fonts if fonts and (fonts.get("text") or fonts.get("display")) else None
    if new != _cfg:
        _cfg = new
        warnings.clear()
        _font.cache_clear()
        _w.cache_clear()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _font_file(family: str, weight: int) -> Path | None:
    """A font file for this family: downloaded earlier, installed on the Mac, or fetched from Google Fonts once."""
    slug = _slug(family)
    d = config.DATA / "fonts"
    d.mkdir(exist_ok=True)
    key = f"{slug}:{weight}"
    if key in _found:
        return _found[key]
    style = WEIGHT_STYLES.get(weight, "Regular")
    found = None
    for f in sorted(d.glob("*.ttf")):  # variable file first, then the static file for this weight
        n = _slug(f.stem)
        if n.startswith(slug) and "italic" not in n and ("wght" in n or n.endswith(_slug(style))):
            found = f
            break
    if not found:
        for base in SYSTEM_DIRS:
            for f in Path(base).glob("*.tt[fc]") if Path(base).exists() else []:
                if _slug(f.stem).startswith(slug):
                    found = f
                    break
            if found:
                break
    if not found:
        try:  # Google Fonts: the family folder lists its files
            r = httpx.get(f"https://api.github.com/repos/google/fonts/contents/ofl/{slug}", timeout=20)
            files = [x for x in r.json() if isinstance(x, dict) and x.get("name", "").endswith(".ttf")] if r.status_code == 200 else []
            pick = next((x for x in files if "[" in x["name"] and "Italic" not in x["name"]), None) or next((x for x in files if x["name"].endswith(f"-{style}.ttf")), None)
            if pick:
                data = httpx.get(pick["download_url"], timeout=60).content
                found = d / pick["name"].replace("[", "").replace("]", "").replace(",", "")
                found.write_bytes(data)
        except Exception:
            found = None
    if not found:
        warnings.append(f"Font “{family}” was not found here, so page lengths are estimated with the default fonts and may be slightly off.")
    _found[key] = found
    return found


def _cfg_font(kind: str, px: int):
    if not _cfg:
        return None
    spec = _cfg.get("display") if kind == "din" else _cfg.get("text")
    if not spec or not spec.get("family"):
        return None
    weight = int(spec.get("weight") if kind == "din" else spec.get(kind, DEFAULT_WEIGHTS[kind]))
    path = _font_file(spec["family"], weight)
    if not path:
        return None
    f = ImageFont.truetype(str(path), px)
    try:
        axes = f.get_variation_axes()
        if axes:
            f.set_variation_by_axes([weight if (a.get("name") in (b"Weight", "Weight")) else a.get("default", 0) for a in axes])
    except Exception:
        pass
    return f


@lru_cache(maxsize=64)
def _font(kind: str, size: float):
    px = int(round(size * SCALE))
    try:
        f = _cfg_font(kind, px)
        if f is not None:
            return f
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
    return {"avenir": os.path.exists(AVENIR), "din_condensed": os.path.exists(DIN), "custom": bool(_cfg), "warnings": list(warnings)}


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
