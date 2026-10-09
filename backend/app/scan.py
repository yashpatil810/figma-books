"""Scan the source doc for mistakes before any design is generated.

Layer 1 (free, deterministic): numbering, ranges, stray characters, punctuation, brackets, structure.
Layer 2 (Sonnet): spelling candidates from a dictionary pass are judged (British spelling / names / terms are fine).
Layer 3 (Opus): proofreader + subject-teacher review for factual, answer-key and consistency errors.

Findings carry a stable fingerprint so user decisions survive a re-scan.
"""
from __future__ import annotations

import hashlib
import re

from . import llm
from .atoms import build_atoms
from .gdoc import block_text
from .structure import MCQ_RE, Q_RE, norm

SEV_ORDER = {"error": 0, "question": 1, "warning": 2, "info": 3}


def fp(code: str, *parts) -> str:
    return hashlib.sha1((code + "|" + "|".join(str(p) for p in parts)).encode()).hexdigest()[:12]


def finding(code, severity, blocks, message, suggestion="", excerpt="", fix=None, blocking=None, source="rule", key=None):
    f = {
        "code": code, "severity": severity, "blocks": blocks, "message": message, "suggestion": suggestion,
        "excerpt": excerpt[:220], "fix": fix or [], "source": source,
        "blocking": (severity in ("error", "question")) if blocking is None else blocking,
    }
    f["fp"] = fp(code, key if key is not None else (excerpt or message), *blocks[:3])
    return f


