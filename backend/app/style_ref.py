"""Read a reference Figma file once and turn it into an editable style profile (colours, capitalisation, typography).

The Figma REST API gives exact fills, fonts, sizes and text-case per layer; Claude looks at a few rendered pages and
the measured numbers together and maps them onto the app's theme roles. The profile is shown on the Colours & samples
screen, where the author can change anything. Pages are still built by the app's own renderer, so nothing is improvised.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from . import config, figma_api, llm

PAGE_KINDS = ("index", "body", "exercise", "worksheet", "answers", "mindmap", "references", "glossary", "end")
THEME_KEYS = ("primary", "text", "strong", "tint", "white", "rule", "footerRule", "tableAlt", "tableBorder", "onPrimary")
CASE_ROLES = ("eyebrow", "title", "h2", "h3", "toc", "pill")
CASE_VALUES = ("ORIGINAL", "TITLE", "UPPER", "LOWER")
MAX_FRAMES = 10


def _hex(c: dict | None) -> str | None:
    if not c:
        return None
    return "#%02X%02X%02X" % (round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255))


def _solid(fills) -> str | None:
    for f in fills or []:
        if f.get("type") == "SOLID" and f.get("visible", True) and f.get("opacity", 1) > 0.05:
            return _hex(f["color"])
    return None


def pick_frames(frames: list[dict], n: int = MAX_FRAMES) -> list[dict]:
    """Evenly spaced pages, so different page types (index, body, exercise, answers…) are all represented."""
    frames = [f for f in frames if (f.get("absoluteBoundingBox") or {}).get("height", 0) > 300]
    if len(frames) <= n:
        return frames
    step = (len(frames) - 1) / (n - 1)
    return [frames[round(i * step)] for i in range(n)]


def measure(frames: list[dict]) -> dict:
    """Plain numbers from the reference pages: backgrounds, fills in use, text styles, and the page geometry."""
    bg, fills, texts, strokes, names = Counter(), defaultdict(float), {}, Counter(), Counter()
    geometry = Counter()

    def walk(n, top, depth=0):
        t = n.get("type")
        bb = n.get("absoluteBoundingBox") or {}
        area = bb.get("width", 0) * bb.get("height", 0)
        if top:
            c = _solid(n.get("fills"))
            if c:
                bg[c] += 1
            geometry[(round(bb.get("width", 0)), round(bb.get("height", 0)))] += 1
        elif t in ("RECTANGLE", "FRAME", "ELLIPSE"):
            c = _solid(n.get("fills"))
            if c and area:
                fills[c] += min(area, 60000)
                names[(c, re.sub(r"\d+", "", n.get("name", ""))[:24])] += 1
            sc = _solid(n.get("strokes"))
            if sc:
                strokes[sc] += 1
        if t == "TEXT":
            st = n.get("style") or {}
            col = _solid(n.get("fills"))
            key = (st.get("fontFamily"), st.get("fontWeight"), round(st.get("fontSize", 0), 1), st.get("textCase", "ORIGINAL"), col, round(st.get("lineHeightPx", 0), 1))
            e = texts.setdefault(key, {"n": 0, "sample": ""})
            e["n"] += 1
            if len(n.get("characters", "")) > len(e["sample"]) and len(e["sample"]) < 60:
                e["sample"] = n.get("characters", "")[:60]
        for c in n.get("children", []) or []:
            walk(c, False, depth + 1)

    for f in frames:
        walk(f, True)
    tstyles = sorted(texts.items(), key=lambda kv: -kv[1]["n"])[:18]
    return {
        "page_size": [list(k) for k, _ in geometry.most_common(1)][0] if geometry else None,
        "page_backgrounds": [{"colour": c, "pages": n} for c, n in bg.most_common(5)],
        "fills_in_use": [{"colour": c, "weight": round(w), "layers": [nm for (cc, nm), _ in names.most_common(40) if cc == c][:4]} for c, w in sorted(fills.items(), key=lambda kv: -kv[1])[:10]],
        "stroke_colours": [{"colour": c, "count": n} for c, n in strokes.most_common(4)],
        "text_styles": [{"font": k[0], "weight": k[1], "size": k[2], "textCase": k[3], "colour": k[4], "lineHeight": k[5], "count": v["n"], "sample": v["sample"]} for k, v in tstyles],
    }


def geometry(frames: list[dict]) -> dict:
    """Where things sit on the reference pages (relative to each page): rules, the pill, the text column, the footer."""
    rules_, pills, lefts, rights, foot, tops, bottoms, sizes = Counter(), Counter(), Counter(), Counter(), Counter(), [], [], Counter()

    def walk(n, ox, oy, ph):
        bb = n.get("absoluteBoundingBox") or {}
        x, y, w, h = bb.get("x", 0) - ox, bb.get("y", 0) - oy, bb.get("width", 0), bb.get("height", 0)
        t = n.get("type")
        if t in ("RECTANGLE", "FRAME", "LINE") and h <= 2.5 and w >= 150 and not n.get("children"):
            rules_[(round(x), round(y), round(w))] += 1
        if t in ("FRAME", "RECTANGLE") and 10 <= h <= 32 and 70 <= w <= 260 and y < 80 and x > 250 and (n.get("cornerRadius", 0) >= h / 2 - 1 or n.get("rectangleCornerRadii")):
            pills[(round(x), round(y), round(w), round(h))] += 1
        if t == "TEXT":
            st = n.get("style") or {}
            size = st.get("fontSize", 0)
            if y > ph - 60:
                foot[(round(x), round(y), round(size, 1), round(w))] += 1
            elif y > 60 and 8 <= size <= 14 and w > 120:
                lefts[round(x)] += 1
                rights[round(x + w)] += 1
                tops.append(y)
                bottoms.append(y + h)
                sizes[(round(size, 1), round(st.get("lineHeightPx", 0), 1))] += 1
        for c in n.get("children", []) or []:
            walk(c, ox, oy, ph)

    for f in frames:
        bb = f.get("absoluteBoundingBox") or {}
        walk(f, bb.get("x", 0), bb.get("y", 0), bb.get("height", 842))
    body_bottoms = sorted(b for b in bottoms if b < 800)
    return {
        "header_rules_(x,y,w)": [list(k) + [n] for k, n in rules_.most_common(6) if k[1] < 120],
        "footer_rules_(x,y,w)": [list(k) + [n] for k, n in rules_.most_common(12) if k[1] > 700][:3],
        "pill_(x,y,w,h)": [list(k) + [n] for k, n in pills.most_common(3)],
        "body_text_left_edges": [[k, n] for k, n in lefts.most_common(3)],
        "body_text_right_edges": [[k, n] for k, n in rights.most_common(3)],
        "first_body_text_y": round(sorted(tops)[len(tops) // 20], 1) if tops else None,
        "lowest_body_text_bottom": round(body_bottoms[-max(1, len(body_bottoms) // 50)], 1) if body_bottoms else None,
        "footer_texts_(x,y,size,width)": [list(k) + [n] for k, n in foot.most_common(4)],
        "body_text_(size,lineHeight)": [list(k) + [n] for k, n in sizes.most_common(4)],
    }


SYSTEM = "You are a careful print designer reading the design system of a school textbook so another tool can reproduce it. Use the Read tool to look at every image file you are given."


def _prompt(stats: dict, shots: list[str]) -> str:
    return (
        f"The image files {', '.join(shots)} are pages of a textbook designed in Figma. Below are measured numbers from {stats['n_pages']} of its pages (colours as hex, fonts, sizes, Figma text-case).\n\n"
        f"MEASURED: {stats['json']}\n\nGEOMETRY (positions relative to each page's top-left): {stats['geometry']}\n\n"
        "Map the design onto these roles and reply with JSON only:\n"
        '{"theme": {"primary": "#hex", "text": "#hex", "strong": "#hex", "tint": "#hex", "white": "#hex", "rule": "#hex", "footerRule": "#hex", "tableAlt": "#hex", "tableBorder": "#hex", "onPrimary": "#hex"},\n'
        ' "case": {"eyebrow": "ORIGINAL|TITLE|UPPER|LOWER", "title": "...", "h2": "...", "h3": "...", "toc": "...", "pill": "..."},\n'
        ' "typography": [{"role": "title|h2|h3|h4|body|pill|footer", "font": "family", "weight": "e.g. Bold", "size": 42}],\n'
        ' "page_types": [{"kind": "index|body|exercise|worksheet|answers|mindmap|references|glossary|end", "background": "#hex", "pillBg": "#hex of the header pill fill", "pillFg": "#hex of the pill text", "rule": "#hex of the header line", "text": "#hex of body/heading text colour on that kind of page", "example_label": "text seen in the header pill, if any"}],\n'
        ' "layout": {"page": {"w": 595, "h": 842}, "col": {"x": 40, "w": 515, "top": 64, "bottom": 786}, "header": {"ruleX": 35, "ruleY": 40, "ruleW": 372, "pillX": 417, "pillY": 33, "pillW": 142, "pillH": 16, "pillSize": 7}, "footer": {"ruleX": 35, "ruleY": 801, "ruleW": 525, "textX": 35, "textY": 813, "textSize": 8, "numX": 520, "numY": 814, "numSize": 8},\n'
        '            "type": {"title": {"size": 42, "lh": 50.4}, "eyebrow": {"size": 20, "lh": 24}, "h2": {"size": 18, "lh": 21.6}, "h3": {"size": 13, "lh": 17.8}, "h4": {"size": 11, "lh": 15}, "h5": {"size": 11, "lh": 15}, "body": {"size": 11, "lh": 15}, "mark": {"size": 10, "lh": 13.7}, "toc": {"size": 18, "lh": 21.6}},\n'
        '            "gap": {"para": 3, "afterHeading": 5, "beforeHeading": 11, "beforeLabel": 10, "block": 10, "image": 5}},\n'
        ' "notes": ["anything the author should know, e.g. fonts that may not be installed"]}\n\n'
        "Roles: primary = the main accent (header pill, table header, bullets, numbers); text = body text colour; strong = heading text colour; "
        "tint = background of non-synopsis pages such as index/exercise/answers (the most common non-white page background); white = background of teaching pages; "
        "rule = header line colour; footerRule = footer line colour; tableAlt = zebra row fill; tableBorder = table border; onPrimary = text colour on the primary fill.\n"
        "case: use the measured Figma textCase for that kind of text (UPPER, LOWER, TITLE, ORIGINAL when absent); look at the images to match each role to its text. "
        "page_types: one entry per kind of page you can SEE in the images or infer from the pill labels (INDEX, EXERCISE, ANSWER KEY, WORKSHEET, MIND MAP…); body = teaching pages. Different kinds of page may have different backgrounds, and the pill, header line and text colours can change with the background (e.g. white pill and white text on a dark page). "
        "layout: the example values above are only the format (they are the defaults). Fill in the numbers you can MEASURE or clearly read from the pages, in points, and leave out any group or key you cannot determine (defaults are used for those). "
        "page = page size; col = the text column (x = left edge, w = width, top = y of the first body text, bottom = lowest y body text may reach, above the footer); header.rule* = the header line, header.pill* = the pill (x, y, width, height, text size); footer.* = footer line and the footer text and page number positions and sizes. "
        "type: size and line height (lh) in points for: title (largest display title), eyebrow (small line above a title), h2/h3/h4/h5 (heading levels from large to small), body (running text), mark (bullet marks and small numbers), toc (index entry labels). Use the measured text_styles and body_text numbers. "
        "gap: vertical spacing in points between paragraphs (para), after a heading (afterHeading), before a larger heading (beforeHeading), before a small bold label (beforeLabel), between a card/table and its neighbours (block), around small pictures (image); estimate from the pages if you can see them, else omit.\n"
        "Only use colours that appear in the measured numbers or the images. If a role is not present, take the closest sensible colour from the palette."
    )


def collect_frames(key: str, node: str | None) -> tuple[str, list[dict]]:
    """Page frames of the reference: a frame, a section, or a whole Figma page (then a few of its largest sections)."""
    if node:
        top = figma_api.nodes(key, [node], plugin_data=False, cache=True)[node]["document"]
        if top["type"] != "CANVAS":
            _, frames = figma_api.container_pages(key, node)
            return top.get("name", ""), frames
        page_name = top.get("name", "")
        secs = [c for c in top.get("children", []) if c["type"] == "SECTION"]
        frames_direct = [c for c in top.get("children", []) if c["type"] == "FRAME"]
    else:
        d = figma_api._get_cached(f"/files/{key}", {"depth": 3})
        page = max(d["document"]["children"], key=lambda pg: sum(len(c.get("children", [])) for c in pg.get("children", [])))
        page_name = page.get("name", "")
        secs = [c for c in page.get("children", []) if c["type"] == "SECTION"]
        frames_direct = [c for c in page.get("children", []) if c["type"] == "FRAME"]
    if not secs:
        return page_name, frames_direct
    ranked = sorted(secs, key=lambda c: -len([x for x in c.get("children", []) if x["type"] == "FRAME"]))[:3]
    frames: list[dict] = []
    for sec in ranked:
        full = figma_api.nodes(key, [sec["id"]], plugin_data=False, cache=True)[sec["id"]]["document"] if not sec.get("children") else sec
        fr = [c for c in full.get("children", []) if c["type"] in ("FRAME", "COMPONENT", "INSTANCE")]
        frames += pick_frames(fr, 4)
    return page_name + " / " + " + ".join(c["name"] for c in ranked), frames


WEIGHT_NUM = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "normal": 400, "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800, "black": 900, "heavy": 900}


def derive_fonts(stats: dict, typography: list) -> dict:
    """Text family and weights from the measured text styles; display family from what Claude saw in the title."""
    by_fam: Counter = Counter()
    weights: dict[str, set] = defaultdict(set)
    for t in stats.get("text_styles", []):
        if t.get("font"):
            by_fam[t["font"]] += t["count"]
            if t.get("weight"):
                weights[t["font"]].add(int(t["weight"]))
    out: dict = {}
    if by_fam:
        fam = by_fam.most_common(1)[0][0]
        ws = sorted(weights[fam]) or [400, 500, 700]

        def pick(prefs):
            return next((w for w in prefs if w in ws), ws[-1] if prefs[-1] >= 700 else ws[0])

        out["text"] = {"family": fam, "medium": pick([500, 400, 600]), "heavy": pick([800, 700, 900]), "black": pick([900, 800, 700])}
    for t in typography or []:
        if isinstance(t, dict) and t.get("role") == "title" and t.get("font") and (not out.get("text") or t["font"] != out["text"]["family"]):
            w = WEIGHT_NUM.get(re.sub(r"[^a-z]", "", str(t.get("weight", "bold")).lower()), 700)
            out["display"] = {"family": str(t["font"]), "weight": w}
            break
    return out


def apply_measured(layout: dict, g: dict) -> dict:
    """Numbers measured on the reference pages win over Claude's reading of them."""
    out = {k: dict(v) if isinstance(v, dict) and k != "type" else v for k, v in layout.items()}
    if g.get("header_rules_(x,y,w)"):
        x, y, w = g["header_rules_(x,y,w)"][0][:3]
        out["header"].update(ruleX=x, ruleY=y, ruleW=w)
    if g.get("pill_(x,y,w,h)"):
        x, y, w, h = g["pill_(x,y,w,h)"][0][:4]
        out["header"].update(pillX=x, pillY=y, pillW=w, pillH=h)
    if g.get("footer_rules_(x,y,w)"):
        x, y, w = g["footer_rules_(x,y,w)"][0][:3]
        out["footer"].update(ruleX=x, ruleY=y, ruleW=w)
    ft = sorted(g.get("footer_texts_(x,y,size,width)") or [], key=lambda t: t[0])
    if ft:
        out["footer"].update(textX=ft[0][0], textY=ft[0][1], textSize=ft[0][2])
        if len(ft) > 1:  # the page number: its right edge stays where the reference has it (the app's number box is 40 wide, right-aligned)
            n = ft[-1]
            out["footer"].update(numX=n[0] + n[3] - 40, numY=n[1], numSize=n[2])
    lefts, rights = g.get("body_text_left_edges") or [], g.get("body_text_right_edges") or []
    if lefts and rights and rights[0][0] - lefts[0][0] > 200:
        out["col"].update(x=lefts[0][0], w=rights[0][0] - lefts[0][0])
    return out


