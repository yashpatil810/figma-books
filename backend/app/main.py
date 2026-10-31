"""FastAPI app: projects, scan/Q&A, preview/spec, plugin job exchange, verification reports."""
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, figma_api, gdoc, images, layout, llm, measure, rules, samples, scan, store, structure, structure_map, style_ref, verify

app = FastAPI(title="Book Builder")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _p(pid):
    try:
        return store.load(pid)
    except KeyError:
        raise HTTPException(404, "Project not found")


# ------------------------------------------------------------------ settings / status
@app.get("/api/status")
def status():
    s = config.settings()
    return {
        "claude": llm.status(), "fonts": measure.fonts_available(), "figma_token": bool(config.figma_token()),
        "plugin": {"version": plugin_version(), **figma_plugin_registration()},
        "models": s["models"], "port": s["port"],
    }


class SettingsIn(BaseModel):
    models: Optional[Dict[str, str]] = None
    claude_bin: Optional[str] = None
    figma_token: Optional[str] = None


@app.put("/api/settings")
def put_settings(s: SettingsIn):
    config.save_settings({k: v for k, v in s.dict().items() if v is not None})
    return status()


# ------------------------------------------------------------------ projects
class ProjectIn(BaseModel):
    name: str
    mode: str = "create"  # create | audit
    doc_url: str
    figma_url: str = ""
    meta: Dict[str, str] = {}


@app.get("/api/projects")
def projects():
    return store.list_all()


@app.post("/api/projects")
def create_project(p: ProjectIn):
    try:
        gdoc.doc_id(p.doc_url)
        if p.mode == "audit":
            figma_api.parse_url(p.figma_url)
    except (gdoc.DocError, figma_api.FigmaError) as e:
        raise HTTPException(400, str(e))
    meta = dict(rules.DEFAULT_META)
    meta.update(p.meta)
    return store.create(p.name, p.mode, p.doc_url, meta, p.figma_url)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    p = _p(pid)
    p["has_doc"] = store.read(pid, "blocks.json") is not None
    blocks = store.read(pid, "blocks.json")
    p["has_structure"] = bool(blocks) and structure_map.load(pid, blocks) is not None
    p["structure_job"] = store.job_get(pid, "structure")
    p["reference_job"] = store.job_get(pid, "reference")
    p["findings_count"] = len(store.read(pid, "findings.json", []))
    p["scan_job"] = store.job_get(pid, "scan")
    p["verify_job"] = store.job_get(pid, "verify")
    return p


@app.delete("/api/projects/{pid}")
def del_project(pid: str):
    _p(pid)
    store.delete(pid)
    return {"ok": True}


class MetaIn(BaseModel):
    meta: Dict[str, str]


@app.put("/api/projects/{pid}/meta")
def put_meta(pid: str, m: MetaIn):
    p = _p(pid)
    p["meta"].update(m.meta)
    store.save(pid, p)
    return p


@app.post("/api/projects/{pid}/fetch")
def fetch_doc(pid: str):
    """Download the Google Doc, parse it and map it onto the book structure."""
    p = _p(pid)
    try:
        data = gdoc.fetch_docx(p["doc_url"])
        parsed = gdoc.parse_docx(data)
    except gdoc.DocError as e:
        raise HTTPException(400, str(e))
    blocks = parsed["blocks"]
    store.write(pid, "blocks.json", blocks)
    try:
        images.save_media(pid, data, blocks)
    except Exception:
        pass
    try:  # real page numbers from Google's own rendering (best effort)
        pdf = gdoc.fetch_pdf(p["doc_url"])
        store.write(pid, "pages.json", gdoc.page_map(blocks, pdf) if pdf else {})
    except Exception:
        store.write(pid, "pages.json", {})
    book = structure.build_book(blocks, _meta(p))
    p = store.load(pid)  # fresh copy: background jobs (reference design) may have saved meanwhile
    if not p["meta"].get("grade"):
        p["meta"]["grade"] = book["meta"].get("grade", "")
    p["meta"]["chapter_title"] = book["meta"].get("chapter_title", "")
    p["doc_fetched"] = time.time()
    if p["stage"] == "setup":  # re-reading the doc must never move a project backwards
        p["stage"] = "theme" if p["mode"] == "create" else "scan"
    store.save(pid, p)
    if p["mode"] == "create":
        start_structure_read(pid, blocks)  # Claude reads the doc for meaning in the background
    return doc_summary(blocks, book)


def doc_summary(blocks, book):
    return {
        "blocks": len(blocks), "images": sum(1 for b in blocks if b["t"] == "img"), "tables": sum(1 for b in blocks if b["t"] == "tbl"),
        "headings": sum(1 for b in blocks if b["t"] == "h"), "meta": book["meta"], "issues": len(book["issues"]),
        "sections": [{"kind": s["kind"], "title": s.get("title")} for s in book["sections"]],
    }


# ------------------------------------------------------------------ how the doc is read
@app.get("/api/projects/{pid}/structure")
def get_structure(pid: str):
    p = _p(pid)
    blocks = _blocks(pid)
    book = structure.build_book(blocks, _meta(p), _fixes(pid))
    by = {b["id"]: b for b in blocks}
    pages = store.read(pid, "pages.json", {})
    sm = structure_map.load(pid, blocks)
    heads = []
    for d in book.get("dividers", []):
        heads.append({**d, "page": pages.get(d["src"]), "override": p.get("roles", {}).get(d["src"])})
    return {
        "profile": book["profile"], "chosen": p.get("profile", "auto"), "detected": structure.detect_profile(blocks),
        "outline": [{**o, "page": pages.get(o.get("src")) if o.get("src") else None} for o in book.get("outline", [])],
        "dividers": heads, "ignored": [{"id": x["id"], "reason": x["reason"], "text": gdoc.block_text(by[x["id"]])[:90] if x["id"] in by else ""} for x in book["ignored"]],
        "notes": [i for i in book["issues"] if i["severity"] != "error"][:20],
        "roles": ["body", "exercise", "answers", "mindmap", "references", "glossary", "inline", "ignore"],
        "candidates": [
            {"src": b["id"], "text": b["text"][:70], "level": b["level"], "page": pages.get(b["id"]), "role": p.get("roles", {}).get(b["id"])}
            for b in blocks if b["t"] == "h"
        ],
        "job": store.job_get(pid, "structure"),
        "map": ({"front": {k: ((f"table ({len(by[v]['rows'])} rows)" if by[v]["t"] == "tbl" else gdoc.block_text(by[v])) if v in by else None) for k, v in (sm.get("front") or {}).items()},
                 "index_entries": len(sm.get("index_entries", [])), "headings": len(sm.get("headings", [])),
                 "sections": [{**x, "page": pages.get(x["src"]), "override": p.get("roles", {}).get(x["src"]), "new_page_eff": p.get("page_breaks", {}).get(x["src"], x.get("new_page"))} for x in sm.get("sections", [])],
                 "heading_breaks": [{"src": x["src"], "title": x["title"][:80], "level": x["level"], "page": pages.get(x["src"]), "new_page": p.get("page_breaks", {}).get(x["src"], bool(x.get("new_page")))} for x in sm.get("headings", [])]} if sm else None),
        "checks": structure_checks(pid, book, blocks, sm),
        "block_breaks": [{"src": k, "on": bool(v), "text": gdoc.block_text(by[k])[:80], "page": pages.get(k)} for k, v in p.get("page_breaks", {}).items()
                         if k in by and k not in {x["src"] for x in (sm or {}).get("sections", []) + (sm or {}).get("headings", [])}],
        "pages_est": None,
    }


def laid_out(pid: str, blocks, sm: Optional[dict] = None):
    """The book laid out exactly as the Preview lays it out (theme fonts and type scale, table pictures swapped in),
    so page numbers quoted by the checks and the chat are the printed ones. Returns (book, pages-output)."""
    p = store.load(pid)
    measure.configure(p["theme"].get("fonts"))
    layout.configure(rules.layout_of(p["theme"]), p["theme"].get("caseRules"))
    meta = _meta(p)
    if sm is not None:
        meta["structure_map"] = sm
    book = structure.build_book(blocks, meta, _fixes(pid))
    book["theme"] = p["theme"]
    tables_from_pictures(pid, book)
    return book, layout.build_pages(book)


