"""Read-only Figma REST access (used for verification and for auditing books not made by this app)."""
from __future__ import annotations

import re

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


def _get(path: str, params: dict | None = None, timeout: int = 180):
    tok = config.figma_token()
    if not tok:
        raise FigmaError("No Figma token set. Add it in Settings.")
    r = httpx.get(API + path, params=params, headers={"X-Figma-Token": tok}, timeout=timeout)
    if r.status_code == 403:
        raise FigmaError("Figma refused access (403). Check the token has file read access to this file.")
    if r.status_code == 404:
        raise FigmaError("Figma file or node not found (404). Check the link.")
    if r.status_code == 429:
        raise FigmaError("Figma rate limit hit (429). Wait a minute and try again.")
    if r.status_code != 200:
        raise FigmaError(f"Figma error {r.status_code}: {r.text[:200]}")
    return r.json()


def nodes(file_key: str, ids: list[str], plugin_data: bool = True) -> dict:
    p = {"ids": ",".join(ids), "geometry": "paths"}
    p.pop("geometry")
    if plugin_data:
        p["plugin_data"] = "shared"
    return _get(f"/files/{file_key}/nodes", p)["nodes"]


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
