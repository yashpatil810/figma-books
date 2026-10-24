"""Book model -> pages. Estimates block heights and flows content onto A4 pages.

Page geometry mirrors the reference Figma: 595x842, content column x=40 w=515, top y=64,
footer rule at y=801. Nothing that is a card/table/image is ever split across pages; lists and
card groups only break between items; headings always stay with the first item that follows.
"""
from __future__ import annotations

import copy
import math

from . import measure
from .atoms import rtext

from . import rules

# All of these come from the style's layout spec (see rules.DEFAULT_LAYOUT); configure() sets them before pagination.
PAGE_W, PAGE_H = 595, 842
CONTENT_W = 515
TOP = 64
BOTTOM = 786  # content may not extend below this (footer rule sits below)
AVAIL = BOTTOM - TOP
LH = 15
BODY = 11
SIZES = {}
TYPE: dict = {}
GAP: dict = {}
CASE: dict = {}


def configure(layout: dict | None = None, case_rules: dict | None = None):
    global PAGE_W, PAGE_H, CONTENT_W, TOP, BOTTOM, AVAIL, LH, BODY, SIZES, TYPE, GAP, CASE
    CASE = {**rules.DEFAULT_CASE, **(case_rules or {})}
    L = layout or rules.DEFAULT_LAYOUT
    PAGE_W, PAGE_H = L["page"]["w"], L["page"]["h"]
    CONTENT_W, TOP, BOTTOM = L["col"]["w"], L["col"]["top"], L["col"]["bottom"]
    AVAIL = BOTTOM - TOP
    TYPE, GAP = L["type"], L["gap"]
    LH, BODY = TYPE["body"]["lh"], TYPE["body"]["size"]
    SIZES = {2: (TYPE["h2"]["size"], "din", TYPE["h2"]["lh"]), 3: (TYPE["h3"]["size"], "black", TYPE["h3"]["lh"]), 4: (TYPE["h4"]["size"], "black", TYPE["h4"]["lh"]), 5: (TYPE["h5"]["size"], "heavy", TYPE["h5"]["lh"])}


configure()

HEADING_TYPES = {"h"}


def _runs_of(x):
    if isinstance(x, str):
        return [{"t": x}]
    return x


def text_box(lines: int, lh: float) -> float:
    """Figma gives a text node a whole-pixel height (13.8pt lines come out as 14): measure the same way."""
    return math.ceil(lines * lh - 1e-6)


def cased(text: str, role: str | None) -> str:
    """The text as the renderer will case it (UPPER is much wider than typed), so widths are measured on the real string."""
    mode = CASE.get(role) if role else None
    if mode == "UPPER":
        return text.upper()
    if mode == "LOWER":
        return text.lower()
    if mode == "TITLE":
        return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))
    return text


def p_h(runs, width, size=None, lh=None, base="medium"):
    return text_box(measure.count_lines(_runs_of(runs), width, size or BODY, base), lh or LH)


def block_h(b: dict) -> float:
    t = b["t"]
    if t == "title":
        h = text_box(1, TYPE["eyebrow"]["lh"]) + 4 if b.get("eyebrow") else 0
        lines = measure.text_lines(cased(b["text"], "title"), CONTENT_W, TYPE["title"]["size"], "din")
        return h + text_box(lines, TYPE["title"]["lh"]) + 6
    if t == "h":
        size, kind, lh = SIZES[b["lvl"]]
        role = {2: "h2", 3: "h3"}.get(b["lvl"])
        return text_box(measure.text_lines(cased(b["text"], role), CONTENT_W, size, kind), lh)
    if t == "p":
        return p_h(b["runs"], CONTENT_W)
    if t == "note":
        return p_h(b["runs"], CONTENT_W)
    if t in ("ul", "ol"):
        return sum(_item_h(it, CONTENT_W - 18) for it in b["items"]) + 5 * (len(b["items"]) - 1)
    if t == "table":
        return table_h(b)
    if t == "callout":
        return callout_h(b)
    if t == "formula":
        return 12 * 2 + text_box(measure.text_lines(b["text"], CONTENT_W - 24, TYPE["h3"]["size"], "heavy"), TYPE["h3"]["lh"])
    if t == "image":
        return b["h"]
    if t == "imagerow":
        rows, x, rh, tot = 0, 0.0, 0.0, 0.0
        for it in b["items"]:
            if x and x + it["w"] > CONTENT_W:
                tot += rh + 8
                x, rh = 0.0, 0.0
            x += it["w"] + 8
            rh = max(rh, it["h"])
        return tot + rh
    if t == "qcard":
        return sum(row_h(it, b.get("cardPad")) for it in b["items"])
    if t == "mcq":
        return mcq_h(b)
    if t == "ans":
        return sum(ans_row_h(it, b.get("cardPad")) for it in b["items"])
    if t in ("toc", "end"):
        return 0
    raise ValueError(t)