def structure_checks(pid, book, blocks, sm):
    """Plain-language sanity checks on how the doc is read. Each one is a question for the author, never a silent change."""
    out = []
    if not sm:
        out.append({"severity": "info", "code": "map-missing", "message": "The document has not been read for meaning yet. Until then, sections are guessed from heading names."})
        return out
    book, out_pages = laid_out(pid, blocks, sm)
    anchors = out_pages["anchors"]
    n_pages = sum(1 for pg in out_pages["pages"] if pg["kind"] not in ("toc", "end")) or 1
    secs = book.get("dividers", [])
    starts = [(anchors.get(f"sec{i}"), d) for i, d in enumerate(secs)]
    for i, (st, d) in enumerate(starts):
        if st is None:
            continue
        nxt = next((x[0] for x in starts[i + 1:] if x[0]), None)
        end = (nxt - 1) if nxt else max((pg["pageNo"] or 0) for pg in out_pages["pages"] if pg["kind"] != "end")
        length = end - st + 1
        limit = 70 if d["role"] == "exercise" else 90 if d["role"] == "body" else 30
        if length > limit:
            out.append({"severity": "question", "code": "section-long", "src": d["src"], "message": f"“{d['text'][:50]}” runs for {length} pages as {d['role']}. Is the whole stretch really one {d['role']} section, or did a later heading start something new?"})
        if d["role"] in ("answers", "exercise") and length >= 0.45 * n_pages and any(x["role"] == "body" for x in secs):
            out.append({"severity": "question", "code": "role-share", "src": d["src"], "message": f"“{d['text'][:50]}” is read as {d['role']} and takes {length} of {n_pages} pages. Please confirm it is not teaching content."})
    by = {b["id"]: b for b in blocks}
    for d in secs:
        if d["role"] == "answers":
            i0 = next((i for i, b in enumerate(blocks) if b["id"] == d["src"]), None)
            peek = " ".join(gdoc.block_text(b) for b in blocks[i0 + 1:i0 + 12]) if i0 is not None else ""
            if re.search(r"learning objectives|after completing this chapter|introduction to", peek, re.I):
                out.append({"severity": "question", "code": "answers-look-like-body", "src": d["src"], "message": f"“{d['text'][:50]}” is read as an answer key, but the text right after it reads like chapter content (objectives or an introduction). Check its role."})
    breaks = {**{x["src"]: x.get("new_page") for x in sm.get("sections", [])}, **{x["src"]: True for x in sm.get("headings", []) if x.get("new_page")}, **store.load(pid).get("page_breaks", {})}
    by_src = {x["src"]: x["title"] for x in sm.get("sections", []) + sm.get("headings", [])}
    prev_pg = None
    for pg in out_pages["pages"]:
        first = pg["blocks"][0] if pg["blocks"] else None
        src0 = (first or {}).get("src", [None])[0] if first else None
        if prev_pg and prev_pg["kind"] == pg["kind"] and src0 and breaks.get(src0) and first.get("t") in ("h", "title"):
            fill = layout.page_used(prev_pg["blocks"]) / layout.AVAIL
            if fill < 0.4:
                out.append({"severity": "question", "code": "sparse-page", "src": src0, "message": f"Page {prev_pg['pageNo']} is only {round(fill * 100)}% full because “{by_src.get(src0, first.get('text', ''))[:50]}” starts a new page (page {pg['pageNo']}). Untick “new page” for it if it should continue on page {prev_pg['pageNo']}."})
        prev_pg = pg
    if not (sm.get("front") or {}).get("title"):
        out.append({"severity": "info", "code": "no-title", "message": "No chapter title line was found at the top of the doc."})
    if not any(x["role"] == "body" for x in sm.get("sections", [])):
        out.append({"severity": "question", "code": "no-body", "message": "No teaching-content section was found. Is this doc only exercises or answers?"})
    for i in book.get("issues", []):
        if i.get("code") == "index-unmatched":
            out.append({"severity": "info", "code": i["code"], "message": i["message"]})
    if book.get("dropped"):
        out.append({"severity": "warning", "code": "dropped", "message": f"{len(book['dropped'])} blocks of text are not used on any page."})
    return out


def sparse_page_starts(pid: str, blocks, sm: dict) -> list[dict]:
    """Page starts (Claude's or the author's) that leave the page before them mostly empty, with the laid-out facts."""
    p = store.load(pid)
    book, out_pages = laid_out(pid, blocks, sm)
    starts = {x["src"]: x for x in sm.get("sections", []) + sm.get("headings", [])}
    overrides = p.get("page_breaks", {})
    cases, prev_pg = [], None
    pages = [pg for pg in out_pages["pages"] if pg["kind"] not in ("toc", "end")]
    for i, pg in enumerate(pages):
        first = pg["blocks"][0] if pg["blocks"] else None
        src0 = (first.get("src") or [None])[0] if first else None
        x = starts.get(src0)
        if prev_pg and x and prev_pg["kind"] == pg["kind"] and first.get("t") in ("h", "title") and overrides.get(src0, x.get("new_page")):
            fill = layout.page_used(prev_pg["blocks"]) / layout.AVAIL
            if fill < 0.4:
                nxt = next((j for j in range(i + 1, len(pages)) if pages[j]["blocks"] and (pages[j]["blocks"][0].get("src") or [None])[0] in starts and pages[j]["blocks"][0].get("t") in ("h", "title")), len(pages))
                cases.append({"id": src0, "title": x["title"][:70], "kind": "section" if "role" in x else "heading", "prev_page": prev_pg["pageNo"], "prev_fill_pct": round(fill * 100),
                              "part_pages": nxt - i, "last_page_fill_pct": round(100 * layout.page_used(pages[nxt - 1]["blocks"]) / layout.AVAIL), "author_fixed": src0 in overrides})
        prev_pg = pg
    return cases


def refine_page_starts(pid: str, blocks, models: dict, prog=None, rounds: int = 2):
    """Claude looks at its own page starts in the laid-out book (how empty the page before is, how long the part is)
    and confirms or changes them. Only Claude's decisions change; the author's own ticks stay."""
    sm = structure_map.load(pid, blocks)
    if not sm:
        return
    for _ in range(rounds):
        cases = [c for c in sparse_page_starts(pid, blocks, sm) if not c["author_fixed"]]
        if not cases:
            return
        if prog:
            prog(f"Claude is checking {len(cases)} page starts against the laid-out pages…", 0.9)
        facts = "\n".join(f"- id {c['id']}: “{c['title']}” ({c['kind']}) starts a new page; the page before it ends {c['prev_fill_pct']}% full; the part then runs {c['part_pages']} page(s), the last of them {c['last_page_fill_pct']}% full." for c in cases)
        reply = llm.ask_json(
            "You earlier decided where new pages start in a school textbook chapter. The book has now been laid out, and these page starts leave the previous page mostly empty:\n"
            + facts + "\n\nFor each one decide, as the book's designer, whether to keep the page start (true) or let that part continue below the previous text on the same page (false). "
            'Reply with JSON only: {"decisions": [{"id": "b0123", "new_page": true|false}]}',
            model=models.get("structure", "opus"), system=structure_map.SYSTEM)
        dec = {d.get("id"): d.get("new_page") for d in llm.as_list(reply.get("decisions") if isinstance(reply, dict) else reply) if isinstance(d, dict) and isinstance(d.get("new_page"), bool)}
        changed = False
        for x in sm.get("sections", []) + sm.get("headings", []):
            if x["src"] in dec and dec[x["src"]] != bool(x.get("new_page")):
                x["new_page"] = dec[x["src"]]
                changed = True
        if not changed:
            return
        structure_map.save(pid, sm)


def start_structure_read(pid: str, blocks, force: bool = False):
    """Claude reads the whole doc for meaning and labels its structure (never its text). Runs as a background job;
    nothing happens if the current map is still valid for this doc."""
    models = config.settings()["models"]

    def work(prog):
        if not force and structure_map.load(pid, blocks):
            prog("Already read", 1)
            return
        prog("Claude is reading the whole document for meaning (this takes a few minutes)…", 0.05)
        m = structure_map.read_map(pid, blocks, models, prog)
        structure_map.save(pid, m)
        store.update(pid, roles={}, page_breaks={}, structure_changed=time.time())  # a fresh reading replaces earlier per-line overrides
        refine_page_starts(pid, blocks, models, prog)

    return store.job_run(pid, "structure", work)


@app.post("/api/projects/{pid}/structure/read")
def read_structure(pid: str, force: bool = False):
    _p(pid)
    return start_structure_read(pid, _blocks(pid), force)


# ------------------------------------------------------------------ review export
SEVERITY_TAGS = {"error": "Error", "warning": "Warning", "question": "Question", "info": "Info"}


