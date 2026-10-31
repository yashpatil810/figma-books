"""Generic, heading-driven reading of a chapter (no fixed template).

Rules of the road (same as the synopsis engine):
  * text is copied verbatim from doc blocks; nothing is ever dropped (leftovers become plain content);
  * sections are found by the document's own headings and by recognisable names (exercise / answers /
    mind map / references / glossary), never required to exist;
  * every guess is surfaced in `outline`/`dividers` so the user can override how a heading is read.
"""
from __future__ import annotations

import difflib
import re

from .atoms import atom_text, build_atoms
from .gdoc import block_text
from .structure import (
    Q_RE,
    apply_fixes,
    group_lists,
    norm,
    para,
    qstream,
)

ROLE_PATTERNS = [
    ("answers", r"\b(answers?|solutions?|hints?)\b|\banswer keys?\b"),
    ("mindmap", r"mind ?map|concept map"),
    ("references", r"\breferences?\b|bibliograph|further reading|\bsources?\b"),
    ("glossary", r"\bglossary\b|\bkey terms\b"),
    ("exercise", r"\b(level|exercise|practice|test|questions?|assignment|worksheet|quiz|problems?|concept application|revision|mcq)\b"),
]
ROLES = ["body", "exercise", "answers", "mindmap", "references", "glossary", "inline", "ignore"]
TINT_KINDS = {"exercise", "answers", "mindmap", "references", "glossary"}
FRONT_RE = re.compile(r"^(chapter|unit|lesson|module|index|contents|table of contents|toc|ch)\b", re.I)
INDEX_RE = re.compile(r"^(index|contents|table of contents|toc)\s*:?$", re.I)
TITLE_RE = re.compile(r"^(chapter|unit|lesson|ch)\b", re.I)
EYEBROW_RE = re.compile(r"^(module|unit|grade|class|subject|part)\b", re.I)


def role_guess(text: str) -> str | None:
    t = text.lower()
    for role, pat in ROLE_PATTERNS:
        if re.search(pat, t):
            return role
    return None


def _idx_key(t: str) -> str:
    """Index line / heading -> comparable key: no list numbers, no 'Part 3:' prefix."""
    t = re.sub(r"^\s*(part|chapter|unit|section|topic)\s*\d+\s*[:.\-–—]?\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*\(?\w{1,3}[.)]\s*", "", t)
    return norm(t)


def split_topics(blocks: list[dict], breaks: dict, anchor: str) -> list[dict]:
    """Cut a section's blocks into topics (forced page starts) wherever a heading was marked new_page — or wherever the
    author asked for a page to start before a particular line (a table, a paragraph, a list, a picture, a card: any block
    whose first doc line carries a page_breaks override)."""
    topics: list[dict] = [{"blocks": [], "anchor": anchor}]
    for b in blocks:
        src0 = (b.get("src") or [None])[0]
        if topics[-1]["blocks"] and src0 and breaks.get(src0):
            topics.append({"blocks": [], "anchor": None})
        topics[-1]["blocks"].append(b)
    return [t for t in topics if t["blocks"]] or [{"blocks": blocks, "anchor": anchor}]


INDEX_HEADER_CELL_RE = re.compile(r"^(s\.?\s*no\.?|sr\.?\s*no\.?|sl\.?\s*no\.?|no\.?|#|contents?|topics?|titles?|chapters?|sections?|names?|description|page\s*(no\.?|numbers?)?|pg\.?\s*(no\.?)?|pages?)$", re.I)
INDEX_CONTENT_CELL_RE = re.compile(r"^(contents?|topics?|titles?|chapters?|sections?|names?|description)$", re.I)
NUMERAL_RE = re.compile(r"^\(?([0-9]+|[ivxlc]+|[a-z])[.)]?$", re.I)