def _item_h(it, width):
    if isinstance(it, dict) and "lines" in it:
        return sum(p_h(l, width) for l in it["lines"]) + 3 * (len(it["lines"]) - 1)
    return p_h(it, width)


def table_h(b):
    ws = b["widths"]
    h = text_box(1, LH) + 12 if b["head"] else 0
    for r in b["rows"]:
        lines = max(measure.text_lines(c, ws[i] - 18, BODY, "medium") for i, c in enumerate(r))
        h += max(text_box(1, LH) + 12, text_box(lines, LH) + 12)
    return h


def callout_h(b):
    inner = 0
    w = CONTENT_W - 24
    prev = None
    inner += LH + 5  # title
    for i, x in enumerate(b["blocks"]):
        inner += (3 if prev in ("p", "ul") else 5 if prev else 0)
        if x["t"] == "ul":
            inner += sum(_item_h(it, w - 18) for it in x["items"]) + 5 * (len(x["items"]) - 1)
        elif x["t"] == "ol":
            inner += sum(_item_h(it, w - 18) for it in x["items"]) + 5 * (len(x["items"]) - 1)
        else:
            inner += p_h(x["runs"], w)
        prev = x["t"]
    return inner + 24


def pics_h(pics, width=None):
    width = width or CONTENT_W - 48
    rows, x, rh, tot = 0, 0.0, 0.0, 0.0
    for it in pics:
        if x and x + it["w"] > width:
            tot += rh + 6
            x, rh = 0.0, 0.0
        x += it["w"] + 6
        rh = max(rh, it["h"])
    return tot + rh


def _pad(pad, dflt, ratio=0.7):
    """Card padding: the style gives the horizontal value; vertical keeps the component's proportion (7.5→5.25, 12→8)."""
    px = dflt if pad is None else float(pad)
    return px, round(px * ratio, 2)


def row_h(it, pad=None):
    px, py = _pad(pad, 7.5)
    w = CONTENT_W - 33 - 2 * px
    lines = it["lines"]
    h = sum(p_h(l, w) for l in lines) + 3 * max(0, len(lines) - 1)
    pics = it.get("pics") or []
    if pics:
        h += (3 if lines else 0) + pics_h(pics, w)
    return max(LH + 2 * py, h + 2 * py)


def ans_row_h(it, pad=None):
    px, py = _pad(pad, 7.5)
    w = CONTENT_W - 33 - 2 * px
    h = 0
    for i, x in enumerate(it["blocks"]):
        h += p_h(x["runs"], w) + (GAP["para"] if i else 0)
    pics = it.get("pics") or []
    if pics:
        h += (3 if it["blocks"] else 0) + pics_h(pics, w)
    return max(LH + 2 * py, h + 2 * py)


def mcq_h(b):
    n = 1 if b.get("columns") == 1 else 2
    px, py = _pad(b.get("cardPad"), 12, 2 / 3)
    w = (CONTENT_W - 2 * px) if n == 1 else (CONTENT_W - 2 * px) / 2 - 8
    rows = [b["options"][i : i + n] for i in range(0, len(b["options"]), n)]
    h = 2 * py + p_h(b["stem"], CONTENT_W - 2 * px)
    for r in rows:
        h += 3 + max(p_h(o["runs"], w) for o in r)
    return h


def b_is_big(b: dict) -> bool:
    return b["t"] == "image" and b["h"] > 140


def gap(prev: dict | None, nxt: dict) -> float:
    if prev is None:
        return 0
    pt, nt = prev["t"], nxt["t"]
    if nt == "h":
        return GAP["afterHeading"] if nxt["lvl"] == 5 else GAP["beforeHeading"] if nxt["lvl"] in (2, 3) else GAP["beforeLabel"]
    if pt == "h" or pt == "note_h":
        return GAP["afterHeading"]
    if nt in ("callout", "image", "imagerow", "formula", "qcard", "mcq", "ans", "table"):
        return GAP["block"] if nt not in ("image", "imagerow") or b_is_big(nxt) else GAP["image"]
    if pt in ("qcard", "mcq", "ans", "callout", "image", "imagerow", "table", "formula"):
        return GAP["block"] if pt not in ("image", "imagerow") or b_is_big(prev) else GAP["image"]
    return GAP["para"]


