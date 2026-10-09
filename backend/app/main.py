"""FastAPI app: projects, scan/Q&A, preview/spec, plugin job exchange, verification reports."""
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

from . import config, figma_api, gdoc, images, layout, llm, measure, rules, samples, scan, store, structure, verify

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
    p["meta"].setdefault("grade", book["meta"].get("grade", ""))
    if not p["meta"].get("grade"):
        p["meta"]["grade"] = book["meta"].get("grade", "")
    p["meta"]["chapter_title"] = book["meta"].get("chapter_title", "")
    p["doc_fetched"] = time.time()
    if p["stage"] == "setup":  # re-reading the doc must never move a project backwards
        p["stage"] = "theme" if p["mode"] == "create" else "scan"
    store.save(pid, p)
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
    }


class StructureIn(BaseModel):
    profile: Optional[str] = None
    roles: Optional[Dict[str, str]] = None
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
    if body.end_page is not None:
        p["meta"]["end_page"] = body.end_page
    store.save(pid, p)
    return get_structure(pid)


# ------------------------------------------------------------------ pictures & diagrams
@app.get("/api/projects/{pid}/images")
def get_images(pid: str):
    p = _p(pid)
    blocks = _blocks(pid)
    inv = images.inventory(pid, blocks, store.read(pid, "pages.json", {}))
    gen_jobs = {k.split(":img-", 1)[1]: v for k, v in store.JOBS.items() if k.startswith(f"{pid}:img-")}
    return {"images": inv, "job": store.job_get(pid, "images"), "gen_job": store.job_get(pid, "imggen"), "gen_jobs": gen_jobs, "chrome": bool(images.chrome_bin()), "needs_media": any(not e["has_media"] for e in inv if not e["tiny"]) or any(b["t"] == "img" and not b.get("hash") for b in blocks),
            "summary": {"total": len(inv), "tiny": sum(1 for e in inv if e["tiny"]), "diagrams": sum(1 for e in inv if e["mode"] == "generate"), "generated": sum(1 for e in inv if e["has_svg"])}}


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
    if body.mode not in ("generate", "placeholder"):
        raise HTTPException(400, "mode must be generate or placeholder")
    images.set_mode(pid, h, body.mode)
    return {"ok": True}


def _gen_one(pid, h, prog):
    p = store.load(pid)
    try:
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
        todo = [e for e in inv if e["mode"] == "generate" and (not only_missing or not e["has_svg"])]
        for i, e in enumerate(todo):
            prog(f"Drawing diagram {i + 1} of {len(todo)}", i / max(1, len(todo)))
            try:
                _gen_one(pid, e["hash"], None)
            except Exception:
                pass

    return store.job_run(pid, "imggen", work)


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
    return {"prompt": p.get("rules") or rules.rules_prompt(p["theme"]), "custom": bool(p.get("rules")), "labels": rules.THEME_LABELS}


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
    return dict(p["meta"], profile=p.get("profile", "auto"), roles=p.get("roles", {}))


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
            svgs[h] = images.svg_for(pid, h)
        if svgs[h]:
            it["svg"] = svgs[h]
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


def build_spec(pid):
    p = _p(pid)
    blocks = _blocks(pid)
    book = structure.build_book(blocks, _meta(p), _fixes(pid))
    book["theme"] = p["theme"]
    meta = book["meta"]
    meta["footer"] = p["meta"].get("footer") or f"Grade {meta.get('grade', '')} - {meta.get('subject', '')} - Module {meta.get('module', '')}".replace("-  -", "-")
    spec = layout.build_pages(book)
    attach_diagrams(pid, spec)
    spec["meta"] = meta
    spec["theme"] = p["theme"]
    spec["name"] = p["name"]
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
    store.save(pid, p)
    return {"job": job["id"], "pages": len(spec["pages"]), "overflow": spec["overflow"]}


@app.get("/api/plugin/jobs")
def plugin_jobs():
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
def plugin_job(project: Optional[str] = None):
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