def index_table_entries(rows: list[list]) -> tuple[list[str], str | None]:
    """An index written as a table -> (entry labels, caption). The caption is a first row with a single filled cell when
    other rows have several (e.g. the chapter title above “S.NO / CONTENT / PAGE NO”). The content column comes from a
    header row (CONTENT, TOPIC, TITLE…); without one, each row's first cell that is not a bare serial number is the entry.
    Header rows, the caption and empty rows give no entry. Only whitespace is normalised; the words stay as typed."""
    rows = [[" ".join(str(c).split()) for c in r] for r in rows]
    caption, col, out = None, None, []
    multi = any(len([c for c in r if c]) >= 2 for r in rows)
    for i, r in enumerate(rows):
        filled = [c for c in r if c]
        if not filled:
            continue
        if i == 0 and multi and len(filled) == 1 and len(rows) > 1:
            caption = filled[0]
            continue
        if all(INDEX_HEADER_CELL_RE.match(c) for c in filled):
            for ci, c in enumerate(r):
                if INDEX_CONTENT_CELL_RE.match(c):
                    col = ci
            continue
        label = r[col] if col is not None and col < len(r) and r[col] else next((c for c in filled if not NUMERAL_RE.match(c)), "")
        if label and not NUMERAL_RE.match(label):
            out.append(label)
    return out, caption


def _title_core(t: str) -> str:
    return norm(re.sub(r"^(chapter|unit|lesson|ch)\s*\d*\s*[:.\-–]?\s*", "", t, flags=re.I))