def read_reference(pid: str, url: str, models: dict, prog=None) -> dict:
    key, node = figma_api.parse_url(url)
    if prog:
        prog("Opening the reference file…", 0.05)
    cname, frames = collect_frames(key, node)
    chosen = pick_frames(frames)
    if not chosen:
        raise figma_api.FigmaError("No page-sized frames found at that link. Paste a link to a section or page of the reference book.")
    ids = [f["id"] for f in chosen]
    if prog:
        prog(f"Measuring {len(ids)} reference pages…", 0.25)
    full = figma_api.nodes(key, ids, plugin_data=False, cache=True)
    trees = [full[i]["document"] for i in ids if i in full]
    stats = measure(trees)
    import json

    stats_json = json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False)
    geom_json = json.dumps(geometry(trees), ensure_ascii=False)
    if prog:
        prog("Looking at the pages…", 0.45)
    d = config.PROJECTS / pid / "reference"
    d.mkdir(parents=True, exist_ok=True)
    shots: dict[str, Path] = {}
    png = figma_api.render_nodes(key, ids[:: max(1, len(ids) // 3)][:3], scale=1.0)
    for i, (nid, data) in enumerate(png.items()):
        p = d / f"page{i + 1}.png"
        p.write_bytes(data)
        shots[f"page{i + 1}.png"] = p
    if prog:
        prog("Working out the style…", 0.65)
    reply = llm.ask_vision(_prompt({"n_pages": len(trees), "json": stats_json, "geometry": geom_json}, list(shots)), shots, model=models.get("scan", "opus"), system=SYSTEM) if shots else llm.ask(_prompt({"n_pages": len(trees), "json": stats_json, "geometry": geom_json}, []), model=models.get("scan", "opus"), system=SYSTEM)
    r = llm.extract_json(reply)
    theme = {k: v.upper() for k, v in (r.get("theme") or {}).items() if k in THEME_KEYS and isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)}
    case = {k: v.upper() for k, v in (r.get("case") or {}).items() if k in CASE_ROLES and isinstance(v, str) and v.upper() in CASE_VALUES}
    from . import rules as _rules

    measured_layout = apply_measured(r.get("layout") or {}, json.loads(geom_json)) if isinstance(r.get("layout"), dict) else {}
    layout = _rules.layout_of({"layout": measured_layout})
    page_types = {}
    for x in r.get("page_types") or []:
        k = x.get("kind") if isinstance(x, dict) else None
        if k not in PAGE_KINDS or k in page_types:
            continue
        ok = lambda v: isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)
        e = {a: x[b].upper() for a, b in (("bg", "background"), ("pillBg", "pillBg"), ("pillFg", "pillFg"), ("rule", "rule"), ("fg", "text")) if ok(x.get(b))}
        if e.get("bg"):
            page_types[k] = e
    return {
        "url": url, "file_key": key, "node": node, "name": cname, "pages_read": len(trees),
        "theme": theme, "case": case, "typography": r.get("typography") or [], "page_types": page_types, "fonts": derive_fonts(stats, r.get("typography") or []), "layout": layout,
        "notes": [str(x) for x in (r.get("notes") or [])][:8], "page_size": stats.get("page_size"),
    }
