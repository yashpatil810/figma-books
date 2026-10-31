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
_found: dict[str, tuple[Path, int] | None] = {}
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


# weight -> style names that count as that weight, best first. Local fonts are picked by style name, exactly as the Figma
# plugin does (Avenir has no "ExtraBold": its 800 is "Heavy", its 900 is "Black"), so the pages are measured with the face
# that will really be used.
STYLE_NAMES = {
    100: ["Thin", "Hairline"], 200: ["ExtraLight", "Extra Light", "UltraLight", "Ultra Light"], 300: ["Light"],
    400: ["Regular", "Book", "Roman", "Normal"], 500: ["Medium"], 600: ["SemiBold", "Semi Bold", "DemiBold", "Demi Bold"],
    700: ["Bold"], 800: ["ExtraBold", "Extra Bold", "Heavy", "UltraBold", "Ultra Bold"], 900: ["Black", "Heavy", "ExtraBlack", "Extra Black", "UltraBlack"],
}
_STYLE_WEIGHT = {_slug(n): w for w, names in STYLE_NAMES.items() for n in names}


def _faces(path: Path) -> list[tuple[int, str, str]]:
    """(index, family, style) of every face in a font file (a .ttc holds several families and weights)."""
    out = []
    for i in range(64):
        try:
            fam, sty = ImageFont.truetype(str(path), 10, index=i).getname()
        except Exception:
            break
        out.append((i, fam or "", sty or ""))
    return out


def _pick_face(path: Path, family: str, weight: int) -> int | None:
    """The upright face of exactly this family whose style name fits the weight, else the nearest weight; None when the
    file holds no face of this family ("Avenir" never matches "Avenir Next" or "Avenir Next Condensed")."""
    slug = _slug(family)
    faces = [(i, sty) for i, fam, sty in _faces(path) if _slug(fam) == slug and not re.search(r"italic|oblique", sty, re.I)]
    if not faces:
        return None
    for want in STYLE_NAMES.get(weight, [WEIGHT_STYLES.get(weight, "Regular")]):
        for i, sty in faces:
            if _slug(sty) == _slug(want):
                return i
    return min(faces, key=lambda f: abs(_STYLE_WEIGHT.get(_slug(f[1]), 400) - weight))[0]


def _font_file(family: str, weight: int) -> tuple[Path, int] | None:
    """A font file and the face index in it for this family and weight: downloaded earlier, installed on the Mac, or
    fetched from Google Fonts once. The face's own family name must match exactly; the file name only narrows the search."""
    slug = _slug(family)
    d = config.DATA / "fonts"
    d.mkdir(exist_ok=True)
    key = f"{slug}:{weight}"
    if key in _found:
        return _found[key]
    style = WEIGHT_STYLES.get(weight, "Regular")
    # downloaded files first (a variable "wght" file before static weights), then the fonts installed on this Mac
    cands = sorted(list(d.glob("*.ttf")) + list(d.glob("*.otf")), key=lambda f: ("wght" not in _slug(f.stem), f.name))
    for base in SYSTEM_DIRS:
        if Path(base).exists():
            cands += sorted(list(Path(base).glob("*.tt[fc]")) + list(Path(base).glob("*.otf")))
    found = None
    for f in cands:
        if not _slug(f.stem).startswith(slug):
            continue
        idx = _pick_face(f, family, weight)
        if idx is not None:
            found = (f, idx)
            break
    if not found:
        try:  # Google Fonts: the family folder lists its files
            r = httpx.get(f"https://api.github.com/repos/google/fonts/contents/ofl/{slug}", timeout=20)
            files = [x for x in r.json() if isinstance(x, dict) and x.get("name", "").endswith(".ttf")] if r.status_code == 200 else []
            pick = next((x for x in files if "[" in x["name"] and "Italic" not in x["name"]), None) or next((x for x in files if x["name"].endswith(f"-{style}.ttf")), None)
            if pick:
                data = httpx.get(pick["download_url"], timeout=60).content
                path = d / pick["name"].replace("[", "").replace("]", "").replace(",", "")
                path.write_bytes(data)
                found = (path, _pick_face(path, family, weight) or 0)
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
    found = _font_file(spec["family"], weight)
    if not found:
        return None
    path, idx = found
    f = ImageFont.truetype(str(path), px, index=idx)
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


@lru_cache(maxsize=64)
def _notdef_w(kind: str, size: float) -> float:
    """Advance of the font's missing-glyph box, to recognise characters the font does not have."""
    f = _font(kind, size)
    return f.getlength("\u0378") / SCALE if f is not None else 0.0


def _fallback_em(ch: str) -> float:
    """Width (in em) a renderer's fallback font gives a character the text font lacks: arrows are set wide (→ ⇒ ≈ 1 em),
    other symbols around 0.65 em. Measured against Chrome's and Figma's substitutes for Avenir."""
    o = ord(ch)
    if 0x2190 <= o <= 0x21FF or 0x27F0 <= o <= 0x27FF or 0x2900 <= o <= 0x297F:
        return 1.0
    return 0.65


@lru_cache(maxsize=20000)
def _w(kind: str, size: float, s: str) -> float:
    f = _font(kind, size)
    if f is None:  # fonts missing: rough average-width fallback
        return len(s) * size * (0.42 if kind == "din" else 0.52)
    w = f.getlength(s) / SCALE
    if any(ord(ch) > 0x7F for ch in s):  # characters the font lacks are drawn from a fallback font, usually wider than the .notdef box
        nd = _notdef_w(kind, size)
        for ch in s:
            if ord(ch) > 0x7F and abs(f.getlength(ch) / SCALE - nd) < 1e-6:
                w += max(0.0, _fallback_em(ch) * size - nd)
    return w


def fonts_available() -> dict:
    return {"avenir": os.path.exists(AVENIR), "din_condensed": os.path.exists(DIN), "custom": bool(_cfg), "warnings": list(warnings)}


def text_width(s: str, size: float, kind: str = "medium") -> float:
    """Width of one string in the given face (the renderers size number labels and bullet marks to their text)."""
    return _w(kind, size, s)


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
