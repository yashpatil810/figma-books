"""Theme (colour roles) and the design-rules prompt derived from the reference book."""
from __future__ import annotations

import re

DEFAULT_THEME = {
    "name": "Reference (Physics G7)",
    "primary": "#1E3A6E",       # eyebrows, header pill, bullets, numbers, table header, answer tabs
    "text": "#2E2E2E",          # body text
    "strong": "#1A1A1A",        # headings
    "tint": "#E9F1FA",          # background of TOC / test / hints / mind-map pages, key-ideas box
    "white": "#FFFFFF",         # background of synopsis pages, cards on tint pages
    "rule": "#C7D4E6",          # header rule
    "footerRule": "#ADADAD",
    "tableAlt": "#DCE6F4",      # zebra rows
    "tableBorder": "#D9D9D9",
    "onPrimary": "#FFFFFF",     # text on primary fills
    "placeholder": "#EDEFF3",
    "misc": {"bg": "#F2EAF6", "fg": "#6B2E7D"},   # Common Misconceptions
    "iit": {"bg": "#E9F5EC", "fg": "#2E7D32"},    # IIT Foundation Understanding
    "dyk": {"bg": "#FBF1DD", "fg": "#B07A1A"},    # Did You Know?
}

# Page geometry, type scale and spacing. The defaults are the app's own; a reference design replaces them.
DEFAULT_LAYOUT = {
    "page": {"w": 595, "h": 842},
    "col": {"x": 40, "w": 515, "top": 64, "bottom": 786},
    "header": {"ruleX": 35, "ruleY": 40, "ruleW": 372, "pillX": 417, "pillY": 33, "pillW": 142, "pillH": 16, "pillSize": 7},
    "footer": {"ruleX": 35, "ruleY": 801, "ruleW": 525, "textX": 35, "textY": 813, "textSize": 8, "numX": 520, "numY": 814, "numSize": 8},
    "type": {
        "title": {"size": 42, "lh": 50.4}, "eyebrow": {"size": 20, "lh": 24}, "h2": {"size": 18, "lh": 21.6}, "h3": {"size": 13, "lh": 17.8},
        "h4": {"size": 11, "lh": 15}, "h5": {"size": 11, "lh": 15}, "body": {"size": 11, "lh": 15}, "mark": {"size": 10, "lh": 13.7}, "toc": {"size": 18, "lh": 21.6},
    },
    "gap": {"para": 3, "afterHeading": 5, "beforeHeading": 11, "beforeLabel": 10, "block": 10, "image": 5},
}
TYPE_LABELS = {"title": "Page / section title", "eyebrow": "Eyebrow", "h2": "Heading 2", "h3": "Heading 3", "h4": "Heading 4", "h5": "Heading 5", "body": "Body text", "mark": "Bullet mark", "toc": "Index entry"}
_LIMITS = {"size": (4, 120), "lh": (4, 160), "w": (200, 2000), "h": (200, 3000)}


def layout_of(theme: dict | None) -> dict:
    """The theme's layout merged over the defaults; any number that is missing or implausible falls back to the default."""
    import copy

    out = copy.deepcopy(DEFAULT_LAYOUT)
    custom = (theme or {}).get("layout") or {}
    for group, vals in custom.items():
        if group not in out or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k not in out[group]:
                continue
            if group == "type":
                if isinstance(v, dict):
                    for f in ("size", "lh"):
                        x = v.get(f)
                        if isinstance(x, (int, float)) and _LIMITS[f][0] <= x <= _LIMITS[f][1]:
                            out["type"][k][f] = float(x)
            elif isinstance(v, (int, float)) and -50 <= v <= 3000:
                out[group][k] = float(v) if not float(v).is_integer() else int(v)
    c = out["col"]
    if not (c["top"] < c["bottom"] <= out["page"]["h"] and c["x"] + c["w"] <= out["page"]["w"]):
        out["col"] = copy.deepcopy(DEFAULT_LAYOUT["col"])
        out["page"] = copy.deepcopy(DEFAULT_LAYOUT["page"])
    return out


LAYOUT_LABELS = {"page": "page size", "col": "text column", "header": "header", "footer": "footer", "type": "type", "gap": "spacing"}


def _num(v):
    v = float(v)
    return int(v) if v.is_integer() else round(v, 2)


def margins_of(layout: dict) -> dict:
    """The page margins implied by the text column: left = col.x, right = page.w - col.x - col.w, top = col.top, bottom = page.h - col.bottom."""
    pg, c = layout["page"], layout["col"]
    return {"left": _num(c["x"]), "right": _num(pg["w"] - c["x"] - c["w"]), "top": _num(c["top"]), "bottom": _num(pg["h"] - c["bottom"])}


