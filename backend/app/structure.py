"""Doc blocks -> book model (sections of renderable component blocks).

Rules of the road:
  * Text is only ever copied from doc blocks (never retyped by a model), so nothing can be paraphrased.
  * Every doc block must end up either in a spec block's `src` or in `ignored` with a reason.
  * Anything the rules can't place is returned in `issues` so the scan step can ask the user.
"""
from __future__ import annotations

import copy
import re

from .atoms import atom_text, build_atoms, lstrip_runs, rtext, trim
from .gdoc import block_text

CALLOUTS = {
    "concept insight": ("insight", "Concept Insight"),
    "did you know": ("dyk", "Did You Know?"),
    "common misconceptions": ("misc", "Common Misconceptions"),
    "iit foundation understanding": ("iit", "IIT Foundation Understanding"),
}
Q_RE = re.compile(r"^\s*(\d+)\s*([.)])(?!\d)\s*")  # "4. text" / "4.text" / "4) text", never a decimal number such as "0.5x + 2.8"
MCQ_RE = re.compile(r"\(\s*([A-D])\s*\)")
QNUM_RE = re.compile(r"^\s*(\d{1,3})\s{2,}\S")  # "01  Stem…" (number, then spaces, no punctuation)
OPT_RE = re.compile(r"^\s*([A-D])[.)]\s+\S")      # "A. option" on its own line
RANGE_RE = re.compile(r"^\(\s*Questions?\b.*\)$", re.I)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower().replace("?", "")).strip()


def up(b) -> str:
    return re.sub(r"\s+", " ", block_text(b)).strip().upper()


# ------------------------------------------------------------------ fixes
def apply_fixes(blocks: list[dict], fixes: list[dict]) -> list[dict]:
    """fixes: {block, find, replace} | {block, drop:true}. Used for findings the user chose to let the app handle."""
    if not fixes:
        return blocks
    by = {}
    for f in fixes:
        by.setdefault(f["block"], []).append(f)
    out = []
    for b in copy.deepcopy(blocks):
        fs = by.get(b["id"], [])
        if any(f.get("drop") for f in fs):
            continue
        for f in fs:
            if "label" in f and b.get("list"):
                mnum = re.match(r"\d+", f["label"])
                b["list"] = dict(b["list"], label=f["label"], num=int(mnum.group(0)) if mnum else b["list"].get("num"))
                continue
            if "find" not in f or b["t"] in ("img", "tbl"):
                continue
            done = False
            for r in b["runs"]:
                if f["find"] in r["t"]:
                    r["t"] = r["t"].replace(f["find"], f.get("replace", ""), 1)
                    done = True
                    break
            if not done and f["find"] in b["text"]:  # spans runs: collapse
                full = b["text"].replace(f["find"], f.get("replace", ""), 1)
                b["runs"] = [{"t": full}]
            b["runs"] = [r for r in b["runs"] if r["t"]]
            b["text"] = "".join(r["t"] for r in b["runs"])
        out.append(b)
    return out


# ------------------------------------------------------------------ helpers
def R(text, **kw):
    return [dict({"t": text}, **kw)]


def unb(runs):
    """Drop the doc's bold from runs (cards use their own weights)."""
    return [{k: v for k, v in r.items() if k != "b"} for r in runs]


def para(runs, src):
    return {"t": "p", "runs": runs, "src": [src]}


def is_heading_atom(a) -> bool:
    if a["k"] == "h":
        return True
    return a["k"] == "p" and a["bold"] and len(atom_text(a)) <= 110 and not Q_RE.match(atom_text(a)) and not re.match(r"^(correct )?answer\b", atom_text(a), re.I) and not a.get("center") is None and True


def callout_key(a):
    if a["k"] not in ("h", "p"):
        return None
    if a["k"] == "p" and not a["bold"]:
        return None
    return CALLOUTS.get(norm(atom_text(a)))


