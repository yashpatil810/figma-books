"""Fetch a Google Doc (link-shared) as .docx and parse it into an ordered list of blocks.

Block kinds:
  h    heading        {level, text, runs}
  p    paragraph      {text, runs, list?: {fmt, lvl, label, num}}
  tbl  table          {rows: [[cell text]]}
  img  image          {w, h, hash, alt}
Every block has a stable id (b0001...) used to trace content through scan -> layout -> verify.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile

import httpx
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS = {"w": W, "r": R, "a": A, "wp": WP}


def q(tag: str) -> str:
    p, t = tag.split(":")
    return "{%s}%s" % (NS[p], t)


class DocError(RuntimeError):
    pass


def doc_id(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if not m:
        raise DocError("That doesn't look like a Google Docs link.")
    return m.group(1)


def fetch_docx(url: str) -> bytes:
    did = doc_id(url)
    last = ""
    for u in (
        f"https://docs.google.com/document/d/{did}/export?format=docx",
        f"https://drive.google.com/uc?export=download&id={did}",
    ):
        try:
            r = httpx.get(u, follow_redirects=True, timeout=120)
        except httpx.HTTPError as e:
            last = str(e)
            continue
        if r.status_code == 200 and r.content[:2] == b"PK":
            return r.content
        last = f"HTTP {r.status_code}"
    raise DocError(f"Could not download the document ({last}). Set sharing to 'Anyone with the link can view'.")


# ---------------------------------------------------------------- numbering
class Numbering:
    def __init__(self, xml: bytes | None):
        self.num_to_abs: dict[str, str] = {}
        self.abs: dict[str, dict[int, dict]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        if not xml:
            return
        root = etree.fromstring(xml)
        for an in root.findall(q("w:abstractNum")):
            lv = {}
            for l in an.findall(q("w:lvl")):
                i = int(l.get(q("w:ilvl")))
                fmt = l.find(q("w:numFmt"))
                txt = l.find(q("w:lvlText"))
                st = l.find(q("w:start"))
                lv[i] = {
                    "fmt": fmt.get(q("w:val")) if fmt is not None else "decimal",
                    "text": txt.get(q("w:val")) if txt is not None else "%1.",
                    "start": int(st.get(q("w:val"))) if st is not None else 1,
                }
            self.abs[an.get(q("w:abstractNumId"))] = lv
        for n in root.findall(q("w:num")):
            a = n.find(q("w:abstractNumId"))
            self.num_to_abs[n.get(q("w:numId"))] = a.get(q("w:val"))

    def label(self, num_id: str, ilvl: int):
        ab = self.num_to_abs.get(num_id)
        lv = self.abs.get(ab, {}).get(ilvl)
        if lv is None:
            return None
        fmt = lv["fmt"]
        if fmt == "bullet":
            return {"fmt": "bullet", "lvl": ilvl, "label": "•", "num": None}
        c = self.counters.setdefault(ab, {})
        c[ilvl] = c.get(ilvl, lv["start"] - 1) + 1
        for deeper in [k for k in c if k > ilvl]:
            del c[deeper]
        n = c[ilvl]
        if fmt == "lowerLetter":
            s = chr(96 + (n - 1) % 26 + 1)
        elif fmt == "upperLetter":
            s = chr(64 + (n - 1) % 26 + 1)
        elif fmt in ("lowerRoman", "upperRoman"):
            s = _roman(n).lower() if fmt == "lowerRoman" else _roman(n)
        else:
            s = str(n)
        label = lv["text"].replace("%%%d" % (ilvl + 1), s)
        return {"fmt": fmt, "lvl": ilvl, "label": label, "num": n}


def _roman(n: int) -> str:
    out = ""
    for v, s in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += s
            n -= v
    return out.upper()


# ---------------------------------------------------------------- parsing
def _on(el, tag):
    if el is None:
        return False
    x = el.find(q(tag))
    if x is None:
        return False
    return x.get(q("w:val")) not in ("0", "false", "off")


def _drawings_ok(dr) -> bool:
    """Skip drawings that live in an mc:Fallback copy (they duplicate the mc:Choice one)."""
    el = dr.getparent()
    while el is not None:
        if el.tag.endswith("}Fallback"):
            return False
        el = el.getparent()
    return True


def _image_info(dr, rels, zf):
    blip = dr.find(".//" + q("a:blip"))
    if blip is None:
        return None
    rid = blip.get(q("r:embed"))
    ext = dr.find(".//" + q("wp:extent"))
    doc = dr.find(".//" + q("wp:docPr"))
    w = h = 0
    if ext is not None:
        w, h = round(int(ext.get("cx")) / 9525), round(int(ext.get("cy")) / 9525)
    target = rels.get(rid)
    hsh = ""
    if target:
        try:
            hsh = hashlib.sha1(zf.read("word/" + target)).hexdigest()[:12]
        except KeyError:
            pass
    return {"w": w, "h": h, "hash": hsh, "file": target or "", "alt": (doc.get("descr") or doc.get("title") or "") if doc is not None else ""}


def _segments(p, rels, zf) -> list[dict]:
    """Paragraph content in true reading order: [{"k":"runs","runs":[...]} | {"k":"img", ...}]."""
    segs: list[dict] = []
    cur: list[dict] = []

    def add_text(t, rpr):
        if not t:
            return
        va = rpr.find(q("w:vertAlign")) if rpr is not None else None
        run = {"t": t}
        if _on(rpr, "w:b"):
            run["b"] = 1
        if _on(rpr, "w:i"):
            run["i"] = 1
        if va is not None and va.get(q("w:val")) in ("superscript", "subscript"):
            run["sup" if va.get(q("w:val")) == "superscript" else "sub"] = 1
        if cur and {k: v for k, v in cur[-1].items() if k != "t"} == {k: v for k, v in run.items() if k != "t"}:
            cur[-1]["t"] += t
        else:
            cur.append(run)

    def flush():
        nonlocal cur
        if cur:
            segs.append({"k": "runs", "runs": cur})
            cur = []

    for el in p.iter():
        if el.tag == q("w:r"):
            rpr = el.find(q("w:rPr"))
            buf = ""
            for ch in el:
                if ch.tag == q("w:t"):
                    buf += ch.text or ""
                elif ch.tag == q("w:tab"):
                    buf += "\t"
                elif ch.tag == q("w:br") and ch.get(q("w:type")) in (None, "textWrapping"):
                    buf += "\n"
            add_text(buf, rpr)
        elif el.tag == q("w:drawing") and _drawings_ok(el):
            info = _image_info(el, rels, zf)
            if info:
                flush()
                segs.append({"k": "img", **info})
    flush()
    return segs


def _runs(p) -> list[dict]:
    """Text runs only (used for table cells)."""
    out: list[dict] = []
    for sg in _segments(p, {}, None):
        if sg["k"] == "runs":
            out += sg["runs"]
    return out


def parse_docx(data: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(data))
    doc = etree.fromstring(zf.read("word/document.xml"))
    rels = {}
    if "word/_rels/document.xml.rels" in zf.namelist():
        for r in etree.fromstring(zf.read("word/_rels/document.xml.rels")):
            rels[r.get("Id")] = r.get("Target")
    numbering = Numbering(zf.read("word/numbering.xml") if "word/numbering.xml" in zf.namelist() else None)
    body = doc.find(q("w:body"))
    blocks: list[dict] = []

    def add(b):
        b["id"] = "b%04d" % (len(blocks) + 1)
        blocks.append(b)

    def para(p):
        ppr = p.find(q("w:pPr"))
        style = None
        jc = None
        numpr = None
        if ppr is not None:
            ps = ppr.find(q("w:pStyle"))
            style = ps.get(q("w:val")) if ps is not None else None
            j = ppr.find(q("w:jc"))
            jc = j.get(q("w:val")) if j is not None else None
            numpr = ppr.find(q("w:numPr"))
        segs = _segments(p, rels, zf)
        first_text = True

        def emit_text(runs):
            nonlocal first_text
            text = "".join(r["t"] for r in runs)
            if not text.strip():
                return
            runs = [dict(r) for r in runs]
            if runs:  # centring-by-spaces in the source: strip it
                runs[0]["t"] = runs[0]["t"].lstrip()
                runs[-1]["t"] = runs[-1]["t"].rstrip()
            runs = [r for r in runs if r["t"]]
            text = "".join(r["t"] for r in runs)
            if not text:
                return
            m = re.match(r"Heading(\d)", style or "")
            if m:
                add({"t": "h", "level": int(m.group(1)), "text": text, "runs": runs, "jc": jc})
                first_text = False
                return
            b = {"t": "p", "text": text, "runs": runs, "jc": jc}
            if first_text and numpr is not None:
                nid = numpr.find(q("w:numId"))
                il = numpr.find(q("w:ilvl"))
                if nid is not None and nid.get(q("w:val")) != "0":
                    lab = numbering.label(nid.get(q("w:val")), int(il.get(q("w:val"))) if il is not None else 0)
                    if lab:
                        b["list"] = lab
            first_text = False
            add(b)

        for sg in segs:
            if sg["k"] == "img":
                add({"t": "img", **{k: v for k, v in sg.items() if k != "k"}})
            else:
                emit_text(sg["runs"])

    for el in body:
        if el.tag == q("w:p"):
            para(el)
        elif el.tag == q("w:tbl"):
            rows = []
            for tr in el.findall(q("w:tr")):
                cells = []
                for tc in tr.findall(q("w:tc")):
                    paras = ["".join(r["t"] for r in _runs(pp)).strip() for pp in tc.findall(q("w:p"))]
                    cells.append("\n".join(x for x in paras if x))
                rows.append(cells)
            if rows:
                add({"t": "tbl", "rows": rows})
        elif el.tag == q("w:sdt"):
            for pp in el.iter(q("w:p")):
                para(pp)
    return {"blocks": blocks}


def block_text(b: dict) -> str:
    if b["t"] == "tbl":
        return " | ".join(" / ".join(r) for r in b["rows"])
    if b["t"] == "img":
        return "[image]"
    return b.get("text", "")


# ---------------------------------------------------------------- page numbers (from Google's own PDF render)
def fetch_pdf(url: str) -> bytes | None:
    try:
        r = httpx.get(f"https://docs.google.com/document/d/{doc_id(url)}/export?format=pdf", follow_redirects=True, timeout=180)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except httpx.HTTPError:
        pass
    return None


def page_map(blocks: list[dict], pdf: bytes) -> dict:
    """block id -> page number in the Google Doc, by locating each block's text in order in the PDF."""
    import bisect

    from pypdf import PdfReader

    def norm(t: str) -> str:
        return re.sub(r"[^a-z0-9]", "", t.lower())

    reader = PdfReader(io.BytesIO(pdf))
    full, offsets = "", []
    for pg in reader.pages:
        offsets.append(len(full))
        full += norm(pg.extract_text() or "")
    out, ptr, last = {}, 0, 1
    for b in blocks:
        if b["t"] == "img":
            out[b["id"]] = last
            continue
        t = block_text(b)
        key = norm(t)[:40]
        if len(key) < 6:  # too short to locate reliably: stay on the current page
            out[b["id"]] = last
            continue
        i = full.find(key, ptr)
        if i < 0 or i - ptr > 20000:  # not found, or a suspiciously far jump
            out[b["id"]] = last
            continue
        ptr = i + len(key)
        last = bisect.bisect_right(offsets, i)
        out[b["id"]] = last
    return out
