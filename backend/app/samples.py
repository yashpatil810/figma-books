"""Fixed-content sample pages: one page per kind of page / component in the book."""
from __future__ import annotations

from .layout import gap, block_h


def R(t, **kw):
    return [dict({"t": t}, **kw)]


def P(t):
    return {"t": "p", "runs": R(t)}


def finish(blocks):
    prev = None
    for b in blocks:
        b["gap"] = gap(prev, b) if prev is not None else 0
        prev = b
    return blocks


def sample_pages(meta: dict) -> dict:
    ch = "Sample Chapter"
    pages = []

    def add(kind, bg, pill, no, blocks, label):
        pages.append({"kind": kind, "bg": bg, "pill": pill, "pageNo": no, "blocks": finish(blocks), "section": kind, "label": label, "sample": True})

    add("toc", "tint", None, None, [{"t": "toc", "title": "Table of Contents", "chapter": ch, "chapter_no": meta.get("module") or "1", "entries": [
        {"label": "SYNOPSIS-1", "title": "Sample Topic One", "page": 2, "kind": "synopsis"},
        {"label": "SYNOPSIS-2", "title": "Sample Topic Two", "page": 8, "kind": "synopsis"},
        {"label": "Test your concepts", "title": None, "page": 13, "kind": "section"},
        {"label": "Hints and Solutions", "title": None, "page": 20, "kind": "section"},
        {"label": "Mind Map", "title": None, "page": 26, "kind": "section"}]}], "Table of contents")

    add("opener", "white", "SAMPLE CHAPTER", 1, [
        {"t": "title", "eyebrow": "CHAPTER", "text": ch},
        {"t": "callout", "variant": "keyideas", "title": "KEY IDEAS", "blocks": [P("After completing this chapter, you should be able to:"),
            {"t": "ul", "mark": "✓", "items": [R("Describe the first key idea of the chapter"), R("Explain the second idea with an example"), R("Apply the third idea to everyday situations")]}]}], "Chapter opener + Key Ideas")

    add("synopsis", "white", "SAMPLE TOPIC ONE", 2, [
        {"t": "title", "eyebrow": "SYNOPSIS-1", "text": "Sample Topic One"},
        {"t": "h", "lvl": 2, "text": "Introduction"},
        P("This is sample body text that shows how a paragraph looks in the book. It wraps across lines at the content width so you can judge line length, colour and leading."),
        {"t": "ul", "mark": "•", "items": [R("First bullet point"), R("Second bullet point")]},
        {"t": "h", "lvl": 3, "text": "Section Heading"},
        {"t": "h", "lvl": 4, "text": "Sub-heading"},
        P("Body text under a sub-heading, with a "), ], "Synopsis opener (title, H2/H3/H4, paragraph, bullets)")
    pages[-1]["blocks"][-1] = {"t": "p", "runs": [{"t": "Body text with a "}, {"t": "bold phrase", "b": 1}, {"t": " inside the sentence."}], "gap": 3}
    pages[-1]["blocks"] += finish([
        {"t": "h", "lvl": 5, "text": "Minor heading"},
        {"t": "ol", "items": [{"label": "1.", "lines": [R("Numbered item title", b=1), R("Description line under the numbered item.")]}, {"label": "2.", "lines": [R("Second item", b=1), R("Another description line.")]}]},
        {"t": "formula", "text": "Quantity = Rate × Time"},
    ])
    for b in pages[-1]["blocks"][-3:]:
        pass
    finish(pages[-1]["blocks"])

    add("synopsis", "white", "SAMPLE TOPIC ONE", 3, [
        {"t": "h", "lvl": 4, "text": "Data table"},
        {"t": "table", "head": ["Item", "Property A", "Property B"], "rows": [["Item one", "Value 1", "Value 2"], ["Item two", "Value 3", "Value 4"], ["Item three", "Value 5", "Value 6"]], "widths": [190, 190, 135]},
        {"t": "image", "label": "Figure from the source document", "w": 395, "h": 230},
        {"t": "callout", "variant": "misc", "title": "Common Misconceptions", "blocks": [P("Misconception 1"), P("“A sample wrong belief.”"), P("Correct Concept"), P("The sample correction.")]},
        {"t": "callout", "variant": "iit", "title": "IIT Foundation Understanding", "blocks": [P("Students should clearly understand:"), {"t": "ul", "mark": "•", "items": [R("A foundation point"), R("Another foundation point")]}]},
        {"t": "callout", "variant": "dyk", "title": "Did You Know?", "blocks": [{"t": "ul", "mark": "•", "items": [R("A surprising fact that fits in a box.")]}]},
    ], "Table, image placeholder, callouts")

    add("test", "tint", "TEST YOUR CONCEPTS", 13, [
        {"t": "title", "text": "Test Your Concepts"},
        {"t": "h", "lvl": 3, "text": "Very Short Answer Type Questions"},
        {"t": "note", "runs": R("Directions for questions 1 to 2: Fill in the blanks with the most appropriate word or term.")},
        {"t": "qcard", "items": [{"label": "1.", "lines": [R("Like charges ________ each other while unlike charges ________ each other.")]}, {"label": "2.", "lines": [R("An ________ is a device used to detect charge on a body.")]}]},
        {"t": "note", "runs": R("Directions for questions 3 to 4: For each of the questions, four choices have been provided. Select the correct alternative.")},
        {"t": "mcq", "n": "3.", "stem": R("Materials like wood and rubber are"), "options": [{"k": "A", "runs": R("(A) good conductors")}, {"k": "B", "runs": R("(B) good insulators")}, {"k": "C", "runs": R("(C) good conductors of heat only")}, {"k": "D", "runs": R("(D) used to make heating elements")}]},
        {"t": "mcq", "n": "4.", "stem": R("A lightning conductor protects buildings by"), "options": [{"k": "A", "runs": R("(A) producing charge")}, {"k": "B", "runs": R("(B) carrying charge to the ground")}, {"k": "C", "runs": R("(C) increasing strength")}, {"k": "D", "runs": R("(D) storing charge")}]},
        {"t": "p", "runs": R("5. Match the items in Column I with Column II.", b=1)},
        {"t": "table", "head": ["Column I", "Column II"], "rows": [["(a) Copper", "(i) Insulator"], ["(b) Plastic", "(ii) Good conductor"]], "widths": [257, 258]},
    ], "Test: fill-in card, MCQ cards, match the column")

    add("concept", "tint", "CONCEPT APPLICATION", 15, [
        {"t": "title", "text": "Concept Application"},
        {"t": "h", "lvl": 3, "text": "Level 1"},
        {"t": "h", "lvl": 3, "text": "True or False"},
        {"t": "note", "runs": R("Directions: Write True or False for each of the following statements.")},
        {"t": "qcard", "items": [{"label": "6.", "lines": [R("Unlike charges repel each other.")]}, {"label": "7.", "lines": [R("A fuse melts when current exceeds the safe limit.")]}]},
    ], "Concept application (true/false list)")

    add("hints", "tint", "HINTS AND SOLUTIONS", 20, [
        {"t": "title", "eyebrow": "ANSWER KEY", "text": "Hints and Solutions"},
        {"t": "h", "lvl": 2, "text": "Test Your Concepts"},
        {"t": "h", "lvl": 3, "text": "Fill in the Blanks"},
        {"t": "ans", "items": [{"label": "1.", "blocks": [P("Like charges repel each other while unlike charges attract each other.")]}, {"label": "2.", "blocks": [P("An electroscope is a device used to detect charge on a body.")]}]},
        {"t": "h", "lvl": 3, "text": "Multiple Choice Questions"},
        {"t": "ans", "items": [{"label": "3.", "blocks": [{"t": "p", "runs": R("Correct Answer: (B) good insulators", b=1)}, P("Explanation: These materials do not allow charge to flow easily.")]}]},
    ], "Hints and solutions (answer cards)")

    add("mindmap", "tint", "MIND MAP", 26, [
        {"t": "h", "lvl": 3, "text": "Mind Map"},
        {"t": "image", "label": "Mind map image", "w": 515, "h": 360},
    ], "Mind map (full-width image)")

    add("end", "tint", "SAMPLE CHAPTER", 27, [{"t": "end", "module": meta.get("module") or "1", "chapter": ch, "grade": meta.get("grade") or "7", "subject": meta.get("subject") or "Subject"}], "End of chapter")
    return {"meta": meta, "pages": pages}