def change_layout(theme: dict | None, change) -> tuple[dict | None, list[str], list[str]]:
    """Apply a layout request (from the structure chat) to the theme's layout spec.
    change = {"margins": {"left": 40, "right": 40, "top": .., "bottom": ..}, "col"|"header"|"footer"|"gap"|"page": {key: number},
              "type": {role: {"size": .., "lh": ..}}}. Margins are the natural way to say where the text sits; the raw groups
    allow anything else the spec holds. Returns (the new full layout or None when nothing valid was asked, what changed, problems)."""
    import copy

    cur = layout_of(theme)
    new = copy.deepcopy(cur)
    done: list[str] = []
    problems: list[str] = []
    if not isinstance(change, dict):
        return None, done, ["layout must be an object"]

    def number(v, lo, hi):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi

    m = change.get("margins")
    if isinstance(m, dict):
        pg = new["page"]
        mg = margins_of(new)
        asked = False
        for k in ("left", "right", "top", "bottom"):
            v = m.get(k)
            if number(v, 0, min(pg["w"], pg["h"]) / 2):
                mg[k] = float(v)
                asked = True
            elif v is not None:
                problems.append(f"margin {k} = {v!r} is not usable")
        col = {"x": mg["left"], "w": pg["w"] - mg["left"] - mg["right"], "top": mg["top"], "bottom": pg["h"] - mg["bottom"]}
        if not asked:
            pass
        elif col["w"] < 150 or col["bottom"] - col["top"] < 200:
            problems.append("those margins would leave too little room for text; the margins were not changed")
        else:
            new["col"].update({k: _num(v) for k, v in col.items()})
            done.append("page margins: " + ", ".join(f"{k} {_num(mg[k])}" for k in ("left", "right", "top", "bottom")))
    for group in ("page", "col", "header", "footer", "gap"):
        vals = change.get(group)
        if not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k in new[group] and number(v, -50, 3000):
                new[group][k] = _num(v)
                done.append(f"{LAYOUT_LABELS[group]} {k} = {_num(v)}")
            else:
                problems.append(f"{group}.{k} = {v!r} was not applied")
    ty = change.get("type")
    if isinstance(ty, dict):
        for role, spec in ty.items():
            if role not in new["type"] or not isinstance(spec, dict):
                problems.append(f"type.{role} was not applied")
                continue
            ratio = cur["type"][role]["lh"] / cur["type"][role]["size"]
            for f in ("size", "lh"):
                v = spec.get(f)
                if number(v, *_LIMITS[f]):
                    new["type"][role][f] = float(v)
                    done.append(f"{TYPE_LABELS[role]} {f} = {_num(v)}")
            if number(spec.get("size"), *_LIMITS["size"]) and spec.get("lh") is None:  # keep the leading in proportion
                new["type"][role]["lh"] = round(float(spec["size"]) * ratio, 1)
    c, pg, f = new["col"], new["page"], new["footer"]
    if not (0 <= c["x"] and c["x"] + c["w"] <= pg["w"] and 0 <= c["top"] < c["bottom"] <= pg["h"]):
        return None, [], problems + ["the text column would not fit on the page, so the layout was left as it was"]
    if c["bottom"] > f["ruleY"] - 6:  # text must stop above the footer rule
        c["bottom"] = _num(f["ruleY"] - 8)
        done.append(f"text column bottom kept above the footer rule (y {c['bottom']})")
    if not done:
        return None, [], problems
    return new, done, problems


