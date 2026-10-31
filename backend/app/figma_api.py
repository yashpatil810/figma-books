"""Read-only Figma REST access (used for verification and for auditing books not made by this app)."""
from __future__ import annotations

import hashlib
import json
import re
import time

import httpx

from . import config

API = "https://api.figma.com/v1"


class FigmaError(RuntimeError):
    pass


def parse_url(url: str) -> tuple[str, str | None]:
    m = re.search(r"figma\.com/(?:design|file|board|proto)/([A-Za-z0-9]+)", url)
    if not m:
        raise FigmaError("That doesn't look like a Figma file link.")
    n = re.search(r"node-id=([0-9]+)[-:]([0-9]+)", url)
    return m.group(1), (f"{n.group(1)}:{n.group(2)}" if n else None)


MAX_AUTO_WAIT = 20  # seconds: a longer Retry-After is reported instead of waited for
RETRIES = 3


def _wait_text(sec: float) -> str:
    sec = int(sec)
    if sec >= 3600:
        return f"about {round(sec / 3600, 1):g} hours"
    if sec >= 90:
        return f"about {round(sec / 60)} minutes"
    return f"{sec} seconds"


def _rate_limit_error(r) -> FigmaError:
    """What Figma said about the limit (it sends how long to wait, the plan tier and the kind of limit) in plain words."""
    h = r.headers
    try:
        wait = float(h.get("retry-after", ""))
    except ValueError:
        wait = None
    plan, kind = h.get("x-figma-plan-tier"), h.get("x-figma-rate-limit-type")
    msg = "Figma rate limit hit (429)."
    if wait is not None:
        msg += f" Figma asks to wait {_wait_text(wait)} before the next request."
    else:
        msg += " Wait a few minutes and try again."
    detail = ", ".join(x for x in (f"plan {plan}" if plan else "", f"limit type {kind}" if kind else "") if x)
    if detail:
        msg += f" ({detail}.)"
    if wait is not None and wait > 3600:
        msg += (" This is a long block, which Figma applies to tokens whose account has a view or collab seat rather than a full Dev/Full seat, "
                "or when the same token has been used heavily from several computers. Use a token from an account with a Full or Dev seat, "
                "or a separate token for each person.")
    elif plan or kind:
        msg += " The limit belongs to the token, so everyone using this token shares it; each person should create their own token."
    return FigmaError(msg)


def _get(path: str, params: dict | None = None, timeout: int = 180):
    tok = config.figma_token()
    if not tok:
        raise FigmaError("No Figma token set. Add it in Settings.")
    for attempt in range(RETRIES + 1):
        r = httpx.get(API + path, params=params, headers={"X-Figma-Token": tok}, timeout=timeout)
        if r.status_code != 429:
            break
        try:
            wait = float(r.headers.get("retry-after", ""))
        except ValueError:
            wait = 5.0 * (attempt + 1)
        if attempt == RETRIES or wait > MAX_AUTO_WAIT:
            raise _rate_limit_error(r)
        time.sleep(wait + 0.5)  # a short block clears by itself: wait it out instead of failing the whole job
    if r.status_code == 403:
        raise FigmaError("Figma refused access (403). Check the token has file read access to this file.")
    if r.status_code == 404:
        raise FigmaError("Figma file or node not found (404). Check the link.")
    if r.status_code != 200:
        raise FigmaError(f"Figma error {r.status_code}: {r.text[:200]}")
    return r.json()


def _get_cached(path: str, params: dict | None = None, ttl: int = 900):
    """Reads of a reference design change rarely: keep the answer on disk for a while so re-reading it (a retry, a second
    person, a re-run) costs no request."""
    key = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
    f = config.CACHE / f"figma-{key}.json"
    if f.exists() and time.time() - f.stat().st_mtime < ttl:
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    d = _get(path, params)
    f.write_text(json.dumps(d))
    return d


def nodes(file_key: str, ids: list[str], plugin_data: bool = True, cache: bool = False) -> dict:
    p = {"ids": ",".join(ids)}
    if plugin_data:
        p["plugin_data"] = "shared"
    return (_get_cached if cache else _get)(f"/files/{file_key}/nodes", p)["nodes"]


def file_outline(file_key: str) -> dict:
    """Pages and their top-level containers, so the user can pick what to verify."""
    d = _get(f"/files/{file_key}", {"depth": 2})
    pages = []
    for pg in d["document"]["children"]:
        items = []
        for c in pg.get("children", []):
            bb = c.get("absoluteBoundingBox") or {}
            items.append({"id": c["id"], "name": c["name"], "type": c["type"], "w": round(bb.get("width", 0)), "h": round(bb.get("height", 0)), "children": len(c.get("children", []))})
        pages.append({"id": pg["id"], "name": pg["name"], "items": items})
    return {"name": d.get("name"), "pages": pages}


def container_pages(file_key: str, node_id: str | None) -> tuple[dict, list[dict]]:
    """Resolve a node (section / page / frame) into its list of page frames."""
    if node_id is None:
        out = file_outline(file_key)
        best = None
        for pg in out["pages"]:
            for it in pg["items"]:
                if it["type"] == "SECTION" and (best is None or it["children"] > best["children"]):
                    best = it
        if best is None:
            for pg in out["pages"]:
                frames = [i for i in pg["items"] if i["type"] == "FRAME"]
                if frames:
                    best = {"id": pg["id"], "children": len(frames)}
                    break
        if best is None:
            raise FigmaError("No pages found in this file. Paste a link to a section or page (select it in Figma, right-click, Copy link).")
        node_id = best["id"]
    n = nodes(file_key, [node_id])[node_id]["document"]
    if n["type"] in ("SECTION", "CANVAS"):
        frames = [c for c in n.get("children", []) if c["type"] in ("FRAME", "COMPONENT", "INSTANCE")]
    else:
        frames = [n]
    return n, frames


def render_nodes(file_key: str, ids: list[str], scale: float = 2.0) -> dict:
    """PNG bytes per node id (Figma's own render)."""
    out = {}
    for i in range(0, len(ids), 20):
        d = _get(f"/images/{file_key}", {"ids": ",".join(ids[i : i + 20]), "format": "png", "scale": scale})
        for nid, url in (d.get("images") or {}).items():
            if url:
                r = httpx.get(url, timeout=120)
                if r.status_code == 200:
                    out[nid] = r.content
    return out