def group_lists(atoms_slice, ctx, inside_callout=False):
    """Plain run of atoms -> p / ul / ol / image / table / formula blocks."""
    out = []
    i = 0
    while i < len(atoms_slice):
        a = atoms_slice[i]
        k = a["k"]
        if k == "li":
            j = i
            bullets = a["bullet"]
            while j < len(atoms_slice) and atoms_slice[j]["k"] == "li" and atoms_slice[j]["bullet"] == bullets:
                j += 1
            seg = atoms_slice[i:j]
            if bullets:
                out.append({"t": "ul", "mark": "•", "items": [x["lines"][0] if len(x["lines"]) == 1 else {"lines": x["lines"]} for x in seg], "src": [x["src"] for x in seg]})
            else:
                items = []
                for x in seg:
                    lines = x["lines"]
                    if len(lines) > 1 and not all(r.get("b") for r in lines[0]):  # title line + description
                        lines = [[dict(r, b=1) for r in lines[0]]] + lines[1:]
                    items.append({"label": x["label"], "lines": lines})
                out.append({"t": "ol", "items": items, "src": [x["src"] for x in seg]})
            i = j
            continue
        if k == "img":
            run = [a]
            j = i + 1
            while j < len(atoms_slice) and atoms_slice[j]["k"] == "img":
                run.append(atoms_slice[j])
                j += 1
            small = all((x["w"] or 0) <= 360 and (x["h"] or 0) <= 140 for x in run)
            if len(run) >= 2 and small:  # a run of small pictures (e.g. equations) laid out in one wrapping row
                out.append({"t": "imagerow", "items": [fit_image(x) for x in run], "src": [x["src"] for x in run]})
                i = j
                continue
            out.append(dict(fit_image(a), t="image", label=a.get("alt") or "Image", src=[a["src"]]))
        elif k == "tbl":
            out.append(table_block(a))
        elif k == "p":
            txt = atom_text(a)
            if re.match(r"^[A-Za-z ]+ = [A-Za-z ]+ [×÷/*x] [A-Za-z ]+$", txt):
                out.append({"t": "formula", "text": txt, "src": [a["src"]]})
            else:
                out.append(para(a["runs"], a["src"]))
        elif k == "h":
            out.append(para([dict(r, b=1) for r in a["runs"]], a["src"]))
        i += 1
    return out


CONTENT_IMG_W, CONTENT_IMG_H = 395, 320


def fit_image(a):
    """Placeholder size: figures fit the column; small inline pictures (equations) are scaled to match body text."""
    w, h = a.get("w") or 400, a.get("h") or 300
    if h <= 140 and w <= 520:
        sc = 0.8
    else:
        sc = min(1.0, CONTENT_IMG_W / w, CONTENT_IMG_H / h)
    return {"w": max(12, round(w * sc)), "h": max(12, round(h * sc)), "hash": a.get("hash", "")}


def table_block(a):
    rows = [list(r) for r in a["rows"]]
    n = max(len(r) for r in rows)  # rows can be ragged (merged cells): pad to the widest
    rows = [r + [""] * (n - len(r)) for r in rows]
    first = [c.strip() for c in rows[0]]
    looks_like_header = (
        len(rows) >= 2
        and all(first)
        and not any(re.match(r"^\(?\d+\s*[.)]|^\(?[ivxIVX]+\)", c) for c in first)
    )
    head, body = (rows[0], rows[1:]) if looks_like_header else ([], rows)
    lens = [max(len(r[c]) for r in rows) for c in range(n)]
    tot = sum(max(l, 8) for l in lens)
    from . import layout as _lay

    W = _lay.CONTENT_W
    ws = [W * max(l, 8) / tot for l in lens]
    # a column is never narrower than its longest word (cell padding is 18px, ~6.4px per character at 11pt)
    floor = [min(200, max(len(w) for r in rows for w in r[c].split() or [""]) * 6.4 + 22) for c in range(n)]
    for _ in range(3):
        short = [c for c in range(n) if ws[c] < floor[c]]
        if not short:
            break
        need = sum(floor[c] - ws[c] for c in short)
        rest = [c for c in range(n) if c not in short]
        room = sum(ws[c] - floor[c] for c in rest if ws[c] > floor[c])
        for c in short:
            ws[c] = floor[c]
        for c in rest:
            if room > 0 and ws[c] > floor[c]:
                ws[c] -= need * (ws[c] - floor[c]) / room
    ws = [round(w) for w in ws]
    ws[-1] = W - sum(ws[:-1])
    return {"t": "table", "head": head, "rows": body, "widths": ws, "src": [a["src"]]}


