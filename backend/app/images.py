"""Pictures in the doc: save them, decide which are diagrams, redraw diagrams as clean SVG.

Rule (from the author): a picture becomes a generated diagram only if it IS a diagram (geometric figure, graph,
circuit, science-experiment set-up ...). Equations, photos, cartoon/infographic artwork etc. stay placeholders.
The author can flip any picture either way; generated diagrams are always shown for review.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image

from . import config, gdoc, llm, store

TINY_W, TINY_H = 70, 45  # smaller than this on the page: an inline symbol/equation piece, never analysed


def mdir(pid: str) -> Path:
    d = config.PROJECTS / pid / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ddir(pid: str) -> Path:
    d = config.PROJECTS / pid / "diagrams"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ media
def save_media(pid: str, docx: bytes, blocks: list[dict]) -> int:
    """Write every distinct picture of the doc to media/<hash>.<ext> plus a small .t.jpg for the UI and the AI."""
    zf = zipfile.ZipFile(io.BytesIO(docx))
    seen = set()
    n = 0
    for b in blocks:
        if b["t"] != "img" or not b.get("hash") or b["hash"] in seen or not b.get("file"):
            continue
        seen.add(b["hash"])
        try:
            raw = zf.read("word/" + b["file"])
        except KeyError:
            continue
        ext = b["file"].rsplit(".", 1)[-1].lower()
        (mdir(pid) / f"{b['hash']}.{ext}").write_bytes(raw)
        try:
            im = Image.open(io.BytesIO(raw))
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, "white")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            full = im.size
            im.thumbnail((1100, 1100))
            im.save(mdir(pid) / f"{b['hash']}.t.jpg", quality=85)
            (mdir(pid) / f"{b['hash']}.size").write_text(json.dumps(full))
        except Exception:
            continue
        n += 1
    return n


def thumb(pid: str, h: str) -> Path | None:
    p = mdir(pid) / f"{h}.t.jpg"
    return p if p.exists() else None


# ------------------------------------------------------------------ inventory
def inventory(pid: str, blocks: list[dict], pages: dict) -> list[dict]:
    state = store.read(pid, "images.json", {})
    out: dict[str, dict] = {}
    for b in blocks:
        if b["t"] != "img" or not b.get("hash"):
            continue
        e = out.setdefault(b["hash"], {"hash": b["hash"], "count": 0, "blocks": [], "pages": [], "w": 0, "h": 0})
        e["count"] += 1
        e["blocks"].append(b["id"])
        pg = pages.get(b["id"])
        if pg and pg not in e["pages"]:
            e["pages"].append(pg)
        e["w"], e["h"] = max(e["w"], b["w"]), max(e["h"], b["h"])
    res = []
    for h, e in out.items():
        st = state.get(h, {})
        e["tiny"] = e["w"] < TINY_W or e["h"] < TINY_H
        e["has_media"] = thumb(pid, h) is not None
        e["class"] = st.get("class", "inline" if e["tiny"] else None)
        e["complexity"] = st.get("complexity")
        e["reason"] = st.get("reason", "")
        e["mode"] = st.get("mode", "placeholder")
        e["status"] = st.get("status", "none")
        e["match"] = st.get("match")
        e["issues"] = st.get("issues", [])
        e["error"] = st.get("error")
        e["has_svg"] = (ddir(pid) / f"{h}.svg").exists()
        res.append(e)
    res.sort(key=lambda e: (e["pages"][0] if e["pages"] else 999, e["blocks"][0]))
    return res


def set_mode(pid: str, h: str, mode: str):
    st = store.read(pid, "images.json", {})
    st.setdefault(h, {})["mode"] = mode
    st[h]["mode_user"] = True
    store.write(pid, "images.json", st)


# ------------------------------------------------------------------ classify
CLASSIFY_SYSTEM = "You are preparing a school textbook for typesetting. Be accurate and conservative. Use the Read tool to look at every image file you are given."


def classify(pid: str, blocks: list[dict], models: dict, prog, force: bool = False):
    inv = inventory(pid, blocks, {})
    state = store.read(pid, "images.json", {})
    todo = [e for e in inv if not e["tiny"] and e["has_media"] and (force or "class" not in state.get(e["hash"], {}))]
    if not todo:
        prog("Nothing new to analyse", 1)
        return
    BATCH = 8
    from concurrent.futures import ThreadPoolExecutor, as_completed

    chunks = [todo[k : k + BATCH] for k in range(0, len(todo), BATCH)]

    def run(chunk):
        files = {f"img{i + 1}.jpg": thumb(pid, e["hash"]) for i, e in enumerate(chunk)}
        return chunk, _classify_call(files, models)

    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(run, c) for c in chunks]
        for f in as_completed(futs):
            try:
                chunk, reply = f.result()
            except Exception as e:  # keep going; unclassified pictures simply stay placeholders
                prog(f"One batch failed: {str(e)[:80]}", done / len(chunks))
                done += 1
                continue
            by = {r.get("file"): r for r in llm.as_list(reply) if isinstance(r, dict)}
            state = store.read(pid, "images.json", {})
            for i, e in enumerate(chunk):
                r = by.get(f"img{i + 1}.jpg") or {}
                cls = r.get("class") if r.get("class") in ("diagram", "equation", "photo", "illustration", "other") else "other"
                cur = state.setdefault(e["hash"], {})
                cur.update({"class": cls, "complexity": r.get("complexity", "medium"), "reason": r.get("reason", "")})
                if not cur.get("mode_user"):
                    cur["mode"] = "generate" if cls == "diagram" else "placeholder"
            store.write(pid, "images.json", state)
            done += 1
            prog(f"Looked at {min(done * BATCH, len(todo))} of {len(todo)} pictures", done / len(chunks))


def _classify_call(files: dict, models: dict):
    names = ", ".join(files)
    prompt = (
        f"Look at each of these image files: {names}.\n"
        "For each one decide:\n"
        '- "class": one of\n'
        '    "diagram"      = a line drawing / schematic that can be redrawn faithfully as clean vector shapes with text labels: geometric figures (circles, triangles, angles), graphs and plots, number lines, circuit diagrams, ray diagrams, labelled science-experiment or apparatus set-ups, flowcharts, simple labelled biology/physics line diagrams;\n'
        '    "equation"     = typeset maths or text (equations, solution steps, expressions, tables of numbers);\n'
        '    "photo"        = a photograph;\n'
        '    "illustration" = painted, cartoon or infographic artwork, heavy shading or many colours, mind maps;\n'
        '    "other"        = anything else (logo, screenshot, decorative line).\n'
        '- "complexity": "simple" | "medium" | "complex" (how hard it is to redraw faithfully as vector).\n'
        '- "reason": one short sentence.\n'
        'Reply with JSON only: an array with one object per file, e.g. [{"file":"img1.jpg","class":"diagram","complexity":"simple","reason":"..."}].'
    )
    text = llm.ask_vision(prompt, files, model=models.get("spelling", "sonnet"), system=CLASSIFY_SYSTEM)
    return llm.extract_json(text)


# ------------------------------------------------------------------ SVG
ALLOWED = {"svg", "g", "path", "line", "polyline", "polygon", "rect", "circle", "ellipse", "text", "tspan", "defs", "lineargradient", "radialgradient", "stop", "clippath", "title", "desc"}


def sanitize_svg(svg: str) -> str:
    m = re.search(r"<svg\b.*?</svg>", svg, flags=re.S | re.I)
    if not m:
        raise ValueError("no <svg> found")
    root = etree.fromstring(m.group(0).encode("utf-8"), parser=etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    if root is None:
        raise ValueError("unparseable svg")
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            el.getparent().remove(el) if el.getparent() is not None else None
            continue
        name = etree.QName(el).localname.lower()
        if name not in ALLOWED:
            if el.getparent() is not None:
                el.getparent().remove(el)
            continue
        for a in list(el.attrib):
            la = etree.QName(a).localname.lower() if "}" in a else a.lower()
            v = el.attrib[a]
            if la in ("marker-start", "marker-mid", "marker-end", "marker") or la.startswith("on") or (la == "href" and not v.startswith("#")) or "javascript:" in v.lower() or re.search(r"url\(\s*['\"]?https?:", v, re.I):
                del el.attrib[a]
    if "viewBox" not in root.attrib:
        w, h = root.get("width", "400"), root.get("height", "300")
        try:
            root.set("viewBox", f"0 0 {float(re.sub('[^0-9.]', '', w)):g} {float(re.sub('[^0-9.]', '', h)):g}")
        except ValueError:
            root.set("viewBox", "0 0 400 300")
    for a in ("width", "height"):
        root.attrib.pop(a, None)
    return normalize_svg(etree.tostring(root, encoding="unicode"))


def normalize_svg(svg: str) -> str:
    """Make the markup strict enough for Figma's importer: one xmlns, unquoted font names, no nested quotes."""
    m = re.match(r"<svg\b[^>]*>", svg)
    if m:
        tag = m.group(0)
        seen = False

        def keep_first(mm):
            nonlocal seen
            if seen:
                return ""
            seen = True
            return mm.group(0)

        tag2 = re.sub(r"\s+xmlns\s*=\s*(\"[^\"]*\"|'[^']*')", keep_first, tag)
        if not seen:
            tag2 = tag2.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        svg = tag2 + svg[len(tag):]

    def fam(mm):
        q, val = mm.group(1), mm.group(2)
        return f'font-family="{val.replace(chr(39), "").replace(chr(34), "")}"'

    svg = re.sub(r"font-family\s*=\s*(\")((?:(?!\").)*)\"", fam, svg)
    svg = re.sub(r"font-family\s*=\s*(')((?:[^'>]|'(?=[A-Za-z ]+'))*)'", fam, svg)
    return svg


