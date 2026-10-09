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
3. Fonts Avenir and DIN Condensed must be installed (they ship with macOS).

## Flow
New book → Setup → Colours & samples (approve) → Review doc (scan, answer questions) → Generate →
run the plugin in Figma (Load, Build) → Report (paste section link, Verify, fix to-dos, Verify again until 100%).
"Audit an existing Figma" runs the same review and report for a Figma you made yourself.

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