# ------------------------------------------------------------------ synopsis
def synopsis_blocks(atoms, topics, issues, syn_no):
    """Atoms of one synopsis body -> list of topics [{pill, anchor?, blocks}]"""
    out_topics = [{"pill": None, "blocks": []}]
    blocks = out_topics[0]["blocks"]
    topic_i = 0
    first_h2_done = False
    i = 0
    has_styled = any(a["k"] == "h" and a["level"] in (2, 3) for a in atoms)
    n = len(atoms)

    def topic_match(a):
        nonlocal topic_i
        if topic_i >= len(topics) or a["k"] != "p" or not a["bold"]:
            return False
        t = norm(atom_text(a))
        if t.startswith(norm(topics[topic_i])):
            return True
        return False

    pending: list = []

    def flush():
        nonlocal pending
        if pending:
            blocks.extend(group_lists(pending, None))
            pending = []

    while i < n:
        a = atoms[i]
        ck = callout_key(a)
        if ck:
            flush()
            variant, title = ck
            hl = a["level"] if a["k"] == "h" else 99
            j = i + 1
            while j < n:
                b = atoms[j]
                if callout_key(b):
                    break
                if b["k"] == "h" and (b["level"] <= hl or hl == 99):
                    break
                if b["k"] == "p" and b["bold"] and is_heading_atom(b) and variant not in ("misc", "iit"):
                    break
                if b["k"] == "p" and b["bold"] and is_heading_atom(b) and variant in ("misc", "iit") and not re.match(r"(misconception|correct concept)", norm(atom_text(b))):
                    break
                j += 1
            body = []
            for x in atoms[i + 1 : j]:
                if x["k"] in ("h",) or (x["k"] == "p" and x["bold"]):
                    body.append(para([dict(r, b=1) for r in x["runs"]], x["src"]))
                else:
                    body.extend(group_lists([x], None, True))
            # merge adjacent bullet lists inside callout
            merged = []
            for b in body:
                if merged and b["t"] == "ul" and merged[-1]["t"] == "ul":
                    merged[-1]["items"] += b["items"]
                    merged[-1]["src"] += b["src"]
                else:
                    merged.append(b)
            srcs = [a["src"]] + [x["src"] for x in atoms[i + 1 : j]]
            if variant == "insight":  # reference: plain sub-heading + paragraph, no box
                blocks.append({"t": "h", "lvl": 4, "text": atom_text(a), "src": [a["src"]]})
                blocks.extend(merged)
            else:
                blocks.append({"t": "callout", "variant": variant, "title": atom_text(a), "title_src": a["src"], "blocks": merged, "src": srcs})
            i = j
            continue
        if a["k"] == "h":
            flush()
            lvl = a["level"]
            txt = atom_text(a)
            if lvl == 1:
                blocks.append({"t": "h", "lvl": 2, "text": txt, "src": [a["src"]]})
            elif lvl == 2:
                nxt = atoms[i + 1] if i + 1 < n else None
                if not first_h2_done:
                    first_h2_done = True
                    L = 2
                elif nxt is not None and nxt["k"] == "h" and nxt["level"] == 3:
                    L = 3
                else:
                    L = 4
                blocks.append({"t": "h", "lvl": L, "text": txt, "src": [a["src"]]})
            else:
                blocks.append({"t": "h", "lvl": 5, "text": txt, "src": [a["src"]]})
            i += 1
            continue
        if a["k"] == "p" and a["bold"] and not a.get("center") and len(atom_text(a)) <= 110 and not Q_RE.match(atom_text(a)):
            flush()
            if topic_match(a):
                if topic_i > 0 or (blocks and topic_i == 0 and False):
                    out_topics.append({"pill": None, "blocks": []})
                    blocks = out_topics[-1]["blocks"]
                out_topics[-1]["pill"] = topics[topic_i].upper() if topic_i < len(topics) else None
                out_topics[-1]["anchor"] = f"syn{syn_no}" if topic_i == 0 else None
                topic_i += 1
                blocks.append({"t": "h", "lvl": 2, "text": atom_text(a), "src": [a["src"]]})
            else:
                blocks.append({"t": "h", "lvl": 4, "text": atom_text(a), "src": [a["src"]]})
            i += 1
            continue
        pending.append(a)
        # flush at heading boundaries only (done above); also keep original adjacency
        i += 1
        if i < n and (atoms[i]["k"] == "h" or callout_key(atoms[i]) or (atoms[i]["k"] == "p" and atoms[i]["bold"] and len(atom_text(atoms[i])) <= 110)):
            flush()
    flush()
    if topics and 0 < topic_i < len(topics):
        issues.append({"code": "topic-not-found", "blocks": [], "message": f"Synopsis {syn_no}: topic '{topics[topic_i]}' listed in the table of contents was not found as a heading in the body, so its page break/pill could not be placed.", "severity": "question"})
    if not out_topics[0].get("pill"):
        out_topics[0]["pill"] = (topics[0] if topics else "").upper() or None
    return out_topics


# ------------------------------------------------------------------ question sections
def parse_mcq(runs):
    """'stem (A) x (B) y (C) z (D) w' -> (stem_runs, [{k, runs}]) or None. Splits runs without altering text."""
    text = rtext(runs)
    ms = list(MCQ_RE.finditer(text))
    if len(ms) < 2 or [m.group(1) for m in ms] != list("ABCD")[: len(ms)]:
        return None

    def sub(a, b):
        out, pos = [], 0
        for r in runs:
            s, e = pos, pos + len(r["t"])
            lo, hi = max(a, s), min(b, e)
            if lo < hi:
                nr = dict(r)
                nr["t"] = r["t"][lo - s : hi - s]
                out.append(nr)
            pos = e
        return trim(out)

    stem = sub(0, ms[0].start())
    opts = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        opts.append({"k": m.group(1), "runs": sub(m.start(), end)})
    return stem, opts


SUBLABEL_RE = re.compile(r"^\s*\(\s*([ivxlcIVXLC]+|[a-zA-Z])\s*\)")
# MCQ options typed with capital letters: "A) text" / "A. text" / "(A) text" on its own line, or several in one line
# ("A) 3/4<tab>B) −3/4<tab>C) 3<tab>D) −3"). Lower-case "(a)" lines are sub-parts or options and stay lines of the question.
OPT_MARK_RE = re.compile(r"(?:^|(?<=\s))\(?([A-D])\s*[.)]\s*(?=\S|$)")  # a marker may have no text (a picture or an equation that is an image)
REASON_RE = re.compile(r"^\s*reason\s*(\(\s*r\s*\))?\s*:", re.I)
LETTER_LABEL_RE = re.compile(r"^\s*\(?\s*([A-Za-z])\s*[.)]?\s*$")


