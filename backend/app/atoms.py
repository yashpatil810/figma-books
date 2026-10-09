"""Doc blocks -> line-level atoms (handles inline bullets, in-paragraph line breaks, list labels)."""
from __future__ import annotations

import re


def split_runs(runs: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = [[]]
    for r in runs:
        parts = r["t"].split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                lines.append([])
            if part:
                nr = dict(r)
                nr["t"] = part
                lines[-1].append(nr)
    return [l for l in lines if "".join(x["t"] for x in l).strip()]


def lstrip_runs(runs: list[dict], n: int) -> list[dict]:
    """Drop the first n characters from a run list."""
    out = []
    for r in runs:
        if n >= len(r["t"]):
            n -= len(r["t"])
            continue
        nr = dict(r)
        nr["t"] = r["t"][n:]
        n = 0
        out.append(nr)
    return out


def trim(runs: list[dict]) -> list[dict]:
    runs = [dict(r) for r in runs]
    if runs:
        runs[0]["t"] = runs[0]["t"].lstrip()
        runs[-1]["t"] = runs[-1]["t"].rstrip()
    return [r for r in runs if r["t"]]


def rtext(runs: list[dict]) -> str:
    return "".join(r["t"] for r in runs)


def all_bold(runs: list[dict]) -> bool:
    return bool(runs) and all(r.get("b") for r in runs if r["t"].strip())


BULLET_RE = re.compile(r"^\s*[•·▪●]\s*")


def build_atoms(blocks: list[dict]) -> list[dict]:
    atoms: list[dict] = []
    for b in blocks:
        t = b["t"]
        if t == "img":
            atoms.append({"k": "img", "src": b["id"], "w": b["w"], "h": b["h"], "alt": b.get("alt", ""), "hash": b.get("hash", "")})
        elif t == "tbl":
            atoms.append({"k": "tbl", "src": b["id"], "rows": b["rows"]})
        elif t == "h":
            atoms.append({"k": "h", "src": b["id"], "level": b["level"], "runs": trim(b["runs"]), "bold": True})
        else:
            lines = split_runs(b["runs"])
            lst = b.get("list")
            if lst:
                first = trim(lines[0]) if lines else []
                m = BULLET_RE.match(rtext(first))
                if m and lst["fmt"] == "bullet":  # "• " typed after an auto bullet: keep text, drop dup marker
                    first = trim(lstrip_runs(first, m.end()))
                ls = [first] + [trim(l) for l in lines[1:]]
                atoms.append({"k": "li", "src": b["id"], "bullet": lst["fmt"] == "bullet", "label": None if lst["fmt"] == "bullet" else lst["label"], "lines": ls})
                continue
            for i, ln in enumerate(lines):
                m = BULLET_RE.match(rtext(ln))
                if m:
                    atoms.append({"k": "li", "src": b["id"], "bullet": True, "label": None, "lines": [trim(lstrip_runs(ln, m.end()))], "inline": True})
                else:
                    runs = trim(ln)
                    atoms.append({"k": "p", "src": b["id"], "runs": runs, "bold": all_bold(runs), "center": b.get("jc") == "center"})
    return atoms


def atom_text(a: dict) -> str:
    if a["k"] == "li":
        return " ".join(rtext(l) for l in a["lines"])
    if a["k"] == "tbl":
        return " ".join(c for r in a["rows"] for c in r)
    if a["k"] == "img":
        return ""
    return rtext(a["runs"])
