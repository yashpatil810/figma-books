# Reference analysis: "Electricity – Grade 7" (Google Doc ↔ Figma)

Source figma: Zv0GkiCv8zs61l4BJ0dUUN, section 250:20 (32 frames). Source doc: 10.9 MB .docx export (6 H1, 18 H2, 30 H3, 5 tables, 8 images).

## Page format
- A4 portrait, 595 × 842 px, one Figma frame per page, named `phyN` (N = internal id, not page number).
- Margins ≈ 36 px left/right. Header rule + pill at top (y≈32). Footer rule at y≈800, footer text bottom-left, page number bottom-right.
- Content is auto-layout (Column / Row frames), text boxes fixed width.

## Fonts
- Display: DIN Condensed Bold (titles, section labels, TOC). Body: Avenir (Medium 500 body, Heavy 800 labels/numbers, Black 900 sub-heads). Both ship with macOS.
- Stray `Mulish` 10px text in Misconceptions box: reference inconsistency, must not be copied.

## Type scale (px / line-height)
| Role | Font | Size/LH | Color token |
|---|---|---|---|
| Page title (Synopsis/Test/Hints) | DIN Cond Bold | 42/50.4, Title Case | text-strong #1A1A1A |
| Eyebrow (CHAPTER, SYNOPSIS-1) | DIN Cond Bold | 20/24, UPPER | primary #1E3A6E |
| H2 | DIN Cond Bold (synopsis) / Avenir Black (inner pages) | 18/21.6 · 13/17.8 TitleCase | strong |
| H3 / sub-head | Avenir Heavy/Black | 11/15 | strong |
| Body | Avenir Medium | 11/15 | text #2E2E2E |
| Bullets | "•" Avenir Heavy 10, primary colored; indent 18 | | |
| Header pill | Avenir Medium 7, UPPER, tracking .35 | white on primary | |
| Footer | Avenir Medium 8 / page no. Avenir Black 8 primary | | |

## Color roles (this book)
primary #1E3A6E · text #2E2E2E · text-strong #1A1A1A · page-tint #E9F1FA (TOC, tests, hints, mind map, end page) · page-white #FFFFFF (synopsis pages) · rule #C7D4E6 / #D9D9D9 · card-bg #FFFFFF on tint pages · table-head = primary, table-alt-row #DCE6F4 · callouts: key-ideas bg #E9F1FA, misconception text #6B2E7D bg #F2EAF6, IIT foundation #2E7D32 bg #E9F5EC, did-you-know #B07A1A bg #FBF1DD.

## Page / component catalog (what samples must show)
1. Front cover (full-bleed image + title + grade) 2. Back cover (publisher details) 3. Table of contents 4. Chapter opener with Key Ideas checklist card 5. Synopsis opener (eyebrow, title, intro, body) 6. Synopsis body page (H2/H3/paragraph/bullets) 7. Full-width figure/image 8. Data table (3 col, header + zebra) 9. Callout boxes: Concept Insight, Common Misconceptions, IIT Foundation Understanding, Did You Know? 10. Numbered list (types of lightning) 11. Formula bar (primary filled) 12. Test Your Concepts page: section heading, directions line, fill-in-blank card (numbered), MCQ cards (2-col options A–D), match-the-column table (primary head) 13. Short/Long answer list cards 14. Concept Application pages: True/False, Fill blanks, MCQ, match, Level 2 15. Hints & Solutions: answer card with numbered primary tab at left, bold answer lead, section sub-headings 16. Mind map full-width image 17. End-of-chapter page. Every inner page: header pill (section name), footer, page number.

## Observations / mismatches between reference doc and reference Figma
- Doc auto-numbering and "•" characters are inline in single paragraphs (`As a result:• …• …`). Parser must split.
- Doc has stray empty `‘` Heading3 between Synopsis 1 and 2.
- Doc `Prepared by : Er.Aman Khan` line does not appear in the Figma.
- Figma adds content not in doc: TOC page numbers, End of Chapter page, back-cover publisher block, Hints answers (Hints section absent from doc?). To be checked in full diff.
- Figma Hints headers have question ranges inconsistent with their contents: "Q24–27" for Q15–27, "Q79–98" for Q49–61, "Q111–120" for Q69–75 (likely reference-file errors).
- Page numbers: Synopsis 1 p2, Synopsis 2 p8, Test p13, Hints p20, Mind map p26, End p27: TOC matches frames.
