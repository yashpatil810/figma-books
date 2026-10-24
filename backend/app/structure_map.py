"""Read a doc for meaning: Claude labels the structural lines of the doc, code typesets them verbatim.

Claude never returns text. It returns block ids with labels (front matter, index list, section start + role, heading +
level). `structure_generic` then builds the pages from those labels, so every word still comes from the doc.
The map is cached per document and is shown on the Structure screen, where the author can correct it.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import llm, store
from .gdoc import block_text

ROLES = ("body", "exercise", "answers", "mindmap", "references", "glossary")
ONE_CALL_CHARS = 140_000  # the whole outline goes to Claude in one call unless the doc is enormous
CHUNK_LINES = 1200
NUMBERED_RE = re.compile(r"^\s*(\(?\d+[.)]|\(?[A-Za-z][.)]|part\b|level\b|section\b|topic\b|case study\b|chapter\b|unit\b|exercise\b|worksheet\b|answer)", re.I)

SYSTEM = ("You read school-book chapters written in a Google Doc and decide how they become book pages. "
          "You never rewrite or quote text: you only label lines by their id. Be consistent and conservative.")


def doc_hash(blocks: list[dict]) -> str:
    h = hashlib.sha256()
    for b in blocks:
        h.update((b["id"] + "|" + block_text(b)[:200]).encode())
    return h.hexdigest()[:16]


def _is_bold(b: dict) -> bool:
    runs = [r for r in b.get("runs", []) if r["t"].strip()]
    return bool(runs) and all(r.get("b") for r in runs)


def outline_lines(blocks: list[dict]) -> list[str]:
    """One compact line per candidate block; runs of plain body paragraphs collapse into a counter line."""
    out: list[str] = []
    run: list[dict] = []

    def flush():
        nonlocal run
        if run:
            n_img = sum(1 for x in run if x["t"] == "img")
            n_p = len(run) - n_img
            out.append(f"   … {n_p} body lines" + (f", {n_img} images" if n_img else "") + f" ({run[0]['id']}–{run[-1]['id']})")
            run = []

    for b in blocks:
        if b["t"] == "img":
            run.append(b)
            continue
        if b["t"] == "tbl":
            flush()
            rows = b.get("rows") or []
            head = " / ".join(str(c).strip()[:18] for c in (rows[0] if rows else [])[:6])
            out.append(f"{b['id']} TABLE {len(rows)} rows | {head[:90]}")
            continue
        t = block_text(b).strip()
        if not t:
            continue
        flags = []
        if b["t"] == "h":
            flags.append(f"H{b.get('level', 1)}")
        if _is_bold(b):
            flags.append("B")
        if b.get("jc") == "center":
            flags.append("C")
        if b.get("list"):
            flags.append("L")
        cand = bool(flags) and not (flags == ["L"]) or len(t) <= 70 or bool(NUMBERED_RE.match(t))
        if flags == ["L"] and len(t) > 70:
            cand = False
        if not cand:
            run.append(b)
            continue
        flush()
        out.append(f"{b['id']} {''.join(f + ' ' for f in flags)}| {t[:80]}")
    flush()
    return out


def _chunks(lines: list[str]) -> list[list[str]]:
    if sum(len(x) + 1 for x in lines) <= ONE_CALL_CHARS:
        return [lines]
    chunks, cur = [], []
    for ln in lines:
        cur.append(ln)
        if len(cur) >= CHUNK_LINES and not ln.startswith("   …"):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _prompt(chunk: list[str], first: bool, so_far: list[dict], idx_open: bool) -> str:
    ctx = ""
    if so_far:
        ctx = "Sections decided so far (latest last): " + "; ".join(f"{s['src']} {s['role']} “{s['title'][:40]}”" for s in so_far[-8:]) + ".\n"
    if idx_open:
        ctx += "The doc's index/contents list was still open at the end of the previous part: keep labelling its lines as index_entry until it ends.\n"
    return (
        "Below is an outline of part of a chapter, one line per block: `id FLAGS| text`. FLAGS: H1-H6 = Word heading style, B = whole line bold, C = centred, L = list item. "
        "Lines like `… 12 body lines (b0100–b0111)` stand for ordinary paragraphs or images that need no label. A line `b0123 TABLE 5 rows | cell / cell…` is a table (its first row is shown).\n\n"
        + ctx +
        "Label only the structural lines. Reply with JSON only:\n"
        '{"front": {"eyebrow": id|null, "title": id|null, "index_heading": id|null, "index_table": id|null},  // ONLY in the first part, otherwise omit\n'
        ' "marks": [ {"id": "b0004", "as": "index_entry"}, {"id": "b0045", "as": "section", "role": "body", "pill": "optional, only for non-body sections", "new_page": true}, {"id": "b0046", "as": "heading", "level": 2, "new_page": false} ]}\n\n'
        "as =\n"
        "- index_entry: a line inside the doc's own index/contents list near the start (label EVERY line of that list, including entries that repeat names of later sections). If the index is written as a TABLE instead of lines, put that table's id in front.index_table and do not label index_entry lines.\n"
        "- section: where a major part of the book really starts, in the real content (never in the index list). role = body (teaching content: Part 1, Part 2… of the chapter; mark every Part-level line of teaching content; the first teaching section starts at the first real content line after the index, e.g. 'Chapter Learning Objectives' or the first Part) | exercise (questions, practice, assignments, worksheets: use pill WORKSHEET for a worksheet) | answers (answer keys, solutions, hints) | mindmap | references | glossary.\n"
        "  An answer key does not always have a heading: a closing part made of short caption lines (e.g. 'Level 1 — Single-correct MCQs') each followed by a table whose header looks like Q. / Key / Correct options / Topic 1… (a table of answer keys) is the answer key, even though the doc never says 'answer key'; mark its FIRST caption line as section role answers (pill ANSWER KEY).\n"
        "- heading: a heading inside a section. level 1 = main topic (e.g. '1. Introduction to …'), 2 = sub-topic ('1.2 Types of …'), 3 = smaller heading, 4 = small bold label. Mark Word headings and heading-like bold lines; do not mark question lines, list items or sentences.\n"
        "Rules: a line listed in the index is an index_entry, never a section. Sub-groups of an exercise (Level 1, Topic 1, Single correct MCQs, Case study 1) are headings inside the exercise section, unless a clearly separate part begins (then a new section). "
        "If the doc has no index list, return no index_entry. Unmarked lines are normal text. Read the WHOLE outline before deciding: the index at the start tells you which parts exist, and an answer key is usually at the very end.\n"
        "- new_page (on every section and heading you mark): whether this part begins at the top of a fresh page. Decide it as the book's designer would, weighing how important and how long the part is against the empty space a page break leaves at the bottom of the previous page. Facts: a page holds about 45 body lines; the `… N body lines` counts show how long each part is; a change of page type (teaching content ↔ exercise ↔ answer key) always starts a page automatically, so you only decide for parts that follow a part of the same type. Give new_page for every section; for headings you may omit it when false.\n"
        + ('For this first part also fill "front": eyebrow = a small line above the title such as grade/board/subject (null if none); title = the chapter title line (it may sit just under the INDEX heading); index_heading = the word INDEX/CONTENTS heading if present; index_table = the id of the index table if the index is a table. ' if first else "")
        + "\n\nOUTLINE:\n" + "\n".join(chunk)
    )


def read_map(pid: str, blocks: list[dict], models: dict, prog=None) -> dict:
    ids = {b["id"] for b in blocks}
    order = {b["id"]: i for i, b in enumerate(blocks)}
    lines = outline_lines(blocks)
    chunks = _chunks(lines)
    marks: dict[str, dict] = {}
    front: dict = {}
    sections: list[dict] = []
    idx_open = False
    for ci, chunk in enumerate(chunks):
        if prog:
            prog(f"Reading the document for meaning (part {ci + 1} of {len(chunks)})…", ci / len(chunks))
        reply = llm.ask_json(_prompt(chunk, ci == 0, sections, idx_open), model=models.get("structure", "sonnet"), system=SYSTEM)
        if not isinstance(reply, dict):
            reply = {"marks": llm.as_list(reply)}
        if ci == 0 and isinstance(reply.get("front"), dict):
            front = {k: (v if v in ids else None) for k, v in reply["front"].items() if k in ("eyebrow", "title", "index_heading", "index_table")}
        last_kind = None
        for m in llm.as_list(reply.get("marks")):
            if not isinstance(m, dict) or m.get("id") not in ids:
                continue
            kind = m.get("as")
            if kind not in ("index_entry", "section", "heading"):
                continue
            rec = {"as": kind}
            if kind == "section":
                rec["role"] = m.get("role") if m.get("role") in ROLES else "body"
                if m.get("pill"):
                    rec["pill"] = str(m["pill"])[:28].upper()
            if kind == "heading":
                try:
                    rec["level"] = max(1, min(4, int(m.get("level", 2))))
                except (TypeError, ValueError):
                    rec["level"] = 2
            if kind in ("section", "heading") and isinstance(m.get("new_page"), bool):
                rec["new_page"] = m["new_page"]
            marks[m["id"]] = rec
            last_kind = kind
            if kind == "section":
                sections.append({"src": m["id"], "role": rec["role"], "title": next((block_text(b) for b in blocks if b["id"] == m["id"]), "")})
        idx_open = last_kind == "index_entry"
    return finish(blocks, front, marks, order)


def finish(blocks: list[dict], front: dict, marks: dict, order: dict | None = None) -> dict:
    order = order or {b["id"]: i for i, b in enumerate(blocks)}
    text = {b["id"]: block_text(b).strip() for b in blocks}
    entries = sorted([i for i, m in marks.items() if m["as"] == "index_entry"], key=order.get)
    # the index list is the contiguous region of entries; a "section" mark inside it is really an index line
    if entries:
        lo, hi = order[entries[0]], order[entries[-1]]
        for i, m in list(marks.items()):
            if m["as"] != "index_entry" and lo <= order[i] <= hi:
                marks[i] = {"as": "index_entry"}
        entries = sorted([i for i, m in marks.items() if m["as"] == "index_entry"], key=order.get)
    secs = sorted([i for i, m in marks.items() if m["as"] == "section"], key=order.get)
    heads = sorted([i for i, m in marks.items() if m["as"] == "heading"], key=order.get)
    return {
        "version": 1, "doc_hash": doc_hash(blocks), "front": front, "index_entries": entries,
        "sections": [{"src": i, "role": marks[i]["role"], "title": text[i], **({"pill": marks[i]["pill"]} if marks[i].get("pill") else {}), **({"new_page": marks[i]["new_page"]} if "new_page" in marks[i] else {})} for i in secs],
        "headings": [{"src": i, "level": marks[i]["level"], "title": text[i], **({"new_page": True} if marks[i].get("new_page") else {})} for i in heads],
    }


def load(pid: str, blocks: list[dict]) -> dict | None:
    m = store.read(pid, "structure_map.json")
    if not m or m.get("doc_hash") != doc_hash(blocks):
        return None  # the doc changed since the map was made: read it again
    return m


def save(pid: str, m: dict):
    store.write(pid, "structure_map.json", m)
