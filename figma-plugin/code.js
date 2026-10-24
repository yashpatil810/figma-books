// Book Builder: builds book pages in Figma from the design spec produced by the local app.
// PLUGIN_VERSION is the spec contract. The app reads this number from this file and stamps it on every job; the plugin
// refuses a job stamped with another number, which means Figma is still running an older copy of this code
// (close the plugin and run it again). Bump it whenever the spec format or the rendering changes.
const PLUGIN_VERSION = 8;
// Text is only ever set from the spec (copied from the Google Doc by the app) - never generated here.
figma.showUI(__html__, { width: 340, height: 400 });
figma.ui.postMessage({ type: 'hello', version: PLUGIN_VERSION });  // the UI sends this version with every request to the app

// Page geometry, type scale and spacing come from the style (T.layout); these are the app's defaults.
const L0 = {
  page: { w: 595, h: 842 }, col: { x: 40, w: 515, top: 64, bottom: 786 },
  header: { ruleX: 35, ruleY: 40, ruleW: 372, pillX: 417, pillY: 33, pillW: 142, pillH: 16, pillSize: 7 },
  footer: { ruleX: 35, ruleY: 801, ruleW: 525, textX: 35, textY: 813, textSize: 8, numX: 520, numY: 814, numSize: 8 },
  type: { title: { size: 42, lh: 50.4 }, eyebrow: { size: 20, lh: 24 }, h2: { size: 18, lh: 21.6 }, h3: { size: 13, lh: 17.8 }, h4: { size: 11, lh: 15 }, h5: { size: 11, lh: 15 }, body: { size: 11, lh: 15 }, mark: { size: 10, lh: 13.7 }, toc: { size: 18, lh: 21.6 } },
};
let L = L0;
let PAGE_W = 595, PAGE_H = 842, COL_X = 40, COL_W = 515, TOP = 64;
function applyLayout() {
  L = (T && T.layout) || L0;
  PAGE_W = L.page.w; PAGE_H = L.page.h; COL_X = L.col.x; COL_W = L.col.w; TOP = L.col.top;
}
let T = null; // theme

function rgb(hex) { const h = hex.replace('#', ''); return { r: parseInt(h.slice(0, 2), 16) / 255, g: parseInt(h.slice(2, 4), 16) / 255, b: parseInt(h.slice(4, 6), 16) / 255 }; }
function solid(hex) { return [{ type: 'SOLID', color: rgb(hex) }]; }

const FONTS = {
  medium: { family: 'Avenir', style: 'Medium' },
  heavy: { family: 'Avenir', style: 'Heavy' },
  black: { family: 'Avenir', style: 'Black' },
  din: { family: 'DIN Condensed', style: 'Bold' },
  oblique: { family: 'Avenir', style: 'Medium Oblique' },
};

