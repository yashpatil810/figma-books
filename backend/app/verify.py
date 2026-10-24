"""Compare a Figma book with its source doc: content diff (exact), layout anomalies, TOC check, manual to-dos.

The score is deterministic code, not an LLM opinion. Opus only explains differences and writes to-do text.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata

from . import figma_api, llm, rules
from .gdoc import block_text

HEADER_Y, FOOTER_Y = 58, 792
ALLOWED_FONTS = {"Avenir", "DIN Condensed"}


def hx(c):
    return "#%02X%02X%02X" % tuple(round(c[k] * 255) for k in "rgb")


def key(tok: str) -> str:
    return re.sub(r"^[\W_]+|[\W_]+$", "", unicodedata.normalize("NFKC", tok).lower().replace("’", "'"))


def toks(s: str) -> list[str]:
    raw = [t for t in re.split(r"\s+", unicodedata.normalize("NFKC", s).replace(chr(160), " ").strip()) if t]
    out: list[str] = []
    for t in raw:  # a detached "." / "," (e.g. "64 .") belongs to the previous word
        if out and re.fullmatch(r"[.,;:!?]+", t):
            out[-1] += t
        else:
            out.append(t)
    return out


def alnum_set(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


# ------------------------------------------------------------------ figma extraction
def extract_page(frame: dict, idx: int) -> dict:
    bb = frame.get("absoluteBoundingBox") or {}
    ox, oy = bb.get("x", 0), bb.get("y", 0)
    texts, placeholders, images, shapes, diagrams = [], [], [], [], []

    def sp(n):
        d = (n.get("sharedPluginData") or {}).get("books") or {}
        return d

    def walk(n, in_ph=False):
        t = n["type"]
        b = n.get("absoluteBoundingBox") or {}
        rel = {"x": b.get("x", 0) - ox, "y": b.get("y", 0) - oy, "w": b.get("width", 0), "h": b.get("height", 0)}
        if n.get("visible") is False:
            return
        data = sp(n)
        if data.get("diagram") or re.match(r"(?i)diagram \(generated", n.get("name", "")):
            diagrams.append({"id": n["id"], "src": [x for x in (data.get("src") or "").split(",") if x], **rel})
            return
        if data.get("pic_table"):  # a table rebuilt from a picture: its text is not in the doc as text
            return
        is_ph = data.get("placeholder") or re.match(r"(?i)image placeholder", n.get("name", ""))
        if is_ph:
            placeholders.append({"id": n["id"], "name": n["name"], "src": data.get("src"), **rel})
            return
        if t == "TEXT":
            st = n.get("style", {})
            f = next((x for x in n.get("fills", []) if x.get("type") == "SOLID" and x.get("visible", True)), None)
            texts.append({
                "id": n["id"], "text": n.get("characters", ""), **rel, "family": st.get("fontFamily"), "ps": st.get("fontPostScriptName"),
                "size": st.get("fontSize"), "color": hx(f["color"]) if f else None, "name": n.get("name"),
                "zone": "header" if rel["y"] < HEADER_Y else "footer" if rel["y"] > FOOTER_Y else "body", "src": data.get("src"),
            })
            return
        for fl in n.get("fills", []) or []:
            if fl.get("type") == "IMAGE" and fl.get("visible", True):
                images.append({"id": n["id"], "name": n["name"], **rel})
        if t in ("RECTANGLE", "ELLIPSE", "VECTOR") and rel["w"] > 0:
            shapes.append(rel)
        kids = n.get("children", [])
        if "layoutMode" not in n or n.get("layoutMode") in (None, "NONE"):
            kids = sorted(kids, key=lambda c: (round(((c.get("absoluteBoundingBox") or {}).get("y", 0)) / 6), (c.get("absoluteBoundingBox") or {}).get("x", 0)))
        for c in kids:
            walk(c)

    walk(frame)
    foot = [t for t in texts if t["zone"] == "footer" and re.fullmatch(r"\d{1,3}", t["text"].strip())]
    return {
        "idx": idx, "id": frame["id"], "name": frame["name"], "w": round(bb.get("width", 0)), "h": round(bb.get("height", 0)),
        "texts": texts, "placeholders": placeholders, "images": images, "diagrams": diagrams, "page_no": int(foot[-1]["text"]) if foot else None,
        "bbox": bb,
    }


def classify_pages(pages):
    # footer zone only holds the repeated footer string and page numbers; anything else down there is
    # misplaced body text (overflow) and must still be compared
    from collections import Counter
    cnt = Counter(t["text"].strip() for p in pages for t in p["texts"] if t["zone"] == "footer")
    common = {k for k, v in cnt.items() if v >= max(2, len(pages) // 3)}
    for p in pages:
        for t in p["texts"]:
            if t["zone"] == "footer" and not re.fullmatch(r"\d{1,3}", t["text"].strip()) and t["text"].strip() not in common:
                t["zone"] = "body"
    for p in pages:
        body = " ".join(t["text"] for t in p["texts"]).lower()
        p["role"] = "content"
        if re.search(r"cover", p["name"], re.I) or not [t for t in p["texts"] if t["zone"] == "body"]:
            p["role"] = "cover/empty" if not p["texts"] else p["role"]
            if re.search(r"cover", p["name"], re.I):
                p["role"] = "cover"
        if "table of contents" in body and len(p["texts"]) < 40:
            p["role"] = "toc"
        if "end of chapter" in body and len(p["texts"]) < 12:
            p["role"] = "end"
    return pages


# ------------------------------------------------------------------ expected (doc) side
def doc_expected(blocks, ignored_ids):
    items = []  # (block_id, raw_token)
    for b in blocks:
        if b["id"] in ignored_ids or b["t"] == "img":
            continue
        parts = []
        lab = (b.get("list") or {})
        if lab.get("label") and lab.get("fmt") != "bullet":
            parts.append(lab["label"])
        if b["t"] == "tbl":
            for r in b["rows"]:
                parts += [c for c in r]
        else:
            parts.append(re.sub(r"^\s*[•·▪●]\s*", "", b["text"]).replace("\n", " "))
        for part in parts:
            for t in toks(re.sub(r"\s*•\s*", " ", part)):
                items.append((b["id"], t))
    return items


def derived_allow(blocks, ignored_ids, meta):
    """Texts that legitimately appear in Figma without being body content (derived from ignored/meta/generated)."""
    sets = []
    for b in blocks:
        if b["id"] in ignored_ids and b["t"] in ("p", "h"):
            sets.append(alnum_set(b["text"]))
        if b["id"] in ignored_ids and b["t"] == "tbl":
            for r in b["rows"]:
                for c in r:
                    sets.append(alnum_set(c))
    gen = ["chapter", "answer key", "end of chapter", "module", "key ideas"]
    for g in gen:
        sets.append(alnum_set(g))
    for k in ("subject", "grade", "chapter_title", "module"):
        if meta.get(k):
            sets.append(alnum_set(str(meta[k])))
    return [s for s in sets if s]


def node_is_derived(text, allow):
    a = alnum_set(text)
    if not a:
        return True  # pure symbols / bullets
    if all(x.isdigit() for x in a):
        return False  # numbers are never "derived": numbering must match
    return any(a <= s for s in allow)


# ------------------------------------------------------------------ compare
def compare(blocks, ignored_ids, pages, meta):
    exp = doc_expected(blocks, ignored_ids)
    exp_text = " " + " ".join(key(t) for _, t in exp if key(t)) + " "
    allow = derived_allow(blocks, ignored_ids, meta)
    fig = []  # (page_idx, node_id, raw token)
    derived_nodes = []
    for p in pages:
        if p["role"] != "content":
            continue
        for t in p["texts"]:
            if t["zone"] != "body":
                continue
            if not alnum_set(t["text"]):  # bullets / check marks / pure symbols
                continue
            for tok in toks(t["text"].replace("•", " ")):
                fig.append((p["idx"], t["id"], tok))
    ek = [(i, key(t)) for i, (_, t) in enumerate(exp) if key(t)]
    fk = [(i, key(t)) for i, (_, _, t) in enumerate(fig) if key(t)]
    a = [k for _, k in ek]
    b = [k for _, k in fk]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [o for o in sm.get_opcodes()]
    diffs, matched, warn_case = [], 0, []
    bad_tokens = 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for x, y in zip(range(i1, i2), range(j1, j2)):
                rd, rf = exp[ek[x][0]][1], fig[fk[y][0]][2]
                ukey = lambda s: re.sub(r"[“”‘’]", "'", unicodedata.normalize("NFKC", s))
                if ukey(rd) == ukey(rf):
                    matched += 1
                elif rd.lower() == rf.lower():
                    matched += 1
                    warn_case.append({"kind": "case", "doc": rd, "figma": rf, "block": exp[ek[x][0]][0], "page": fig[fk[y][0]][0], "node": fig[fk[y][0]][1]})
                else:
                    bad_tokens += 1
                    diffs.append({"kind": "punctuation", "doc": rd, "figma": rf, "block": exp[ek[x][0]][0], "page": fig[fk[y][0]][0], "node": fig[fk[y][0]][1]})
            continue
        dt = [exp[ek[x][0]][1] for x in range(i1, i2)]
        ft = [fig[fk[y][0]][2] for y in range(j1, j2)]
        blk = exp[ek[i1][0]][0] if i1 < len(ek) else (exp[ek[i1 - 1][0]][0] if ek else None)
        if j1 < len(fk):
            pg, nd = fig[fk[j1][0]][0], fig[fk[j1][0]][1]
        elif fk:
            pg, nd = fig[fk[-1][0]][0], fig[fk[-1][0]][1]
        else:
            pg, nd = None, None
        if tag == "delete":
            kind = "missing"
        elif tag == "insert":
            kind = "extra"
        else:
            r = difflib.SequenceMatcher(None, " ".join(dt).lower(), " ".join(ft).lower()).ratio()
            kind = "typo" if r >= 0.75 and len(dt) == len(ft) else "changed"
        if tag == "insert" and ft and node_is_derived(" ".join(ft), allow) and len(ft) <= 8:
            derived_nodes.append({"page": pages[pg]["name"] if pg is not None else "", "text": " ".join(ft)[:60]})
            continue
        bad_tokens += max(len(dt), len(ft))
        diffs.append({"kind": kind, "doc": " ".join(dt), "figma": " ".join(ft), "block": blk, "page": pg, "node": nd, "ctx": _ctx(exp, ek, i1, i2)})
    # text that is present but in a different reading order (e.g. two-column option layouts): warn, don't fail
    miss = [d for d in diffs if d["kind"] == "missing"]
    extra = [d for d in diffs if d["kind"] == "extra"]
    for m in miss:
        for e in extra:
            if e.get("_used"):
                continue
            if sorted(key(t) for t in m["doc"].split()) == sorted(key(t) for t in e["figma"].split()):
                e["_used"] = m["_used"] = True
                break
    moved = [d for d in diffs if d.get("_used")]
    for d in moved:
        d["kind"] = "reordered"
    if moved:
        n = sum(len(d["doc"].split()) for d in moved if d["doc"])
        bad_tokens -= n * 2 if n else 0
        matched += n
        diffs = [d for d in diffs if not (d["kind"] == "reordered" and not d["doc"])]
        warn_case += [{"kind": "reordered", "doc": d["doc"], "figma": d["figma"], "block": d["block"], "page": d["page"], "node": d["node"]} for d in diffs if d["kind"] == "reordered"]
        diffs = [d for d in diffs if d["kind"] != "reordered"]
    total = matched + bad_tokens
    score = 100.0 if not diffs else min(99.9, round(100 * matched / max(1, total), 1))
    return {"diffs": diffs, "case_warnings": warn_case, "matched": matched, "doc_tokens": len(ek), "figma_tokens": len(fk), "score": score, "derived": derived_nodes}


def _in_doc(text, exp_text):
    k = " ".join(key(t) for t in toks(text) if key(t))
    return bool(k) and (" " + k + " ") in exp_text


def _ctx(exp, ek, i1, i2):
    lo, hi = max(0, i1 - 6), min(len(ek), i2 + 6)
    return " ".join(exp[ek[x][0]][1] for x in range(lo, hi))


# ------------------------------------------------------------------ anomalies
def anomalies(pages, theme):
    out = []
    pal = set()
    for k, v in (theme or {}).items():
        if isinstance(v, str) and v.startswith("#"):
            pal.add(v.upper())
        if isinstance(v, dict):
            pal |= {x.upper() for x in v.values() if isinstance(x, str) and x.startswith("#")}
    pal |= {"#000000", "#FFFFFF"}

    def near(c):
        if c is None or not pal:
            return True
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        return any(abs(r - int(p[1:3], 16)) + abs(g - int(p[3:5], 16)) + abs(b - int(p[5:7], 16)) <= 12 for p in pal)

    for p in pages:
        nm = p["name"]
        if p["role"] in ("cover", "cover/empty"):
            continue
        lay = rules.layout_of(theme)
        if (p["w"], p["h"]) != (lay["page"]["w"], lay["page"]["h"]):
            out.append({"kind": "page-size", "page": p["idx"], "node": p["id"], "msg": f"{nm}: page size is {p['w']}×{p['h']} (expected {lay['page']['w']}×{lay['page']['h']})."})
        fonts = {}
        allowed = set(ALLOWED_FONTS)
        tf = (theme or {}).get("fonts") or {}
        if tf:  # a style with its own fonts: those are the fonts of the book
            allowed = {x["family"] for x in (tf.get("text"), tf.get("display")) if x and x.get("family")} or allowed
        for t in p["texts"]:
            fam = t["family"]
            if fam and fam not in allowed:
                fonts.setdefault(fam, t)
        for fam, t in fonts.items():
            out.append({"kind": "font", "page": p["idx"], "node": t["id"], "msg": f"{nm}: uses font “{fam}” (e.g. “{t['text'][:30]}”). The book uses {' and '.join(sorted(allowed))} only."})
        seen = set()
        for t in p["texts"]:
            if t["color"] and not near(t["color"]) and t["color"] not in seen:
                seen.add(t["color"])
                out.append({"kind": "color", "page": p["idx"], "node": t["id"], "msg": f"{nm}: text colour {t['color']} is not in the colour scheme (e.g. “{t['text'][:30]}”)."})
        for t in p["texts"]:
            if t["zone"] == "body" and alnum_set(t["text"]) and (t["y"] + t["h"] > FOOTER_Y + 6 or t["x"] + t["w"] > rules.layout_of(theme)["page"]["w"] - 30):
                out.append({"kind": "overflow", "page": p["idx"], "node": t["id"], "msg": f"{nm}: “{t['text'][:40]}…” runs into the footer or margin. Move it to the next page or resize."})
                break
        if p["role"] == "content" and not [t for t in p["texts"] if t["zone"] == "body"]:
            out.append({"kind": "empty-page", "page": p["idx"], "node": p["id"], "msg": f"{nm}: page has no body text."})
    return out


def toc_check(pages):
    toc = next((p for p in pages if p["role"] == "toc"), None)
    out = []
    if not toc:
        return out
    ts = [t for t in toc["texts"] if t["zone"] != "footer"]
    for i, t in enumerate(ts):
        if re.fullmatch(r"\d{1,3}", t["text"].strip()):
            title = next((ts[j] for j in range(i - 1, -1, -1) if not re.fullmatch(r"\d{1,3}", ts[j]["text"].strip())), None)
            if not title:
                continue
            tn = re.sub(r"[^a-z0-9]+", " ", title["text"].lower()).strip()
            target = None
            for p in pages:
                if p["role"] != "content":
                    continue
                for pt in p["texts"]:
                    if pt["zone"] == "body" and (pt["size"] or 0) >= 18 and re.sub(r"[^a-z0-9]+", " ", pt["text"].lower()).strip() == tn:
                        target = p
                        break
                if target:
                    break
            if target and target["page_no"] is not None and target["page_no"] != int(t["text"]):
                out.append({"kind": "toc", "page": toc["idx"], "node": t["id"], "msg": f"Table of contents says “{title['text']}” is on page {t['text']}, but it starts on page {target['page_no']}."})
    return out


# ------------------------------------------------------------------ report
def tid(*p):
    return hashlib.sha1("|".join(str(x) for x in p).encode()).hexdigest()[:10]


def build_todos(cmp_, anoms, tocs, pages, file_key):
    todos = []
    pname = {p["idx"]: p for p in pages}

    def link(node):
        return f"https://www.figma.com/design/{file_key}?node-id={node.replace(':', '-')}" if node else None

    seen_ids: dict = {}
    for d in cmp_["diffs"]:
        p = pname.get(d["page"])
        where = f"{p['name']} (page {p['page_no']})" if p and p["page_no"] else (p["name"] if p else "unknown page")
        if d["kind"] == "missing":
            txt = f"{where}: this doc text is missing from Figma: “{d['doc'][:160]}”. Add it."
        elif d["kind"] == "extra":
            txt = f"{where}: this text is in Figma but not in the doc: “{d['figma'][:160]}”. Remove it (or confirm it is intended)."
        elif d["kind"] == "typo":
            txt = f"{where}: spelling differs. Doc: “{d['doc'][:120]}” → Figma: “{d['figma'][:120]}”. Fix the Figma text."
        elif d["kind"] == "punctuation":
            txt = f"{where}: character/punctuation differs. Doc: “{d['doc']}” → Figma: “{d['figma']}”."
        else:
            txt = f"{where}: wording differs. Doc: “{d['doc'][:140]}” → Figma: “{d['figma'][:140]}”."
        base = tid("diff", d["kind"], d["doc"], d["figma"], d.get("node"), d.get("page"))
        n = seen_ids.get(base, 0)
        seen_ids[base] = n + 1
        d["id"] = base if n == 0 else f"{base}{n}"
        todos.append({"id": d["id"], "type": "content", "severity": "error", "text": txt, "page": d["page"], "node": d["node"], "link": link(d["node"]), "diff": d["id"]})
    for a in anoms + tocs:
        todos.append({"id": tid("anom", a["kind"], a["msg"]), "type": a["kind"], "severity": "warning", "text": a["msg"], "page": a["page"], "node": a["node"], "link": link(a["node"])})
    for p in pages:
        phs = p["placeholders"]
        if not phs:
            continue
        n = len(phs)
        todos.append({"id": tid("img", p["name"], p["id"]), "type": "image", "severity": "manual", "page": p["idx"], "node": phs[0]["id"], "link": link(phs[0]["id"]),
                      "text": f"{p['name']} (page {p['page_no'] or '?'}): place the artwork for {n} image placeholder{'s' if n > 1 else ''}, then delete the placeholder{'s' if n > 1 else ''}.",
                      "count": n})
    return todos


def judge(diffs, blocks, models, rules_prompt, prog=None):
    """Opus explains each difference and says how to fix it. Never changes the score."""
    if not diffs:
        return
    by = {b["id"]: b for b in blocks}
    for k in range(0, len(diffs), 40):
        chunk = diffs[k : k + 40]
        if prog:
            prog(f"Analysing differences ({k}/{len(diffs)})", None)
        payload = [{"id": d["id"], "kind": d["kind"], "doc": d["doc"][:300], "figma": d["figma"][:300], "context": d.get("ctx", "")[:300], "doc_block": block_text(by[d["block"]])[:200] if d.get("block") in by else ""} for d in chunk]
        try:
            import json

            reply = llm.ask_json(
                "Each item is a difference between the source document and a Figma book page. Explain it for the designer: say what is likely wrong and the exact fix. "
                f"There are {len(payload)} items: return a JSON array with exactly one object for EVERY item, using each item's id. "
                "If the difference is only a typographic/formatting artefact of the design (not a content change), say so.\n"
                'Return JSON: [{"id":"...","explanation":"one sentence","fix":"instruction for the designer","content_change":true|false}]\n\n' + json.dumps(payload, ensure_ascii=False),
                model=models["judge"], system=rules_prompt[:6000], timeout=900,
            )
            m = {r["id"]: r for r in llm.as_list(reply) if isinstance(r, dict) and r.get("id")}
            for d in chunk:
                r = m.get(d["id"])
                if r:
                    d["explanation"], d["fix"], d["content_change"] = r.get("explanation", ""), r.get("fix", ""), r.get("content_change", True)
        except Exception as e:
            for d in chunk:
                d.setdefault("explanation", "")
            diffs[0]["judge_error"] = str(e)
            break


def run(file_url: str, blocks: list[dict], ignored: list[dict], meta: dict, theme: dict, models: dict, rules_prompt: str, prog, node_id: str | None = None, use_llm=True, accepted=None):
    global HEADER_Y, FOOTER_Y
    lay = rules.layout_of(theme)  # the style's own page geometry, not a fixed one
    HEADER_Y, FOOTER_Y = lay["col"]["top"] - 6, lay["col"]["bottom"] + 6
    key_, node = figma_api.parse_url(file_url)
    node = node_id or node
    prog("Reading the Figma file…", 0.1)
    container, frames = figma_api.container_pages(key_, node)
    if not frames:
        raise figma_api.FigmaError("No pages (frames) found in that Figma selection.")
    ids = [f["id"] for f in frames]
    # container_pages returns summaries for sections at depth; fetch full frames
    full = []
    for i in range(0, len(ids), 40):
        nd = figma_api.nodes(key_, ids[i : i + 40])
        full += [nd[x]["document"] for x in ids[i : i + 40] if x in nd]
    # order: by canvas position (rows then columns)
    full.sort(key=lambda f: (round((f.get("absoluteBoundingBox") or {}).get("y", 0) / 200), (f.get("absoluteBoundingBox") or {}).get("x", 0)))
    prog("Extracting text…", 0.3)
    pages = classify_pages([extract_page(f, i) for i, f in enumerate(full)])
    ign = {x["id"] for x in ignored}
    prog("Comparing with the doc…", 0.5)
    cmp_ = compare(blocks, ign, pages, meta)
    anoms = anomalies(pages, theme)
    tocs = toc_check(pages)
    todos = build_todos(cmp_, anoms, tocs, pages, key_)
    if use_llm:
        try:
            judge(cmp_["diffs"], blocks, models, rules_prompt, prog)
        except Exception:
            pass
        ex = {d["id"]: d for d in cmp_["diffs"]}
        for t in todos:
            d = ex.get(t.get("diff"))
            if d and d.get("fix"):
                t["text"] += f"  → {d['fix']}"
    images_in_doc = sum(1 for b in blocks if b["t"] == "img" and b["id"] not in ign)
    placeholders = sum(len(p["placeholders"]) for p in pages)
    placed = sum(len(p["images"]) for p in pages if p["role"] == "content")
    return {
        "file_key": key_, "container": container.get("name"), "pages": [{k: v for k, v in p.items() if k not in ("texts", "bbox")} | {"text_nodes": len(p["texts"])} for p in pages],
        "score": cmp_["score"], "stats": {k: cmp_[k] for k in ("matched", "doc_tokens", "figma_tokens")},
        "diffs": cmp_["diffs"], "case_warnings": cmp_["case_warnings"][:200], "case_total": len(cmp_["case_warnings"]), "derived": cmp_["derived"][:50],
        "anomalies": anoms + tocs, "todos": todos, "images": {"in_doc": images_in_doc, "placeholders": placeholders, "placed": placed},
        "accepted": accepted or [],
    }