# ------------------------------------------------------------------ layer 1
def rule_findings(blocks: list[dict], book: dict) -> list[dict]:
    out: list[dict] = []
    by = {b["id"]: b for b in blocks}

    # carry structural issues found while mapping the doc
    for i in book["issues"]:
        out.append(finding(i["code"], i["severity"], i.get("blocks", []), i["message"], i.get("suggestion", ""), blocking=i.get("blocking", i["severity"] in ("error", "question")), key=i["message"]))
    for d in book["dropped"]:
        out.append(finding("unplaced-content", "error", [d], f"This text sits outside every section the reading rules know about, so it would be left off the pages: “{block_text(by[d])[:100]}”.", "Open Setup → “How I read your document”, switch the layout to “Generic chapter” (or adjust the headings) so it lands in a section.", excerpt=block_text(by[d]), blocking=True))

    for b in blocks:
        if b["t"] == "img":
            continue
        txt = block_text(b)
        bid = b["id"]
        if b["t"] == "h" and (len(re.sub(r"\W", "", txt)) < 2 or not re.search(r"\w", txt)):
            out.append(finding("stray-heading", "error", [bid], f"Heading contains only a stray symbol: “{txt}”.", "Delete it.", excerpt=txt, fix=[{"block": bid, "drop": True}]))
            continue
        if b["t"] == "p" and re.fullmatch(r"[\\/|~`^_\s]+", txt):
            out.append(finding("stray-symbol", "warning", [bid], f"A paragraph contains only the symbol “{txt.strip()}”.", "Delete it.", excerpt=txt, fix=[{"block": bid, "drop": True}], blocking=False))
            continue
        if b["t"] == "tbl":
            for ri, r in enumerate(b["rows"]):
                for ci, c in enumerate(r):
                    if not c.strip():
                        out.append(finding("empty-cell", "warning", [bid], f"Table cell is empty (row {ri + 1}, column {ci + 1}).", "Fill it or confirm it is intentionally blank.", key=f"{bid}{ri}{ci}"))
            continue
        # a typed "N. " followed by a stray dot
        m = re.match(r"^\s*(?:\d+\s*\.)?\s*\.\s+\S", txt)
        if (b.get("list") or re.match(r"^\s*\d+\s*\.", txt)) and re.match(r"^\s*(\d+\s*\.\s*)?\.\s", txt):
            find = re.match(r"^\s*(?:\d+\s*\.\s*)?(\.\s)", txt).group(1)
            out.append(finding("stray-dot", "error", [bid], f"A stray “.” follows the question number: “{txt[:60]}”.", "Remove the extra full stop.", excerpt=txt[:80], fix=[{"block": bid, "find": find, "replace": ""}]))
        for m in re.finditer(r"(?<![.…])\.\.(?!\.)", txt):
            out.append(finding("double-period", "error", [bid], f"Double full stop: “…{txt[max(0, m.start() - 25):m.end() + 5]}”.", "Use a single full stop.", excerpt=txt[max(0, m.start() - 25):m.end() + 5], fix=[{"block": bid, "find": "..", "replace": "."}], key=txt[max(0, m.start() - 25):m.end()]))
        for m in re.finditer(r"\S {2,}\S", txt):
            out.append(finding("double-space", "warning", [bid], f"Extra spaces between words: “{txt[max(0, m.start() - 15):m.end() + 15]}”.", "Use single spaces.", excerpt=txt[max(0, m.start() - 15):m.end() + 15], fix=[{"block": bid, "find": m.group(0), "replace": re.sub(r" +", " ", m.group(0))}], blocking=False, key=m.group(0) + bid))
        for m in re.finditer(r"\w \.|\w ,|\d+ \.\s", txt):
            out.append(finding("space-before-punct", "warning", [bid], f"Space before punctuation: “{txt[max(0, m.start() - 15):m.end() + 12]}”.", "Remove the space.", excerpt=txt[max(0, m.start() - 15):m.end() + 12], fix=[{"block": bid, "find": m.group(0), "replace": m.group(0).replace(" ", "", 1)}], blocking=False, key=m.group(0) + bid))
        label_only = re.fullmatch(r"\s*\(?\s*(\d+|[a-zA-Z]|[ivxIVX]+)\s*\)?\s*[.:]?\s*", txt) is not None
        if not label_only and (txt.count("(") != txt.count(")") or txt.count("“") != txt.count("”") or txt.count("[") != txt.count("]")):
            out.append(finding("unbalanced", "warning", [bid], f"Unbalanced brackets or quotes in: “{txt[:80]}…”.", "Check for a missing closing/opening mark.", excerpt=txt[:100], blocking=False))
        if re.search(r"[^\x00-⿿\U0001F300-\U0001FAFF]", txt) or "�" in txt:
            out.append(finding("odd-character", "warning", [bid], f"Unusual character in: “{txt[:80]}”.", "Check the encoding/symbol.", excerpt=txt[:100], blocking=False))

    # inline bullets / manual line breaks inside one paragraph (grouped, informational)
    inline = [b["id"] for b in blocks if b["t"] == "p" and (("\n" in b["text"] and "•" in b["text"]) or re.search(r"\S\s*•\s*\S", b["text"]) and not b["text"].lstrip().startswith("•"))]
    if inline:
        out.append(finding("inline-bullets", "info", inline[:40], f"{len(inline)} paragraphs contain bullets typed inside the paragraph (e.g. “As a result:• …• …”). The app splits them into real lists; no action needed unless a split looks wrong in the preview.", "Optional: convert to real list items in the doc.", blocking=False, key=len(inline)))

    out += numbering_findings(blocks, book)
    out += mcq_findings(blocks)
    return out