def option_marks(runs, expect: str = "A"):
    """The capital-letter option markers of a line, in order, when the line starts with the expected letter (A for a
    fresh set, the next letter while a set is being collected) and the markers continue in sequence (so a stray "(c)"
    inside a formula never counts). Returns the matches or []."""
    text = rtext(runs)
    ms = [m for m in OPT_MARK_RE.finditer(text)]
    if not ms or ms[0].start() != len(text) - len(text.lstrip()) or expect not in "ABCD":
        return []
    letters = [m.group(1) for m in ms]
    want = list("ABCD")[list("ABCD").index(expect):]
    for n in range(min(len(letters), len(want)), 0, -1):  # the longest run expect, expect+1, …
        if letters[:n] == want[:n]:
            return ms[:n]
    return []


def split_options(runs, marks):
    """Cut a line at its option markers into [{k, runs}] without altering the text (separating tabs/spaces are dropped)."""
    text = rtext(runs)

    def sub(a, b):
        out, pos = [], 0
        for r in runs:
            s, e = pos, pos + len(r["t"])
            lo, hi = max(a, s), min(b, e)
            if lo < hi:
                nr = dict(r)
                nr["t"] = r["t"][lo - s : hi - s]
                out.append(nr)
            pos = e
        return trim(out)

    opts = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        opts.append({"k": m.group(1), "runs": unb(sub(m.start(), end))})
    return opts


def _item_has_text(item) -> bool:
    if "lines" in item:
        return any(rtext(l).strip() for l in item["lines"])
    return any(rtext(b["runs"]).strip() for b in item["blocks"])