const WEIGHT_NAMES = { 100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black' };
// A style from a reference design names its own fonts: try the usual Figma style spellings ("SemiBold" / "Semi Bold").
async function pickFont(family, weight, italic) {
  const base = WEIGHT_NAMES[weight] || 'Regular';
  const names = [base, base.replace(/([a-z])([A-Z])/, '$1 $2')];
  if (italic) { const it = []; for (const n of names) { it.push(n === 'Regular' ? 'Italic' : n + ' Italic'); } names.length = 0; names.push.apply(names, it.concat(['Italic'])); }
  for (const style of names) { try { await figma.loadFontAsync({ family, style }); return { family, style }; } catch (e) {} }
  return null;
}
async function loadFonts() {
  const missing = [];
  const tf = T && T.fonts;
  if (tf && (tf.text || tf.display)) {
    if (tf.text) {
      const t = tf.text;
      for (const [k, w] of [['medium', t.medium || 500], ['heavy', t.heavy || 800], ['black', t.black || 900]]) {
        const f = await pickFont(t.family, w);
        if (f) FONTS[k] = f; else missing.push(t.family + ' ' + (WEIGHT_NAMES[w] || w));
      }
      const it = await pickFont(t.family, t.medium || 500, true);
      if (it) FONTS.oblique = it; else delete FONTS.oblique;
    }
    if (tf.display) {
      const f = await pickFont(tf.display.family, tf.display.weight || 700);
      if (f) FONTS.din = f; else missing.push(tf.display.family + ' ' + (WEIGHT_NAMES[tf.display.weight || 700] || ''));
    }
    return missing;
  }
  for (const k of Object.keys(FONTS)) {
    try { await figma.loadFontAsync(FONTS[k]); } catch (e) { if (k !== 'oblique') missing.push(FONTS[k].family + ' ' + FONTS[k].style); else delete FONTS.oblique; }
  }
  return missing;
}

// ---------------------------------------------------------------- primitives
function frame(name, o) {
  o = o || {};
  const f = figma.createFrame();
  f.name = name;
  f.fills = o.fill ? solid(o.fill) : [];
  f.clipsContent = !!o.clip;
  if (o.radius) f.cornerRadius = o.radius;
  f.layoutMode = o.dir === 'H' ? 'HORIZONTAL' : 'VERTICAL';
  f.itemSpacing = o.gap || 0;
  const p = o.pad || [0, 0, 0, 0];
  f.paddingTop = p[0]; f.paddingRight = p[1]; f.paddingBottom = p[2]; f.paddingLeft = p[3];
  if (o.w) { f.resize(o.w, 10); if (o.dir === 'H') { f.layoutSizingHorizontal = 'FIXED'; f.layoutSizingVertical = 'HUG'; } else { f.layoutSizingHorizontal = 'FIXED'; f.layoutSizingVertical = 'HUG'; } }
  else { f.layoutSizingHorizontal = 'HUG'; f.layoutSizingVertical = 'HUG'; }
  if (o.align) f.counterAxisAlignItems = o.align;
  if (o.main) f.primaryAxisAlignItems = o.main;
  if (o.stroke) { f.strokes = solid(o.stroke); f.strokeWeight = 1; f.strokeAlign = 'INSIDE'; }
  return f;
}
function add(parent, child, o) {
  parent.appendChild(child);
  o = o || {};
  if (o.fill) child.layoutSizingHorizontal = 'FILL';        // fill parent's width (vertical parent) / grow (horizontal parent)
  if (o.fillV) child.layoutSizingVertical = 'FILL';
  if (o.stretch) child.layoutAlign = 'STRETCH';
  return child;
}
function rect(name, x, y, w, h, hex) {
  const r = figma.createRectangle(); r.name = name; r.x = x; r.y = y; r.resize(w, h); r.fills = solid(hex); return r;
}

// styles: [font, size, lineHeight, colorKey]
// Display titles set in Title Case: Figma's TITLE case does not lower-case an ALL-CAPS source, so do it here.
// Only used for page/section titles; the letters stay the same, only capitalisation changes.
const PAGE_KINDS = ['index', 'body', 'exercise', 'worksheet', 'answers', 'mindmap', 'references', 'glossary', 'end'];
function lumOf(hex) { const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
// Each kind of page has its own background; on dark backgrounds text, pill and rules switch to light colours automatically.
function pageType(page) {
  const k = page.kind === 'toc' ? 'index' : page.kind;
  if (k === 'exercise' && /worksheet/i.test(page.pill || '')) return 'worksheet';
  if (PAGE_KINDS.includes(k)) return k;
  return page.bg === 'white' ? 'body' : 'exercise';
}
function pageStyle(page, T) {
  const kind = pageType(page);
  const pt = (T.pageTypes && T.pageTypes[kind]) || {};
  const ps = page.pageStyle || {};  // one section's own page colours (from the chat) win over the page kind's
  const bg = ps.bg || pt.bg || (kind === 'body' ? T.white : T.tint);
  const dark = lumOf(bg) < 0.35;
  return { kind, bg, dark, fg: ps.fg || pt.fg || (dark ? '#FFFFFF' : null), pillBg: ps.pillBg || pt.pillBg || (dark ? '#FFFFFF' : T.primary), pillFg: ps.pillFg || pt.pillFg || (dark ? bg : T.onPrimary), rule: ps.rule || pt.rule || (dark ? '#FFFFFF' : T.rule) };
}
// Component styles: the theme's (T.components) overridden by the section's (page.components). Colour tokens resolve
// against the theme; 'none' means no fill.
function colorOf(v, dflt) {
  if (v == null) return dflt;
  if (v === 'none') return null;
  if (/^#/.test(v)) return v;
  return ({ white: T.white, primary: T.primary, tint: T.tint, text: T.text, strong: T.strong, onPrimary: T.onPrimary })[v] || dflt;
}
// Text inside a card: the style's textColor, else automatic — the page's text colour when the card has no fill (so it
// never vanishes on a dark page), else the body text colour.
function cardText(ctx, cs, dflt) {
  if (cs.textColor) return colorOf(cs.textColor, dflt);
  if (cs.fill === 'none' && ctx && ctx.style && ctx.style.dark) return ctx.style.fg;
  return dflt;
}
function padOf(cs, dflt, ratio) { const px = cs.pad != null ? cs.pad : dflt; const py = Math.round(px * (ratio || 0.7) * 100) / 100; return [py, px, py, px]; }
function comp(ctx, name) {
  const base = (T.components && T.components[name]) || {};
  const pg = ctx && ctx.page && ctx.page.components && ctx.page.components[name];
  return Object.assign({}, base, pg || {});
}
const SMALL_WORDS = new Set(['a', 'an', 'the', 'and', 'or', 'but', 'nor', 'of', 'in', 'on', 'at', 'to', 'for', 'by', 'with', 'vs', 'as', 'per']);
// Capitalisation is decided by the app, from the style's case rule for that kind of text. Only letter case changes.
// Words that are acronyms (short all-caps words that appear in capitals in ordinary text), single letters, Roman numerals,
// formulas and anything with digits are never lowered; inner capitals in mixed-case text (pH, mRNA) are never touched.
function applyCase(s, mode, acr) {
  if (mode !== 'TITLE') return s;
  const allCaps = s === s.toUpperCase() && s !== s.toLowerCase();
  let first = true;
  return s.split(/(\s+|[-\u2013\u2014:])/).map(w => {
    if (!/[A-Za-z]/.test(w)) return w;
    const bare = w.replace(/[^A-Za-z]/g, '');
    const wasFirst = first; first = false;
    if (allCaps) {
      if (acr.has(bare) || bare.length === 1 || /^[IVXLC]+$/.test(bare) || /[0-9\u2080-\u2089\u00b2\u00b3\u00b9]/.test(w)) return w;
      w = w.toLowerCase();
    } else if (/[A-Z]/.test(w.slice(1)) || /\d/.test(w)) return w;
    if (!wasFirst && SMALL_WORDS.has(bare.toLowerCase())) return w.toLowerCase();
    return w.replace(/[A-Za-z]/, c => c.toUpperCase());
  }).join('');
}
let ACR_SET = null;
function caseMode(o) { return (o.role && T && T.caseRules && T.caseRules[o.role]) || o.case || 'ORIGINAL'; }
function text(chars, o) {
  const mode = caseMode(o);
  if (!ACR_SET) ACR_SET = new Set((T && T.acronyms) || []);
  if (mode === 'TITLE') chars = applyCase(chars, mode, ACR_SET);
  const t = figma.createText();
  t.fontName = FONTS[o.font || 'medium'];
  t.characters = chars;
  t.fontSize = o.size || L.type.body.size;
  t.lineHeight = { value: o.lh || L.type.body.lh, unit: 'PIXELS' };
  t.fills = solid(o.color || T.text);
  if (mode === 'UPPER' || mode === 'LOWER') t.textCase = mode;
  if (o.ls) t.letterSpacing = { value: o.ls, unit: 'PIXELS' };
  if (o.align) t.textAlignHorizontal = o.align;
  t.textAutoResize = 'HEIGHT';
  t.name = (o.name || chars).slice(0, 40).split(NL).join(' ');
  if (o.src) t.setSharedPluginData('books', 'src', Array.isArray(o.src) ? o.src.join(',') : String(o.src));
  return t;
}
// text from runs [{t,b,i}] (bold -> Avenir Black)
function runsText(runs, o) {
  runs = supsub(runs);
  o = Object.assign({}, o);
  const chars = runs.map(r => r.t).join('');
  const t = text(chars, o);
  let pos = 0;
  for (const r of runs) {
    const end = pos + r.t.length;
    if (r.b && !o.allBold) { try { t.setRangeFontName(pos, end, FONTS.black); } catch (e) {} }
    else if (r.i && FONTS.oblique) { try { t.setRangeFontName(pos, end, FONTS.oblique); } catch (e) {} }
    pos = end;
  }
  return t;
}
const SUP = { '0': '\u2070', '1': '\u00b9', '2': '\u00b2', '3': '\u00b3', '4': '\u2074', '5': '\u2075', '6': '\u2076', '7': '\u2077', '8': '\u2078', '9': '\u2079', '+': '\u207a', '-': '\u207b', '\u2212': '\u207b', '=': '\u207c', '(': '\u207d', ')': '\u207e', n: '\u207f', i: '\u2071' };
const SUB = { '0': '\u2080', '1': '\u2081', '2': '\u2082', '3': '\u2083', '4': '\u2084', '5': '\u2085', '6': '\u2086', '7': '\u2087', '8': '\u2088', '9': '\u2089', '+': '\u208a', '-': '\u208b', '=': '\u208c', '(': '\u208d', ')': '\u208e', a: '\u2090', e: '\u2091', o: '\u2092', x: '\u2093', h: '\u2095', k: '\u2096', l: '\u2097', m: '\u2098', n: '\u2099', p: '\u209a', s: '\u209b', t: '\u209c' };
// A superscript run is written with real superscript characters when every character has one
// (x2 -> x\u00b2); otherwise it is left as typed. The letters/digits stay the same, only their form changes.
function supsub(runs) {
  return runs.map(r => {
    const m = r.sup ? SUP : r.sub ? SUB : null;
    if (!m) return r;
    let out = '';
    for (const ch of r.t) { if (!m[ch]) return r; out += m[ch]; }
    return Object.assign({}, r, { t: out });
  });
}
function plainOf(runs) { return runs.map(r => r.t).join(''); }
const NL = String.fromCharCode(10);
function linesRuns(lines) { // [[runs],[runs]] -> single runs with a newline between
  const out = [];
  lines.forEach((l, i) => { if (i) out.push({ t: NL }); l.forEach(r => out.push(r)); });
  return out;
}
function itemRuns(it) { return Array.isArray(it) ? it : linesRuns(it.lines); }

function placeholder(b, src) {
  const ph = frame('IMAGE PLACEHOLDER', { dir: 'V', fill: T.placeholder, w: b.w, align: 'CENTER', main: 'CENTER', pad: [0, 0, 0, 0] });
  ph.resize(b.w, b.h); ph.layoutSizingVertical = 'FIXED'; ph.layoutSizingHorizontal = 'FIXED';
  ph.strokes = solid('#9AA6BA'); ph.strokeWeight = 1; ph.dashPattern = [6, 4];
  try { ph.setSharedPluginData('books', 'placeholder', '1'); ph.setSharedPluginData('books', 'src', (src || []).join(',')); } catch (e) {}
  if (b.h >= 40 && b.w >= 90) add(ph, text('IMAGE PLACEHOLDER', { font: 'heavy', size: 10, lh: 14, color: '#6B778C', align: 'CENTER', ls: 1 }), { stretch: true });
  return ph;
}

// A picture becomes an editable vector drawing when the app generated one for it, else a labelled placeholder.
async function diagramNode(b, src) {
  // vector part: shapes only (the app strips all lettering from the SVG, so nothing is ever outlined into paths)
  let vec = null;
  try { vec = figma.createNodeFromSvg(b.svg); } catch (e) { if (!(b.labels && b.labels.length)) throw e; }
  const vb = /viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)/.exec(b.svg);
  const vw = vb ? parseFloat(vb[1]) : (vec ? vec.width : b.w), vh = vb ? parseFloat(vb[2]) : (vec ? vec.height : b.h);
  const k = b.w / vw;
  const g = figma.createFrame();
  g.name = 'DIAGRAM (generated, review against the original)';
  g.fills = []; g.clipsContent = false; g.resize(b.w, Math.max(1, vh * k));
  if (vec) { vec.name = 'Vector shapes'; g.appendChild(vec); vec.x = 0; vec.y = 0; if (vec.width > 0) vec.rescale(k); }
  const FM = FONTS.medium, FH = FONTS.heavy;
  for (const L of (b.labels || [])) {
    const t = figma.createText();
    t.fontName = L.b ? FH : (L.i && FONTS.oblique ? FONTS.oblique : FM);
    t.characters = supsub([{ t: L.t }])[0].t;
    t.fontSize = Math.max(4, L.size * k);
    t.lineHeight = { value: Math.round(L.size * k * 1.25 * 10) / 10, unit: 'PIXELS' };
    t.fills = solid(/^#[0-9a-f]{6}$/i.test(L.fill || '') ? L.fill : '#000000');
    t.textAutoResize = 'WIDTH_AND_HEIGHT';
    t.name = L.t.slice(0, 40);
    g.appendChild(t);
    const w = t.width, h = t.height;
    const ax = L.x * k, ay = L.y * k;                                   // SVG anchor: baseline at (x, y)
    let left = L.anchor === 'middle' ? ax - w / 2 : L.anchor === 'end' ? ax - w : ax;
    const top = ay - (h / 2 + L.size * k * 0.32);                       // baseline sits ~0.32em below the line's middle
    if (L.rot) {
      const ph = L.rot * Math.PI / 180, cs = Math.cos(ph), sn = Math.sin(ph);
      const rx = (L.rx != null ? L.rx : L.x) * k, ry = (L.ry != null ? L.ry : L.y) * k;
      const cx = left + w / 2, cy = top + h / 2;                        // rotate the label's centre about the SVG origin of the rotation
      const dx = cx - rx, dy = cy - ry;
      const ncx = rx + dx * cs - dy * sn, ncy = ry + dx * sn + dy * cs;
      t.relativeTransform = [[cs, -sn, ncx - (cs * w / 2 - sn * h / 2)], [sn, cs, ncy - (sn * w / 2 + cs * h / 2)]];
    } else { t.x = left; t.y = top; }
    t.setSharedPluginData('books', 'diagram_label', '1');
  }
  try { g.setSharedPluginData('books', 'diagram', '1'); g.setSharedPluginData('books', 'src', (src || []).join(',')); } catch (e) {}
  return g;
}
async function pic(b, src) {
  if (b.svg) { try { return await diagramNode(b, src); } catch (e) { diagramErrors.push(String(e && e.message || e)); } }
  return placeholder(b, src);
}
const diagramErrors = [];

async function picsRow(col, pics) {
  if (!pics || !pics.length) return;
  const row = frame('Pictures', { dir: 'H', gap: 6 });
  add(col, row, { fill: true });
  row.layoutWrap = 'WRAP'; row.counterAxisSpacing = 6;
  for (const it of pics) add(row, await pic(it, it.src ? [it.src] : []));
}

// ---------------------------------------------------------------- blocks
const TEXT_ON_PAGE = new Set(['title', 'h', 'p', 'note', 'ul', 'ol', 'toc', 'end']);
async function build(b, parent, ctx) {
  const st = ctx && ctx.style;
  if (st && st.dark && !ctx.card && TEXT_ON_PAGE.has(b.t)) {  // text sitting directly on a dark page
    const prev = T;
    T = Object.assign({}, T, { text: st.fg, strong: st.fg, primary: st.fg, rule: st.rule });
    try { return await buildBlock(b, parent, ctx); } finally { T = prev; }
  }
  return buildBlock(b, parent, ctx);
}
async function buildBlock(b, parent, ctx) {
  const src = b.src;
  switch (b.t) {
    case 'title': {
      const f = frame('Title', { gap: b.eyebrow ? 4 : 2, pad: [0, 0, b.eyebrow ? 6 : 4, 0] });
      add(parent, f, { fill: true });
      if (b.eyebrow) add(f, text(b.eyebrow, { font: 'din', size: L.type.eyebrow.size, lh: L.type.eyebrow.lh, color: T.primary, case: 'ORIGINAL', role: 'eyebrow', name: 'eyebrow' }), { fill: true });
      add(f, text(b.text, { font: 'din', size: L.type.title.size, lh: L.type.title.lh, color: T.strong, case: 'TITLE', role: 'title', src }), { fill: true });
      return f;
    }
    case 'h': {
      const st = { 2: ['din', L.type.h2.size, L.type.h2.lh, null], 3: ['black', L.type.h3.size, L.type.h3.lh, 'TITLE'], 4: ['black', L.type.h4.size, L.type.h4.lh, null], 5: ['heavy', L.type.h5.size, L.type.h5.lh, null] }[b.lvl];
      return add(parent, text(b.text, { font: st[0], size: st[1], lh: st[2], color: T.strong, case: st[3] || 'ORIGINAL', role: b.lvl === 3 ? 'h3' : b.lvl === 2 ? 'h2' : null, src }), { fill: true });
    }
    case 'p': return add(parent, runsText(b.runs, { src }), { fill: true });
    case 'note': {
      const full = plainOf(b.runs);
      const c = full.indexOf(':');
      let runs = b.runs;
      if (!b.muted && c > 0 && c < 80 && !b.runs.some(r => r.b)) runs = [{ t: full.slice(0, c + 1), b: 1 }, { t: full.slice(c + 1) }];
      return add(parent, runsText(runs, { src }), { fill: true });
    }
    case 'ul': {
      const f = frame('Bullets', { gap: 5 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Bullet', { dir: 'H', gap: 6 });
        add(f, row, { fill: true });
        const check = b.mark === '✓';
        add(row, text(b.mark, { font: check ? 'medium' : 'heavy', size: check ? L.type.body.size : L.type.mark.size, lh: check ? L.type.body.lh : L.type.mark.lh, color: colorOf(comp(ctx, 'bullets').markColor, T.primary), name: 'mark' }));
        const t = runsText(itemRuns(it), { src: b.src });
        add(row, t); t.layoutSizingHorizontal = 'FILL';
      }
      return f;
    }
    case 'ol': {
      const f = frame('Numbered list', { gap: 5 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Item', { dir: 'H', gap: 4 });
        add(f, row, { fill: true });
        const lab = text(it.label, { font: 'heavy', size: L.type.body.size, color: T.primary, name: 'label' });
        add(row, lab); lab.textAutoResize = 'WIDTH_AND_HEIGHT'; lab.resize(Math.max(lab.width, 18), lab.height);
        const col = frame('Text', { gap: 3 });
        add(row, col); col.layoutSizingHorizontal = 'FILL';
        for (const l of it.lines) add(col, runsText(l, { src: b.src }), { fill: true });
      }
      return f;
    }
    case 'table': {
      const f = frame('Table', {});
      add(parent, f, { fill: true });
      if (b.from_pic) { f.name = 'Table (read from picture, review against the original)'; try { f.setSharedPluginData('books', 'pic_table', '1'); f.setSharedPluginData('books', 'src', (src || []).join(',')); } catch (e) {} }
      const hasHead = b.head && b.head.length > 0;
      const rows = hasHead ? [b.head].concat(b.rows) : b.rows;
      rows.forEach((r, ri) => {
        const isHead = hasHead && ri === 0;
        const row = frame(isHead ? 'Header row' : 'Row', { dir: 'H' });
        add(f, row, { fill: true });
        const k = hasHead ? ri : ri + 1;
        const ts = comp(ctx, 'table');
        const fillHex = isHead ? colorOf(ts.headFill, T.primary) : (ts.zebra === false || k % 2 === 1 ? T.white : T.tableAlt);
        r.forEach((c, ci) => {
          const cell = frame('Cell', { dir: 'H', pad: [6, 9, 6, 9], fill: fillHex, stroke: T.tableBorder, w: b.widths[ci] });
          add(row, cell); cell.layoutSizingVertical = 'FILL';
          add(cell, text(c || ' ', { font: isHead ? 'black' : 'medium', color: isHead ? colorOf(ts.headText, T.onPrimary) : T.text, src: b.src }), { fill: true });
        });
      });
      return f;
    }
    case 'callout': {
      const cc = b.variant === 'keyideas' ? { bg: T.tint, fg: T.primary } : T[b.variant];
      const f = frame('Callout: ' + b.title, { gap: 5, pad: [12, 12, 12, 12], fill: cc.bg, radius: comp(ctx, 'callout').radius != null ? comp(ctx, 'callout').radius : 8 });
      add(parent, f, { fill: true });
      add(f, text(b.title, { font: 'black', size: L.type.body.size, color: cc.fg, src: b.title_src || b.src }), { fill: true });
      const inner = frame('Content', { gap: 3 });
      add(f, inner, { fill: true });
      let prev = null;
      for (const x of b.blocks) {
        if (prev && prev.t === 'p' && x.t === 'ul') { /* keep 3 gap */ }
        await build(x, inner, Object.assign({}, ctx, { card: true }));
        prev = x;
      }
      return f;
    }
    case 'formula': {
      const fs = comp(ctx, 'formula');
      const f = frame('Formula', { dir: 'H', pad: [12, 12, 12, 12], fill: colorOf(fs.fill, T.primary), radius: 6, main: 'CENTER' });
      add(parent, f, { fill: true });
      add(f, text(b.text, { font: 'heavy', size: 13, lh: 17.8, color: colorOf(fs.text, T.onPrimary), align: 'CENTER', src }), { fill: true });
      return f;
    }
    case 'image': {
      const small = b.w <= 360;
      const wrap = frame('Image', { dir: 'H', main: small ? 'MIN' : 'CENTER' });
      add(parent, wrap, { fill: true });
      add(wrap, await pic(b, src));
      return wrap;
    }
    case 'imagerow': {
      const row = frame('Pictures', { dir: 'H', gap: 8 });
      add(parent, row, { fill: true });
      row.layoutWrap = 'WRAP'; row.counterAxisSpacing = 8;
      for (const it of b.items) add(row, await pic(it, src));
      return row;
    }
    case 'qcard': {
      const qs = comp(ctx, 'qcard');
      const f = frame('Question card', { radius: qs.radius != null ? qs.radius : 8, clip: true, gap: 0 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Question', { dir: 'H', gap: 4, pad: padOf(qs, 7.5), fill: colorOf(qs.fill, T.white) });
        add(f, row, { fill: true });
        const lab = text(it.label, { font: 'heavy', size: L.type.body.size, color: qs.numberColor ? colorOf(qs.numberColor, T.primary) : (qs.fill === 'none' && ctx.style && ctx.style.dark ? ctx.style.fg : T.primary), name: 'number' });
        add(row, lab); lab.textAutoResize = 'WIDTH_AND_HEIGHT'; lab.resize(Math.max(lab.width, 18), lab.height);
        if (it.lines.length || (it.pics && it.pics.length)) {  // an empty column would not collapse in Figma
          const col = frame('Text', { gap: 3 });
          add(row, col); col.layoutSizingHorizontal = 'FILL';
          for (const l of it.lines) add(col, runsText(l, { src: b.src, color: cardText(ctx, qs, T.text) }), { fill: true });
          await picsRow(col, it.pics);
        }
      }
      return f;
    }
    case 'mcq': {
      const ms = comp(ctx, 'mcq');
      const ncol = b.columns || ms.columns || 2;
      const f = frame('MCQ', { gap: 3, pad: padOf(ms, 12, 2 / 3), fill: colorOf(ms.fill, T.white), radius: ms.radius != null ? ms.radius : 8 });
      const mtext = cardText(ctx, ms, T.text);
      add(parent, f, { fill: true });
      const stem = [{ t: b.n + ' ', b: 1 }].concat(b.stem.map(r => Object.assign({}, r, { b: 1 })));
      add(f, runsText(stem, { font: 'heavy', color: ms.textColor || (ms.fill === 'none' && ctx.style && ctx.style.dark) ? mtext : T.strong, src: b.src, allBold: true }), { fill: true });
      for (let i = 0; i < b.options.length; i += ncol) {
        const row = frame('Options', { dir: 'H', gap: 12 });
        add(f, row, { fill: true });
        for (const o of b.options.slice(i, i + ncol)) {
          const t = runsText(o.runs, { src: b.src, color: mtext });
          add(row, t); t.layoutSizingHorizontal = 'FILL';
        }
        if (ncol === 2 && b.options.slice(i, i + 2).length === 1) { const sp = frame('spacer', { dir: 'H' }); add(row, sp); sp.layoutSizingHorizontal = 'FILL'; }
      }
      return f;
    }
    case 'ans': {
      const as_ = comp(ctx, 'ans');
      const f = frame('Answer card', { radius: as_.radius != null ? as_.radius : 8, clip: true, gap: 1 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Answer', { dir: 'H', gap: 0 });
        add(f, row, { fill: true });
        const tab = frame('Number tab', { dir: 'V', fill: colorOf(as_.tabFill, T.primary), w: 33, pad: [5.25, 4, 5.25, 4], align: 'CENTER' });
        add(row, tab); tab.layoutSizingVertical = 'FILL';
        add(tab, text(it.label, { font: 'heavy', size: L.type.body.size, color: T.onPrimary, align: 'CENTER', name: 'number' }), { fill: true });
        const col = frame('Text', { gap: 3, pad: padOf(as_, 7.5), fill: colorOf(as_.fill, T.white) });
        add(row, col); col.layoutSizingHorizontal = 'FILL'; col.layoutSizingVertical = 'FILL';
        for (const x of it.blocks) add(col, runsText(x.runs, { src: x.src || b.src, color: cardText(ctx, as_, T.text) }), { fill: true });
        await picsRow(col, it.pics);
      }
      return f;
    }
    case 'toc': {
      const f = frame('Table of contents', { gap: b.compact ? 4 : 10 });
      add(parent, f, { fill: true });
      if (!b.cont) {
        if (b.eyebrow) add(f, text(b.eyebrow, { font: 'din', size: L.type.eyebrow.size, lh: L.type.eyebrow.lh, color: T.primary, case: 'ORIGINAL', role: 'eyebrow', name: 'eyebrow' }), { fill: true });
        add(f, text(b.title, { font: 'din', size: L.type.title.size, lh: L.type.title.lh, color: (ctx && ctx.style && ctx.style.dark) ? T.strong : '#000000', case: 'TITLE', role: 'title', src }), { fill: true });
        add(f, text(b.chapter_line || ('Chapter ' + (b.chapter_no ? b.chapter_no + ' - ' : '') + b.chapter), { font: 'din', size: L.type.eyebrow.size, lh: L.type.eyebrow.lh, color: (ctx && ctx.style && ctx.style.dark) ? T.strong : '#000000', case: 'TITLE', role: 'toc', name: 'chapter (generated)' }), { fill: true });
      }
      for (const e of b.entries) {
        const box = frame('Entry', { gap: 4, pad: b.compact ? [4, 0, 4, 0] : [8, 0, 8, 0], stroke: T.rule });
        box.strokeTopWeight = 0; box.strokeLeftWeight = 0; box.strokeRightWeight = 0; box.strokeBottomWeight = 1;
        add(f, box, { fill: true });
        const row = frame('Row', { dir: 'H', align: 'MAX' });
        if (e.title) {
          add(box, text(e.label, { font: L.type.toc.size >= 14 ? 'din' : 'heavy', size: L.type.toc.size, lh: L.type.toc.lh, color: T.primary, case: 'TITLE', role: 'toc' }), { fill: true });
          add(box, row, { fill: true });
          add(row, text(e.title, { font: 'medium', size: L.type.body.size, color: T.text }), { fill: true });
        } else {
          add(box, row, { fill: true });
          add(row, text(e.label, { font: L.type.toc.size >= 14 ? 'din' : 'heavy', size: L.type.toc.size, lh: L.type.toc.lh, color: T.primary, case: 'TITLE', role: 'toc' }), { fill: true });
        }
        const pn = text(e.page == null ? '' : String(e.page), { font: 'black', size: L.type.mark.size, lh: L.type.mark.lh, color: T.primary, align: 'RIGHT', name: 'page' });
        add(row, pn); pn.textAutoResize = 'WIDTH_AND_HEIGHT';
      }
      return f;
    }
    case 'end': {
      const f = frame('End of chapter', { gap: 10, align: 'CENTER' });
      add(parent, f, { fill: true });
      add(f, text(/^module/i.test(b.module || '') ? b.module : 'MODULE ' + (b.module || ''), { font: 'din', size: 16, lh: 19.2, color: T.primary, ls: 1, align: 'CENTER', name: 'module (generated)' }), { stretch: true });
      add(f, text('End of Chapter', { font: 'din', size: 34, lh: 40.8, color: T.strong, align: 'CENTER', name: 'end (generated)' }), { stretch: true });
      f.appendChild(rect('rule', 0, 0, 120, 2, T.primary)); 
      add(f, text([b.chapter, 'Grade ' + b.grade + ' ' + b.subject].join(' · '), { font: 'medium', size: 11, color: T.text, case: 'TITLE', align: 'CENTER', name: 'subtitle (generated)' }), { stretch: true });
      return f;
    }
  }
  throw new Error('Unknown block type: ' + b.t);
}

// ---------------------------------------------------------------- pages
async function makePage(page, idx, meta) {
  const f = figma.createFrame();
  const label = page.kind === 'toc' ? 'Table of contents' : page.kind;
  f.name = (page.pageNo != null ? 'Page ' + page.pageNo : 'Page') + ' · ' + (page.pill ? page.pill.toLowerCase() : label);
  f.resize(PAGE_W, PAGE_H);
  const pst = pageStyle(page, T);
  f.fills = solid(pst.bg);
  f.clipsContent = true;
  f.setSharedPluginData('books', 'page', String(page.pageNo == null ? 0 : page.pageNo));
  const H = L.header, F = L.footer;
  if (page.pill) {
    f.appendChild(rect('Header rule', H.ruleX, H.ruleY, H.ruleW, 1, pst.rule));
    const pill = frame('Header pill', { dir: 'H', pad: [3, 9, 3, 9], fill: pst.pillBg, radius: H.pillH, w: H.pillW, align: 'CENTER' });
    f.appendChild(pill); pill.x = H.pillX; pill.y = H.pillY;
    add(pill, text(page.pill, { font: 'medium', size: H.pillSize, lh: Math.round(H.pillSize * 1.37 * 10) / 10, color: pst.pillFg, case: 'UPPER', role: 'pill', ls: 0.35, align: 'CENTER', name: 'section' }), { fill: true });
  }
  f.appendChild(rect('Footer rule', F.ruleX, F.ruleY, F.ruleW, 1, T.footerRule));
  const ft = text(meta.footer || '', { font: 'medium', size: F.textSize, lh: Math.round(F.textSize * 1.36 * 10) / 10, color: pst.dark ? '#FFFFFF' : '#000000', name: 'footer' });
  f.appendChild(ft); ft.x = F.textX; ft.y = F.textY; ft.textAutoResize = 'WIDTH_AND_HEIGHT';
  if (page.pageNo != null) {
    const pn = text(String(page.pageNo), { font: 'black', size: F.numSize, lh: Math.round(F.numSize * 1.36 * 10) / 10, color: pst.dark ? '#FFFFFF' : T.primary, align: 'RIGHT', name: 'page number' });
    f.appendChild(pn); pn.textAutoResize = 'HEIGHT'; pn.resize(40, pn.height); pn.x = F.numX; pn.y = F.numY;
  }
  const col = frame('Column', { gap: 0, pad: [0, PAGE_W - COL_X - COL_W, 0, COL_X], w: PAGE_W });
  f.appendChild(col); col.x = 0; col.y = page.kind === 'end' ? 0 : TOP;
  if (page.kind === 'end') { col.resize(PAGE_W, PAGE_H); col.layoutSizingVertical = 'FIXED'; col.primaryAxisAlignItems = 'CENTER'; }
  for (const b of page.blocks) {
    let host = col;
    if (b.gap > 0) { host = frame('gap', { pad: [b.gap, 0, 0, 0] }); add(col, host, { fill: true }); }
    await build(b, host, { page, style: pst });
  }
  const bottom = col.y + col.height;
  return { frame: f, bottom, overflow: page.kind !== 'end' && bottom > L.col.bottom + 0.5 };
}

figma.ui.onmessage = async msg => {
  if (msg.type !== 'build') return;
  const job = msg.job, spec = job.spec;
  if (spec.pluginVersion !== PLUGIN_VERSION) {
    figma.ui.postMessage({ type: 'error', text: 'The plugin running in Figma is out of date (it is version ' + PLUGIN_VERSION + ', the app made this job for version ' + spec.pluginVersion + '). Close the plugin, run it again from Plugins → Development → Book Builder, then Load and Build again.' });
    return;
  }
  T = spec.theme;
  applyLayout();
  try {
    figma.ui.postMessage({ type: 'progress', n: 0, total: spec.pages.length, text: 'Loading fonts…' });
    const missing = await loadFonts();
    if (missing.length) { figma.ui.postMessage({ type: 'error', text: 'Missing fonts in Figma: ' + missing.join(', ') + '. Install them on this computer and restart Figma.' }); return; }
    const section = figma.createSection();
    section.name = (spec.name || 'Book') + ' (generated ' + new Date().toLocaleString() + ')';
    const c = figma.viewport.center;
    const COLS = 6, GAP = 60, PAD = 60;
    const rows = Math.ceil(spec.pages.length / COLS);
    section.x = Math.round(c.x - 300); section.y = Math.round(c.y - 400);
    section.resizeWithoutConstraints(PAD * 2 + COLS * PAGE_W + (COLS - 1) * GAP, PAD * 2 + rows * PAGE_H + (rows - 1) * GAP);
    const report = { job: job.id, pages: [], errors: [] };
    for (let i = 0; i < spec.pages.length; i++) {
      figma.ui.postMessage({ type: 'progress', n: i, total: spec.pages.length, text: 'Building page ' + (i + 1) + ' of ' + spec.pages.length + '…' });
      await new Promise(r => setTimeout(r, 0));
      const p = spec.pages[i];
      try {
        const r = await makePage(p, i, spec.meta);
        section.appendChild(r.frame);
        r.frame.x = PAD + (i % COLS) * (PAGE_W + GAP);
        r.frame.y = PAD + Math.floor(i / COLS) * (PAGE_H + GAP);
        report.pages.push({ index: i, pageNo: p.pageNo, kind: p.kind, nodeId: r.frame.id, contentBottom: Math.round(r.bottom), overflow: r.overflow });
      } catch (e) { report.errors.push({ index: i, pageNo: p.pageNo, error: String(e && e.message || e) }); }
    }
    report.sectionId = section.id; report.sectionName = section.name; report.diagramErrors = diagramErrors.slice(0, 20); report.pluginVersion = PLUGIN_VERSION;
    figma.currentPage.selection = [section];
    figma.viewport.scrollAndZoomIntoView([section]);
    figma.ui.postMessage({ type: 'done', report });
    figma.notify('Book Builder: built ' + report.pages.length + ' pages' + (report.errors.length ? ' (' + report.errors.length + ' errors)' : ''));
  } catch (e) {
    figma.ui.postMessage({ type: 'error', text: 'Build failed: ' + String(e && e.message || e) });
  }
};