def numbering_findings(blocks, book):
    """Question numbers: continuous, no repeats, ranges in headings match, hints align with questions."""
    out = []
    idx = {b["id"]: i for i, b in enumerate(blocks)}
    marks = {}
    for s in book["sections"]:
        pass
    # find section bounds by marker text
    def at(txt, start=0):
        for i in range(start, len(blocks)):
            if blocks[i]["t"] in ("p", "h") and re.sub(r"\s+", " ", blocks[i].get("text", "")).strip().upper() == txt:
                return i
        return None

    test_i = at("TEST YOUR CONCEPTS", 30)
    hints_i = at("HINTS AND SOLUTIONS", (test_i or 0) + 1)
    mind_i = at("MIND MAP", hints_i or 0)
    if test_i is None or hints_i is None:
        return out

    def seq(a, b):
        res = []
        for i in range(a, b):
            blk = blocks[i]
            if blk["t"] != "p":
                continue
            lab = (blk.get("list") or {})
            if lab.get("fmt") == "decimal":
                res.append((i, int(lab["num"]), "auto"))
                continue
            m = Q_RE.match(blk["text"])
            if m:
                res.append((i, int(m.group(1)), "typed"))
            elif re.fullmatch(r"\d+\s*\.", blk["text"].strip()):
                res.append((i, int(re.match(r"\d+", blk["text"].strip()).group(0)), "typed"))
        return res

    qs, hs = seq(test_i, hints_i), seq(hints_i, mind_i or len(blocks))

    def sequence_issues(s, where):
        prev = None
        seen = {}
        for i, n, kind in s:
            if n in seen:
                out.append(finding("number-repeat", "error", [blocks[i]["id"]], f"{where}: question number {n} appears twice (also at “{block_text(blocks[seen[n]])[:50]}”).", "Renumber so each number appears once.", excerpt=block_text(blocks[i])[:80], key=f"{where}{n}"))
            seen.setdefault(n, i)
            if prev is not None and n != prev + 1 and n not in seen or (prev is not None and n < prev):
                if prev is not None and n != prev + 1:
                    out.append(finding("number-jump", "error", [blocks[i]["id"]], f"{where}: numbering jumps from {prev} to {n} at “{block_text(blocks[i])[:60]}”.", f"Expected {prev + 1}.", excerpt=block_text(blocks[i])[:80], key=f"{where}{prev}-{n}"))
            prev = n

    sequence_issues(qs, "Questions")
    sequence_issues(hs, "Hints & Solutions")

    # hints vs questions: same stem text but different number (grouped when a run is consistently off)
    qtext: dict[str, set] = {}
    for i, n, kind in qs:
        t = norm(re.sub(r"\(\s*A\s*\).*$", "", re.sub(Q_RE, "", re.sub(r"^\s*\.\s*", "", blocks[i]["text"]))))
        if t:
            qtext.setdefault(t, set()).add(n)
    bad = []
    for i, n, kind in hs:
        t = norm(re.sub(Q_RE, "", re.sub(r"^\s*\.\s*", "", blocks[i]["text"])))
        want = qtext.get(t)
        if want and n not in want and len(want) == 1:
            bad.append((i, n, next(iter(want)), kind))
    k = 0
    while k < len(bad):
        j = k
        while j + 1 < len(bad) and bad[j + 1][2] - bad[j + 1][1] == bad[k][2] - bad[k][1] and bad[j + 1][1] == bad[j][1] + 1:
            j += 1
        grp = bad[k : j + 1]
        fixes = []
        for i, n, want, kind in grp:
            if blocks[i].get("list"):
                fixes.append({"block": blocks[i]["id"], "label": f"{want}."})
            else:
                fixes.append({"block": blocks[i]["id"], "find": f"{n}.", "replace": f"{want}."})
        lo, hi = grp[0], grp[-1]
        msg = (f"Answer-key items numbered {lo[1]}–{hi[1]} answer questions {lo[2]}–{hi[2]} (their text matches those questions), so every number is off by {abs(lo[2] - lo[1])}."
               if len(grp) > 1 else f"Answer-key item numbered {lo[1]} answers question {lo[2]}.")
        out.append(finding("hint-number-mismatch", "error", [blocks[x[0]]["id"] for x in grp], msg, f"Renumber them {lo[2]}–{hi[2]} (the app can do this automatically).", excerpt=block_text(blocks[lo[0]])[:80], fix=fixes, key=f"{lo[1]}-{hi[1]}->{lo[2]}"))
        k = j + 1

    # ranges stated in headings/directions vs numbers that follow
    def check_ranges(a, b, s, where):
        nums = [(i, n) for i, n, k in s]
        for i in range(a, b):
            blk = blocks[i]
            if blk["t"] not in ("p", "h"):
                continue
            t = blk["text"]
            m = re.search(r"[Qq]uestions?\s*(\d+)\s*(?:to|[-–])\s*(\d+)", t) or re.search(r"\(Q\s*(\d+)\s*[-–]\s*(\d+)\)", t)
            if not m:
                continue
            lo, hi = int(m.group(1)), int(m.group(2))
            # numbers after this heading until the next heading-like paragraph
            follow = []
            for j, n in nums:
                if j > i:
                    follow.append((j, n))
            nxt = [n for j, n in follow]
            if not nxt:
                continue
            if nxt[0] != lo:
                # actual span of the group = consecutive run starting at first follower
                run = [nxt[0]]
                for n in nxt[1:]:
                    if n == run[-1] + 1:
                        run.append(n)
                    else:
                        break
                out.append(finding("range-mismatch", "error", [blk["id"]], f"{where}: “{t.strip()}” says questions {lo}–{hi}, but the items that follow are numbered {run[0]}–{run[-1]}.", f"Change the heading to {run[0]}–{run[-1]} (or fix the numbering).", excerpt=t.strip(), key=t.strip() + str(run[0])))

    check_ranges(test_i, hints_i, qs, "Questions")
    check_ranges(hints_i, mind_i or len(blocks), hs, "Hints & Solutions")

    # duplicate headings with same range text
    seen_h = {}
    for i in range(test_i, mind_i or len(blocks)):
        b = blocks[i]
        if b["t"] == "p" and b["runs"] and b["runs"][0].get("b") and re.search(r"Q\d+\s*[-–]\s*\d+", b["text"]):
            if b["text"] in seen_h:
                out.append(finding("duplicate-heading", "warning", [b["id"]], f"The heading “{b['text']}” appears twice.", "Probably the second one needs a different range/title.", excerpt=b["text"], key=b["text"]))
            seen_h[b["text"]] = i
    return out