def clean_statement(msg: str) -> str:
    """The finding's statement without internal block ids (b0003, b0003–b0005, (b0003)) or doubled spaces."""
    t = re.sub(r"\(?\bb\d{4}(?:\s*[–\-,]\s*b\d{4})*\b\)?", "", msg or "")
    t = re.sub(r"\s+([,.;:)])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


@app.get("/api/projects/{pid}/findings.csv")
def findings_csv(pid: str, severities: str = "", statuses: str = ""):
    """The review comments as a CSV: Statement, Doc page, Tag. Filtered by severity (and status) if asked."""
    import csv
    import io

    from fastapi.responses import Response

    p = _p(pid)
    fs = store.read(pid, "findings.json", [])
    pages = store.read(pid, "pages.json", {})
    sev = {x.strip() for x in severities.split(",") if x.strip()}
    sts = {x.strip() for x in statuses.split(",") if x.strip()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Statement", "Doc page", "Tag"])
    rows = []
    for f in fs:
        if sev and f.get("severity") not in sev:
            continue
        if sts and f.get("status") not in sts:
            continue
        pg = [pages[b] for b in f.get("blocks", []) if b in pages]
        rows.append((min(pg) if pg else 10**6, clean_statement(f.get("message", "")), str(min(pg)) if pg else "", SEVERITY_TAGS.get(f.get("severity"), f.get("severity", ""))))
    for _, stmt, page, tag in sorted(rows, key=lambda r: r[0]):
        w.writerow([stmt, page, tag])
    name = re.sub(r"[^A-Za-z0-9]+", "-", p.get("name", "book")).strip("-")[:60] or "book"
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}-review.csv"'})


# ------------------------------------------------------------------ structure chat (requests in plain language)
CHAT_SYSTEM = (
    "You help the author of a school textbook adjust how a chapter is split into sections and pages, how its components look, its colours and its page layout. "
    "You never change, add or remove text: every word comes from the author's document. You can change five things.\n"
    "(1) The role of any line: a section start of kind body (teaching content), exercise, answers (answer key), mindmap, references or glossary, "
    "or 'inline' (not a section: just a heading inside the page) or 'ignore' (leave the line and everything up to the next section out of the book).\n"
    "(2) Where pages start. page_breaks {id: true} makes the block with that id begin at the top of a new page; {id: false} removes a forced start. "
    "Any id listed under a page in CURRENT PAGES can be used — a heading, a paragraph, a table, a list, a picture, a card — so 'move the table on page 8 to page 9 but keep the paragraph' is done with the table's own id. "
    "Sections and headings have their new_page flag in the same map. A change of page type (teaching → exercise → answer key) always starts a page because the page background changes; say so if asked otherwise. "
    "Pages are laid out with the real fonts and the current layout, so the pt used / free figures are exact and text never runs past the column: moving a block changes where it sits, never whether it fits.\n"
    "(3) The look of components, for the whole book (scope 'all') or for one section (scope = that section's id): qcard = question cards (fill, radius, numberColor, textColor, pad), mcq = MCQ cards (fill, radius, columns 1|2|4|auto — auto puts 4 short options in a row like the reference design, else 2 columns — textColor, pad), "
    "ans = answer cards (fill, tabFill, radius, textColor, pad), table (headFill, headText, zebra true/false), callout (radius), formula (fill, text), bullets (markColor), "
    "page (bg, pillBg, pillFg, rule, fg = that kind of page's colours; with scope 'all' give kind = index|body|exercise|worksheet|answers|mindmap). "
    "pad is a card's inner padding in points (0 = none); textColor unset = automatic (the page's text colour when the card has no fill). Colour values: white, none (= no fill, no box), primary, tint, text, strong, onPrimary, or a #hex.\n"
    "(4) The book's colours (#hex only): primary (the accent: header pill, bullets, numbers, table header, answer tabs), text (body text), strong (headings), tint (tinted page background / key-ideas box), "
    "white (teaching page background / cards), rule (header line), footerRule, tableAlt (zebra rows), tableBorder, onPrimary (text on the accent); the callout boxes misc (Common Misconceptions), iit (IIT Foundation), dyk (Did You Know) each with bg and fg.\n"
    "(5) The page layout, in points (CURRENT LAYOUT shows it): margins left / right / top / bottom — the text column follows ('40 px padding on both sides' = margins left 40, right 40); "
    "header (ruleX, ruleY, ruleW, pillX, pillY, pillW, pillH, pillSize), footer (ruleX, ruleY, ruleW, textX, textY, textSize, numX, numY, numSize), type (title, eyebrow, h2, h3, h4, h5, body, mark, toc: size and lh), "
    "gap (para, afterHeading, beforeHeading, beforeLabel, block, image). Header and footer positions are independent of the margins: change them only when asked or clearly implied. "
    "Changing margins or type re-flows the whole book, so page numbers move.\n"
    "(6) The front matter, i.e. what the doc's opening lines are used for (FRONT MATTER lists them with ids): front {eyebrow: the small line above the title, title: the chapter title line, "
    "index_heading: the INDEX/CONTENTS heading, index_table: the doc's index when it is a table} — each an id or null — and index_entries [ids of the lines of the doc's own contents list]. "
    "The index page is built from these: it needs an index heading or an index table (or index entry lines); its title is the index heading, else the index table's caption, else the chapter title; "
    "its entries get the printed page numbers automatically. 'index' is not a section role, so never use roles for it. Lines used as front matter are not repeated in the chapter.\n"
    "Make the result look right, as a book designer would, not just the literal change: when you remove a box (fill none) also remove its padding (pad 0) unless the author wants it kept, and make sure every text stays readable on the page background — "
    "on a dark page use light text (textColor / numberColor such as white or onPrimary), on a light page dark text. Think through what else the change affects (contrast, alignment, consistency with the other sections of the same kind) and adjust it; "
    "say in the reply what you adjusted beyond the literal request and why. Refer to pages by their printed page numbers. Describe as done only what you put in the JSON; if a request is outside these five things, say so plainly. Be brief and concrete."
)


def _runs_text(runs) -> str:
    return "".join(r.get("t", "") for r in (runs or []) if isinstance(r, dict))


def _block_preview(b: dict) -> str:
    """The first words of a laid-out block, so the chat can name it."""
    t = b.get("t")
    if t in ("title", "h", "formula"):
        return b.get("text", "")
    if t in ("p", "note"):
        return _runs_text(b.get("runs"))
    if t in ("ul", "ol"):
        it = (b.get("items") or [None])[0]
        return _runs_text(it["lines"][0] if isinstance(it, dict) and it.get("lines") else it if isinstance(it, list) else [])
    if t == "table":
        return " / ".join(str(c) for c in (b.get("head") or (b.get("rows") or [[]])[0]))
    if t == "callout":
        return b.get("title", "")
    if t == "qcard":
        it = (b.get("items") or [None])[0]
        return f"{it.get('label', '')} {_runs_text(it['lines'][0]) if it.get('lines') else ''}".strip() if it else ""
    if t == "mcq":
        return f"{b.get('n', '')} {_runs_text(b.get('stem'))}".strip()
    if t == "ans":
        it = (b.get("items") or [None])[0]
        return f"{it.get('label', '')} {_runs_text(it['blocks'][0].get('runs')) if it.get('blocks') else ''}".strip() if it else ""
    return b.get("alt", "") or ""


def _block_kind(b: dict) -> str:
    t = b.get("t")
    n = len(b.get("items") or [])
    return {"title": "section title", "h": "heading", "p": "paragraph", "note": "note", "ul": f"bullet list ({n} items)", "ol": f"numbered list ({n} items)",
            "table": f"table ({len(b.get('rows') or [])} rows)", "callout": "callout", "formula": "formula", "image": "picture", "imagerow": "pictures",
            "qcard": f"question cards ({n})", "mcq": "MCQ", "ans": f"answer cards ({n})"}.get(t, str(t))


def structure_context(pid: str, blocks) -> dict:
    """What Claude needs to understand a request: the sections, the laid-out pages and the headings."""
    p = store.load(pid)
    sm = structure_map.load(pid, blocks)
    book, out = laid_out(pid, blocks)
    anchors = out["anchors"]
    breaks = p.get("page_breaks", {})
    pages = []
    for pg in out["pages"]:
        if pg["kind"] in ("toc", "end"):
            continue
        used = layout.page_used(pg["blocks"])
        lines = [f"p{pg['pageNo']} [{pg['kind']}] {round(100 * used / layout.AVAIL)}% full ({round(layout.AVAIL - used)} pt free)"]
        for b in pg["blocks"]:  # every block with its id: the chat may start a page before any of them
            src0 = (b.get("src") or [None])[0]
            lines.append(f"  {src0 or '-'} {_block_kind(b)}{' (continued)' if b.get('cont') else ''} h={round(layout.block_h(b))} “{_block_preview(b)[:48]}”")
        pages.append("\n".join(lines))
    secs = []
    for i, d in enumerate(book.get("dividers", [])):
        start = anchors.get(f"sec{i}")
        secs.append(f"{d['src']} [{d['role']}] “{d['text'][:60]}” starts p{start} · new_page={breaks.get(d['src'], next((x.get('new_page') for x in (sm or {}).get('sections', []) if x['src'] == d['src']), True))}")
    heads = [f"{h['src']} H{h['level']} p{anchors.get('h:' + h['src'], '?')} “{h['title'][:60]}”" + (" · new_page=true" if breaks.get(h["src"], h.get("new_page")) else "") for h in (sm or {}).get("headings", [])]
    comps = rules.components_of(p["theme"])
    th = p["theme"]
    styles = ["theme colours: " + ", ".join(f"{k} {th.get(k)}" for k in rules.THEME_COLOR_KEYS) + "; callouts: " + ", ".join(f"{k} {th.get(k)}" for k in rules.CALLOUT_KEYS),
              "page kinds: " + "; ".join(f"{k} {v}" for k, v in (th.get("pageTypes") or {}).items()),
              "components everywhere: " + "; ".join(f"{c} {v}" for c, v in comps.items())]
    for src, st in (p["theme"].get("sectionStyles") or {}).items():
        styles.append(f"section {src}: {st}")
    front = []
    if sm:
        first_sec = next((x["src"] for x in sm.get("sections", [])), None)
        fr = sm.get("front") or {}
        used_as = {v: k for k, v in fr.items() if v}
        entry_ids = set(sm.get("index_entries") or [])
        for b in blocks:
            if b["id"] == first_sec or len(front) >= 40:
                break
            txt = gdoc.block_text(b).strip()
            if b["t"] == "img" or not txt:
                continue
            flags = [f for f, on in (("bold", b["t"] != "tbl" and bool(b.get("runs")) and all(r.get("b") for r in b["runs"] if r["t"].strip())), ("centred", b.get("jc") == "center")) if on]
            kind = f"table ({len(b['rows'])} rows)" if b["t"] == "tbl" else "heading" if b["t"] == "h" else "line"
            use = used_as.get(b["id"]) or ("index entry" if b["id"] in entry_ids else None)
            front.append(f"{b['id']} {kind}{' (' + ', '.join(flags) + ')' if flags else ''} “{txt[:90]}”" + (f" — used as {use.replace('_', ' ')}" if use else ""))
        toc = next((pg for pg in out["pages"] if pg["kind"] == "toc"), None)
        if toc:
            tb = toc["blocks"][0]
            front.append(f"An index page is built: eyebrow “{tb.get('eyebrow') or '-'}”, title “{tb.get('title')}”, {len(tb.get('entries') or [])} entries" + (f", chapter line “{tb['chapter_line']}”" if tb.get("chapter_line") else "") + ".")
        else:
            front.append("No index page is built (no index heading, index table or index entry lines are set).")
    else:
        front.append("(the document has not been read for meaning yet)")
    L = rules.layout_of(p["theme"])
    mg = rules.margins_of(L)
    lay = [f"page {L['page']['w']} x {L['page']['h']} pt; margins left {mg['left']}, right {mg['right']}, top {mg['top']}, bottom {mg['bottom']} (text column x {L['col']['x']} w {L['col']['w']}, from y {L['col']['top']} to y {L['col']['bottom']})",
           "header: " + ", ".join(f"{k} {v}" for k, v in L["header"].items()),
           "footer: " + ", ".join(f"{k} {v}" for k, v in L["footer"].items()),
           "type (size/lh): " + ", ".join(f"{k} {v['size']}/{v['lh']}" for k, v in L["type"].items()),
           "gap: " + ", ".join(f"{k} {v}" for k, v in L["gap"].items())]
    return {"pages": pages, "sections": secs, "headings": heads, "styles": styles, "layout": lay, "front": front, "overrides": {"roles": p.get("roles", {}), "page_breaks": breaks}}


class ChatIn(BaseModel):
    message: str


@app.get("/api/projects/{pid}/structure/chat")
def get_chat(pid: str):
    _p(pid)
    return {"turns": store.read(pid, "structure_chat.json", [])}


@app.post("/api/projects/{pid}/structure/chat")
def post_chat(pid: str, body: ChatIn):
    """One request in plain language -> Claude answers and applies the changes it can (roles / page starts)."""
    p = _p(pid)
    blocks = _blocks(pid)
    ids = {b["id"] for b in blocks}
    turns = store.read(pid, "structure_chat.json", [])
    ctx = structure_context(pid, blocks)
    history = "\n".join(f"{'Author' if t['role'] == 'user' else 'You'}: {t['text'][:400]}" for t in turns[-8:])
    prompt = (
        "CURRENT PAGES (printed page numbers; under each page its blocks: id, kind, height in pt, first words):\n" + "\n".join(ctx["pages"])
        + "\n\nSECTIONS (id [role] title · start page · new_page):\n" + "\n".join(ctx["sections"])
        + "\n\nHEADINGS INSIDE SECTIONS (id level page title):\n" + "\n".join(ctx["headings"])
        + "\n\nCURRENT COMPONENT STYLES:\n" + "\n".join(ctx["styles"])
        + "\n\nCURRENT LAYOUT:\n" + "\n".join(ctx["layout"])
        + "\n\nFRONT MATTER (the doc's opening lines before the first section, and what each is used as):\n" + "\n".join(ctx["front"])
        + (f"\n\nEARLIER CONVERSATION:\n{history}" if history else "")
        + f"\n\nAUTHOR'S REQUEST: {body.message.strip()}\n\n"
        'Reply with JSON only: {"reply": "one or two sentences to the author saying what you changed (with page numbers) or why you cannot", '
        '"roles": {"<line id>": "body|exercise|answers|mindmap|references|glossary|inline|ignore"}, "page_breaks": {"<block id>": true|false}, '
        '"styles": [{"scope": "all" or "<section id>", "component": "qcard|mcq|ans|table|callout|formula|bullets|page", "kind": "only for page with scope all", "set": {"property": value}}], '
        '"theme": {"primary|text|strong|tint|white|rule|footerRule|tableAlt|tableBorder|onPrimary": "#hex", "misc|iit|dyk": {"bg": "#hex", "fg": "#hex"}}, '
        '"layout": {"margins": {"left": pt, "right": pt, "top": pt, "bottom": pt}, "header": {...}, "footer": {...}, "type": {"body": {"size": pt, "lh": pt}}, "gap": {...}}, '
        '"front": {"eyebrow": "<id>|null", "title": "<id>|null", "index_heading": "<id>|null", "index_table": "<id>|null"}, "index_entries": ["<id>", ...], '
        '"show_pages": [printed page numbers worth looking at after the change, at most 4]}. '
        "Use only ids from the lists above. Give only the keys that should change (an empty object or omitted key = no change)."
    )
    r = llm.ask_json(prompt, model=config.settings()["models"].get("structure", "opus"), system=CHAT_SYSTEM, timeout=600)
    if not isinstance(r, dict):
        raise HTTPException(500, "Claude did not answer in the expected form.")
    rejected: list[str] = []  # what the model asked for but the app could not apply (told to the author, so the reply never overstates)
    roles = {k: v for k, v in (r.get("roles") or {}).items() if k in ids and v in ("body", "exercise", "answers", "mindmap", "references", "glossary", "inline", "ignore")}
    rejected += [f"role of {k}" for k in (r.get("roles") or {}) if k not in roles]
    breaks = {k: bool(v) for k, v in (r.get("page_breaks") or {}).items() if k in ids and isinstance(v, bool)}
    rejected += [f"page start at {k}" for k in (r.get("page_breaks") or {}) if k not in breaks]
    smap = structure_map.load(pid, blocks)
    sm = smap or {}
    section_ids = {x["src"] for x in sm.get("sections", [])} | set(p.get("roles", {}).keys())
    by = {b["id"]: gdoc.block_text(b)[:50] for b in blocks}
    blk = {b["id"]: b for b in blocks}
    map_changes: list[str] = []  # front matter lives in the structure map (it is Claude's reading of the doc, corrected by the author)
    before_map = None
    fr_in, ent_in = r.get("front"), r.get("index_entries")
    if (isinstance(fr_in, dict) and fr_in) or isinstance(ent_in, list):
        if not smap:
            rejected.append("front matter (the document has not been read for meaning yet)")
        else:
            before_map = {"front": dict(smap.get("front") or {}), "index_entries": list(smap.get("index_entries") or [])}
            new_front = dict(before_map["front"])
            for k, v in (fr_in or {}).items() if isinstance(fr_in, dict) else []:
                if k not in ("eyebrow", "title", "index_heading", "index_table"):
                    rejected.append(f"front.{k}")
                elif v is None or (v in ids and (k != "index_table" or blk[v]["t"] == "tbl")):
                    if new_front.get(k) != v:
                        new_front[k] = v
                        map_changes.append(f"{k.replace('_', ' ')} → " + (f"“{by[v]}”" if v else "none"))
                else:
                    rejected.append(f"front.{k} = {v}")
            new_entries = before_map["index_entries"]
            if isinstance(ent_in, list):
                good = [x for x in ent_in if isinstance(x, str) and x in ids]
                bad = [str(x) for x in ent_in if not (isinstance(x, str) and x in ids)]
                if bad:
                    rejected.append("index entries " + ", ".join(bad[:3]))
                order = {b["id"]: i for i, b in enumerate(blocks)}
                good.sort(key=order.get)
                if good != before_map["index_entries"]:
                    new_entries = good
                    map_changes.append(f"index entries → {len(good)} lines")
            if map_changes:
                smap["front"], smap["index_entries"] = new_front, new_entries
                structure_map.save(pid, smap)
    theme = json.loads(json.dumps(p["theme"]))
    style_changes = []
    for it in (llm.as_list(r.get("styles")) if r.get("styles") else []):
        if not isinstance(it, dict):
            continue
        comp, scope = it.get("component"), it.get("scope") or "all"
        vals = rules.clean_style(comp, it.get("set"))
        if comp not in rules.COMPONENT_SCHEMA or not vals or (scope != "all" and scope not in section_ids):
            rejected.append(f"style of {comp} ({scope})")
            continue
        label = rules.COMPONENT_LABELS[comp]
        if comp == "page":
            hexvals = {k: (rules.resolve_color(theme, v) or theme.get("white")) for k, v in vals.items()}
            desc = ", ".join(f"{k} {v}" for k, v in hexvals.items())
            if scope == "all":
                kind = it.get("kind")
                if kind not in rules.PAGE_KIND_KEYS:
                    continue
                theme.setdefault("pageTypes", {}).setdefault(kind, {}).update(hexvals)
                style_changes.append(f"{kind} pages: {desc}")
            else:
                theme.setdefault("sectionStyles", {}).setdefault(scope, {}).setdefault("page", {}).update(hexvals)
                style_changes.append(f"“{gdoc.block_text(next(b for b in blocks if b['id'] == scope))[:40]}” pages: {desc}")
            continue
        if scope == "all":
            theme.setdefault("components", {}).setdefault(comp, {}).update(vals)
            style_changes.append(f"{label} everywhere: " + ", ".join(f"{k} = {v}" for k, v in vals.items()))
        else:
            theme.setdefault("sectionStyles", {}).setdefault(scope, {}).setdefault(comp, {}).update(vals)
            style_changes.append(f"{label} in “{gdoc.block_text(next(b for b in blocks if b['id'] == scope))[:40]}”: " + ", ".join(f"{k} = {v}" for k, v in vals.items()))
    for k, v in (r.get("theme") or {}).items() if isinstance(r.get("theme"), dict) else []:
        if k in rules.THEME_COLOR_KEYS and isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            theme[k] = v.upper()
            style_changes.append(f"colour “{k}” → {v.upper()}")
        elif k in rules.CALLOUT_KEYS and isinstance(v, dict):
            pair = {kk: vv.upper() for kk, vv in v.items() if kk in ("bg", "fg") and isinstance(vv, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", vv)}
            if pair:
                theme[k] = {**(theme.get(k) or {}), **pair}
                style_changes.append(f"callout “{k}”: " + ", ".join(f"{kk} {vv}" for kk, vv in pair.items()))
    if isinstance(r.get("layout"), dict) and r["layout"]:  # margins, header/footer positions, type scale, gaps
        new_layout, done, problems = rules.change_layout(theme, r["layout"])
        if new_layout:
            theme["layout"] = new_layout
            style_changes += [f"layout: {d}" for d in done]
        rejected += problems
    before = {"roles": dict(p.get("roles", {})), "page_breaks": dict(p.get("page_breaks", {})), "map": before_map if map_changes else None,
              "theme": {k: json.loads(json.dumps(p["theme"].get(k))) for k in ("components", "sectionStyles", "pageTypes", "layout") + rules.THEME_COLOR_KEYS + rules.CALLOUT_KEYS}}
    if roles or breaks or style_changes or map_changes:
        store.update(pid, roles={**p.get("roles", {}), **roles}, page_breaks={**p.get("page_breaks", {}), **breaks}, theme=theme, structure_changed=time.time())
    changes = [f"“{by.get(k, k)}” → {v}" for k, v in roles.items()] + [f"“{by.get(k, k)}” → {'new page' if v else 'continues on the previous page'}" for k, v in breaks.items()] + map_changes + style_changes
    reply = str(r.get("reply", "")).strip()
    if rejected:
        reply += " (Not applied: " + "; ".join(rejected[:4]) + (", …" if len(rejected) > 4 else "") + ".)"
    elif not changes and re.search(r"\b(changed|set|added|moved|reduced|increased|updated)\b", reply, re.I) and not re.search(r"\b(cannot|can't|could not|not possible|unable|outside)\b", reply, re.I):
        reply += " (Nothing was changed.)"
    turns.append({"role": "user", "text": body.message.strip(), "ts": time.time()})
    turns.append({"role": "assistant", "text": reply, "changes": changes, "before": before, "show_pages": [int(x) for x in (r.get("show_pages") or []) if isinstance(x, (int, float))][:4], "ts": time.time()})
    store.write(pid, "structure_chat.json", turns)
    return {"turns": turns, "applied": bool(roles or breaks or style_changes or map_changes)}


@app.post("/api/projects/{pid}/structure/chat/undo")
def undo_chat(pid: str):
    """Put the overrides back as they were before the last chat change."""
    _p(pid)
    turns = store.read(pid, "structure_chat.json", [])
    last = next((t for t in reversed(turns) if t.get("role") == "assistant" and t.get("changes")), None)
    if not last:
        raise HTTPException(400, "Nothing to undo.")
    p = store.load(pid)
    theme = dict(p["theme"])
    for k, v in (last["before"].get("theme") or {}).items():
        if v is None:
            theme.pop(k, None)
        else:
            theme[k] = v
    store.update(pid, roles=last["before"]["roles"], page_breaks=last["before"]["page_breaks"], theme=theme, structure_changed=time.time())
    if last["before"].get("map"):
        smap = structure_map.load(pid, store.read(pid, "blocks.json") or [])
        if smap:
            smap["front"], smap["index_entries"] = last["before"]["map"]["front"], last["before"]["map"]["index_entries"]
            structure_map.save(pid, smap)
    last["changes"] = []
    last["undone"] = True
    store.write(pid, "structure_chat.json", turns)
    return {"turns": turns}


class StructureIn(BaseModel):
    profile: Optional[str] = None
    roles: Optional[Dict[str, str]] = None
    page_breaks: Optional[Dict[str, bool]] = None
    end_page: Optional[str] = None


@app.put("/api/projects/{pid}/structure")
def put_structure(pid: str, body: StructureIn):
    p = _p(pid)
    if body.profile is not None:
        if body.profile not in ("auto", "synopsis", "generic"):
            raise HTTPException(400, "profile must be auto, synopsis or generic")
        p["profile"] = body.profile
    if body.roles is not None:
        p["roles"] = {k: v for k, v in body.roles.items() if v}
    if body.page_breaks is not None:  # the screen sends only the lines the author changed
        p["page_breaks"] = {**p.get("page_breaks", {}), **body.page_breaks}
    p["structure_changed"] = time.time()
    if body.end_page is not None:
        p["meta"]["end_page"] = body.end_page
    store.save(pid, p)
    return get_structure(pid)


# ------------------------------------------------------------------ reference Figma (style)
class RefIn(BaseModel):
    url: str


@app.put("/api/projects/{pid}/reference")
def set_reference(pid: str, body: RefIn):
    p = _p(pid)
    url = body.url.strip()
    if url:
        try:
            figma_api.parse_url(url)
        except figma_api.FigmaError as e:
            raise HTTPException(400, str(e))
    ref = p.get("reference") or {}
    if url != ref.get("url"):
        p["reference"] = {"url": url} if url else None
    store.save(pid, p)
    return {"reference": p["reference"]}


@app.post("/api/projects/{pid}/reference/read")
def read_reference(pid: str):
    """Read the reference Figma once: colours, capitalisation, typography. The author can change everything afterwards."""
    p = _p(pid)
    url = (p.get("reference") or {}).get("url")
    if not url:
        raise HTTPException(400, "Paste a Figma link first.")
    models = config.settings()["models"]

    def work(prog):
        ref = style_ref.read_reference(pid, url, models, prog)
        p2 = store.load(pid)
        theme = dict(p2["theme"])
        theme.update(ref["theme"])
        theme["caseRules"] = {**rules.DEFAULT_CASE, **ref["case"]}
        theme["pageTypes"] = ref.get("page_types") or {}
        theme["fonts"] = ref.get("fonts") or {}
        theme["layout"] = ref.get("layout") or rules.DEFAULT_LAYOUT
        if ref.get("page_types", {}).get("body", {}).get("bg"):
            theme["white"] = ref["page_types"]["body"]["bg"]
        theme["name"] = "From reference: " + (ref.get("name") or "Figma file")[:60]
        store.update(pid, reference=ref, theme=theme, samples_approved=False)  # colours changed: look at the samples again

    return store.job_run(pid, "reference", work)


@app.get("/api/projects/{pid}/reference")
def get_reference(pid: str):
    p = _p(pid)
    return {"reference": p.get("reference"), "job": store.job_get(pid, "reference"), "case_labels": rules.CASE_LABELS, "case_defaults": rules.DEFAULT_CASE}


# ------------------------------------------------------------------ pictures & diagrams
@app.get("/api/projects/{pid}/images")
def get_images(pid: str):
    p = _p(pid)
    blocks = _blocks(pid)
    inv = images.inventory(pid, blocks, store.read(pid, "pages.json", {}))
    gen_jobs = {k.split(":img-", 1)[1]: v for k, v in store.JOBS.items() if k.startswith(f"{pid}:img-")}
    return {"images": inv, "job": store.job_get(pid, "images"), "gen_job": store.job_get(pid, "imggen"), "gen_jobs": gen_jobs, "chrome": bool(images.chrome_bin()), "needs_media": any(not e["has_media"] for e in inv if not e["tiny"]) or any(b["t"] == "img" and not b.get("hash") for b in blocks),
            "summary": {"total": len(inv), "tiny": sum(1 for e in inv if e["tiny"]), "diagrams": sum(1 for e in inv if e["mode"] in ("generate", "table")), "generated": sum(1 for e in inv if e["has_svg"] or e["has_table"])}}


@app.post("/api/projects/{pid}/images/analyse")
def analyse_images(pid: str, force: bool = False):
    _p(pid)
    blocks = _blocks(pid)
    models = config.settings()["models"]
    return store.job_run(pid, "images", lambda prog: images.classify(pid, blocks, models, prog, force))


class ImgIn(BaseModel):
    mode: str


@app.patch("/api/projects/{pid}/images/{h}")
def patch_image(pid: str, h: str, body: ImgIn):
    _p(pid)
    if body.mode not in ("generate", "table", "placeholder"):
        raise HTTPException(400, "mode must be generate, table or placeholder")
    images.set_mode(pid, h, body.mode)
    return {"ok": True}


def _gen_one(pid, h, prog):
    p = store.load(pid)
    try:
        if store.read(pid, "images.json", {}).get(h, {}).get("mode") == "table":
            images.extract_table(pid, h, config.settings()["models"])
        else:
            images.generate(pid, h, p["theme"], config.settings()["models"], prog)
    except Exception as e:
        st = store.read(pid, "images.json", {})
        st.setdefault(h, {}).update({"status": "failed", "error": str(e)[:300]})
        store.write(pid, "images.json", st)
        raise


@app.post("/api/projects/{pid}/images/{h}/generate")
def generate_image(pid: str, h: str):
    _p(pid)
    if not re.fullmatch(r"[0-9a-f]{6,20}", h):
        raise HTTPException(400, "bad id")
    return store.job_run(pid, "img-" + h, lambda prog: _gen_one(pid, h, prog))


@app.post("/api/projects/{pid}/images/generate-all")
def generate_all(pid: str, only_missing: bool = True):
    _p(pid)
    blocks = _blocks(pid)

    def work(prog):
        inv = images.inventory(pid, blocks, store.read(pid, "pages.json", {}))
        todo = [e for e in inv if e["mode"] in ("generate", "table") and (not only_missing or not (e["has_table"] if e["mode"] == "table" else e["has_svg"]))]
        for i, e in enumerate(todo):
            prog(f"Drawing picture {i + 1} of {len(todo)}", i / max(1, len(todo)))
            try:
                _gen_one(pid, e["hash"], None)
            except Exception:
                pass

    return store.job_run(pid, "imggen", work)


@app.post("/api/projects/{pid}/tables/prepare")
def prepare_tables(pid: str):
    """Before the Preview: find the pictures that are tables and read them into real tables (so pages are laid out correctly)."""
    _p(pid)
    blocks = _blocks(pid)
    models = config.settings()["models"]

    def work(prog):
        images.classify(pid, blocks, models, lambda m, f=0: prog("Looking at the pictures… " + m, f * 0.4))
        inv = images.inventory(pid, blocks, store.read(pid, "pages.json", {}))
        st = store.read(pid, "images.json", {})
        todo = [e for e in inv if e["class"] == "table" and not st.get(e["hash"], {}).get("mode_user") and not e["has_table"]]
        for e in todo:
            st.setdefault(e["hash"], {})["mode"] = "table"
        store.write(pid, "images.json", st)
        for i, e in enumerate(todo):
            prog(f"Reading table {i + 1} of {len(todo)}…", 0.4 + 0.6 * i / max(1, len(todo)))
            try:
                images.extract_table(pid, e["hash"], models)
            except Exception as ex:  # a table that cannot be read stays a placeholder
                st2 = store.read(pid, "images.json", {})
                st2.setdefault(e["hash"], {}).update({"status": "failed", "error": str(ex)[:300], "mode": "placeholder", "mode_user": True})
                store.write(pid, "images.json", st2)
        prog("Done", 1)

    return store.job_run(pid, "tables", work)


@app.get("/api/projects/{pid}/tables")
def tables_status(pid: str):
    _p(pid)
    return {"job": store.job_get(pid, "tables")}


@app.get("/api/projects/{pid}/media/{h}")
def media_file(pid: str, h: str):
    _p(pid)
    if not re.fullmatch(r"[0-9a-f]{6,20}", h):
        raise HTTPException(400, "bad id")
    t = images.thumb(pid, h)
    if not t:
        raise HTTPException(404, "no picture")
    return FileResponse(t, media_type="image/jpeg")


@app.get("/api/projects/{pid}/diagrams/{h}")
def diagram_file(pid: str, h: str):
    _p(pid)
    svg = images.svg_for(pid, h) if re.fullmatch(r"[0-9a-f]{6,20}", h) else None
    if not svg:
        raise HTTPException(404, "no drawing")
    from fastapi.responses import Response

    return Response(svg, media_type="image/svg+xml")


# ------------------------------------------------------------------ rules / theme / samples
@app.get("/api/projects/{pid}/rules")
def get_rules(pid: str):
    p = _p(pid)
    return {"prompt": p.get("rules") or rules.rules_prompt(p["theme"]), "custom": bool(p.get("rules")), "labels": rules.THEME_LABELS, "layout_default": rules.DEFAULT_LAYOUT, "type_labels": rules.TYPE_LABELS, "layout": rules.layout_of(p["theme"])}


class RulesIn(BaseModel):
    prompt: Optional[str] = None


@app.put("/api/projects/{pid}/rules")
def put_rules(pid: str, r: RulesIn):
    p = _p(pid)
    p["rules"] = r.prompt or None
    store.save(pid, p)
    return get_rules(pid)


@app.put("/api/projects/{pid}/theme")
def put_theme(pid: str, theme: Dict[str, Any] = Body(...)):
    p = _p(pid)
    for k, v in theme.items():
        if isinstance(v, str) and k != "name" and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise HTTPException(400, f"'{k}' must be a #RRGGBB colour")
    p["theme"].update(theme)
    p["samples_approved"] = False  # any change needs a fresh approval
    store.save(pid, p)
    return p["theme"]


@app.get("/api/projects/{pid}/samples")
def get_samples(pid: str):
    p = _p(pid)
    measure.configure(p["theme"].get("fonts"))
    layout.configure(rules.layout_of(p["theme"]), p["theme"].get("caseRules"))
    s = samples.sample_pages(p["meta"])
    s["theme"] = p["theme"]
    return s


@app.post("/api/projects/{pid}/approve-samples")
def approve(pid: str, approved: bool = True):
    p = _p(pid)
    p["samples_approved"] = approved
    if approved and p["stage"] in ("setup", "theme", "samples"):
        p["stage"] = "scan"
    store.save(pid, p)
    return p


# ------------------------------------------------------------------ scan & Q&A
def _meta(p):
    """Project meta plus the reading profile and the user's per-heading role overrides."""
    m = dict(p["meta"], profile=p.get("profile", "auto"), roles=p.get("roles", {}), page_breaks=p.get("page_breaks", {}))
    if p.get("use_structure_map", True):
        blocks = store.read(p["id"], "blocks.json")
        sm = structure_map.load(p["id"], blocks) if blocks else None
        if sm:
            m["structure_map"] = sm
    return m


def _blocks(pid):
    b = store.read(pid, "blocks.json")
    if b is None:
        raise HTTPException(400, "Fetch the document first.")
    return b


def _fixes(pid):
    # Only deterministic fixes are ever applied automatically (stray characters, double punctuation,
    # renumbering, spelling). AI-suggested rewordings are never applied silently: the text stays verbatim.
    return [x for f in store.read(pid, "findings.json", []) if f.get("status") == "auto" and (f.get("source") == "rule" or f.get("code") == "spelling") for x in f.get("fix", [])]


@app.post("/api/projects/{pid}/scan")
def start_scan(pid: str, refetch: bool = True, use_llm: bool = True):
    p = _p(pid)
    if refetch:
        fetch_doc(pid)
        p = _p(pid)
    blocks = _blocks(pid)
    models = config.settings()["models"]

    def work(prog):
        book = structure.build_book(blocks, _meta(p))
        prog("Running structural checks…", 0.05)
        fs = scan.run_scan(blocks, book, book["meta"], models, prog, use_llm=use_llm)
        old = store.read(pid, "findings.json", [])
        merged = scan.merge(old, fs)
        # keep 'auto' (proceed-anyway) decisions only for findings still present; carry over
        if use_llm:
            adjudicate(merged, blocks, models, prog)
        store.write(pid, "findings.json", merged)
        pp = store.load(pid)
        pp["stage"] = "scan"
        pp["last_scan"] = time.time()
        store.save(pid, pp)

    return store.job_run(pid, "scan", work)


def adjudicate(findings, blocks, models, prog):
    """When the user says 'not required'/'clarified', Opus decides whether the explanation settles it."""
    todo = [f for f in findings if f["status"] in ("not_required", "clarified") and f.get("note") and not f.get("judged_note") == f["note"]]
    by = {b["id"]: b for b in blocks}
    for i, f in enumerate(todo):
        prog(f"Reading your clarifications ({i + 1}/{len(todo)})", None)
        ctx = "\n".join(f"[{b}] {gdoc.block_text(by[b])[:300]}" for b in f["blocks"][:4] if b in by)
        try:
            r = llm.ask_json(
                "A proofreader flagged an issue in a textbook source document and the author answered. Decide if the answer settles it.\n\n"
                f"ISSUE: {f['message']}\nSUGGESTION: {f.get('suggestion', '')}\nTEXT:\n{ctx}\nAUTHOR'S ANSWER (status={f['status']}): {f['note']}\n\n"
                'Return JSON {"accept": true|false, "reply": "one or two sentences to the author", "followup": "a follow-up question if not accepted, else empty"}. '
                "Accept only if the explanation is sound; for factual/scientific claims, do not accept an unsupported assertion.",
                model=models["judge"],
            )
        except Exception:
            continue
        f["judged_note"] = f["note"]
        f["thread"].append({"role": "app", "text": r.get("reply", "")})
        if not r.get("accept"):
            f["status"] = "open"
            if r.get("followup"):
                f["thread"].append({"role": "app", "text": r["followup"]})


@app.get("/api/projects/{pid}/findings")
def get_findings(pid: str):
    _p(pid)
    fs = store.read(pid, "findings.json", [])
    open_block = [f for f in fs if f["status"] == "open" and f["blocking"]]
    by = {b["id"]: b for b in store.read(pid, "blocks.json", [])}
    pages = store.read(pid, "pages.json", {})
    for f in fs:
        f["context"] = [{"id": b, "text": gdoc.block_text(by[b])[:240], "page": pages.get(b)} for b in f["blocks"][:3] if b in by]
        pgs = sorted({pages[b] for b in f["blocks"] if b in pages})
        f["doc_pages"] = pgs
    return {"findings": fs, "open_blocking": len(open_block), "job": store.job_get(pid, "scan"), "ready": not open_block and bool(fs is not None and _p(pid).get("last_scan"))}


class FindingIn(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None


@app.patch("/api/projects/{pid}/findings/{fid}")
def patch_finding(pid: str, fid: str, body: FindingIn):
    _p(pid)
    fs = store.read(pid, "findings.json", [])
    f = next((x for x in fs if x["id"] == fid), None)
    if not f:
        raise HTTPException(404, "Finding not found")
    if body.status:
        if body.status not in ("open", "done", "not_required", "clarified", "auto"):
            raise HTTPException(400, "bad status")
        f["status"] = body.status
    if body.note is not None and body.note != f.get("note"):
        f["note"] = body.note
        f["thread"].append({"role": "user", "text": body.note})
    store.write(pid, "findings.json", fs)
    return f


@app.post("/api/projects/{pid}/proceed-anyway")
def proceed_anyway(pid: str):
    """Skip unresolved items: the app will handle them itself (apply suggested fixes, otherwise copy text verbatim)."""
    p = _p(pid)
    fs = store.read(pid, "findings.json", [])
    n = 0
    for f in fs:
        if f["status"] == "open" and f["blocking"]:
            f["status"] = "auto"
            f["thread"].append({"role": "app", "text": "Skipped by 'Proceed anyway'. " + ("The suggested fix will be applied while generating." if (f.get("fix") and (f.get("source") == "rule" or f.get("code") == "spelling")) else "The text will be copied exactly as written.")})
            n += 1
    store.write(pid, "findings.json", fs)
    p["proceed_anyway"] = True
    store.save(pid, p)
    return {"skipped": n}


# ------------------------------------------------------------------ preview / generate
def attach_diagrams(pid, spec):
    """Pictures the author wants generated (and that have a drawing) carry their SVG in the spec."""
    st = store.read(pid, "images.json", {})
    svgs = {}
    n = 0

    def put(it):
        nonlocal n
        h = it.get("hash")
        if not h or st.get(h, {}).get("mode") != "generate":
            return
        if h not in svgs:
            svgs[h] = images.drawing_for(pid, h)
        if svgs[h]:
            it["svg"] = svgs[h]["svg"]
            it["labels"] = svgs[h]["labels"]
            n += 1

    def walk(o):
        if isinstance(o, dict):
            if o.get("t") == "image":
                put(o)
            for k in ("items", "pics", "blocks"):
                if isinstance(o.get(k), list):
                    for x in o[k]:
                        if k in ("items", "pics") and isinstance(x, dict) and "w" in x and "h" in x:
                            put(x)
                        walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for pg in spec["pages"]:
        walk(pg["blocks"])
    spec["diagrams"] = n


def tables_from_pictures(pid, book):
    """A picture of a table becomes a real table block (house style) before pagination, so page heights are right."""
    st = store.read(pid, "images.json", {})
    cache: dict = {}

    def table_of(h):
        if h not in cache:
            t = images.table_for(pid, h) if st.get(h, {}).get("mode") == "table" else None
            cache[h] = structure.table_block({"rows": ([t["head"]] if t["head"] else []) + t["rows"], "src": None}) if t and t["rows"] else None
            if cache[h] and t["head"]:
                cache[h]["head"], cache[h]["rows"] = t["head"], t["rows"]  # an explicit header row from the picture wins over the guess
        return cache[h]

    def walk(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if isinstance(v, list):
                    o[k] = [dict(table_of(x["hash"]), src=x.get("src"), from_pic=True) if isinstance(x, dict) and x.get("t") == "image" and x.get("hash") and table_of(x["hash"]) else x for x in v]
                    for x in o[k]:
                        walk(x)
                elif isinstance(v, dict):
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(book)


ACRONYM_DEFAULTS = {"IIT", "NEET", "CBSE", "ICSE", "JEE", "DNA", "RNA", "ATP", "NCERT", "MCQ", "MCQS", "HOT", "IUPAC", "PVC", "LPG", "CNG", "UV"}


def doc_acronyms(blocks) -> list[str]:
    """Short all-caps words that appear in capitals inside ordinary (mixed-case) text are acronyms: capitalisation rules never lower them."""
    found = set(ACRONYM_DEFAULTS)
    for b in blocks:
        t = gdoc.block_text(b)
        if len(t) < 12 or t == t.upper():
            continue
        for m in re.finditer(r"\b([A-Z]{2,6})(s?)\b", t):
            found.add(m.group(1))
            if m.group(2):
                found.add(m.group(1) + "S")
    return sorted(found)


PLUGIN_DIR = config.ROOT / "figma-plugin"


def figma_plugin_registration() -> dict:
    """Which folder Figma desktop runs the Book Builder plugin from (its settings file lists development plugins)."""
    f = Path(os.path.expanduser("~/Library/Application Support/Figma/settings.json"))
    ours = str(PLUGIN_DIR / "manifest.json")
    if not f.exists():
        return {"known": False, "ok": None, "path": None, "expected": ours}
    try:
        paths = sorted(set(re.findall(r'"[^"]*?([^"]*figma-plugin/manifest\.json)"', f.read_text())))
    except Exception:
        return {"known": False, "ok": None, "path": None, "expected": ours}
    paths = ["/" + x.lstrip("/") for x in paths]
    if not paths:
        return {"known": False, "ok": None, "path": None, "expected": ours}
    ok = any(os.path.realpath(x) == os.path.realpath(ours) for x in paths)
    return {"known": True, "ok": ok, "path": paths[-1], "expected": ours}


def plugin_stale_error(version) -> Optional[str]:
    """None when the calling plugin is current; otherwise what to tell the person running it."""
    cur = plugin_version()
    try:
        v = int(version) if version not in (None, "") else 0
    except ValueError:
        v = 0
    if v == cur:
        return None
    reg = figma_plugin_registration()
    where = f" Figma is running the plugin from {reg['path']}, but this app's plugin is {reg['expected']}." if reg.get("known") and not reg.get("ok") else ""
    return (f"This copy of the plugin is out of date (version {v}, the app needs version {cur}).{where} "
            f"In Figma: Plugins → Development → Import plugin from manifest… and pick {reg['expected']}, then run Book Builder again.")


def plugin_version() -> int:
    """The spec contract number declared in figma-plugin/code.js (so the app and the file on disk can never disagree)."""
    m = re.search(r"PLUGIN_VERSION = (\d+)", (config.ROOT / "figma-plugin" / "code.js").read_text())
    return int(m.group(1)) if m else 0


def build_spec(pid):
    p = _p(pid)
    measure.configure(p["theme"].get("fonts"))
    layout.configure(rules.layout_of(p["theme"]), p["theme"].get("caseRules"))
    blocks = _blocks(pid)
    book = structure.build_book(blocks, _meta(p), _fixes(pid))
    book["theme"] = p["theme"]
    tables_from_pictures(pid, book)
    meta = book["meta"]
    meta["footer"] = p["meta"].get("footer") or f"Grade {meta.get('grade', '')} - {meta.get('subject', '')} - Module {meta.get('module', '')}".replace("-  -", "-")
    spec = layout.build_pages(book)
    attach_diagrams(pid, spec)
    spec["meta"] = meta
    # a document read for meaning keeps its capitalisation exactly as written (no Title Case restyling of headings)
    spec["theme"] = {**p["theme"], "caseRules": {**rules.DEFAULT_CASE, **(p["theme"].get("caseRules") or {})}, "acronyms": doc_acronyms(blocks), "layout": rules.layout_of(p["theme"]), "components": rules.components_of(p["theme"])}
    sstyles = p["theme"].get("sectionStyles") or {}
    for pg in spec["pages"]:  # a section with its own look carries the merged styles on each of its pages
        src = pg.get("sectionSrc")
        if src and src in sstyles:
            pg["components"] = rules.components_of(p["theme"], src)
            if sstyles[src].get("page"):
                pg["pageStyle"] = dict(sstyles[src]["page"])
    spec["name"] = p["name"]
    spec["pluginVersion"] = plugin_version()
    spec["font_warnings"] = list(measure.warnings)
    return spec, book


@app.get("/api/projects/{pid}/spec")
def get_spec(pid: str):
    spec, book = build_spec(pid)
    spec["issues"] = book["issues"]
    spec["ignored"] = book["ignored"]
    spec["dropped"] = book["dropped"]
    return spec


@app.post("/api/projects/{pid}/generate")
def generate(pid: str):
    p = _p(pid)
    fs = store.read(pid, "findings.json", [])
    blocking = [f for f in fs if f["status"] == "open" and f["blocking"]]
    if blocking and not p.get("proceed_anyway"):
        raise HTTPException(400, f"{len(blocking)} open items still need your answer (or use Proceed anyway).")
    if not p.get("samples_approved"):
        raise HTTPException(400, "Approve the sample pages first.")
    spec, book = build_spec(pid)
    if book["dropped"]:
        raise HTTPException(400, f"{len(book['dropped'])} doc blocks cannot be placed; resolve them before generating.")
    job = {"id": f"{pid}-{int(time.time())}", "project": pid, "created": time.time(), "state": "pending", "spec": spec}
    store.write(pid, "job.json", job)
    (config.DATA / "plugin_job.json").write_text(__import__("json").dumps(job, ensure_ascii=False))
    p["stage"] = "generated"
    p["last_job"] = job["id"]
    p["generated_at"] = time.time()
    store.save(pid, p)
    return {"job": job["id"], "pages": len(spec["pages"]), "overflow": spec["overflow"]}


@app.get("/api/plugin/jobs")
def plugin_jobs(plugin: Optional[str] = None):
    err = plugin_stale_error(plugin)
    if err:  # an old plugin shows this as the only "book" in its list, so the message reaches it
        return {"jobs": [{"project": "", "name": "⚠ PLUGIN OUT OF DATE — " + err, "chapter": "", "pages": 0, "created": time.time(), "state": "stale"}], "error": err}
    """Every book with a generated design, newest first, for the plugin's dropdown."""
    out = []
    for d in config.PROJECTS.iterdir():
        f = d / "job.json"
        if not f.exists():
            continue
        try:
            j = __import__("json").loads(f.read_text())
            proj = store.load(d.name)
        except Exception:
            continue
        sp = j.get("spec", {})
        out.append({"id": j["id"], "project": d.name, "name": proj.get("name") or sp.get("name") or d.name, "created": j.get("created", 0),
                    "pages": len(sp.get("pages", [])), "state": j.get("state"), "chapter": (sp.get("meta") or {}).get("chapter_title", "")})
    out.sort(key=lambda x: x["created"], reverse=True)
    return {"jobs": out}


@app.get("/api/plugin/job")
def plugin_job(project: Optional[str] = None, plugin: Optional[str] = None):
    err = plugin_stale_error(plugin)
    if err:
        return {"job": None, "error": err}
    if project:
        try:
            return {"job": store.read(project, "job.json")}
        except KeyError:
            return {"job": None}
    f = config.DATA / "plugin_job.json"
    if not f.exists():
        return {"job": None}
    return {"job": __import__("json").loads(f.read_text())}


@app.post("/api/plugin/report")
def plugin_report(rep: Dict[str, Any] = Body(...)):
    pid = (rep.get("job") or "").split("-")[0]
    try:
        store.read(pid, "job.json")
    except KeyError:
        raise HTTPException(404, "unknown job")
    rep["received"] = time.time()
    store.write(pid, "plugin_report.json", rep)
    jj = store.read(pid, "job.json")
    if jj and jj.get("id") == rep.get("job"):
        jj["state"] = "built"
        store.write(pid, "job.json", jj)
    f = config.DATA / "plugin_job.json"
    if f.exists():
        j = __import__("json").loads(f.read_text())
        if j.get("id") == rep.get("job"):
            j["state"] = "built"
            f.write_text(__import__("json").dumps(j, ensure_ascii=False))
    p = store.load(pid)
    p["stage"] = "built"
    p["plugin_section"] = rep.get("sectionId")
    store.save(pid, p)
    return {"ok": True}


@app.get("/api/projects/{pid}/plugin-report")
def get_plugin_report(pid: str):
    _p(pid)
    return store.read(pid, "plugin_report.json") or {}


# ------------------------------------------------------------------ verify & report
class VerifyIn(BaseModel):
    figma_url: Optional[str] = None
    node_id: Optional[str] = None
    use_llm: bool = True


@app.get("/api/figma/outline")
def figma_outline(url: str):
    try:
        key, node = figma_api.parse_url(url)
        o = figma_api.file_outline(key)
        o["key"], o["node"] = key, node
        return o
    except figma_api.FigmaError as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/verify")
def start_verify(pid: str, body: VerifyIn):
    p = _p(pid)
    if body.figma_url:
        p["figma_url"] = body.figma_url
    if body.node_id:
        p["figma_node"] = body.node_id
    url = p.get("figma_url")
    if not url:
        raise HTTPException(400, "Paste the link to the generated Figma section.")
    if "node-id" not in url and not p.get("figma_node") and p.get("plugin_section"):
        p["figma_node"] = p["plugin_section"]
    store.save(pid, p)
    blocks = _blocks(pid)
    models = config.settings()["models"]

    def work(prog):
        pp = store.load(pid)
        fx = _fixes(pid)
        eff = structure.apply_fixes(blocks, fx)
        book = structure.build_book(blocks, _meta(pp), fx)
        rp = pp.get("rules") or rules.rules_prompt(pp["theme"])
        rep = verify.run(url, eff, book["ignored"], book["meta"], pp["theme"], models, rp, prog, node_id=pp.get("figma_node"), use_llm=body.use_llm)
        try:
            diagram_report(pid, rep, blocks, models, prog, body.use_llm)
        except Exception as e:
            rep["diagram_error"] = str(e)[:200]
        # accepted deviations: fixes the app applied on the user's behalf, and findings the user declared not required
        fs = store.read(pid, "findings.json", [])
        rep["accepted"] = [{"message": f["message"], "status": f["status"], "note": f.get("note", "")} for f in fs if f["status"] in ("auto", "not_required", "clarified")]
        hist = store.read(pid, "reports.json", [])
        prev = store.read(pid, "report.json")
        done_marks = {t["id"]: t.get("user_done") for t in (prev or {}).get("todos", [])}
        for t in rep["todos"]:
            if done_marks.get(t["id"]):
                t["user_done"] = True
                t["still_open"] = True
        rep["time"] = time.time()
        rep["run"] = len(hist) + 1
        hist.append({"run": rep["run"], "time": rep["time"], "score": rep["score"], "diffs": len(rep["diffs"]), "todos": len(rep["todos"])})
        store.write(pid, "report.json", rep)
        store.write(pid, "reports.json", hist)
        pp = store.load(pid)
        pp["stage"] = "report"
        store.save(pid, pp)

    return store.job_run(pid, "verify", work)


def diagram_report(pid, rep, blocks, models, prog, use_llm):
    """Compare each generated diagram in Figma with the original picture (Figma's own render vs the doc image)."""
    by_hash = {b["id"]: b.get("hash") for b in blocks if b["t"] == "img"}
    items = []
    for pg in rep["pages"]:
        for d in pg.get("diagrams", []):
            h = next((by_hash.get(x) for x in d["src"] if by_hash.get(x)), None)
            items.append({"node": d["id"], "page": pg["idx"], "page_name": pg["name"], "page_no": pg.get("page_no"), "hash": h})
    rep["diagram_checks"] = []
    if not items:
        return
    link = lambda n: f"https://www.figma.com/design/{rep['file_key']}?node-id={n.replace(':', '-')}"
    renders = figma_api.render_nodes(rep["file_key"], [i["node"] for i in items], 2.0) if use_llm else {}
    work = config.CLI_CWD / "dg"
    work.mkdir(exist_ok=True)
    for k, it in enumerate(items):
        orig = images.thumb(pid, it["hash"]) if it["hash"] else None
        res = {**it, "match": None, "issues": []}
        if use_llm and orig and it["node"] in renders:
            prog(f"Checking diagram {k + 1} of {len(items)}", None)
            png = work / f"{it['node'].replace(':', '_')}.png"
            png.write_bytes(renders[it["node"]])
            try:
                txt = llm.ask_vision(
                    "orig.jpg is the ORIGINAL diagram from a school textbook. fig.png is how it was rebuilt in Figma as vector shapes.\n"
                    "Compare shapes, positions and EVERY label/number (exact spelling and values). Ignore font differences.\n"
                    'Reply JSON only: {"match": <0-100>, "issues": ["each concrete difference"]}',
                    {"orig.jpg": orig, "fig.png": png}, model=models["judge"], system="You are a careful proofreader of textbook diagrams. Use the Read tool to look at the image files.")
                r = llm.extract_json(txt)
                res["match"], res["issues"] = r.get("match"), [str(x) for x in (r.get("issues") or [])][:8]
            except Exception as e:
                res["issues"] = [f"Could not compare automatically: {str(e)[:100]}"]
        rep["diagram_checks"].append(res)
        bad = (isinstance(res["match"], (int, float)) and res["match"] < 90) or res["issues"]
        rep["todos"].append({"id": verify.tid("diagram", it["node"]), "type": "diagram", "severity": "warning" if bad else "manual", "page": it["page"], "node": it["node"], "link": link(it["node"]),
                             "text": f"{it['page_name']} (page {it['page_no'] or '?'}): generated diagram" + (f" — {res['match']}% match. " if res["match"] is not None else ". ") + ("; ".join(res["issues"][:3]) if res["issues"] else "Look at it once next to the original in the doc and confirm it is right.")})
    shutil.rmtree(work, ignore_errors=True)


@app.get("/api/projects/{pid}/report")
def get_report(pid: str):
    _p(pid)
    return {"report": store.read(pid, "report.json"), "history": store.read(pid, "reports.json", []), "job": store.job_get(pid, "verify")}


@app.get("/api/projects/{pid}/report.xlsx")
def report_xlsx(pid: str):
    """The report tabs (To-do, Differences, Layout, Capitalisation, Accepted) as one Excel workbook."""
    import io

    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    p = _p(pid)
    r = store.read(pid, "report.json")
    if not r:
        raise HTTPException(404, "No report yet")
    pg = lambda i: (r["pages"][i] if isinstance(i, int) and 0 <= i < len(r["pages"]) else {})
    pname = lambda i: pg(i).get("name", "")
    pno = lambda i: pg(i).get("page_no") or ""
    open_ = [t for t in r["todos"] if not t.get("user_done") or t.get("still_open")]
    sheets = [
        (f"To-do ({len(open_)})", ["Type", "Severity", "Page", "Page no.", "Issue", "Done", "Figma link"],
         [[t["type"], t["severity"], pname(t.get("page")), pno(t.get("page")), t["text"], "Yes" if t.get("user_done") and not t.get("still_open") else "No", t.get("link") or ""] for t in r["todos"]]),
        (f"Differences ({len(r['diffs'])})", ["Type", "Page", "Page no.", "Doc says", "Figma has", "Explanation", "Fix"],
         [[d["kind"], pname(d["page"]), pno(d["page"]), d["doc"], d["figma"], d.get("explanation", ""), d.get("fix", "")] for d in r["diffs"]]),
        (f"Layout ({len(r['anomalies'])})", ["Type", "Page", "Page no.", "Issue"],
         [[a["kind"], pname(a["page"]), pno(a["page"]), a["msg"]] for a in r["anomalies"]]),
        (f"Capitalisation ({r['case_total']})", ["Page", "Page no.", "Doc says", "Figma has"],
         [[pname(c["page"]), pno(c["page"]), c["doc"], c["figma"]] for c in r["case_warnings"]]),
        (f"Accepted ({len(r['accepted'])})", ["Status", "Message", "Note"],
         [[a["status"], a["message"], a.get("note", "")] for a in r["accepted"]]),
    ]
    wb = Workbook()
    wb.remove(wb.active)
    for title, head, rows in sheets:
        ws = wb.create_sheet(title)
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="333333")
        for row in rows:
            ws.append([("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for v in row])
        for i, h in enumerate(head, 1):
            longest = max([len(str(h))] + [len(str(rw[i - 1])) for rw in rows])
            ws.column_dimensions[get_column_letter(i)].width = min(max(longest + 2, 10), 70)
        for rw in ws.iter_rows(min_row=2):
            for c in rw:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    name = re.sub(r"[^A-Za-z0-9]+", "-", p.get("name", "book")).strip("-")[:60] or "book"
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}-report.xlsx"'})


@app.patch("/api/projects/{pid}/todos/{tid}")
def patch_todo(pid: str, tid: str, done: bool = True):
    _p(pid)
    rep = store.read(pid, "report.json")
    if not rep:
        raise HTTPException(404, "No report yet")
    for t in rep["todos"]:
        if t["id"] == tid:
            t["user_done"] = done
            t.pop("still_open", None)
    store.write(pid, "report.json", rep)
    return {"ok": True}


# ------------------------------------------------------------------ static frontend
DIST = config.ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
