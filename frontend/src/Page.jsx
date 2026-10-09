// Renders a page spec as DOM. Mirrors figma-plugin/code.js so the preview matches what gets built in Figma.
import React from 'react'

const AV = "Avenir, 'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
const DIN = "'DIN Condensed', 'Arial Narrow', Impact, sans-serif"

const titleCase = s => s.toLowerCase().replace(/(^|[\s\-(])([a-z])/g, (m, a, b) => a + b.toUpperCase())
const tc = s => s.replace(/(^|[\s\-(])(\S)/g, (m, a, b) => a + b.toUpperCase()).replace(/\b([A-Z])([A-Z]+)\b/g, (m, a, b) => a + b.toLowerCase())

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
    const html = b.svg.replace('<svg ', '<svg style="width:100%;height:100%;display:block" ')
    return <div title="Generated diagram" style={{ width: b.w, height: b.h }} dangerouslySetInnerHTML={{ __html: html }} />
  }
  return <div style={{ width: b.w, height: b.h, background: T.placeholder, border: '1px dashed #9AA6BA', boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: AV, fontWeight: 800, fontSize: 10, letterSpacing: 1, color: '#6B778C', overflow: 'hidden' }}>{b.h >= 40 && b.w >= 90 ? 'IMAGE PLACEHOLDER' : ''}</div>
}