def mcq_findings(blocks):
    out = []
    for b in blocks:
        if b["t"] != "p":
            continue
        t = b["text"]
        ms = [m.group(1) for m in MCQ_RE.finditer(t)]
        if len(ms) >= 2 and ms != list("ABCD")[: len(ms)]:
            out.append(finding("mcq-options", "error", [b["id"]], f"Answer options are not (A)(B)(C)(D) in order: found {', '.join(ms)} in “{t[:70]}…”.", "Fix the option letters.", excerpt=t[:100]))
        elif len(ms) == 3 or len(ms) == 5:
            out.append(finding("mcq-options", "error", [b["id"]], f"A question has {len(ms)} options (expected 4): “{t[:70]}…”.", "Add/remove an option.", excerpt=t[:100]))
    return out


# ------------------------------------------------------------------ layer 2: spelling
_spell = None
WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*[A-Za-z]|[A-Za-z]")


def spelling_candidates(blocks):
    global _spell
    if _spell is None:
        from spellchecker import SpellChecker

        _spell = SpellChecker()
    cands: dict[str, list[str]] = {}
    for b in blocks:
        if b["t"] in ("img",):
            continue
        txts = [block_text(b)] if b["t"] != "tbl" else [c for r in b["rows"] for c in r]
        for txt in txts:
            for m in WORD.finditer(txt):
                w = m.group(0)
                if len(w) < 3 or w.isupper():
                    continue
                base = w.replace("’", "'")
                parts = [p for p in re.split(r"[-']", base) if p]
                bad = [p for p in parts if len(p) > 2 and p.lower() not in _spell and not p.istitle()]
                if bad:
                    cands.setdefault(w, []).append(b["id"])
    return cands


