"""Tiny JSON-file project store (everything stays on this machine under data/projects/<id>/)."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid

from . import config

_lock = threading.RLock()


def pdir(pid: str):
    d = config.PROJECTS / pid
    if not re.fullmatch(r"[a-z0-9]+", pid) or not d.exists():
        raise KeyError(pid)
    return d


def create(name: str, mode: str, doc_url: str, meta: dict, figma_url: str = "") -> dict:
    pid = uuid.uuid4().hex[:10]
    d = config.PROJECTS / pid
    d.mkdir(parents=True)
    from .rules import DEFAULT_THEME

    proj = {
        "id": pid, "name": name, "mode": mode, "doc_url": doc_url, "figma_url": figma_url, "meta": meta,
        "theme": DEFAULT_THEME, "created": time.time(), "stage": "setup",
        "samples_approved": False, "proceed_anyway": False, "rules": None,
    }
    save(pid, proj)
    return proj


def load(pid: str) -> dict:
    with _lock:
        return json.loads((pdir(pid) / "project.json").read_text())


def save(pid: str, proj: dict):
    with _lock:
        d = config.PROJECTS / pid
        (d / "project.json").write_text(json.dumps(proj, indent=2, ensure_ascii=False))


def update(pid: str, **kw) -> dict:
    with _lock:
        p = load(pid)
        p.update(kw)
        save(pid, p)
        return p


def read(pid: str, name: str, default=None):
    f = pdir(pid) / name
    if not f.exists():
        return default
    return json.loads(f.read_text())


def write(pid: str, name: str, data):
    with _lock:
        (pdir(pid) / name).write_text(json.dumps(data, indent=1, ensure_ascii=False))


def list_all() -> list[dict]:
    out = []
    for d in sorted(config.PROJECTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        f = d / "project.json"
        if f.exists():
            p = json.loads(f.read_text())
            out.append({k: p.get(k) for k in ("id", "name", "mode", "stage", "created", "doc_url")})
    return out


def delete(pid: str):
    import shutil

    shutil.rmtree(pdir(pid))


# ---- background jobs (scan / verify) -------------------------------------------------
JOBS: dict[str, dict] = {}


def job_get(pid: str, kind: str) -> dict:
    return JOBS.get(f"{pid}:{kind}", {"state": "idle"})


def job_run(pid: str, kind: str, fn):
    key = f"{pid}:{kind}"
    if JOBS.get(key, {}).get("state") == "running":
        return JOBS[key]
    JOBS[key] = {"state": "running", "message": "Starting…", "progress": 0, "started": time.time()}

    def prog(msg, frac=None):
        JOBS[key]["message"] = msg
        if frac is not None:
            JOBS[key]["progress"] = frac

    def work():
        try:
            fn(prog)
            JOBS[key].update(state="done", message="Done", progress=1)
        except Exception as e:  # surface to the UI
            import traceback

            traceback.print_exc()
            JOBS[key].update(state="error", message=str(e))

    threading.Thread(target=work, daemon=True).start()
    return JOBS[key]