function Block({ b, T }) {
  const base = { fontFamily: AV, fontSize: 11, lineHeight: '15px', color: T.text, fontWeight: 500 }
  switch (b.t) {
    case 'title': return (
      <div style={{ paddingBottom: b.eyebrow ? 6 : 4, display: 'flex', flexDirection: 'column', gap: b.eyebrow ? 4 : 2 }}>
        {b.eyebrow && <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 20, lineHeight: '24px', color: T.primary, textTransform: b.eyebrow === b.eyebrow.toUpperCase() ? 'none' : 'capitalize' }}>{b.eyebrow}</div>}
        <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 42, lineHeight: '50.4px', color: T.strong }}>{tc(b.text)}</div>
      </div>)
    case 'h': {
      const st = { 2: { fontFamily: DIN, fontWeight: 700, fontSize: 18, lineHeight: '21.6px' }, 3: { fontFamily: AV, fontWeight: 900, fontSize: 13, lineHeight: '17.8px' }, 4: { fontFamily: AV, fontWeight: 900, fontSize: 11, lineHeight: '15px' }, 5: { fontFamily: AV, fontWeight: 800, fontSize: 11, lineHeight: '15px' } }[b.lvl]
      return <div style={{ ...st, color: T.strong }}>{b.lvl === 3 ? tc(b.text) : b.text}</div>
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
            <span style={{ fontFamily: AV, fontWeight: b.mark === '✓' ? 500 : 800, fontSize: b.mark === '✓' ? 11 : 10, lineHeight: b.mark === '✓' ? '15px' : '13.7px', color: T.primary }}>{b.mark}</span>
            <div style={{ ...base, flex: 1 }}><Runs runs={itemRuns(it)} /></div>
          </div>))}
      </div>)
    case 'ol': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 4 }}>
            <span style={{ fontFamily: AV, fontWeight: 800, fontSize: 11, lineHeight: '15px', color: T.primary, minWidth: 18 }}>{it.label}</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>{it.lines.map((l, j) => <div key={j} style={base}><Runs runs={l} /></div>)}</div>
          </div>))}
      </div>)
    case 'table': {
      const hasHead = b.head && b.head.length > 0
      const rows = hasHead ? [b.head, ...b.rows] : b.rows
      return <div>{rows.map((r, ri) => {
        const isHead = hasHead && ri === 0, k = hasHead ? ri : ri + 1
        return (
          <div key={ri} style={{ display: 'flex' }}>
            {r.map((c, ci) => <div key={ci} style={{ width: b.widths[ci], boxSizing: 'border-box', padding: '6px 9px', border: `1px solid ${T.tableBorder}`, marginTop: ri ? -1 : 0, marginLeft: ci ? -1 : 0, background: isHead ? T.primary : k % 2 === 1 ? T.white : T.tableAlt, color: isHead ? T.onPrimary : T.text, fontFamily: AV, fontSize: 11, lineHeight: '15px', fontWeight: isHead ? 900 : 500, whiteSpace: 'pre-wrap' }}>{c}</div>)}
          </div>)
      })}</div>
    }
    case 'callout': {
      const cc = b.variant === 'keyideas' ? { bg: T.tint, fg: T.primary } : T[b.variant]
      return (
        <div style={{ background: cc.bg, borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 5 }}>
          <div style={{ fontFamily: AV, fontWeight: 900, fontSize: 11, lineHeight: '15px', color: cc.fg }}>{b.title}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>{b.blocks.map((x, i) => <Block key={i} b={x} T={T} />)}</div>
        </div>)
    }
    case 'formula': return <div style={{ background: T.primary, color: T.onPrimary, borderRadius: 6, padding: 12, textAlign: 'center', fontFamily: AV, fontWeight: 800, fontSize: 13, lineHeight: '17.8px' }}>{b.text}</div>
    case 'image': return (
      <div style={{ display: 'flex', justifyContent: b.w <= 360 ? 'flex-start' : 'center' }}>
        <Ph b={b} T={T} />
      </div>)
    case 'imagerow': return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{b.items.map((it, i) => <Ph key={i} b={it} T={T} />)}</div>
    case 'qcard': return (
      <div style={{ borderRadius: 8, overflow: 'hidden' }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 4, padding: '5.25px 7.5px', background: T.white }}>
            <span style={{ fontFamily: AV, fontWeight: 800, fontSize: 11, lineHeight: '15px', color: T.primary, minWidth: 18 }}>{it.label}</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>{it.lines.map((l, j) => <div key={j} style={base}><Runs runs={l} /></div>)}{it.pics?.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{it.pics.map((q, j) => <Ph key={j} b={q} T={T} />)}</div>}</div>
          </div>))}
      </div>)
    case 'mcq': return (
      <div style={{ background: T.white, borderRadius: 8, padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ ...base, fontWeight: 800, color: T.strong }}><b style={{ fontWeight: 800 }}>{b.n} </b><Runs runs={b.stem} style={{ fontWeight: 800 }} /></div>
        {Array.from({ length: Math.ceil(b.options.length / 2) }).map((_, r) => (
          <div key={r} style={{ display: 'flex', gap: 12 }}>
            {b.options.slice(r * 2, r * 2 + 2).map((o, i) => <div key={i} style={{ ...base, flex: 1 }}><Runs runs={o.runs} /></div>)}
            {b.options.slice(r * 2, r * 2 + 2).length === 1 && <div style={{ flex: 1 }} />}
          </div>))}
      </div>)
    case 'ans': return (
      <div style={{ borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 1 }}>
        {b.items.map((it, i) => (
          <div key={i} style={{ display: 'flex' }}>
            <div style={{ width: 33, background: T.primary, color: T.onPrimary, fontFamily: AV, fontWeight: 800, fontSize: 11, lineHeight: '15px', textAlign: 'center', padding: '5.25px 4px', boxSizing: 'border-box' }}>{it.label}</div>
            <div style={{ flex: 1, background: T.white, padding: '5.25px 7.5px', display: 'flex', flexDirection: 'column', gap: 3 }}>{it.blocks.map((x, j) => <div key={j} style={base}><Runs runs={x.runs} /></div>)}{it.pics?.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{it.pics.map((q, j) => <Ph key={j} b={q} T={T} />)}</div>}</div>
          </div>))}
      </div>)
    case 'toc': return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 42, lineHeight: '50.4px', color: '#000' }}>{tc(b.title)}</div>
        <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 20, lineHeight: '24px', color: '#000' }}>{b.chapter_line ? tc(b.chapter_line) : `Chapter ${b.chapter_no ? b.chapter_no + ' - ' : ''}${tc(b.chapter)}`}</div>
        {b.entries.map((e, i) => (
          <div key={i} style={{ borderBottom: `1px solid ${T.rule}`, padding: '8px 0', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {e.title ? <>
              <div style={{ fontFamily: DIN, fontWeight: 700, fontSize: 18, lineHeight: '21.6px', color: T.primary }}>{tc(e.label)}</div>
              <div style={{ display: 'flex', alignItems: 'flex-end' }}><span style={{ ...base, flex: 1 }}>{e.title}</span><span style={{ fontFamily: AV, fontWeight: 900, fontSize: 10, color: T.primary }}>{e.page ?? ''}</span></div>
            </> : <div style={{ display: 'flex', alignItems: 'flex-end' }}><span style={{ fontFamily: DIN, fontWeight: 700, fontSize: 18, lineHeight: '21.6px', color: T.primary, flex: 1 }}>{tc(e.label)}</span><span style={{ fontFamily: AV, fontWeight: 900, fontSize: 10, color: T.primary }}>{e.page ?? ''}</span></div>}
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
  const end = page.kind === 'end'
  return (
    <div style={{ width: 595 * scale, height: 842 * scale }}>
      <div style={{ width: 595, height: 842, transform: `scale(${scale})`, transformOrigin: 'top left', position: 'relative', background: page.bg === 'tint' ? T.tint : T.white, overflow: 'hidden', boxShadow: '0 0 0 1px rgba(0,0,0,.08)' }}>
        {page.pill && <>
          <div style={{ position: 'absolute', left: 35, top: 40, width: 372, height: 1, background: T.rule }} />
          <div style={{ position: 'absolute', left: 417, top: 33, width: 142, height: 16, boxSizing: 'border-box', background: T.primary, borderRadius: 16, padding: '3px 9px', color: T.onPrimary, fontFamily: AV, fontWeight: 500, fontSize: 7, lineHeight: '9.6px', letterSpacing: .35, textTransform: 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textAlign: 'center' }}>{page.pill}</div>
        </>}
        <div style={{ position: 'absolute', left: 35, top: 801, width: 525, height: 1, background: T.footerRule }} />
        <div style={{ position: 'absolute', left: 35, top: 813, fontFamily: AV, fontWeight: 500, fontSize: 8, lineHeight: '10.9px', color: '#000' }}>{meta.footer}</div>
        {page.pageNo != null && <div style={{ position: 'absolute', left: 520, width: 40, top: 814, textAlign: 'right', fontFamily: AV, fontWeight: 900, fontSize: 8, lineHeight: '10.9px', color: T.primary }}>{page.pageNo}</div>}
        <div style={{ position: 'absolute', left: 0, top: end ? 0 : 64, width: 595, height: end ? 842 : undefined, padding: '0 40px', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', justifyContent: end ? 'center' : undefined }}>
          {page.blocks.map((b, i) => <div key={i} style={{ marginTop: b.gap || 0 }}><Block b={b} T={T} /></div>)}
        </div>
      </div>
    </div>
  )
}