# ----------------------------------------------------------------- splitting
def splittable(b):
    return b["t"] in ("ul", "ol", "qcard", "ans")


def split_block(b, room, first_gap=0):
    """Split a list-like block so the head fits in `room`. Returns (head, rest|None)."""
    items = b["items"]
    acc, n = 0.0, 0
    for i, it in enumerate(items):
        if b["t"] in ("ul", "ol"):
            ih = _item_h(it, CONTENT_W - 18) + (5 if i else 0)
        elif b["t"] == "qcard":
            ih = row_h(it, b.get("cardPad"))
        else:
            ih = ans_row_h(it, b.get("cardPad"))
        if acc + ih > room:
            break
        acc += ih
        n += 1
    if n == 0:
        return None, b
    if n >= len(items):
        return b, None
    head = dict(b, items=items[:n])
    rest = dict(b, items=items[n:])
    rest["cont"] = True
    return head, rest


def first_unit_h(b):
    if splittable(b):
        it = b["items"][0]
        if b["t"] in ("ul", "ol"):
            return _item_h(it, CONTENT_W - 18)
        return row_h(it, b.get("cardPad")) if b["t"] == "qcard" else ans_row_h(it, b.get("cardPad"))
    return block_h(b)


def page_used(blocks: list[dict]) -> float:
    """Height already taken on a page by these blocks (gaps included)."""
    h, prev = 0.0, None
    for b in blocks:
        h += (gap(prev, b) if prev is not None else 0) + block_h(b)
        prev = b
    return h


def paginate_blocks(blocks: list[dict], first_avail: float, avail: float | None = None, prev0: dict | None = None):
    """Flow blocks onto pages. Returns (pages: list[list[block]], overflows).
    With prev0, the first page list continues an existing page (prev0 = its last block, first_avail = the room left);
    it stays empty when nothing fits there."""
    avail = AVAIL if avail is None else avail
    pages: list[list[dict]] = [[]]
    used = 0.0
    cap = first_avail
    overflow = []
    queue = list(blocks)
    prev = prev0
    while queue:
        b = queue.pop(0)
        on_page = bool(pages[-1]) or (prev0 is not None and len(pages) == 1)
        g = gap(prev, b) if on_page else 0
        h = block_h(b)
        need = g + h
        if b["t"] in HEADING_TYPES and queue:  # keep heading with what follows
            j, prv = 0, b
            while j < len(queue):
                need += gap(prv, queue[j]) + first_unit_h(queue[j])
                if queue[j]["t"] not in HEADING_TYPES:
                    break
                prv = queue[j]
                j += 1
            if need > avail:  # the pair can never share a page: place the heading now rather than alone on a fresh page
                need = g + h
        if used + need <= cap:
            pages[-1].append(b)
            used += g + h
            prev = b
            continue
        if splittable(b) and on_page:
            head, rest = split_block(b, cap - used - g)
            if head is not None:
                pages[-1].append(head)
                queue.insert(0, rest) if rest else None
                pages.append([])
                used, cap, prev = 0.0, avail, None
                continue
        if on_page:
            pages.append([])
            used, cap, prev = 0.0, avail, None
            queue.insert(0, b)
            continue
        # empty page and still too big
        if splittable(b):
            head, rest = split_block(b, cap)
            if head is None:  # a single item bigger than a page
                head, rest = dict(b, items=b["items"][:1]), (dict(b, items=b["items"][1:]) if len(b["items"]) > 1 else None)
            pages[-1].append(head)
            if rest:
                queue.insert(0, rest)
                pages.append([])
                used, cap, prev = 0.0, avail, None
            else:
                used += h
            continue
        pages[-1].append(b)
        overflow.append(b.get("src"))
        used += h
        prev = b
    if not pages[-1] and len(pages) > 1:
        pages.pop()
    return pages, overflow


def toc_entry_h(e, compact=False):
    pad, gap = (4, 4) if compact else (8, 10)
    return (TYPE["toc"]["lh"] + 2 * pad + 1 + gap) + (LH if e.get("title") else 0)