def qstream(atoms, mode, issues):
    """Questions / answers stream -> blocks. mode: 'q' (questions) | 'a' (answers/hints)."""
    out: list[dict] = []
    cur = None  # {"kind": "qcard"|"ans", "items": [...]}
    item = None
    pending_match = None

    def flush():
        nonlocal cur, item
        if cur and cur["items"]:
            for it in cur["items"]:
                it.pop("_src", None)
            out.append(cur)
        cur = None
        item = None

    def start_item(label, runs, src, extra_kind):
        nonlocal cur, item, mcq
        mcq = None
        kind = "ans" if mode == "a" else "qcard"
        if cur is None or cur["t"] != kind:
            flush()
            cur = {"t": kind, "items": [], "src": []}
        if kind == "ans":
            item = {"label": label, "blocks": [para(runs, src)] if runs else [], "pics": []}
        else:
            item = {"label": label, "lines": [runs] if runs else [], "pics": []}
        item["_src"] = [src]
        cur["items"].append(item)
        cur["src"].append(src)

    mcq = None  # an MCQ card being assembled from a question line and the option lines typed after it

    def to_mcq(marks, runs, src):
        """The open question item becomes an MCQ card (stem = its lines) and these options are its first options."""
        nonlocal cur, item, mcq
        it = cur["items"].pop()
        srcs = it.pop("_src")
        cur["src"] = [x for x in cur["src"] if x not in srcs]
        flush()
        stem = []
        for i, ln in enumerate(it["lines"]):
            stem += ([{"t": "\n"}] if i else []) + list(ln)
        mcq = {"t": "mcq", "n": it["label"], "stem": unb(trim(stem)), "options": split_options(runs, marks), "src": srcs + [src]}
        out.append(mcq)

    skip_to = 0
    for idx, a in enumerate(atoms):
        if idx < skip_to:
            continue
        k = a["k"]
        txt = atom_text(a) if k != "img" else ""
        if mode == "q" and k == "p" and QNUM_RE.match(txt):  # a question typed as "01  stem" + A./B./C./D. lines
            j, opts = idx + 1, []
            while j < len(atoms) and atoms[j]["k"] == "p" and OPT_RE.match(atom_text(atoms[j]).strip()):
                opts.append(atoms[j])
                j += 1
            if len(opts) >= 2:
                flush()
                lead = re.match(r"^\s*(\d{1,3})\s+", rtext(a["runs"]))
                out.append({"t": "mcq", "n": lead.group(1), "stem": unb(trim(lstrip_runs(a["runs"], lead.end()))),
                            "options": [{"k": atom_text(o).strip()[0], "runs": unb(trim(o["runs"]))} for o in opts],
                            "src": [a["src"]] + [o["src"] for o in opts]})
                skip_to = j
                continue
        # numbering: auto label, or typed "29. text"
        label, runs, src = None, None, a["src"]
        if k == "li" and not a["bullet"]:
            label = a["label"]
            runs = a["lines"][0]
            m = re.match(r"^\s*[.]\s*", rtext(runs))  # stray ". " after the auto number
            if m:
                runs = trim(lstrip_runs(runs, m.end()))
        elif k == "p" and Q_RE.match(txt):
            m = Q_RE.match(rtext(a["runs"]))
            label = m.group(1) + m.group(2)
            runs = trim(lstrip_runs(a["runs"], m.end()))
        elif k == "p" and re.fullmatch(r"\d+\s*[.)]", txt.strip()):  # "62." alone: label with answer lines after it
            label = txt.strip().replace(" ", "")
            runs = []

        # capital-letter options ("A) …", or "A) … B) … C) … D) …" in one line, or a lettered list item) after a question
        # line, or after options already collected: they belong to that question, in one MCQ card
        opt_runs = None
        if mode == "q" and k == "p" and label is None and not is_heading_atom(a):
            opt_runs = a["runs"]
        elif mode == "q" and k == "li" and not a["bullet"] and a["label"] and LETTER_LABEL_RE.match(a["label"]) and (item is not None or mcq is not None):
            opt_runs = [{"t": a["label"] + " "}] + list(a["lines"][0])
            label, runs = None, None  # not a question of its own
        expect = chr(ord(mcq["options"][-1]["k"]) + 1) if mcq is not None and mcq["options"] else "A"
        marks = option_marks(opt_runs, expect) if opt_runs is not None else []
        if marks and mcq is not None:
            mcq["options"] += split_options(opt_runs, marks)
            mcq["src"].append(src)
            continue
        if marks and item is not None and cur is not None and cur["t"] == "qcard" and not item["pics"]:
            to_mcq(marks, opt_runs, src)
            continue
        if mcq is not None and k == "p" and label is None and REASON_RE.match(txt):  # "Reason: …" of an assertion-reason MCQ
            mcq["stem"] = mcq["stem"] + [{"t": "\n"}] + unb(trim(a["runs"]))
            mcq["src"].append(src)
            continue
        if k != "img":
            mcq = None  # anything else closes the MCQ being assembled (pictures inside it are handled below)

        if k == "img" and item is not None and cur is not None:
            item["pics"].append(dict(fit_image(a), src=a["src"]))
            cur["src"].append(a["src"])
            item["_src"].append(a["src"])
        elif k == "p" and label is None and item is not None and cur is not None and mode == "q" and not is_heading_atom(a) and not re.match(r"^directions\b", txt, re.I) and not RANGE_RE.match(txt):
            # text between a numbered question and the next one belongs to that question (its remaining lines, sub-parts, "Reason")
            item["lines"].append(a["runs"])
            cur["src"].append(src)
            item["_src"].append(src)
        elif opt_runs is not None and k == "li" and item is not None and cur is not None and mode == "q":  # "(a) …" list item under a question: a line of it
            item["lines"].append(opt_runs)
            cur["src"].append(src)
            item["_src"].append(src)
        elif k == "img":
            flush()
            out.extend(group_lists([a], None))
        elif k == "tbl":
            flush()
            tb = table_block(a)
            if pending_match:
                out.append(pending_match)
                pending_match = None
            out.append(tb)
        elif label is not None:
            if mode == "q":
                runs = unb(runs) if runs else runs
                parsed = parse_mcq(runs) if runs else None
                if parsed:
                    flush()
                    stem, opts = parsed
                    out.append({"t": "mcq", "n": label, "stem": stem, "options": opts, "src": [src]})
                    continue
                if runs and re.search(r"\bcolumn i\b", rtext(runs), re.I):  # match-the-column stem
                    flush()
                    pending_match = {"t": "p", "runs": [dict(r, b=1) for r in ([{"t": label + " "}] + runs)], "src": [src]}
                    continue
            start_item(label, runs, src, None)
            if k == "li" and len(a["lines"]) > 1:
                for ln in a["lines"][1:]:
                    (item["blocks"].append(para(ln, src)) if mode == "a" else item["lines"].append(unb(ln)))
        elif k == "p" and re.match(r"^directions\b", txt, re.I):
            flush()
            out.append({"t": "note", "runs": unb(a["runs"]), "src": [src]})
        elif is_heading_atom(a) and not (re.match(r"^(correct )?answer\b|^explanation\b", txt, re.I)):
            flush()
            if RANGE_RE.match(txt):
                out.append({"t": "note", "runs": a["runs"], "src": [src], "muted": True})
            else:
                lvl = 2 if (norm(txt) in ("test your concepts", "concept application") and mode == "a") else 3
                out.append({"t": "h", "lvl": lvl, "text": txt, "src": [src]})
        elif k == "p" and re.match(r"^directions\b", txt, re.I):
            flush()
            out.append({"t": "note", "runs": a["runs"], "src": [src]})
        elif k == "p" and item is not None and mode == "a":
            item["blocks"].append(para(a["runs"], src))
            cur["src"].append(src)
            item["_src"].append(src)
        elif k == "li" and item is not None and mode == "a":
            item["blocks"].append(para(a["lines"][0], src))
            cur["src"].append(src)
            item["_src"].append(src)
        elif k == "p" and mode == "q":
            # typed "(a) ..." etc. or free text
            flush()
            out.append(para(a["runs"], src))
        else:
            flush()
            out.extend(group_lists([a], None))
    flush()
    if pending_match:
        out.append(pending_match)
    return out


