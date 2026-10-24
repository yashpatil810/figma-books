// Renders a page spec as DOM. Mirrors figma-plugin/code.js so the preview matches what gets built in Figma.
import React from 'react'

let AV = "Avenir, 'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
let DIN = "'DIN Condensed', 'Arial Narrow', Impact, sans-serif"
const AV0 = AV, DIN0 = DIN
// A style with its own fonts: use them in the preview too (loaded from Google Fonts when the browser does not have them).
function useStyleFonts(T) {
  const tf = T.fonts || {}
  AV = tf.text?.family ? `'${tf.text.family}', ${AV0}` : AV0
  DIN = tf.display?.family ? `'${tf.display.family}', ${DIN0}` : DIN0
  const fams = [tf.text && `${tf.text.family}:wght@400;500;700;800;900`, tf.display && `${tf.display.family}:wght@700`].filter(Boolean)
  if (fams.length && typeof document !== 'undefined') {
    const href = 'https://fonts.googleapis.com/css2?' + fams.map(f => 'family=' + f.replace(/ /g, '+')).join('&') + '&display=swap'
    if (!document.querySelector(`link[data-style-fonts="${href}"]`)) { const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = href; l.setAttribute('data-style-fonts', href); document.head.appendChild(l) }
  }
}

const titleCase = s => s.toLowerCase().replace(/(^|[\s\-(])([a-z])/g, (m, a, b) => a + b.toUpperCase())
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
const TEXT_ON_PAGE = new Set(['title', 'h', 'p', 'note', 'ul', 'ol', 'toc', 'end'])
// Component styles: the theme's overridden by the section's (set per page in Page()). Colour tokens resolve against the theme.
let COMP = {}
let THEME_COMP = {}
let PAGE_ST = { dark: false, fg: null }
// Text inside a card: the style's textColor, else automatic — the page's text colour when the card has no fill.
const cardText = (T, cs, dflt) => cs.textColor ? colorOf(T, cs.textColor, dflt) : (cs.fill === 'none' && PAGE_ST.dark ? PAGE_ST.fg : dflt)
const padCss = (cs, dflt, ratio = 0.7) => { const px = cs.pad ?? dflt; return `${Math.round(px * ratio * 100) / 100}px ${px}px` }
const comp = n => ({ ...(THEME_COMP[n] || {}), ...(COMP[n] || {}) })
const colorOf = (T, v, dflt) => v == null ? dflt : v === 'none' ? 'transparent' : /^#/.test(v) ? v : ({ white: T.white, primary: T.primary, tint: T.tint, text: T.text, strong: T.strong, onPrimary: T.onPrimary })[v] || dflt
const LY0 = {
  page: { w: 595, h: 842 }, col: { x: 40, w: 515, top: 64, bottom: 786 },
  header: { ruleX: 35, ruleY: 40, ruleW: 372, pillX: 417, pillY: 33, pillW: 142, pillH: 16, pillSize: 7 },
  footer: { ruleX: 35, ruleY: 801, ruleW: 525, textX: 35, textY: 813, textSize: 8, numX: 520, numY: 814, numSize: 8 },
  type: { title: { size: 42, lh: 50.4 }, eyebrow: { size: 20, lh: 24 }, h2: { size: 18, lh: 21.6 }, h3: { size: 13, lh: 17.8 }, h4: { size: 11, lh: 15 }, h5: { size: 11, lh: 15 }, body: { size: 11, lh: 15 }, mark: { size: 10, lh: 13.7 }, toc: { size: 18, lh: 21.6 } },
}
let LY = LY0
const TY = role => ({ fontSize: LY.type[role].size, lineHeight: LY.type[role].lh + 'px' })
let CASE_RULES = {}, ACR = new Set()
const tc = (s, role = 'title') => applyCase(s, CASE_RULES[role] || 'TITLE', ACR)
const cssCase = role => { const m = CASE_RULES[role]; return m === 'UPPER' ? 'uppercase' : m === 'LOWER' ? 'lowercase' : 'none' }

const SUP = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹', '+': '⁺', '-': '⁻', '−': '⁻', '=': '⁼', '(': '⁽', ')': '⁾', n: 'ⁿ', i: 'ⁱ' }
const SUB = { 0: '₀', 1: '₁', 2: '₂', 3: '₃', 4: '₄', 5: '₅', 6: '₆', 7: '₇', 8: '₈', 9: '₉', '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎', a: 'ₐ', e: 'ₑ', o: 'ₒ', x: 'ₓ', h: 'ₕ', k: 'ₖ', l: 'ₗ', m: 'ₘ', n: 'ₙ', p: 'ₚ', s: 'ₛ', t: 'ₜ' }
function supsub(runs) {
  return runs.map(r => {
    const m = r.sup ? SUP : r.sub ? SUB : null
    if (!m) return r
    let out = ''
    for (const ch of r.t) { if (!m[ch]) return r; out += m[ch] }
    return { ...r, t: out }
  })
}

function Runs({ runs, black, style }) {
  runs = supsub(runs)
  return <span style={style}>{runs.map((r, i) => (
    <span key={i} style={{ fontWeight: r.b ? 900 : undefined, fontStyle: r.i ? 'italic' : undefined, whiteSpace: 'pre-wrap' }}>{r.t}</span>
  ))}</span>
}
const itemRuns = it => Array.isArray(it) ? it : it.lines.flatMap((l, i) => (i ? [{ t: '\n' }] : []).concat(l))

function Ph({ b, T }) {
  if (b.svg) {
    const esc = x => x.replace(/&/g, '&amp;').replace(/</g, '&lt;')
    const txt = (b.labels || []).map(L => `<text x="${L.x}" y="${L.y}" font-size="${L.size}" text-anchor="${L.anchor}" fill="${L.fill}" font-family="Avenir, Helvetica, Arial, sans-serif"${L.b ? ' font-weight="800"' : ''}${L.i ? ' font-style="italic"' : ''}${L.rot ? ` transform="rotate(${L.rot} ${L.rx ?? L.x} ${L.ry ?? L.y})"` : ''}>${esc(L.t)}</text>`).join('')
    const html = b.svg.replace('<svg ', '<svg style="width:100%;height:100%;display:block" ').replace(/<\/svg>\s*$/, txt + '</svg>')
    return <div title="Generated diagram" style={{ width: b.w, height: b.h }} dangerouslySetInnerHTML={{ __html: html }} />
  }
  return <div style={{ width: b.w, height: b.h, background: T.placeholder, border: '1px dashed #9AA6BA', boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: AV, fontWeight: 800, fontSize: 10, letterSpacing: 1, color: '#6B778C', overflow: 'hidden' }}>{b.h >= 40 && b.w >= 90 ? 'IMAGE PLACEHOLDER' : ''}</div>
}

function Block({ b, T }) {
  const base = { fontFamily: AV, ...TY('body'), color: T.text, fontWeight: 500 }
  switch (b.t) {
    case 'title': return (
      <div style={{ paddingBottom: b.eyebrow ? 6 : 4, display: 'flex', flexDirection: 'column', gap: b.eyebrow ? 4 : 2 }}>
        {b.eyebrow && <div style={{ fontFamily: DIN, fontWeight: 700, ...TY('eyebrow'), color: T.primary, textTransform: cssCase('eyebrow') }}>{tc(b.eyebrow, 'eyebrow')}</div>}
        <div style={{ fontFamily: DIN, fontWeight: 700, ...TY('title'), color: T.strong }}>{tc(b.text)}</div>
      </div>)
    case 'h': {
      const st = { 2: { fontFamily: DIN, fontWeight: 700, ...TY('h2') }, 3: { fontFamily: AV, fontWeight: 900, ...TY('h3') }, 4: { fontFamily: AV, fontWeight: 900, ...TY('h4') }, 5: { fontFamily: AV, fontWeight: 800, ...TY('h5') } }[b.lvl]
      return <div style={{ ...st, color: T.strong }}>{b.lvl === 3 ? tc(b.text, 'h3') : b.lvl === 2 ? tc(b.text, 'h2') : b.text}</div>
    }
    case 'p': return <div style={base}><Runs runs={b.runs} /></div>
    case 'note': {
      const full = b.runs.map(r => r.t).join(''), c = full.indexOf(':')
      const runs = (!b.muted && c > 0 && c < 80 && !b.runs.some(r => r.b)) ? [{ t: full.slice(0, c + 1), b: 1 }, { t: full.slice(c + 1) }] : b.runs
      return <div style={base}><Runs runs={runs} /></div>
    }
    case 'ul': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 6 }}>
            <span style={{ fontFamily: AV, fontWeight: b.mark === '✓' ? 500 : 800, ...TY(b.mark === '✓' ? 'body' : 'mark'), color: colorOf(T, comp('bullets').markColor, T.primary) }}>{b.mark}</span>
            <div style={{ ...base, flex: 1 }}><Runs runs={itemRuns(it)} /></div>
          </div>))}
      </div>)
    case 'ol': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 4 }}>
            <span style={{ fontFamily: AV, fontWeight: 800, ...TY('body'), color: T.primary, minWidth: 18 }}>{it.label}</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>{it.lines.map((l, j) => <div key={j} style={base}><Runs runs={l} /></div>)}</div>
          </div>))}
      </div>)
    case 'table': {
      const hasHead = b.head && b.head.length > 0
      const rows = hasHead ? [b.head, ...b.rows] : b.rows
      const ts = comp('table')
      return <div>{rows.map((r, ri) => {
        const isHead = hasHead && ri === 0, k = hasHead ? ri : ri + 1
        return (
          <div key={ri} style={{ display: 'flex' }}>
            {r.map((c, ci) => <div key={ci} style={{ width: b.widths[ci], boxSizing: 'border-box', padding: '6px 9px', border: `1px solid ${T.tableBorder}`, marginTop: ri ? -1 : 0, marginLeft: ci ? -1 : 0, background: isHead ? colorOf(T, ts.headFill, T.primary) : (ts.zebra === false || k % 2 === 1) ? T.white : T.tableAlt, color: isHead ? colorOf(T, ts.headText, T.onPrimary) : T.text, fontFamily: AV, ...TY('body'), fontWeight: isHead ? 900 : 500, whiteSpace: 'pre-wrap' }}>{c}</div>)}
          </div>)
      })}</div>
    }
    case 'callout': {
      const cc = b.variant === 'keyideas' ? { bg: T.tint, fg: T.primary } : T[b.variant]
      return (
        <div style={{ background: cc.bg, borderRadius: comp('callout').radius ?? 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 5 }}>
          <div style={{ fontFamily: AV, fontWeight: 900, ...TY('body'), color: cc.fg }}>{b.title}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>{b.blocks.map((x, i) => <Block key={i} b={x} T={T} />)}</div>
        </div>)
    }
    case 'formula': return <div style={{ background: colorOf(T, comp('formula').fill, T.primary), color: colorOf(T, comp('formula').text, T.onPrimary), borderRadius: 6, padding: 12, textAlign: 'center', fontFamily: AV, fontWeight: 800, fontSize: 13, lineHeight: '17.8px' }}>{b.text}</div>
    case 'image': return (
      <div style={{ display: 'flex', justifyContent: b.w <= 360 ? 'flex-start' : 'center' }}>
        <Ph b={b} T={T} />
      </div>)
    case 'imagerow': return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{b.items.map((it, i) => <Ph key={i} b={it} T={T} />)}</div>
    case 'qcard': { const qs = comp('qcard'); return (
      <div style={{ borderRadius: qs.radius ?? 8, overflow: 'hidden' }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 4, padding: padCss(qs, 7.5), background: colorOf(T, qs.fill, T.white) }}>
            <span style={{ fontFamily: AV, fontWeight: 800, ...TY('body'), color: qs.numberColor ? colorOf(T, qs.numberColor, T.primary) : (qs.fill === 'none' && PAGE_ST.dark ? PAGE_ST.fg : T.primary), minWidth: 18 }}>{it.label}</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>{it.lines.map((l, j) => <div key={j} style={{ ...base, color: cardText(T, qs, T.text) }}><Runs runs={l} /></div>)}{it.pics?.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{it.pics.map((q, j) => <Ph key={j} b={q} T={T} />)}</div>}</div>
          </div>))}
      </div>) }
    case 'mcq': { const ms = comp('mcq'); const nc = b.columns || ms.columns || 2; return (
      <div style={{ background: colorOf(T, ms.fill, T.white), borderRadius: ms.radius ?? 8, padding: padCss(ms, 12, 2 / 3), display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ ...base, fontWeight: 800, color: (ms.textColor || (ms.fill === 'none' && PAGE_ST.dark)) ? cardText(T, ms, T.strong) : T.strong }}><b style={{ fontWeight: 800 }}>{b.n} </b><Runs runs={b.stem} style={{ fontWeight: 800 }} /></div>
        {Array.from({ length: Math.ceil(b.options.length / nc) }).map((_, r) => (
          <div key={r} style={{ display: 'flex', gap: 12 }}>
            {b.options.slice(r * nc, r * nc + nc).map((o, i) => <div key={i} style={{ ...base, flex: 1, color: cardText(T, ms, T.text) }}><Runs runs={o.runs} /></div>)}
            {nc === 2 && b.options.slice(r * 2, r * 2 + 2).length === 1 && <div style={{ flex: 1 }} />}
          </div>))}
      </div>) }
    case 'ans': { const as_ = comp('ans'); return (
      <div style={{ borderRadius: as_.radius ?? 8, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 1 }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex' }}>
            <div style={{ width: 33, background: colorOf(T, as_.tabFill, T.primary), color: T.onPrimary, fontFamily: AV, fontWeight: 800, ...TY('body'), textAlign: 'center', padding: '5.25px 4px', boxSizing: 'border-box' }}>{it.label}</div>
            <div style={{ flex: 1, background: colorOf(T, as_.fill, T.white), padding: padCss(as_, 7.5), display: 'flex', flexDirection: 'column', gap: 3 }}>{it.blocks.map((x, j) => <div key={j} style={{ ...base, color: cardText(T, as_, T.text) }}><Runs runs={x.runs} /></div>)}{it.pics?.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{it.pics.map((q, j) => <Ph key={j} b={q} T={T} />)}</div>}</div>
          </div>))}
      </div>) }
    case 'toc': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: b.compact ? 4 : 10 }}>
        {!b.cont && <>
          {b.eyebrow && <div style={{ fontFamily: DIN, fontWeight: 700, ...TY('eyebrow'), color: T.primary, textTransform: cssCase('eyebrow') }}>{tc(b.eyebrow, 'eyebrow')}</div>}
          <div style={{ fontFamily: DIN, fontWeight: 700, ...TY('title'), color: T.onDark ? T.strong : '#000' }}>{tc(b.title)}</div>
          <div style={{ fontFamily: DIN, fontWeight: 700, ...TY('eyebrow'), color: T.onDark ? T.strong : '#000' }}>{b.chapter_line ? tc(b.chapter_line, 'toc') : `Chapter ${b.chapter_no ? b.chapter_no + ' - ' : ''}${tc(b.chapter, 'toc')}`}</div>
        </>}
        {b.entries.map((e, i) => (
          <div key={i} style={{ borderBottom: `1px solid ${T.rule}`, padding: b.compact ? '4px 0' : '8px 0', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {e.title ? <>
              <div style={{ fontFamily: LY.type.toc.size >= 14 ? DIN : AV, fontWeight: LY.type.toc.size >= 14 ? 700 : 800, ...TY('toc'), color: T.primary }}>{tc(e.label, 'toc')}</div>
              <div style={{ display: 'flex', alignItems: 'flex-end' }}><span style={{ ...base, flex: 1 }}>{e.title}</span><span style={{ fontFamily: AV, fontWeight: 900, fontSize: LY.type.mark.size, color: T.primary }}>{e.page ?? ''}</span></div>
            </> : <div style={{ display: 'flex', alignItems: 'flex-end' }}><span style={{ fontFamily: LY.type.toc.size >= 14 ? DIN : AV, fontWeight: LY.type.toc.size >= 14 ? 700 : 800, ...TY('toc'), color: T.primary, flex: 1 }}>{tc(e.label, 'toc')}</span><span style={{ fontFamily: AV, fontWeight: 900, fontSize: LY.type.mark.size, color: T.primary }}>{e.page ?? ''}</span></div>}
          </div>))}
      </div>)
    case 'end': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center', textAlign: 'center' }}>
        <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 16, letterSpacing: 1, color: T.primary }}>{/^module/i.test(b.module || '') ? b.module : 'MODULE ' + (b.module || '')}</div>
        <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 34, lineHeight: '40.8px', color: T.strong }}>End of Chapter</div>
        <div style={{ width: 120, height: 2, background: T.primary }} />
        <div style={{ ...base }}>{[tc(b.chapter), [b.grade ? 'Grade ' + b.grade : '', b.subject].filter(Boolean).join(' ')].filter(Boolean).join(' · ')}</div>
      </div>)
    default: return <div style={{ color: 'red' }}>Unknown block {b.t}</div>
  }
}

