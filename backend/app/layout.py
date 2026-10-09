"""Book model -> pages. Estimates block heights and flows content onto A4 pages.

Page geometry mirrors the reference Figma: 595x842, content column x=40 w=515, top y=64,
footer rule at y=801. Nothing that is a card/table/image is ever split across pages; lists and
card groups only break between items; headings always stay with the first item that follows.
"""
from __future__ import annotations

import copy

from . import measure
from .atoms import rtext

PAGE_W, PAGE_H = 595, 842
CONTENT_W = 515
TOP = 64
BOTTOM = 786  # content may not extend below this (footer rule sits at 801)
AVAIL = BOTTOM - TOP

LH = 15
SIZES = {2: (18, "din", 21.6), 3: (13, "black", 17.8), 4: (11, "black", 15), 5: (11, "heavy", 15)}

HEADING_TYPES = {"h"}


def _runs_of(x):
    if isinstance(x, str):
        return [{"t": x}]
    return x


def p_h(runs, width, size=11, lh=LH, base="medium"):
    return measure.count_lines(_runs_of(runs), width, size, base) * lh


def block_h(b: dict) -> float:
    t = b["t"]
    if t == "title":
        h = 24 + 4 if b.get("eyebrow") else 0
        lines = measure.text_lines(b["text"], CONTENT_W, 42, "din")
        return h + lines * 50.4 + 6
    if t == "h":
        size, kind, lh = SIZES[b["lvl"]]
        return measure.text_lines(b["text"], CONTENT_W, size, kind) * lh
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
        return 12 * 2 + 17.8 * measure.text_lines(b["text"], CONTENT_W - 24, 13, "heavy")
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
        return sum(row_h(it) for it in b["items"])
    if t == "mcq":
        return mcq_h(b)
    if t == "ans":
        return sum(ans_row_h(it) for it in b["items"])
    if t in ("toc", "end"):
        return 0
    raise ValueError(t)


def _item_h(it, width):
    if isinstance(it, dict) and "lines" in it:
        return sum(p_h(l, width) for l in it["lines"]) + 3 * (len(it["lines"]) - 1)
    return p_h(it, width)


def table_h(b):
    ws = b["widths"]
    h = 27 if b["head"] else 0
    for r in b["rows"]:
        lines = max(measure.text_lines(c, ws[i] - 18, 11, "medium") for i, c in enumerate(r))
        h += max(27, lines * LH + 12)
    return h


def callout_h(b):
    inner = 0
    w = CONTENT_W - 24
    prev = None
    inner += 15 + 5  # title
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


def pics_h(pics, width=467):
    rows, x, rh, tot = 0, 0.0, 0.0, 0.0
    for it in pics:
        if x and x + it["w"] > width:
            tot += rh + 6
            x, rh = 0.0, 0.0
        x += it["w"] + 6
        rh = max(rh, it["h"])
    return tot + rh


def row_h(it):
    lines = it["lines"]
    h = sum(p_h(l, 467) for l in lines) + 3 * max(0, len(lines) - 1)
    pics = it.get("pics") or []
    if pics:
        h += (3 if lines else 0) + pics_h(pics)
    return max(25, h + 10.5)


def ans_row_h(it):
    h = 0
    for i, x in enumerate(it["blocks"]):
        h += p_h(x["runs"], 467) + (3 if i else 0)
    pics = it.get("pics") or []
    if pics:
        h += (3 if it["blocks"] else 0) + pics_h(pics)
    return max(25, h + 10.5)


def mcq_h(b):
    w = (CONTENT_W - 24) / 2 - 8
    rows = [b["options"][i : i + 2] for i in range(0, len(b["options"]), 2)]
    h = 16 + p_h(b["stem"], CONTENT_W - 24)
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
        return 5 if nxt["lvl"] == 5 else 11 if nxt["lvl"] in (2, 3) else 10
    if pt == "h" or pt == "note_h":
        return 5
    if nt in ("callout", "image", "imagerow", "formula", "qcard", "mcq", "ans", "table"):
        return 10 if nt not in ("image", "imagerow") or b_is_big(nxt) else 5
    if pt in ("qcard", "mcq", "ans", "callout", "image", "imagerow", "table", "formula"):
        return 10 if pt not in ("image", "imagerow") or b_is_big(prev) else 5
    return 3


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
            ih = row_h(it)
        else:
            ih = ans_row_h(it)
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
        return row_h(it) if b["t"] == "qcard" else ans_row_h(it)
    return block_h(b)


def paginate_blocks(blocks: list[dict], first_avail: float, avail: float = AVAIL):
    """Flow blocks onto pages. Returns (pages: list[list[block]], overflows)."""
    pages: list[list[dict]] = [[]]
    used = 0.0
    cap = first_avail
    overflow = []
    queue = list(blocks)
    prev = None
    while queue:
        b = queue.pop(0)
        g = gap(prev, b) if pages[-1] else 0
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
        if used + need <= cap:
            pages[-1].append(b)
            used += g + h
            prev = b
            continue
        if splittable(b) and pages[-1]:
            head, rest = split_block(b, cap - used - g)
            if head is not None:
                pages[-1].append(head)
                queue.insert(0, rest) if rest else None
                pages.append([])
                used, cap, prev = 0.0, avail, None
                continue
        if pages[-1]:
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
            toc_page = {"kind": "toc", "bg": "tint", "pill": None, "pageNo": None, "blocks": [sec["block"]], "section": kind}
            pages.append(toc_page)
            continue
        if kind == "end":
            page_no += 1
            pages.append({"kind": "end", "bg": "tint", "pill": sec["pill"], "pageNo": page_no, "blocks": [sec["block"]], "section": kind})
            continue
        # a section may contain several "topics" (forced page breaks)
        for ti, topic in enumerate(sec["topics"]):
            pill = topic.get("pill") or sec["pill"]
            tpages, ov = paginate_blocks(topic["blocks"], AVAIL)
            overflows += ov
            for pi, blks in enumerate(tpages):
                page_no += 1
                if pi == 0 and topic.get("anchor"):
                    anchors[topic["anchor"]] = page_no
                pages.append({"kind": kind, "bg": sec["bg"], "pill": pill, "pageNo": page_no, "blocks": blks, "section": kind, "cont": pi > 0})
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