def chrome_bin() -> str | None:
    for c in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chrome") or "",
    ):
        if c and Path(c).exists():
            return c
    return None


def render_png(svg: str, w: int, h: int, out: Path) -> bool:
    b = chrome_bin()
    if not b:
        return False
    html = out.with_suffix(".html")
    html.write_text(f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fff"><div style="width:{w}px;height:{h}px">'
                    + svg.replace("<svg ", f'<svg width="{w}" height="{h}" ', 1) + "</div>")
    try:
        subprocess.run([b, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}", "--virtual-time-budget=3000", f"--screenshot={out}", f"file://{html}"],
                       capture_output=True, timeout=90)
    except Exception:
        return False
    finally:
        html.unlink(missing_ok=True)
    return out.exists() and out.stat().st_size > 200


# ------------------------------------------------------------------ generate
GEN_SYSTEM = ("You are a precise technical illustrator preparing a school textbook for students; accuracy is critical. "
              "You redraw diagrams as clean, editable SVG. Use the Read tool to look at the image files you are given.")


def _size(pid: str, h: str) -> tuple[int, int]:
    f = mdir(pid) / f"{h}.size"
    if f.exists():
        w, hh = json.loads(f.read_text())
        return int(w), int(hh)
    return 600, 400


def generate(pid: str, h: str, theme: dict, models: dict, prog=None, rounds: int = 2) -> dict:
    st = store.read(pid, "images.json", {})
    cur = st.setdefault(h, {})
    cur["status"] = "working"
    store.write(pid, "images.json", st)
    t = thumb(pid, h)
    if not t:
        raise ValueError("picture file missing")
    W, H = _size(pid, h)
    sc = min(1.0, 1000 / max(W, H))
    vw, vh = round(W * sc), round(H * sc)
    model = models.get("scan", "opus")
    prompt = (
        "Redraw the diagram in the image file orig.jpg as clean SVG.\n"
        f"- Use viewBox=\"0 0 {vw} {vh}\" (match the picture's proportions and positions).\n"
        "- Allowed elements only: svg, g, path, line, polyline, polygon, rect, circle, ellipse, text, tspan, defs. No images, no scripts, no external references.\n"
        "- NEVER use <marker> or marker-start/marker-end (the Figma importer drops them). Draw every arrowhead explicitly as a small filled <polygon> or <path> at the end of the line.\n"
        "- Copy EVERY label, letter, number and symbol EXACTLY as written in the picture (spelling matters; keep subscripts/superscripts as characters, Greek letters as Unicode).\n"
        "- Keep shapes, angles, proportions, arrows, dashed/solid line styles, shading and relative positions faithful. Do not invent or omit parts.\n"
        "- Text: font-family=\"Avenir, 'Helvetica Neue', Arial, sans-serif\", font-size so that labels look the same size relative to the drawing as in the picture (not smaller); text must stay readable and not overlap.\n"
        "- Keep the original colours (black line work stays black). Transparent background (no full-size background rect).\n"
        "Reply with the SVG only, starting with <svg."
    )
    svg = None
    notes: list = []
    match = None
    work = ddir(pid) / "tmp"
    work.mkdir(exist_ok=True)
    try:
        if prog:
            prog("Drawing the diagram…")
        files = {"orig.jpg": t}
        text = llm.ask_vision(prompt, files, model=model, system=GEN_SYSTEM)
        svg = sanitize_svg(text)
        for rd in range(rounds):
            png = work / f"{h}.r{rd}.png"
            if not render_png(svg, vw, vh, png):
                notes.append("Could not render the drawing here to double-check it (no Chrome/Chromium found).")
                break
            if prog:
                prog(f"Checking the drawing against the original (round {rd + 1})…")
            review = llm.ask_vision(
                "Image orig.jpg is the ORIGINAL diagram from a school textbook. Image draw.png is a redraw made as SVG.\n"
                "Compare them carefully: shapes, proportions, positions, arrowheads, line styles, and EVERY label/number (exact spelling and values). Arrowheads must be explicit polygons/paths (never <marker>).\n"
                'Reply with JSON only: {"match": <0-100 how faithful the redraw is>, "issues": ["each concrete difference"], "svg": "<the corrected full SVG, or the same SVG if nothing needs changing>"}\n'
                "Current SVG:\n" + svg,
                {"orig.jpg": t, "draw.png": png}, model=model, system=GEN_SYSTEM,
            )
            try:
                r = llm.extract_json(review)
            except Exception:
                break
            match = r.get("match")
            notes = [str(x) for x in (r.get("issues") or [])][:12]
            if r.get("svg") and "<svg" in r["svg"]:
                try:
                    svg = sanitize_svg(r["svg"])
                except Exception:
                    pass
            if isinstance(match, (int, float)) and match >= 94 and not notes:
                break
    finally:
        shutil.rmtree(work, ignore_errors=True)
    (ddir(pid) / f"{h}.svg").write_text(svg)
    st = store.read(pid, "images.json", {})
    cur = st.setdefault(h, {})
    cur.update({"status": "generated", "match": match, "issues": notes, "error": None})
    store.write(pid, "images.json", st)
    return cur


def svg_for(pid: str, h: str) -> str | None:
    f = ddir(pid) / f"{h}.svg"
    return normalize_svg(f.read_text()) if f.exists() else None