def split_toc(b):
    """The index can be longer than a page: entries flow onto continuation pages (title only on the first)."""
    head = TYPE["title"]["lh"] + 10 + TYPE["eyebrow"]["lh"] + 10 + (TYPE["eyebrow"]["lh"] + 10 if b.get("eyebrow") else 0)
    compact = len(b["entries"]) > 14
    pages, cur, used, first = [], [], head, True
    for e in b["entries"]:
        h = toc_entry_h(e, compact)
        if cur and used + h > AVAIL:
            pages.append((cur, first))
            cur, used, first = [], 0, False
        cur.append(e)
        used += h
    pages.append((cur, first))
    return [dict(b, entries=ents, cont=not f, compact=compact) for ents, f in pages]


# ----------------------------------------------------------------- book -> pages
def build_pages(book: dict) -> dict:
    """book = {meta, sections:[{kind, pill, bg, blocks, toc_key?}]} -> {pages:[...], toc anchors filled}."""
    meta = book["meta"]
    pages: list[dict] = []
    anchors: dict[str, int] = {}
    overflows = []
    page_no = 0
    toc_page = None

    for sec in book["sections"]:
        kind = sec["kind"]
        if kind == "toc":
            toc_pages = split_toc(sec["block"])
            for tp in toc_pages:
                pages.append({"kind": "toc", "bg": "tint", "pill": None, "pageNo": None, "blocks": [tp], "section": kind})
            toc_page = {"blocks": [{"entries": [e for tp in toc_pages for e in tp["entries"]]}]}
            continue
        if kind == "end":
            page_no += 1
            pages.append({"kind": "end", "bg": "tint", "pill": sec["pill"], "pageNo": page_no, "blocks": [sec["block"]], "section": kind})
            continue
        # the section's component styles decide the MCQ column count (pagination must know it)
        comps = rules.components_of(book.get("theme"), sec.get("src"))
        for topic in sec["topics"]:
            for b in topic["blocks"]:
                if b.get("t") == "mcq":
                    b["columns"] = comps["mcq"]["columns"]
                if b.get("t") in ("qcard", "mcq", "ans") and comps[b["t"]].get("pad") is not None:
                    b["cardPad"] = comps[b["t"]]["pad"]
        # a section may contain several "topics" (forced page starts); a section marked flow_on continues on the
        # previous page when that page is of the same kind (same background and pill)
        for ti, topic in enumerate(sec["topics"]):
            pill = topic.get("pill") or sec["pill"]
            last = pages[-1] if pages else None
            continuing = ti == 0 and sec.get("flow_on") and last and last["kind"] == kind and last["bg"] == sec["bg"] and last["pill"] == pill and last["blocks"]
            if continuing:
                room = AVAIL - page_used(last["blocks"])
                tpages, ov = paginate_blocks(topic["blocks"], room, AVAIL, prev0=last["blocks"][-1])
                if tpages and tpages[0]:
                    last["blocks"] += tpages[0]
                    if topic.get("anchor"):
                        anchors[topic["anchor"]] = last["pageNo"]
                    for hb in tpages[0]:
                        if hb.get("anchor") and hb["anchor"] not in anchors:
                            anchors[hb["anchor"]] = last["pageNo"]
                tpages = tpages[1:] if tpages else []
            else:
                tpages, ov = paginate_blocks(topic["blocks"], AVAIL)
            overflows += ov
            for pi, blks in enumerate(tpages):
                page_no += 1
                if topic.get("anchor") and topic["anchor"] not in anchors:
                    anchors[topic["anchor"]] = page_no
                for hb in blks:
                    if hb.get("anchor") and hb["anchor"] not in anchors:
                        anchors[hb["anchor"]] = page_no
                pages.append({"kind": kind, "bg": sec["bg"], "pill": pill, "pageNo": page_no, "blocks": blks, "section": kind, "sectionSrc": sec.get("src"), "cont": pi > 0 or bool(continuing)})
    # resolve TOC page refs
    if toc_page:
        for e in toc_page["blocks"][0]["entries"]:
            if e.get("ref"):
                e["page"] = anchors.get(e["ref"])
    for pg in pages:
        prev = None
        for b in pg["blocks"]:
            b["gap"] = gap(prev, b) if prev is not None else 0
            prev = b
    out = {"meta": meta, "theme": book.get("theme"), "pages": pages, "overflow": overflows, "anchors": anchors}
    return out