def build_book_generic(blocks: list[dict], meta: dict, fixes: list | None = None, overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    blocks = apply_fixes(blocks, fixes or [])
    issues: list[dict] = []
    ignored: list[dict] = []
    atoms = build_atoms(blocks)
    book_meta = {k: v for k, v in meta.items() if k not in ("structure_map", "roles")}

    def ign(src, why):
        ignored.append({"id": src, "reason": why})

    smap = meta.get("structure_map")
    strict = bool(smap and smap.get("sections"))
    index_entry_atoms: list[dict] = []
    idx_tbl = None  # the doc's index written as a table (its CONTENT column becomes the index entries)
    index_caption = None

    # ------------------------------------------------------------ front matter
    if strict:
        fr = smap.get("front") or {}
        first_of = {}
        for a in atoms:
            first_of.setdefault(a["src"], a)
        title_atom = first_of.get(fr.get("title"))
        eyebrow_atom = first_of.get(fr.get("eyebrow"))
        idx_atom = first_of.get(fr.get("index_heading"))
        entry_ids = set(smap.get("index_entries") or [])
        index_entry_atoms = [a for a in atoms if a["src"] in entry_ids]
        idx_tbl = fr.get("index_table")
        if idx_tbl and not index_entry_atoms:
            tb = next((a for a in atoms if a["src"] == idx_tbl and a["k"] == "tbl"), None)
            if tb:  # one pseudo-atom per entry row
                labels, index_caption = index_table_entries(tb["rows"])
                for label in labels:
                    index_entry_atoms.append({"k": "p", "src": idx_tbl, "runs": [{"t": label}], "bold": False})
                entry_ids.add(idx_tbl)
                # the serial numbers and column headers of the table are not shown; the verifier must not expect them
                ign(idx_tbl, "index table: its entries are listed on the index page (serial numbers and column headers are not shown)")
            else:
                idx_tbl = None
        used_front = {a["src"] for a in (title_atom, eyebrow_atom, idx_atom) if a} | entry_ids
        last = max((i for i, a in enumerate(atoms) if a["src"] in used_front), default=-1)
        for a in atoms[: last + 1]:  # anything else before the first real content (decorative images, stray lines)
            if a["src"] in used_front:
                continue
            ign(a["src"], "decorative image/line before the chapter" if a["k"] == "img" else "front-matter line not used on pages")
        body_atoms = atoms[last + 1 :]
        title_text = atom_text(title_atom).strip() if title_atom else ""
    else:
        i = 0
        front: list[dict] = []
        while i < len(atoms):
            a = atoms[i]
            t = atom_text(a).strip() if a["k"] in ("p", "h", "li") else ""
            is_front_line = a["k"] in ("p", "h") and t and (FRONT_RE.match(t) or EYEBROW_RE.match(t) or INDEX_RE.match(t)) and len(t) <= 90
            if is_front_line:
                front.append(a)
                i += 1
                continue
            if a["k"] == "img" and not front:  # decorative lines/images before everything
                front.append(a)
                i += 1
                continue
            break
        body_atoms = atoms[i:]

        idx_atom = next((a for a in front if a["k"] in ("p", "h") and INDEX_RE.match(atom_text(a).strip())), None)
        title_atom = next((a for a in front if a["k"] in ("p", "h") and TITLE_RE.match(atom_text(a).strip())), None)
        eyebrow_atom = next((a for a in front if a["k"] in ("p", "h") and a is not title_atom and EYEBROW_RE.match(atom_text(a).strip())), None)
        title_text = atom_text(title_atom).strip() if title_atom else ""
        for a in front:
            if a is title_atom or a is eyebrow_atom or a is idx_atom:
                continue
            if a["k"] == "img":
                ign(a["src"], "decorative image/line before the chapter title")
            elif title_atom and _title_core(atom_text(a)) == _title_core(title_text):
                ign(a["src"], "repeats the chapter title (shown once)")
                issues.append({"code": "front-duplicate", "blocks": [a["src"]], "severity": "info", "blocking": False, "message": f"“{atom_text(a).strip()}” repeats the chapter title, so it is shown once."})
            else:
                ign(a["src"], "front-matter line not used on pages")
                issues.append({"code": "front-line", "blocks": [a["src"]], "severity": "question", "blocking": False, "message": f"“{atom_text(a).strip()}” is at the top of the doc but has no place in the page design. It is left out of the pages. Tell me if it should appear somewhere.", "suggestion": "Confirm it can be left out."})

    # ------------------------------------------------------------ dividers (page-start headings)
    h1_count = sum(1 for a in body_atoms if a["k"] == "h" and a["level"] == 1)
    dividers = []  # {idx, src, text, level, role, auto}
    map_roles = {x["src"]: x["role"] for x in (smap or {}).get("sections", [])} if strict else {}
    map_pills = {x["src"]: x["pill"] for x in (smap or {}).get("sections", []) if x.get("pill")} if strict else {}
    map_heads = {x["src"]: x["level"] for x in (smap or {}).get("headings", [])} if strict else {}
    if strict:
        overrides = {**map_roles, **overrides}  # the author's own choices win over the map
    for ix, a in enumerate(body_atoms):
        t = atom_text(a).strip() if a["k"] in ("h", "p") else ""
        if not t:
            continue
        styled = a["k"] == "h"
        lvl = a["level"] if styled else 9
        role = role_guess(t) if len(t) <= 70 else None
        capsline = a["k"] == "p" and (a.get("bold") or t.isupper()) and len(t) <= 40 and not Q_RE.match(t)
        cand = None
        if strict:
            pass  # sections come from the map (and the author's overrides) only
        elif styled and role in ("answers", "mindmap", "references", "glossary", "exercise"):
            cand = role
        elif styled and lvl == 1 and h1_count >= 2:
            cand = "body"
        elif capsline and role in ("answers", "mindmap", "references", "glossary"):
            cand = role
        elif capsline and role == "exercise" and t.isupper():
            cand = role
        ov = overrides.get(a["src"])
        if ov:
            cand = None if ov == "inline" else ov
        if cand:
            dividers.append({"idx": ix, "src": a["src"], "text": t, "level": 1 if strict else lvl, "role": cand, "auto": ov is None or (strict and ov == map_roles.get(a["src"]))})

    # nesting: a lower-importance heading inside an exercise/answers section stays inside it
    secs: list[dict] = []
    cur = None
    for d in dividers:
        same_kind = d["role"] == cur["role"] if cur else False
        inside_answers = bool(cur) and cur["role"] == "answers" and d["role"] == "exercise"
        if not strict and cur and d["level"] > cur["level"] and cur["role"] in ("exercise", "answers") and (same_kind or inside_answers):
            continue  # a lower-importance heading of the same kind stays inside the current section
        role = d["role"]
        if not strict and cur and cur["role"] == "answers" and role == "exercise" and d["level"] == cur["level"] and d["auto"]:
            role = "answers"  # "Level - 2" under "Answer Keys" holds the answers for that level
        secs.append({**d, "role": role})
        cur = secs[-1]

    # Where a new page starts is Claude's decision (new_page on sections and headings), overridable per line by the author.
    # Only a change of page type (background / pill) forces a page on its own. Without a map: every section starts a page
    # and consecutive teaching parts flow on, as before.
    part_srcs: set[str] = set()
    breaks: dict[str, bool] = {}
    if strict:
        for x in smap.get("sections", []):
            if "new_page" in x:
                breaks[x["src"]] = bool(x["new_page"])
        for x in smap.get("headings", []):
            if x.get("new_page"):
                breaks[x["src"]] = True
    for k, v in (meta.get("page_breaks") or {}).items():
        breaks[k] = bool(v)
    prev_d = None
    for d in secs:
        same_kind = prev_d is not None and prev_d["role"] == d["role"] and d["role"] != "ignore"
        wants = breaks.get(d["src"])
        if wants is None:
            wants = not (strict and d["role"] == "body" and same_kind)  # default: teaching parts flow on, everything else starts a page
        d["flow_on"] = same_kind and not wants
        if d["role"] != "ignore":
            prev_d = d

    # ------------------------------------------------------------ heading levels -> visual rank
    divider_srcs = {d["src"] for d in secs}
    body_levels = sorted({a["level"] for a in body_atoms if a["k"] == "h" and a["src"] not in divider_srcs and a["level"] >= 1})
    rank_style = {}
    for r, lvl in enumerate(body_levels):
        rank_style[lvl] = min(5, 2 + r)

    def flow(atom_slice):
        """Plain flow for body-like sections: headings, paragraphs, lists, tables, images."""
        out: list[dict] = []
        pend: list[dict] = []

        def flush():
            nonlocal pend
            if pend:
                out.extend(group_lists(pend, None))
                pend = []

        for a in atom_slice:
            t = atom_text(a).strip() if a["k"] in ("p", "h") else ""
            if a["src"] in part_srcs and a["k"] in ("p", "h") and t:
                flush()
                out.append({"t": "title", "text": t, "src": [a["src"]], "anchor": "h:" + a["src"], "gen_eyebrow": False})
            elif a["k"] == "h":
                flush()
                lv = map_heads.get(a["src"])
                out.append({"t": "h", "lvl": min(5, 1 + lv) if lv else rank_style.get(a["level"], 4), "text": atom_text(a), "src": [a["src"]], "anchor": "h:" + a["src"]})
            elif a["k"] == "p" and a["src"] in map_heads and t:
                flush()
                out.append({"t": "h", "lvl": min(5, 1 + map_heads[a["src"]]), "text": atom_text(a), "src": [a["src"]], "anchor": "h:" + a["src"]})
            elif a["k"] == "p" and a.get("bold") and not a.get("center") and 0 < len(t) <= 120 and not Q_RE.match(t) and not re.search(r"[.?!]$", t):
                flush()
                out.append({"t": "h", "lvl": 4, "text": atom_text(a), "src": [a["src"]]})
            else:
                pend.append(a)
        flush()
        merged = []  # adjacent bullet lists -> one list
        for b in out:
            if merged and b["t"] == "ul" and merged[-1]["t"] == "ul":
                merged[-1]["items"] += b["items"]
                merged[-1]["src"] += b["src"]
            else:
                merged.append(b)
        return merged

    # ------------------------------------------------------------ sections
    sections: list[dict] = []
    outline: list[dict] = []
    chapter_short = title_text.split(":", 1)[1].strip() if ":" in title_text else title_text
    first_div = secs[0]["idx"] if secs else len(body_atoms)

    # chapter body (everything before the first divider)
    lead = body_atoms[:first_div]
    title_block = None
    if title_atom:
        title_block = {"t": "title", "eyebrow": atom_text(eyebrow_atom).strip() if eyebrow_atom else None, "text": title_text, "gen_eyebrow": False, "src": [title_atom["src"]] + ([eyebrow_atom["src"]] if eyebrow_atom else [])}
    if lead or (title_block and not strict):
        blks = ([title_block] if title_block else []) + flow(lead)
        sections.append({"kind": "body", "bg": "white", "pill": (chapter_short or "").upper() or None, "topics": split_topics(blks, breaks, "body")})
        outline.append({"kind": "body", "title": title_text or "Chapter content", "src": title_atom["src"] if title_atom else None, "blocks": len(lead)})

    for si, sc in enumerate(secs):
        end = secs[si + 1]["idx"] if si + 1 < len(secs) else len(body_atoms)
        content = body_atoms[sc["idx"] + 1 : end]
        kind = sc["role"]
        if kind == "ignore":
            for a in body_atoms[sc["idx"] : end]:
                ign(a["src"], "left out at your request")
            continue
        if kind in ("exercise",):
            blks = qstream(content, "q", issues)
        elif kind == "answers":
            blks = qstream(content, "a", issues)
        else:
            blks = flow(content)
        for hb in blks:
            if hb.get("t") == "h" and hb.get("src") and "anchor" not in hb:
                hb["anchor"] = "h:" + hb["src"][0]
        head = {"t": "title", "text": sc["text"], "gen_eyebrow": False, "src": [sc["src"]], "anchor": "h:" + sc["src"]}
        pill = sc["text"].upper() if len(sc["text"]) <= 40 else sc["text"][:40].upper()
        if strict:
            pill = ((chapter_short or "").upper() if kind == "body" else map_pills.get(sc["src"]) or {"exercise": "EXERCISE", "answers": "ANSWER KEY", "mindmap": "MIND MAP", "references": "REFERENCES", "glossary": "GLOSSARY"}.get(kind, kind.upper())) or pill
        topics = split_topics([head] + blks, breaks, f"sec{si}")
        sections.append({"kind": kind, "bg": "tint" if kind in TINT_KINDS else "white", "pill": pill, "topics": topics, "flow_on": bool(sc.get("flow_on")), "src": sc["src"]})
        outline.append({"kind": kind, "title": sc["text"], "src": sc["src"], "blocks": len(content)})

    # ------------------------------------------------------------ index page + end page
    ordered: list[dict] = []
    if strict and index_entry_atoms and (idx_atom or idx_tbl):
        targets = [(_idx_key(sc["text"]), f"sec{si}") for si, sc in enumerate(secs) if sc["role"] != "ignore"]
        targets += [(_idx_key(x["title"]), "h:" + x["src"]) for x in (smap or {}).get("headings", []) if x.get("title")]
        targets += [(_idx_key(x["title"]), "h:" + x["src"]) for x in (smap or {}).get("sections", []) if x["src"] in part_srcs]
        all_pos = {a["src"]: i for i, a in enumerate(body_atoms)}
        targets.sort(key=lambda t: all_pos.get(t[1][2:], 0) if t[1].startswith("h:") else secs[int(t[1][3:])]["idx"])
        entries, cursor, unmatched = [], 0, 0
        for a in index_entry_atoms:
            label = atom_text(a).strip()
            key = _idx_key(label)
            ref = None
            best, bj = 0.0, None
            for j in range(cursor, min(len(targets), cursor + 120)):  # in reading order: the best match in the next stretch
                if not targets[j][0]:
                    continue
                r = difflib.SequenceMatcher(None, key, targets[j][0]).ratio()
                kw, tw = set(key.split()), set(targets[j][0].split())
                if kw and (kw <= tw or tw <= kw) and min(len(kw), len(tw)) >= 2:
                    r = max(r, 0.8)
                if r > best:
                    best, bj = r, j
            if bj is not None and best >= 0.66:
                ref, cursor = targets[bj][1], bj + 1
            if ref is None:  # lines that name a kind of section ("answer keys", "practice questions") point at the first one of that kind
                role_hit = "answers" if re.search(r"answer|solution|hint|explanation", key) else "exercise" if re.search(r"exercise|practice|question|problem|assignment|quiz", key) else None
                for si, sc in enumerate(secs):
                    if role_hit and sc["role"] == role_hit and not (role_hit == "exercise" and re.search(r"worksheet", sc["text"], re.I)):
                        ref = f"sec{si}"
                        break
            unmatched += ref is None
            entries.append({"label": label, "title": None, "ref": ref, "kind": "section", "src": a["src"]})
        # Title of the index page: the doc's index heading; without one, the index table's caption, else the chapter title.
        # The chapter line under it is left out when it would only repeat the title.
        toc_title = atom_text(idx_atom).strip() if idx_atom else (index_caption or chapter_short or title_text)
        chapter_line = "" if (not idx_atom and norm(toc_title) in (norm(title_text), norm(chapter_short))) else title_text
        toc = {"t": "toc", "title": toc_title, "chapter": title_text, "chapter_no": "", "chapter_line": chapter_line, "eyebrow": atom_text(eyebrow_atom).strip() if eyebrow_atom else None, "entries": entries,
               "src": ([idx_atom["src"]] if idx_atom else []) + [e["src"] for e in entries] + ([eyebrow_atom["src"]] if eyebrow_atom else []) + ([title_atom["src"]] if title_atom else [])}
        ordered.append({"kind": "toc", "block": toc})
        if unmatched:
            issues.append({"code": "index-unmatched", "blocks": [], "severity": "info", "blocking": False, "message": f"{unmatched} of {len(entries)} lines of the doc's own index could not be matched to a heading in the chapter, so they have no page number."})
    elif idx_atom:
        entries = []
        if title_text:
            entries.append({"label": title_text, "title": None, "ref": "body", "kind": "section"})
        seen_answers = False
        for si, sc in enumerate(secs):
            if sc["role"] == "ignore":
                continue
            if sc["role"] == "answers":
                if seen_answers:
                    continue
                seen_answers = True
            entries.append({"label": sc["text"], "title": None, "ref": f"sec{si}", "kind": "section"})
        toc = {"t": "toc", "title": atom_text(idx_atom).strip(), "chapter": title_text, "chapter_no": "", "chapter_line": title_text, "entries": entries, "src": [idx_atom["src"]]}
        ordered.append({"kind": "toc", "block": toc})
        issues.append({"code": "index-generated", "blocks": [idx_atom["src"]], "severity": "question", "blocking": False, "message": f"The doc has an “{atom_text(idx_atom).strip()}” heading with no entries under it. An index page listing the chapter and its main sections (with page numbers) is generated.", "suggestion": "Tell me if the index should list something different."})
    ordered += sections
    if str(meta.get("end_page", "1")) != "0":
        ordered.append({"kind": "end", "pill": (chapter_short or "").upper() or None, "block": {"t": "end", "module": atom_text(eyebrow_atom).strip() if eyebrow_atom else meta.get("module", ""), "chapter": title_text, "grade": meta.get("grade", ""), "subject": meta.get("subject", "")}})

    book_meta["chapter_title"] = title_text
    # ------------------------------------------------------------ coverage
    used = {x["id"] for x in ignored}

    def collect(o):
        if isinstance(o, dict):
            if isinstance(o.get("src"), list):
                used.update(o["src"])
            if "title_src" in o:
                used.add(o["title_src"])
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)

    collect(ordered)
    dropped = [b["id"] for b in blocks if b["id"] not in used and block_text(b).strip()]
    return {
        "meta": book_meta, "sections": ordered, "issues": issues, "ignored": ignored, "dropped": dropped,
        "outline": outline,
        "dividers": [{"src": d["src"], "text": d["text"], "level": d["level"], "role": d["role"], "auto": d["auto"]} for d in secs],
        "heading_levels": body_levels,
    }
