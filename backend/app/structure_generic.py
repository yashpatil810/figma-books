"""Generic, heading-driven reading of a chapter (no fixed template).

Rules of the road (same as the synopsis engine):
  * text is copied verbatim from doc blocks; nothing is ever dropped (leftovers become plain content);
  * sections are found by the document's own headings and by recognisable names (exercise / answers /
    mind map / references / glossary), never required to exist;
  * every guess is surfaced in `outline`/`dividers` so the user can override how a heading is read.
"""
from __future__ import annotations

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


def _title_core(t: str) -> str:
    return norm(re.sub(r"^(chapter|unit|lesson|ch)\s*\d*\s*[:.\-–]?\s*", "", t, flags=re.I))


def build_book_generic(blocks: list[dict], meta: dict, fixes: list | None = None, overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    blocks = apply_fixes(blocks, fixes or [])
    issues: list[dict] = []
    ignored: list[dict] = []
    atoms = build_atoms(blocks)
    book_meta = dict(meta)

    def ign(src, why):
        ignored.append({"id": src, "reason": why})

    # ------------------------------------------------------------ front matter
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
    for ix, a in enumerate(body_atoms):
        t = atom_text(a).strip() if a["k"] in ("h", "p") else ""
        if not t:
            continue
        styled = a["k"] == "h"
        lvl = a["level"] if styled else 9
        role = role_guess(t) if len(t) <= 70 else None
        capsline = a["k"] == "p" and (a.get("bold") or t.isupper()) and len(t) <= 40 and not Q_RE.match(t)
        cand = None
        if styled and role in ("answers", "mindmap", "references", "glossary", "exercise"):
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
            dividers.append({"idx": ix, "src": a["src"], "text": t, "level": lvl, "role": cand, "auto": ov is None})

    # nesting: a lower-importance heading inside an exercise/answers section stays inside it
    secs: list[dict] = []
    cur = None
    for d in dividers:
        same_kind = d["role"] == cur["role"] if cur else False
        inside_answers = bool(cur) and cur["role"] == "answers" and d["role"] == "exercise"
        if cur and d["level"] > cur["level"] and cur["role"] in ("exercise", "answers") and (same_kind or inside_answers):
            continue  # a lower-importance heading of the same kind stays inside the current section
        role = d["role"]
        if cur and cur["role"] == "answers" and role == "exercise" and d["level"] == cur["level"] and d["auto"]:
            role = "answers"  # "Level - 2" under "Answer Keys" holds the answers for that level
        secs.append({**d, "role": role})
        cur = secs[-1]

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
            if a["k"] == "h":
                flush()
                out.append({"t": "h", "lvl": rank_style.get(a["level"], 4), "text": atom_text(a), "src": [a["src"]]})
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
    if lead or title_block:
        blks = ([title_block] if title_block else []) + flow(lead)
        sections.append({"kind": "body", "bg": "white", "pill": (chapter_short or "").upper() or None, "topics": [{"blocks": blks, "anchor": "body"}]})
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
        head = {"t": "title", "text": sc["text"], "gen_eyebrow": False, "src": [sc["src"]]}
        pill = sc["text"].upper() if len(sc["text"]) <= 40 else sc["text"][:40].upper()
        sections.append({"kind": kind, "bg": "tint" if kind in TINT_KINDS else "white", "pill": pill, "topics": [{"blocks": [head] + blks, "anchor": f"sec{si}"}]})
        outline.append({"kind": kind, "title": sc["text"], "src": sc["src"], "blocks": len(content)})

    # ------------------------------------------------------------ index page + end page
    ordered: list[dict] = []
    if idx_atom:
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
