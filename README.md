# Book Builder

Local web app: Google Doc → reviewed, verified Figma book pages. Uses your Claude Max plan through the
Claude Code CLI (no API key).

## Run
```
./run.sh        # http://localhost:8765
```
Dev UI with hot reload: `cd frontend && npm run dev` (port 5173, proxies to 8765).

## One-time setup
1. Settings (top right): confirm "Claude connected"; paste your Figma token (or keep it in `.env` as `FIGMA_TOKEN=`).
2. Figma desktop: Plugins → Development → Import plugin from manifest… → `figma-plugin/manifest.json`.
3. Fonts Avenir and DIN Condensed must be installed (they ship with macOS). A style read from a reference design may use
   other fonts (e.g. Mulish, Oswald): Google Fonts are available in Figma automatically.
4. **After updating the app, close and re-run the plugin in Figma** (Plugins → Development → Book Builder): Figma keeps
   the plugin code it loaded when the plugin was opened. The app stamps every job with the plugin version it expects
   (`PLUGIN_VERSION` in `figma-plugin/code.js`); the plugin sends its version with every request and the app refuses to
   hand a job to any other version (an old copy sees "PLUGIN OUT OF DATE" in its book list). The app also reads Figma's
   own settings to see which folder the plugin is registered from and warns on the Preview when it is not this project's
   `figma-plugin/` (`/api/status` → `plugin`).

## Flow
New book → Setup (doc, optional **reference design** link) → Colours & samples (approve) → Review doc (scan, answer questions) →
**Structure** (Claude reads the doc for meaning; tables in pictures are read) → Preview & build → run the plugin in Figma (Load, Build) →
optional Images & diagrams → Report (paste section link, Verify, fix to-dos, Verify again until 100%).

## Reference design (style profile)
Paste a link to a Figma file, page or section on Setup. The app reads it once with the Figma REST API (measured numbers: colours,
fonts, text sizes, header/footer/column positions) and Claude looks at a few rendered pages. The result is an editable style on
Colours & samples: 10 theme colours, a background and pill/line/text colours per page type (index, body, exercise, worksheet, answer
key…), fonts (Google Fonts are downloaded once into `data/fonts` so page lengths are measured exactly), capitalisation rules per kind of
text (acronyms are protected), and the layout spec (page size, text column, header/footer, type scale, gaps). The pages are still built
by the app's own renderer (`layout.py`, `figma-plugin/code.js`, `Page.jsx` all read the same layout spec), so text stays verbatim.
Without a link the defaults in `rules.py` (`DEFAULT_THEME`, `DEFAULT_LAYOUT`) apply.

## Structure
No template or keyword rules decide the structure: as soon as the doc is fetched, `structure_map.py` sends Claude (Opus, one call
for the whole doc) a compact outline (block ids + short text + table headers, never rewritten text) and gets back labels:
front matter, the doc's own index list, where each section really starts and its role (teaching content, exercise, answer key, mind
map…), heading levels, and **where a new page starts** (`new_page` on every section and heading; a change of page type
always starts a page because the background changes). `structure_generic.py` builds the pages from those labels; a section
Claude lets flow continues on the previous page (`layout.build_pages`). The Structure screen shows every decision with a
checkbox. The Structure screen also has a chat: a request in plain language ("let Part 12 continue on page 57", "the
worksheet is an exercise", "remove the box behind the questions in the worksheet") is turned by Claude into overrides —
roles, page starts, and the look of components (`rules.DEFAULT_COMPONENTS`: question/MCQ/answer cards, tables, callouts,
formula bars, bullet marks; for the whole book or for one section), and colours (the ten theme colours, the callout
pairs, and each page kind's background / pill / line / text — or one section's own page colours) — never into text changes — with
the pages it touched shown as thumbnails and an undo. Checks and chat lay the book out exactly as the Preview does, so page
numbers match. The old synopsis template and keyword rules are only a fallback when Claude is unavailable (the screen says so).
"Audit an existing Figma" runs the same review and report for a Figma you made yourself.

## Review export
Review doc → "Export CSV" downloads the review comments (`/api/projects/<id>/findings.csv`): columns Statement, Doc page,
Tag (Error / Warning / Question / Info), sorted by doc page, with no suggestions and no internal block ids. The dropdown
chooses which kinds to include (`?severities=error,question`; `?statuses=open` also works).

## Different kinds of documents
Not every chapter has synopses, key ideas or tests. The app picks a reading profile per document
(Setup → "How I read your document"):
- **Synopsis template** – chapter marker, key ideas, synopses, test / concept application / hints, mind map.
- **Generic chapter** – follows the doc's own headings. Sections named like LEVEL / Exercise / Answer Keys /
  Hints & Solutions / Mind Map / References become their own pages; everything else is plain content.
  Nothing is ever dropped, and any heading can be re-classified from the Setup screen.
Images become labelled placeholders (small equation pictures are grouped into rows). Superscripts and
subscripts are written as real superscript/subscript characters (x², H₂O).

## Pictures and diagrams
Step "Images & diagrams": Claude looks at every picture and classifies it. Real **diagrams** (geometric figures, graphs,
circuits, experiment set-ups…) are redrawn as clean SVG (Opus, with a render-and-compare check), shown next to the
original for review, and built in Figma as editable vector shapes. Equations, photos and artwork stay labelled
placeholders. Any picture can be flipped either way. After building, Verify compares each generated diagram in Figma with
the original picture and reports differences. Notes: Figma drops SVG `<marker>`s, so arrowheads are drawn as shapes;
superscripts in labels are kept as typed characters.

## Layout
- `backend/app` FastAPI: `gdoc` parse, `structure` doc→components, `layout` pagination, `scan` review,
  `verify` comparison/score, `llm` Claude CLI provider, `rules` theme + rules prompt, `samples`.
- `frontend/` React UI (`Page.jsx` mirrors the plugin renderer).
- `figma-plugin/` builds the pages from the spec. Text is only copied from the spec, never generated.
- `docs/reference-analysis.md` what was learned from the reference book. `data/` projects, caches (git-ignored).