# ------------------------------------------------------------------ main
def build_book_synopsis(blocks: list[dict], meta: dict, fixes: list[dict] | None = None) -> dict:
    blocks = apply_fixes(blocks, fixes or [])
    issues: list[dict] = []
    ignored: list[dict] = []
    idx = {b["id"]: i for i, b in enumerate(blocks)}

    def find(pred, start=0, end=None):
        for i in range(start, end if end is not None else len(blocks)):
            if pred(blocks[i]):
                return i
        return None

    def ign(i, why):
        ignored.append({"id": blocks[i]["id"], "reason": why})

    ch_i = find(lambda b: up(b).startswith("CHAPTER:"))
    key_i = find(lambda b: up(b).startswith("KEY IDEAS"))
    toc_i = find(lambda b: up(b) == "TABLE OF CONTENTS")
    syn_re = re.compile(r"^SYNOPSIS[\s-]*(\d+)\b")
    first_syn = find(lambda b: b["t"] in ("p", "h") and syn_re.match(up(b)) is not None, (toc_i or 0) + 2)
    test_i = find(lambda b: up(b) == "TEST YOUR CONCEPTS", first_syn or 0)
    ca_i = find(lambda b: up(b) == "CONCEPT APPLICATION", test_i or 0)
    hints_i = find(lambda b: up(b) == "HINTS AND SOLUTIONS", ca_i or test_i or 0)
    mind_i = find(lambda b: up(b) == "MIND MAP", hints_i or 0)
    end_i = find(lambda b: up(b) == "END", mind_i or 0)
    for name, v in (("CHAPTER:", ch_i), ("KEY IDEAS", key_i), ("TABLE OF CONTENTS", toc_i), ("SYNOPSIS 1", first_syn), ("TEST YOUR CONCEPTS", test_i), ("CONCEPT APPLICATION", ca_i), ("HINTS AND SOLUTIONS", hints_i), ("MIND MAP", mind_i)):
        if v is None:
            issues.append({"code": "marker-missing", "blocks": [], "severity": "info", "message": f"No '{name}' section in this document, so that part of the book is skipped.", "blocking": False})

    sections: list[dict] = []
    # --- meta
    book_meta = dict(meta)
    if ch_i is not None:
        book_meta["chapter_title"] = re.sub(r"^CHAPTER\s*:\s*", "", block_text(blocks[ch_i]), flags=re.I).strip()
        for j in range(0, ch_i):
            if blocks[j]["t"] == "img":
                ign(j, "cover image (covers are made manually)")
        for j in range(ch_i, (key_i or ch_i + 1)):
            t = up(blocks[j])
            m = re.match(r"GRADE\s*(\d+)", t)
            if m:
                if not book_meta.get("grade"):
                    book_meta["grade"] = m.group(1)
                ign(j, "cover text (covers are made manually)")
            elif t.startswith("PREPARED BY"):
                ign(j, "cover text (covers are made manually)")
                issues.append({"code": "prepared-by", "blocks": [blocks[j]["id"]], "severity": "question", "message": f"'{block_text(blocks[j])}' is in the doc but the reference book has no place for it. It will be left out of the pages (cover is manual). Confirm.", "suggestion": "Confirm it belongs only on the cover."})
            elif blocks[j]["t"] == "img":
                ign(j, "cover image (covers are made manually)")
        ign(ch_i, "chapter title (used as chapter title and page header)")

    # --- key ideas
    if key_i is not None and toc_i is not None:
        at = build_atoms(blocks[key_i + 1 : toc_i])
        ci = []
        intro = None
        for a in at:
            if a["k"] == "li" and a["bullet"]:
                ci.append({"lines": a["lines"], "src": [a["src"]]})
            elif a["k"] == "p" and not ci and intro is None:
                intro = a
            elif a["k"] == "p" and ci:  # wrapped continuation of the previous bullet
                ci[-1]["lines"] = [ci[-1]["lines"][0] + [{"t": " "}] + a["runs"]]
                ci[-1]["src"].append(a["src"])
                issues.append({"code": "key-idea-wrapped", "blocks": [a["src"]], "severity": "warning", "message": "A key-idea bullet is split across two paragraphs in the doc. The app joins them into one bullet.", "suggestion": "Merge the two paragraphs in the doc."})
            elif a["k"] == "img":
                ign(idx[a["src"]], "image inside key ideas")
        inner = []
        if intro:
            inner.append(para(intro["runs"], intro["src"]))
        inner.append({"t": "ul", "mark": "✓", "items": [c["lines"][0] for c in ci], "src": [s for c in ci for s in c["src"]]})
        ko = {"t": "callout", "variant": "keyideas", "title": block_text(blocks[key_i]).strip(), "title_src": blocks[key_i]["id"], "blocks": inner, "src": [blocks[key_i]["id"]] + [s for s in [intro["src"] if intro else None] if s] + [s for c in ci for s in c["src"]]}
        sections.append({"kind": "opener", "bg": "white", "pill": book_meta["chapter_title"].upper(), "topics": [{"blocks": [{"t": "title", "eyebrow": "CHAPTER", "text": book_meta["chapter_title"], "gen_eyebrow": True, "src": [blocks[ch_i]["id"]]}, ko]}]})
    # --- synopses
    syn_marks = []
    if first_syn is not None:
        end_of_syn = test_i if test_i is not None else len(blocks)
        for i in range(first_syn, end_of_syn):
            m = syn_re.match(up(blocks[i])) if blocks[i]["t"] in ("p", "h") else None
            if m and (not syn_marks or i > syn_marks[-1][0]):
                if blocks[i]["t"] == "p" and not blocks[i]["runs"][0].get("b") and len(block_text(blocks[i])) > 60:
                    continue
                syn_marks.append((i, int(m.group(1))))
    # TOC table
    toc_rows = []
    toc_extra = []
    if toc_i is not None:
        for j in range(toc_i + 1, first_syn or toc_i + 1):
            b = blocks[j]
            if b["t"] == "tbl":
                toc_rows = b["rows"][1:]
                ign(j, "table of contents (rebuilt with page numbers)")
            elif b["t"] == "p":
                toc_extra.append(b)
                ign(j, "table of contents entry (rebuilt with page numbers)")
        ign(toc_i, "table of contents heading (rebuilt)")
    toc_by_no = {}
    for r in toc_rows:
        m = re.search(r"(\d+)", r[0])
        if m:
            toc_by_no[int(m.group(1))] = r
    book_meta["synopsis_count"] = len(syn_marks)
    for si, (i, no) in enumerate(syn_marks):
        end = syn_marks[si + 1][0] if si + 1 < len(syn_marks) else (test_i if test_i is not None else len(blocks))
        row = toc_by_no.get(no)
        topics = [t.strip() for t in re.split(r"[,;]", row[2])] if row and len(row) > 2 else []
        marker = blocks[i]
        mt = block_text(marker)
        mm = re.match(r"^SYNOPSIS[\s-]*\d+\s*[-–:]?\s*(.*)$", mt, re.I)
        title_inline = (mm.group(1).strip() if mm else "") or None
        j = i + 1
        while j < end and blocks[j]["t"] == "img":
            ign(j, "decorative banner image under the synopsis title")
            j += 1
        title, title_src = title_inline, marker["id"]
        if j < end and blocks[j]["t"] in ("p", "h") and (title_inline is None or norm(block_text(blocks[j])) == norm(title_inline)):
            title, title_src = block_text(blocks[j]), blocks[j]["id"]
            if title_inline:
                ignored.append({"id": marker["id"], "reason": "synopsis marker line (number and title are shown as eyebrow and title)"})
            j += 1
        if not title:
            issues.append({"code": "synopsis-title", "blocks": [marker["id"]], "severity": "error", "message": f"Synopsis {no} has no title.", "blocking": True})
            title = f"Synopsis {no}"
        eyebrow = (row[0].strip() if row else f"SYNOPSIS-{no}")
        at = build_atoms(blocks[j:end])
        tps = synopsis_blocks(at, topics, issues, no)
        head = {"t": "title", "eyebrow": eyebrow, "text": title, "gen_eyebrow": row is None, "src": [title_src] + ([marker["id"]] if not title_inline else [])}
        tps[0]["blocks"].insert(0, head)
        tps[0]["anchor"] = f"syn{no}"
        sections.append({"kind": "synopsis", "bg": "white", "pill": (topics[0] if topics else title).upper(), "topics": tps, "no": no, "title": title})
        if row and norm(row[1]) != norm(title):
            issues.append({"code": "toc-title-mismatch", "blocks": [title_src], "severity": "warning", "message": f"Synopsis {no}: title in the table of contents ('{row[1]}') differs from the heading in the body ('{title}')."})

    # --- test / concept application / hints / mind map
    def qsection(kind, pill, start, end, title_text, mode, bg="tint", eyebrow=None, anchor=None):
        if start is None:
            return
        end = end if end is not None else len(blocks)
        at = build_atoms(blocks[start + 1 : end])
        blks = qstream(at, mode, issues)
        title = {"t": "title", "eyebrow": eyebrow, "text": title_text, "gen_eyebrow": bool(eyebrow), "src": [blocks[start]["id"]]}
        sections.append({"kind": kind, "bg": bg, "pill": pill, "topics": [{"blocks": [title] + blks, "anchor": anchor}]})

    qsection("test", "TEST YOUR CONCEPTS", test_i, ca_i if ca_i is not None else hints_i, block_text(blocks[test_i]) if test_i is not None else "", "q", anchor="test")
    if ca_i is not None:
        qsection("concept", "CONCEPT APPLICATION", ca_i, hints_i, block_text(blocks[ca_i]), "q", anchor="concept")
    qsection("hints", "HINTS AND SOLUTIONS", hints_i, mind_i, block_text(blocks[hints_i]) if hints_i is not None else "", "a", eyebrow="ANSWER KEY", anchor="hints")
    if mind_i is not None:
        at = build_atoms(blocks[mind_i + 1 : end_i if end_i is not None else len(blocks)])
        mb = [{"t": "h", "lvl": 3, "text": block_text(blocks[mind_i]), "src": [blocks[mind_i]["id"]]}]
        for a in at:
            if a["k"] == "img":
                w, h = a["w"] or 500, a["h"] or 350
                sc = min(515 / w, 640 / h) if w and h else 1
                mb.append({"t": "image", "label": "Mind map image", "w": round(w * sc), "h": round(h * sc), "src": [a["src"]]})
            elif a["k"] == "p" and re.fullmatch(r"[\\/\s]*", atom_text(a)):
                issues.append({"code": "stray-symbol", "blocks": [a["src"]], "severity": "warning", "message": f"Stray character '{atom_text(a)}' near the mind map. It will be ignored.", "suggestion": "Delete it in the doc."})
                ignored.append({"id": a["src"], "reason": "stray symbol"})
            else:
                mb.extend(group_lists([a], None))
        sections.append({"kind": "mindmap", "bg": "tint", "pill": "MIND MAP", "topics": [{"blocks": mb, "anchor": "mind"}]})
    if end_i is not None:
        ign(end_i, "end marker (an End of Chapter page is generated)")
    # trailing stray blocks between mind map and end that were not consumed are covered by build_atoms above

    # --- TOC + end page
    toc_entries = []
    for no in sorted(toc_by_no) or []:
        r = toc_by_no[no]
        toc_entries.append({"label": r[0].strip(), "title": r[1].strip(), "ref": f"syn{no}", "kind": "synopsis"})
    for b in toc_extra:
        t = norm(block_text(b))
        ref = {"test your concepts": "test", "hints and solutions": "hints", "mind map": "mind", "concept application": "concept"}.get(t)
        toc_entries.append({"label": block_text(b).strip(), "title": None, "ref": ref, "kind": "section"})
    toc_block = {"t": "toc", "title": block_text(blocks[toc_i]) if toc_i is not None else "Table of Contents", "chapter": book_meta.get("chapter_title", ""), "chapter_no": book_meta.get("module", ""), "entries": toc_entries, "src": [blocks[toc_i]["id"]] if toc_i is not None else []}
    ordered = [{"kind": "toc", "block": toc_block}] + sections
    ordered.append({"kind": "end", "pill": (book_meta.get("chapter_title") or "").upper(), "block": {"t": "end", "module": book_meta.get("module", ""), "chapter": book_meta.get("chapter_title", ""), "grade": book_meta.get("grade", ""), "subject": book_meta.get("subject", "")}})

    # --- coverage: every doc block must be used or ignored
    used = set(x["id"] for x in ignored)

    def collect(o):
        if isinstance(o, dict):
            for s in o.get("src", []) if isinstance(o.get("src"), list) else []:
                used.add(s)
            if "title_src" in o:
                used.add(o["title_src"])
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)

    collect(ordered)
    dropped = [b["id"] for b in blocks if b["id"] not in used and block_text(b).strip()]
    return {"meta": book_meta, "sections": ordered, "issues": issues, "ignored": ignored, "dropped": dropped}