def judge_spelling(blocks, cands, model, prog=None):
    by = {b["id"]: b for b in blocks}
    items = []
    for w, ids in cands.items():
        ctx = block_text(by[ids[0]])
        i = ctx.find(w)
        items.append({"word": w, "context": ctx[max(0, i - 50): i + len(w) + 50], "blocks": ids[:3]})
    out = []
    for k in range(0, len(items), 60):
        chunk = items[k : k + 60]
        if prog:
            prog(f"Checking spelling ({k}/{len(items)})", None)
        reply = llm.ask_json(
            "Below are words flagged by a US-English dictionary in a school textbook (Indian English / British spelling is expected, "
            "e.g. aluminium, ionised, colour, litre; scientific terms and personal names are fine). "
            "Return ONLY the words that are genuinely misspelled or typo'd, as JSON: "
            '[{"word": "...", "suggestion": "...", "reason": "..."}]. Return [] if none.\n\n' + _dump(chunk),
            model=model,
            system="You are a meticulous proofreader for a school textbook. Be conservative: only flag real errors.",
        )
        bad = {r["word"]: r for r in llm.as_list(reply) if isinstance(r, dict) and r.get("word")}
        for it in chunk:
            r = bad.get(it["word"])
            if r:
                sug = r.get("suggestion", "")
                for bid in it["blocks"]:
                    out.append(finding("spelling", "error", [bid], f"Possible misspelling: “{it['word']}” → “{sug}”. {r.get('reason', '')}".strip(), f"Change to “{sug}”." if sug else "", excerpt=it["context"], fix=[{"block": bid, "find": it["word"], "replace": sug}] if sug else [], key=it["word"] + bid))
    return out


def _dump(o):
    import json

    return json.dumps(o, ensure_ascii=False, indent=0)


# ------------------------------------------------------------------ layer 3: Opus review
REVIEW_SYSTEM = """You are a senior subject teacher and proofreader reviewing a school textbook source document BEFORE it is typeset.
Students will study from it, so accuracy must be 100%. The text will be copied into the book exactly as written, so every mistake you miss ships.
Report only real problems, each tied to the block ids shown in [bNNNN] tags:
 - factual / scientific errors, wrong units, wrong formulas or arithmetic
 - answer-key errors: an answer or explanation that does not match its question (check every answer!)
 - grammar, punctuation, capitalisation, inconsistent terminology or style
 - content that contradicts another part of the document
 - ambiguous instructions, missing or duplicated questions/options, broken sentences
 - anything that looks accidentally pasted, truncated or misplaced
Do NOT flag: Indian/British spelling, stylistic preferences, or things already correct.
If you are unsure whether something is an error, report it as severity "question" and phrase it as a question to the author.

Reading notes about the source:
 - "[image]" marks a picture whose content you CANNOT see (often equations, figures or tables). Never report text as missing, empty, incomplete or out of order just because the thing it refers to is probably in an image.
 - "^" marks a superscript and "_" a subscript, e.g. x^2 is x squared. Do not report these as formatting errors.
 - Typed list labels such as "(i)", "1)" or "Soln :" are normal.
 - Judge only what you can actually read."""


def review_chunks(blocks, limit=22000):
    chunks, cur, n = [], [], 0
    for b in blocks:
        t = block_text(b)
        if b["t"] in ("p", "h") and any(r.get("sup") or r.get("sub") for r in b.get("runs", [])):
            t = "".join(("^" + r["t"]) if r.get("sup") else ("_" + r["t"]) if r.get("sub") else r["t"] for r in b["runs"])
        if b["t"] == "img":
            t = "[image]"
        line = f"[{b['id']}] " + ("(heading) " if b["t"] == "h" else "") + (f"{(b.get('list') or {}).get('label', '')} " if b.get("list") else "") + t
        if n + len(line) > limit and cur:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(line)
        n += len(line)
    if cur:
        chunks.append(cur)
    return chunks


