// Book Builder: builds book pages in Figma from the design spec produced by the local app.
// Text is only ever set from the spec (copied from the Google Doc by the app) - never generated here.
figma.showUI(__html__, { width: 340, height: 400 });

const PAGE_W = 595, PAGE_H = 842, COL_X = 40, COL_W = 515, TOP = 64;
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

async function loadFonts() {
  const missing = [];
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
function titleCaseCaps(s) {
  if (s === s.toLowerCase() || s !== s.toUpperCase()) return s;
  let out = '', cap = true;
  for (const ch of s.toLowerCase()) { out += cap ? ch.toUpperCase() : ch; cap = ch === ' ' || ch === '-' || ch === '('; }
  return out;
}
function text(chars, o) {
  if (o.case === 'TITLE') chars = titleCaseCaps(chars);
  const t = figma.createText();
  t.fontName = FONTS[o.font || 'medium'];
  t.characters = chars;
  t.fontSize = o.size || 11;
  t.lineHeight = { value: o.lh || 15, unit: 'PIXELS' };
  t.fills = solid(o.color || T.text);
  if (o.case) t.textCase = o.case;
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
  const n = figma.createNodeFromSvg(b.svg);
  n.name = 'DIAGRAM (generated, review against the original)';
  const f = FONTS.medium;
  for (const t of n.findAll(x => x.type === 'TEXT')) { try { await figma.loadFontAsync(f); t.fontName = f; } catch (e) {} }
  if (n.width > 0) n.rescale(b.w / n.width);
  n.clipsContent = false;
  try { n.setSharedPluginData('books', 'diagram', '1'); n.setSharedPluginData('books', 'src', (src || []).join(',')); } catch (e) {}
  return n;
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
async function build(b, parent, ctx) {
  const src = b.src;
  switch (b.t) {
    case 'title': {
      const f = frame('Title', { gap: b.eyebrow ? 4 : 2, pad: [0, 0, b.eyebrow ? 6 : 4, 0] });
      add(parent, f, { fill: true });
      if (b.eyebrow) add(f, text(b.eyebrow, { font: 'din', size: 20, lh: 24, color: T.primary, case: b.eyebrow === b.eyebrow.toUpperCase() ? 'ORIGINAL' : 'TITLE', name: 'eyebrow' }), { fill: true });
      add(f, text(b.text, { font: 'din', size: 42, lh: 50.4, color: T.strong, case: 'TITLE', src }), { fill: true });
      return f;
    }
    case 'h': {
      const st = { 2: ['din', 18, 21.6, null], 3: ['black', 13, 17.8, 'TITLE'], 4: ['black', 11, 15, null], 5: ['heavy', 11, 15, null] }[b.lvl];
      return add(parent, text(b.text, { font: st[0], size: st[1], lh: st[2], color: T.strong, case: st[3] || 'ORIGINAL', src }), { fill: true });
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
        add(row, text(b.mark, { font: check ? 'medium' : 'heavy', size: check ? 11 : 10, lh: check ? 15 : 13.7, color: T.primary, name: 'mark' }));
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
        const lab = text(it.label, { font: 'heavy', size: 11, color: T.primary, name: 'label' });
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
      const hasHead = b.head && b.head.length > 0;
      const rows = hasHead ? [b.head].concat(b.rows) : b.rows;
      rows.forEach((r, ri) => {
        const isHead = hasHead && ri === 0;
        const row = frame(isHead ? 'Header row' : 'Row', { dir: 'H' });
        add(f, row, { fill: true });
        const k = hasHead ? ri : ri + 1;
        const fillHex = isHead ? T.primary : (k % 2 === 1 ? T.white : T.tableAlt);
        r.forEach((c, ci) => {
          const cell = frame('Cell', { dir: 'H', pad: [6, 9, 6, 9], fill: fillHex, stroke: T.tableBorder, w: b.widths[ci] });
          add(row, cell); cell.layoutSizingVertical = 'FILL';
          add(cell, text(c || ' ', { font: isHead ? 'black' : 'medium', color: isHead ? T.onPrimary : T.text, src: b.src }), { fill: true });
        });
      });
      return f;
    }
    case 'callout': {
      const cc = b.variant === 'keyideas' ? { bg: T.tint, fg: T.primary } : T[b.variant];
      const f = frame('Callout: ' + b.title, { gap: 5, pad: [12, 12, 12, 12], fill: cc.bg, radius: 8 });
      add(parent, f, { fill: true });
      add(f, text(b.title, { font: 'black', size: 11, color: cc.fg, src: b.title_src || b.src }), { fill: true });
      const inner = frame('Content', { gap: 3 });
      add(f, inner, { fill: true });
      let prev = null;
      for (const x of b.blocks) {
        if (prev && prev.t === 'p' && x.t === 'ul') { /* keep 3 gap */ }
        await build(x, inner, ctx);
        prev = x;
      }
      return f;
    }
    case 'formula': {
      const f = frame('Formula', { dir: 'H', pad: [12, 12, 12, 12], fill: T.primary, radius: 6, main: 'CENTER' });
      add(parent, f, { fill: true });
      add(f, text(b.text, { font: 'heavy', size: 13, lh: 17.8, color: T.onPrimary, align: 'CENTER', src }), { fill: true });
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
      const f = frame('Question card', { radius: 8, clip: true, gap: 0 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Question', { dir: 'H', gap: 4, pad: [5.25, 7.5, 5.25, 7.5], fill: T.white });
        add(f, row, { fill: true });
        const lab = text(it.label, { font: 'heavy', size: 11, color: T.primary, name: 'number' });
        add(row, lab); lab.textAutoResize = 'WIDTH_AND_HEIGHT'; lab.resize(Math.max(lab.width, 18), lab.height);
        if (it.lines.length || (it.pics && it.pics.length)) {  // an empty column would not collapse in Figma
          const col = frame('Text', { gap: 3 });
          add(row, col); col.layoutSizingHorizontal = 'FILL';
          for (const l of it.lines) add(col, runsText(l, { src: b.src }), { fill: true });
          await picsRow(col, it.pics);
        }
      }
      return f;
    }
    case 'mcq': {
      const f = frame('MCQ', { gap: 3, pad: [8, 12, 8, 12], fill: T.white, radius: 8 });
      add(parent, f, { fill: true });
      const stem = [{ t: b.n + ' ', b: 1 }].concat(b.stem.map(r => Object.assign({}, r, { b: 1 })));
      add(f, runsText(stem, { font: 'heavy', color: T.strong, src: b.src, allBold: true }), { fill: true });
      for (let i = 0; i < b.options.length; i += 2) {
        const row = frame('Options', { dir: 'H', gap: 12 });
        add(f, row, { fill: true });
        for (const o of b.options.slice(i, i + 2)) {
          const t = runsText(o.runs, { src: b.src });
          add(row, t); t.layoutSizingHorizontal = 'FILL';
        }
        if (b.options.slice(i, i + 2).length === 1) { const sp = frame('spacer', { dir: 'H' }); add(row, sp); sp.layoutSizingHorizontal = 'FILL'; }
      }
      return f;
    }
    case 'ans': {
      const f = frame('Answer card', { radius: 8, clip: true, gap: 1 });
      add(parent, f, { fill: true });
      for (const it of b.items) {
        const row = frame('Answer', { dir: 'H', gap: 0 });
        add(f, row, { fill: true });
        const tab = frame('Number tab', { dir: 'V', fill: T.primary, w: 33, pad: [5.25, 4, 5.25, 4], align: 'CENTER' });
        add(row, tab); tab.layoutSizingVertical = 'FILL';
        add(tab, text(it.label, { font: 'heavy', size: 11, color: T.onPrimary, align: 'CENTER', name: 'number' }), { fill: true });
        const col = frame('Text', { gap: 3, pad: [5.25, 7.5, 5.25, 7.5], fill: T.white });
        add(row, col); col.layoutSizingHorizontal = 'FILL'; col.layoutSizingVertical = 'FILL';
        for (const x of it.blocks) add(col, runsText(x.runs, { src: x.src || b.src }), { fill: true });
        await picsRow(col, it.pics);
      }
      return f;
    }
    case 'toc': {
      const f = frame('Table of contents', { gap: 10 });
      add(parent, f, { fill: true });
      add(f, text(b.title, { font: 'din', size: 42, lh: 50.4, color: '#000000', case: 'TITLE', src }), { fill: true });
      add(f, text(b.chapter_line || ('Chapter ' + (b.chapter_no ? b.chapter_no + ' - ' : '') + b.chapter), { font: 'din', size: 20, lh: 24, color: '#000000', case: 'TITLE', name: 'chapter (generated)' }), { fill: true });
      for (const e of b.entries) {
        const box = frame('Entry', { gap: 4, pad: [8, 0, 8, 0], stroke: T.rule });
        box.strokeTopWeight = 0; box.strokeLeftWeight = 0; box.strokeRightWeight = 0; box.strokeBottomWeight = 1;
        add(f, box, { fill: true });
        const row = frame('Row', { dir: 'H', align: 'MAX' });
        if (e.title) {
          add(box, text(e.label, { font: 'din', size: 18, lh: 21.6, color: T.primary, case: 'TITLE' }), { fill: true });
          add(box, row, { fill: true });
          add(row, text(e.title, { font: 'medium', size: 11, color: T.text }), { fill: true });
        } else {
          add(box, row, { fill: true });
          add(row, text(e.label, { font: 'din', size: 18, lh: 21.6, color: T.primary, case: 'TITLE' }), { fill: true });
        }
        const pn = text(e.page == null ? '' : String(e.page), { font: 'black', size: 10, lh: 13.7, color: T.primary, align: 'RIGHT', name: 'page' });
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
  f.fills = solid(page.bg === 'tint' ? T.tint : T.white);
  f.clipsContent = true;
  f.setSharedPluginData('books', 'page', String(page.pageNo == null ? 0 : page.pageNo));
  if (page.pill) {
    f.appendChild(rect('Header rule', 35, 40, 372, 1, T.rule));
    const pill = frame('Header pill', { dir: 'H', pad: [3, 9, 3, 9], fill: T.primary, radius: 15.75, w: 142, align: 'CENTER' });
    f.appendChild(pill); pill.x = 417; pill.y = 33;
    add(pill, text(page.pill, { font: 'medium', size: 7, lh: 9.6, color: T.onPrimary, case: 'UPPER', ls: 0.35, align: 'CENTER', name: 'section' }), { fill: true });
  }
  f.appendChild(rect('Footer rule', 35, 801, 525, 1, T.footerRule));
  const ft = text(meta.footer || '', { font: 'medium', size: 8, lh: 10.9, color: '#000000', name: 'footer' });
  f.appendChild(ft); ft.x = 35; ft.y = 813; ft.textAutoResize = 'WIDTH_AND_HEIGHT';
  if (page.pageNo != null) {
    const pn = text(String(page.pageNo), { font: 'black', size: 8, lh: 10.9, color: T.primary, align: 'RIGHT', name: 'page number' });
    f.appendChild(pn); pn.textAutoResize = 'HEIGHT'; pn.resize(40, pn.height); pn.x = 520; pn.y = 814;
  }
  const col = frame('Column', { gap: 0, pad: [0, 40, 0, 40], w: PAGE_W });
  f.appendChild(col); col.x = 0; col.y = page.kind === 'end' ? 0 : TOP;
  if (page.kind === 'end') { col.resize(PAGE_W, PAGE_H); col.layoutSizingVertical = 'FIXED'; col.primaryAxisAlignItems = 'CENTER'; }
  for (const b of page.blocks) {
    let host = col;
    if (b.gap > 0) { host = frame('gap', { pad: [b.gap, 0, 0, 0] }); add(col, host, { fill: true }); }
    await build(b, host, { page });
  }
  const bottom = col.y + col.height;
  return { frame: f, bottom, overflow: page.kind !== 'end' && bottom > 786.5 };
}

figma.ui.onmessage = async msg => {
  if (msg.type !== 'build') return;
  const job = msg.job, spec = job.spec;
  T = spec.theme;
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
    report.sectionId = section.id; report.sectionName = section.name; report.diagramErrors = diagramErrors.slice(0, 20);
    figma.currentPage.selection = [section];
    figma.viewport.scrollAndZoomIntoView([section]);
    figma.ui.postMessage({ type: 'done', report });
    figma.notify('Book Builder: built ' + report.pages.length + ' pages' + (report.errors.length ? ' (' + report.errors.length + ' errors)' : ''));
  } catch (e) {
    figma.ui.postMessage({ type: 'error', text: 'Build failed: ' + String(e && e.message || e) });
  }
};