export function Page({ page, theme: T, meta, scale = 1 }) {
  LY = T.layout || LY0
  useStyleFonts(T)
  const pst = pageStyle(page, T)
  const darkT = pst.dark ? { ...T, onDark: true, text: pst.fg, strong: pst.fg, primary: pst.fg, rule: pst.rule } : T
  CASE_RULES = T.caseRules || {}; ACR = new Set(T.acronyms || [])
  THEME_COMP = T.components || {}; COMP = page.components || {}; PAGE_ST = pst
  const end = page.kind === 'end'
  return (
    <div style={{ width: LY.page.w * scale, height: LY.page.h * scale }}>
      <div style={{ width: LY.page.w, height: LY.page.h, transform: `scale(${scale})`, transformOrigin: 'top left', position: 'relative', background: pst.bg, overflow: 'hidden', boxShadow: '0 0 0 1px rgba(0,0,0,.08)' }}>
        {page.pill && <>
          <div style={{ position: 'absolute', left: LY.header.ruleX, top: LY.header.ruleY, width: LY.header.ruleW, height: 1, background: pst.rule }} />
          <div style={{ position: 'absolute', left: LY.header.pillX, top: LY.header.pillY, width: LY.header.pillW, height: LY.header.pillH, boxSizing: 'border-box', background: pst.pillBg, borderRadius: LY.header.pillH, padding: '3px 9px', color: pst.pillFg, fontFamily: AV, fontWeight: 500, fontSize: LY.header.pillSize, lineHeight: (LY.header.pillSize * 1.37) + 'px', letterSpacing: .35, textTransform: CASE_RULES.pill === 'ORIGINAL' ? 'none' : 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textAlign: 'center' }}>{page.pill}</div>
        </>}
        <div style={{ position: 'absolute', left: LY.footer.ruleX, top: LY.footer.ruleY, width: LY.footer.ruleW, height: 1, background: T.footerRule }} />
        <div style={{ position: 'absolute', left: LY.footer.textX, top: LY.footer.textY, fontFamily: AV, fontWeight: 500, fontSize: LY.footer.textSize, lineHeight: (LY.footer.textSize * 1.36) + 'px', color: pst.dark ? '#fff' : '#000' }}>{meta.footer}</div>
        {page.pageNo != null && <div style={{ position: 'absolute', left: LY.footer.numX, width: 40, top: LY.footer.numY, textAlign: 'right', fontFamily: AV, fontWeight: 900, fontSize: LY.footer.numSize, lineHeight: (LY.footer.numSize * 1.36) + 'px', color: pst.dark ? '#fff' : T.primary }}>{page.pageNo}</div>}
        <div style={{ position: 'absolute', left: 0, top: end ? 0 : LY.col.top, width: LY.page.w, height: end ? LY.page.h : undefined, padding: `0 ${LY.page.w - LY.col.x - LY.col.w}px 0 ${LY.col.x}px`, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', justifyContent: end ? 'center' : undefined }}>
          {page.blocks.map((b, i) => <div key={i} style={{ marginTop: b.gap || 0 }}><Block b={b} T={TEXT_ON_PAGE.has(b.t) ? darkT : T} /></div>)}
        </div>
      </div>
    </div>
  )
}