# ------------------------------------------------------------------ profile selection
TEMPLATE_MARKERS = [r"^CHAPTER\s*:", r"^KEY IDEAS", r"^TABLE OF CONTENTS$", r"^SYNOPSIS[\s-]*\d+", r"^TEST YOUR CONCEPTS$", r"^CONCEPT APPLICATION$", r"^HINTS AND SOLUTIONS$"]


def detect_profile(blocks: list[dict]) -> str:
    texts = [up(b) for b in blocks if b["t"] in ("p", "h")]
    hit = sum(1 for pat in TEMPLATE_MARKERS if any(re.match(pat, t) for t in texts))
    return "synopsis" if hit >= 3 else "generic"


def build_book(blocks: list[dict], meta: dict, fixes: list[dict] | None = None) -> dict:
    """Build the book model. With a structure map (Claude's reading of the doc) the generic engine follows the map and
    no template is guessed; the synopsis template and keyword rules are only a fallback when no map exists."""
    from .structure_generic import build_book_generic

    if meta.get("structure_map"):
        book = build_book_generic(blocks, meta, fixes, meta.get("roles") or {})
        book["profile"] = "map"
        return book
    prof = (meta.get("profile") or "auto").lower()
    if prof == "auto":
        prof = detect_profile(blocks)
    if prof == "synopsis":
        book = build_book_synopsis(blocks, meta, fixes)
    else:
        book = build_book_generic(blocks, meta, fixes, meta.get("roles") or {})
    book["profile"] = prof
    return book
