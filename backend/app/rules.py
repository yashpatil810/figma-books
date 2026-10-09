"""Theme (colour roles) and the design-rules prompt derived from the reference book."""
from __future__ import annotations

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

## Page format
- A4 portrait 595 x 842, one frame per page, all pages of a book in one Section.
- Content column: x=40, width 515, starts at y=64. Never extend below y=786.
- Header: 1px rule (x35..407, y40, {rule}) plus a pill (x417, y33, 142x16, radius 16, fill {primary}) holding the
  current section/topic name in 7px Avenir Medium, UPPERCASE, tracking 0.35, white.
- Footer: 1px rule at y=801 ({footerRule}); footer text bottom-left (Avenir Medium 8, black); page number
  bottom-right (Avenir Black 8, {primary}).
- Synopsis pages are on {white}. TOC, Test Your Concepts, Concept Application, Hints & Solutions, Mind Map and End
  pages are on {tint}. The TOC page has no header pill and no page number.

## Typography (fonts: DIN Condensed Bold for display, Avenir for text)
- Eyebrow (CHAPTER / SYNOPSIS-N / ANSWER KEY): DIN Condensed Bold 20/24, UPPER, {primary}.
- Page title: DIN Condensed Bold 42/50.4, Title Case, {strong}.
- H2 (first section of a synopsis, topic starts, big groups): DIN Condensed Bold 18/21.6, {strong}.
- H3: Avenir Black 13/17.8, Title Case. H4: Avenir Black 11/15. H5: Avenir Heavy 11/15. All {strong}.
- Body: Avenir Medium 11/15, {text}. Bold runs: Avenir Black. Paragraph gap 3, heading-to-content gap 5,
  section gap 11.
- Bullets: "•" Avenir Heavy 10 in {primary}, 6px gap, 5px between items. Key ideas use a "✓" mark.

## Components
- Key Ideas box: {tint} fill, radius 8, padding 12, title "KEY IDEAS" Avenir Black 11 {primary}.
- Callouts (radius 8, padding 12): Common Misconceptions (purple), IIT Foundation Understanding (green),
  Did You Know? (gold). Title Avenir Black 11 in the callout's strong colour. Concept Insight is NOT boxed.
- Table: header row {primary} with white Avenir Black 11; body rows alternate white / {tableAlt}; 1px {tableBorder};
  cell padding 9 x 6.
- Formula bar: {primary} fill, white Avenir Heavy 13, centred.
- Question cards (fill-in, true/false, short answer): white card, radius 8, rows padding 7.5 x 5.25, number in
  Avenir Heavy 11 {primary}.
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


def rules_prompt(theme: dict | None = None) -> str:
    t = dict(DEFAULT_THEME)
    t.update(theme or {})
    return RULES_TEMPLATE.format(**{k: v for k, v in t.items() if isinstance(v, str)})