# The look of the components. The structure chat can change these for the whole book (theme["components"]) or for one
# section (theme["sectionStyles"][section id]). Colour values: a token (white, none = no fill, primary, tint, text, strong,
# onPrimary) or a hex colour; both renderers resolve tokens against the theme.
DEFAULT_COMPONENTS = {
    "qcard": {"fill": "white", "radius": 8, "numberColor": "primary", "pad": 7.5},   # textColor: automatic (page text colour when there is no fill)
    "mcq": {"fill": "white", "radius": 8, "columns": "auto", "pad": 12},   # auto: 4 options in a row when they are short, else 2 columns, else 1
    "ans": {"fill": "white", "tabFill": "primary", "radius": 8, "pad": 7.5},
    "table": {"headFill": "primary", "headText": "onPrimary", "zebra": True},
    "callout": {"radius": 8},
    "formula": {"fill": "primary", "text": "onPrimary"},
    "bullets": {"markColor": "primary"},
}
COMPONENT_SCHEMA = {
    "qcard": {"fill": "color", "radius": "num", "numberColor": "color", "textColor": "color", "pad": "num"},
    "mcq": {"fill": "color", "radius": "num", "columns": "cols", "textColor": "color", "pad": "num"},
    "ans": {"fill": "color", "tabFill": "color", "radius": "num", "textColor": "color", "pad": "num"},
    "table": {"headFill": "color", "headText": "color", "zebra": "bool"},
    "callout": {"radius": "num"},
    "formula": {"fill": "color", "text": "color"},
    "bullets": {"markColor": "color"},
    "page": {"bg": "color", "pillBg": "color", "pillFg": "color", "rule": "color", "fg": "color"},
}
# Colours the chat may change directly on the theme (see DEFAULT_THEME for what each one does)
THEME_COLOR_KEYS = ("primary", "text", "strong", "tint", "white", "rule", "footerRule", "tableAlt", "tableBorder", "onPrimary")
CALLOUT_KEYS = ("misc", "iit", "dyk")
PAGE_KIND_KEYS = ("index", "body", "exercise", "worksheet", "answers", "mindmap", "references", "glossary", "end")
COMPONENT_LABELS = {"qcard": "question cards", "mcq": "MCQ cards", "ans": "answer cards", "table": "tables", "callout": "callout boxes", "formula": "formula bars", "bullets": "bullet marks", "page": "page background"}
COLOR_TOKENS = ("white", "none", "primary", "tint", "text", "strong", "onPrimary")