def llm_review(blocks, meta, model, prog=None):
    out = []
    chunks = review_chunks(blocks)
    ids = {b["id"] for b in blocks}
    for ci, ch in enumerate(chunks):
        if prog:
            prog(f"Reviewing content with {model} ({ci + 1}/{len(chunks)})", ci / max(1, len(chunks)))
        reply = llm.ask_json(
            f"Book: {meta.get('subject', '')} Grade {meta.get('grade', '')}, chapter {meta.get('chapter_title', '')}. "
            f"This is part {ci + 1} of {len(chunks)} of the document.\n\n" + "\n".join(ch) +
            '\n\nReturn JSON: {"findings":[{"blocks":["bNNNN"],"severity":"error|warning|question","message":"what is wrong and why",'
            '"suggestion":"the exact correction or the question to the author","replace":{"find":"exact text in the block","replace":"corrected text"} or null}]}',
            model=model, system=REVIEW_SYSTEM, timeout=1500,
        )
        for r in (reply.get("findings") if isinstance(reply, dict) else reply) or []:
            bl = [x for x in r.get("blocks", []) if x in ids]
            if not bl:
                continue
            sev = r.get("severity") if r.get("severity") in ("error", "warning", "question") else "warning"
            rep = r.get("replace")
            fix = [{"block": bl[0], "find": rep["find"], "replace": rep["replace"]}] if isinstance(rep, dict) and rep.get("find") and "replace" in rep else []
            out.append(finding("review", sev, bl, r.get("message", ""), r.get("suggestion", ""), excerpt=r.get("message", "")[:120], fix=fix, source="llm", blocking=sev in ("error", "question"), key=r.get("message", "")[:80]))
    return out


# ------------------------------------------------------------------ orchestration & merging
def run_scan(blocks, book, meta, models, prog, use_llm=True):
    findings = rule_findings(blocks, book)
    if use_llm:
        prog("Dictionary pass…", 0.1)
        try:
            cands = spelling_candidates(blocks)
            findings += judge_spelling(blocks, cands, models["spelling"], prog)
        except llm.LLMError as e:
            findings.append(finding("llm-unavailable", "warning", [], f"Spelling check was skipped: {e}", blocking=False))
        try:
            findings += llm_review(blocks, meta, models["scan"], prog)
        except llm.LLMError as e:
            findings.append(finding("llm-unavailable", "warning", [], f"AI content review was skipped: {e}", "Fix the Claude CLI connection in Settings and re-scan.", blocking=True))
    # drop AI findings that merely repeat a block already flagged by a rule that carries its own fix
    ruled = {b for f in findings if f["source"] == "rule" and f["fix"] for b in f["blocks"]}
    findings = [f for f in findings if not (f["source"] == "llm" and f["blocks"] and all(b in ruled for b in f["blocks"]) and re.search(r"full stop|period|stray|extra space|double", f["message"], re.I))]
    # dedupe by fingerprint
    seen, uniq = set(), []
    for f in findings:
        if f["fp"] in seen:
            continue
        seen.add(f["fp"])
        uniq.append(f)
    uniq.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["blocks"][0] if f["blocks"] else ""))
    return uniq


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    """Keep the user's decisions across re-scans."""
    old_by = {f["fp"]: f for f in old}
    # Fallback match: the same issue with the same wording, even if block ids shifted after the doc was re-read
    old_msg: dict = {}
    for f in old:
        old_msg.setdefault((f["code"], f["message"]), f)
    used = set()
    out = []
    for i, f in enumerate(new):
        o = old_by.get(f["fp"])
        if o is None:
            cand = old_msg.get((f["code"], f["message"]))
            if cand is not None and cand["fp"] not in used:
                o = cand
        if o is not None:
            used.add(o["fp"])
        f = dict(f)
        if o:
            f["id"] = o["id"]
            f["thread"] = o.get("thread", [])
            st = o.get("status", "open")
            if st == "done":  # user says they fixed it, but it is still detected
                f["status"] = "open"
                f["thread"] = f["thread"] + [{"role": "app", "text": "Re-scan still finds this issue in the doc. If you changed it, make sure the doc was saved; otherwise mark it 'Not required' with a reason."}]
            else:
                f["status"] = st
            f["note"] = o.get("note", "")
        else:
            f["id"] = "f" + f["fp"]
            f["status"] = "open"
            f["thread"] = []
            f["note"] = ""
        out.append(f)
    return out