def clean_style(component: str, values) -> dict:
    """Keep only the properties a component has, with sane values."""
    schema = COMPONENT_SCHEMA.get(component) or {}
    out = {}
    for k, v in (values or {}).items() if isinstance(values, dict) else []:
        t = schema.get(k)
        if t == "color" and isinstance(v, str) and (v in COLOR_TOKENS or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
            out[k] = v.upper() if v.startswith("#") else v
        elif t == "num" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 40:
            out[k] = v
        elif t == "cols" and (v in (1, 2, 3, 4) or v == "auto"):
            out[k] = v if v == "auto" else int(v)
        elif t == "bool" and isinstance(v, bool):
            out[k] = v
    return out


def resolve_color(theme: dict, v: str) -> str | None:
    """A colour token -> the theme's hex (None for 'none')."""
    if v == "none":
        return None
    if isinstance(v, str) and v.startswith("#"):
        return v
    return (theme or {}).get(v) or DEFAULT_THEME.get(v)


def components_of(theme: dict | None, section_src: str | None = None) -> dict:
    """Effective component styles: defaults < theme.components < theme.sectionStyles[section]."""
    out = {k: dict(v) for k, v in DEFAULT_COMPONENTS.items()}
    layers = [(theme or {}).get("components") or {}]
    if section_src:
        layers.append((((theme or {}).get("sectionStyles") or {}).get(section_src) or {}))
    for layer in layers:
        for comp, vals in layer.items():
            if comp in out and isinstance(vals, dict):
                out[comp].update(clean_style(comp, vals))
    return out


# How each kind of text is capitalised (ORIGINAL = as typed in the doc). Replaced by the reference file's own rules when one is read.
DEFAULT_CASE = {"eyebrow": "ORIGINAL", "title": "TITLE", "h2": "ORIGINAL", "h3": "TITLE", "toc": "TITLE", "pill": "UPPER"}
CASE_LABELS = {"eyebrow": "Eyebrow (small line above a title)", "title": "Page / section titles", "h2": "Heading 2", "h3": "Heading 3", "toc": "Index entries", "pill": "Header pill"}

THEME_LABELS = {
    "primary": "Primary (eyebrows, pill, bullets, numbers, table header, answer tabs)",
    "text": "Body text",
    "strong": "Headings text",
    "tint": "Tinted page background / key-ideas box",
    "white": "White page background / cards",
    "rule": "Header rule",
    "footerRule": "Footer rule",
    "tableAlt": "Table zebra row",
    "tableBorder": "Table border",
    "onPrimary": "Text on primary",
}

DEFAULT_META = {"subject": "", "module": "", "grade": "", "footer": ""}

RULES_TEMPLATE = """# Figma book design rules (derived from the reference book)

You are checking or generating textbook pages for students. Accuracy is paramount: the book text must be
100% identical to the source Google Doc (no dropped, added, reworded or misspelled content).

## Absolute content rules
1. Every word of the source document appears exactly once, in the original order, with the original spelling,
   punctuation and numbering. Never paraphrase, correct, summarise, or reorder.
2. Only decorative/generated text may be added: header pill, footer, page numbers, TOC page numbers,
   "ANSWER KEY", "Chapter N - Title", the End of Chapter page. These are never counted as content.
3. Images from the doc are replaced by labelled placeholders; the designer places the artwork by hand.
4. Covers are made manually and are out of scope.

{page_format}

{typography}

## Components
- Key Ideas box: {tint} fill, radius 8, padding 12, title "KEY IDEAS" {text_font} Black 11 {primary}.
- Callouts (radius 8, padding 12): Common Misconceptions (purple), IIT Foundation Understanding (green),
  Did You Know? (gold). Title {text_font} Black 11 in the callout's strong colour. Concept Insight is NOT boxed.
- Table: header row {primary} with white {text_font} Black 11; body rows alternate white / {tableAlt}; 1px {tableBorder};
  cell padding 9 x 6.
- Formula bar: {primary} fill, white {text_font} Heavy 13, centred.
- Question cards (fill-in, true/false, short answer): white card, radius 8, rows padding 7.5 x 5.25, number in
  {text_font} Heavy 11 {primary}.
- MCQ card: white, radius 8; stem bold; options in two columns "(A) (B)" / "(C) (D)".
- Match the column: stem bold + table (Column I / Column II).
- Answer card (Hints): white rows; a 33px {primary} tab on the left with the question number in white.
- Image placeholder: grey box with the original image proportions and a "PLACEHOLDER" label.
- Never split a card, table, callout or image across pages. Lists and card groups may break between items.
  A heading is never left alone at the bottom of a page.

## Verification expectations
- Compare content case-insensitively ignoring punctuation-only styling; report spelling, missing, extra and
  reordered text separately. Layout deviations from these rules are warnings, never content errors.
"""


def _font_names(theme: dict) -> tuple[str, str]:
    f = (theme or {}).get("fonts") or {}
    return (f.get("text") or {}).get("family") or "Avenir", (f.get("display") or {}).get("family") or "DIN Condensed"


def rules_prompt(theme: dict | None = None) -> str:
    t = dict(DEFAULT_THEME)
    t.update(theme or {})
    L = layout_of(t)
    text_font, display_font = _font_names(t)
    pg, c, h, f, ty = L["page"], L["col"], L["header"], L["footer"], L["type"]
    page_format = f"""## Page format
- Portrait {pg['w']} x {pg['h']}, one frame per page, all pages of a book in one Section.
- Content column: x={c['x']}, width {c['w']}, starts at y={c['top']}. Never extend below y={c['bottom']}.
- Header: 1px rule (x{h['ruleX']}..{h['ruleX'] + h['ruleW']}, y{h['ruleY']}) plus a pill (x{h['pillX']}, y{h['pillY']}, {h['pillW']}x{h['pillH']}) holding the current section name in {h['pillSize']}px {text_font} Medium, UPPERCASE, tracking 0.35.
- Footer: 1px rule at y={f['ruleY']} ({t['footerRule']}); footer text bottom-left ({text_font} Medium {f['textSize']}); page number bottom-right ({text_font} Black {f['numSize']}, {t['primary']}).
- Each kind of page (index, teaching content, exercise, worksheet, answer key, mind map…) has its own background colour from the style; the pill, header line and text switch to light colours on dark backgrounds. The index page has no header pill and no page number."""
    typography = f"""## Typography (fonts: {display_font} for display, {text_font} for text)
- Eyebrow: {display_font} {ty['eyebrow']['size']}/{ty['eyebrow']['lh']}, {t['primary']}.
- Page title: {display_font} {ty['title']['size']}/{ty['title']['lh']}, {t['strong']}.
- H2: {display_font} {ty['h2']['size']}/{ty['h2']['lh']}. H3: {text_font} Black {ty['h3']['size']}/{ty['h3']['lh']}. H4: {text_font} Black {ty['h4']['size']}/{ty['h4']['lh']}. H5: {text_font} Heavy {ty['h5']['size']}/{ty['h5']['lh']}. All {t['strong']}.
- Capitalisation of titles and headings follows the style's case rules (the app applies it; wording never changes).
- Body: {text_font} Medium {ty['body']['size']}/{ty['body']['lh']}, {t['text']}. Bold runs use the Black weight.
- Bullets: "•" in {t['primary']}, size {ty['mark']['size']}."""
    fields = {k: v for k, v in t.items() if isinstance(v, str)}
    return RULES_TEMPLATE.format(page_format=page_format, typography=typography, text_font=text_font, **fields)
