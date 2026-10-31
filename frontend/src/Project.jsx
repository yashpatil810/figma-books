import React, { useEffect, useState, useCallback, useRef } from 'react'
import { api } from './api.js'
import { Page } from './Page.jsx'

function usePoll(fn, active, ms = 1500) {
  useEffect(() => { if (!active) return; const t = setInterval(fn, ms); return () => clearInterval(t) }, [active, fn, ms])
}

// ------------------------------------------------------------------ Reference Figma (style source)
function ReferenceCard({ p, reload }) {
  const [url, setUrl] = useState(p.reference?.url || '')
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(async () => { const x = await api(`/projects/${p.id}/reference`); setD(x); return x }, [p.id])
  useEffect(() => { load().catch(() => {}) }, [load])
  const running = d?.job?.state === 'running'
  usePoll(async () => { const x = await load(); if (x.job?.state !== 'running') reload() }, running, 2000)
  const ref = d?.reference
  const go = async () => { setErr(''); try { await api(`/projects/${p.id}/reference`, { method: 'PUT', body: { url } }); await api(`/projects/${p.id}/reference/read`, { method: 'POST' }); await load() } catch (e) { setErr(e.message) } }
  const clear = async () => { setErr(''); try { await api(`/projects/${p.id}/reference`, { method: 'PUT', body: { url: '' } }); setUrl(''); await load(); reload() } catch (e) { setErr(e.message) } }
  const swatches = ref?.theme ? Object.entries(ref.theme) : []
  return (
    <div className="card">
      <h2>Reference design <span className="muted small">(optional)</span></h2>
      <div className="muted small" style={{ marginBottom: 8 }}>Paste a link to a Figma file, page or section that looks the way you want the book to look (select it in Figma, right-click, Copy link). The app reads its colours, text styles and capitalisation once and uses them as your starting point on the next screen, where you can change anything. Without a link, the default style is used.</div>
      <div className="row" style={{ gap: 8 }}>
        <input type="url" style={{ flex: 1 }} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.figma.com/design/…?node-id=…" />
        <button className="btn primary" disabled={running || !url.trim()} onClick={go}>{running ? 'Reading…' : ref?.pages_read ? '↻ Read again' : 'Read the reference'}</button>
        {ref && <button className="btn" disabled={running} onClick={clear}>Remove</button>}
      </div>
      {running && <div style={{ marginTop: 8 }}><div className="small muted">{d.job.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (d.job.progress || 0) * 100)}%` }} /></div></div>}
      {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
      {d?.job?.state === 'failed' && <div className="banner err" style={{ marginTop: 8 }}>{d.job.error || d.job.message}</div>}
      {ref?.pages_read > 0 && <div style={{ marginTop: 10 }}>
        <div className="small"><b>Read {ref.pages_read} pages</b> from “{ref.name}”. {ref.page_size ? `Page ${ref.page_size[0]}×${ref.page_size[1]}. ` : ''}Colours found:</div>
        <div className="row" style={{ gap: 6, margin: '6px 0', flexWrap: 'wrap' }}>{swatches.map(([k, v]) => <span key={k} className="small" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><i style={{ width: 14, height: 14, background: v, border: '1px solid #0002', borderRadius: 3, display: 'inline-block' }} />{k}</span>)}</div>
        {ref.notes?.map((n, i) => <div key={i} className="small muted">• {n}</div>)}
        <div className="small muted" style={{ marginTop: 4 }}>Next: Colours &amp; samples shows these colours so you can adjust them.</div>
      </div>}
    </div>)
}

// Progress of Claude's automatic reading of the document (starts as soon as the doc is fetched)
function StructureStatus({ p, reload, goto }) {
  const j = p.structure_job || {}
  usePoll(reload, j.state === 'running', 2500)
  return (
    <div className="card">
      <h2>Reading the document</h2>
      {j.state === 'running' && <><div className="small muted">{j.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (j.progress || 0) * 100)}%` }} /></div></>}
      {j.state === 'failed' && <div className="banner err">Claude could not read the document: {j.error || j.message}. <button className="btn" style={{ marginLeft: 8 }} onClick={() => api(`/projects/${p.id}/structure/read?force=true`, { method: 'POST' }).then(reload)}>Try again</button></div>}
      {j.state !== 'running' && j.state !== 'failed' && p.has_structure && <div className="small">Claude has read the whole document and worked out its structure (index, sections, exercises, answer keys). <button className="btn" style={{ marginLeft: 8 }} onClick={() => goto('structure')}>See the structure</button></div>}
      {j.state !== 'running' && j.state !== 'failed' && !p.has_structure && <div className="small muted">Not read yet. <button className="btn" style={{ marginLeft: 8 }} onClick={() => api(`/projects/${p.id}/structure/read`, { method: 'POST' }).then(reload)}>Read now</button></div>}
    </div>)
}

// ------------------------------------------------------------------ Setup
function Setup({ p, reload, goto }) {
  const [meta, setMeta] = useState(p.meta)
  const [busy, setBusy] = useState(false)
  const [sum, setSum] = useState(null)
  const [err, setErr] = useState('')
  const set = k => e => setMeta({ ...meta, [k]: e.target.value })
  const save = async () => { await api(`/projects/${p.id}/meta`, { method: 'PUT', body: { meta } }); reload() }
  const refetch = async () => { setBusy(true); setErr(''); try { setSum(await api(`/projects/${p.id}/fetch`, { method: 'POST' })); reload() } catch (e) { setErr(e.message) } finally { setBusy(false) } }
  useEffect(() => { if (p.has_doc && !sum) api(`/projects/${p.id}/spec`).then(s => setSum({ pages: s.pages.length, meta: s.meta })).catch(() => {}) }, [])
  return (
    <>
    <div className="card">
      <h2>Document</h2>
      <div className="small muted" style={{ wordBreak: 'break-all' }}>{p.doc_url}</div>
      {p.mode === 'audit' && <div className="small muted" style={{ wordBreak: 'break-all' }}>Figma: {p.figma_url}</div>}
      <div className="grid2">
        <div><label>Subject</label><input type="text" value={meta.subject || ''} onChange={set('subject')} /></div>
        <div><label>Module / chapter number</label><input type="text" value={meta.module || ''} onChange={set('module')} /></div>
        <div><label>Grade (read from the doc: {p.meta.grade || '—'})</label><input type="text" value={meta.grade || ''} onChange={set('grade')} /></div>
        <div><label>Footer text (blank = “Grade {'{grade}'} - {'{subject}'} - Module {'{n}'}”)</label><input type="text" value={meta.footer || ''} onChange={set('footer')} /></div>
      </div>
      {err && <div className="banner err" style={{ marginTop: 10 }}>{err}</div>}
      {sum && <div className="banner info" style={{ marginTop: 10 }}>Chapter “{sum.meta?.chapter_title}” read from the doc{sum.blocks ? ` · ${sum.blocks} blocks, ${sum.images} images, ${sum.tables} tables` : ''}{sum.pages ? ` · ${sum.pages} pages when laid out` : ''}.</div>}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={async () => { await save(); goto(p.mode === 'audit' ? 'review' : 'design') }}>Save and continue</button>
        <button className="btn" onClick={save}>Save</button>
        <button className="btn" disabled={busy} onClick={refetch}>{busy ? 'Reading…' : 'Re-read the doc'}</button>
      </div>
    </div>
    {p.mode !== 'audit' && <ReferenceCard p={p} reload={reload} />}
    {p.has_doc && p.mode !== 'audit' && <StructureStatus p={p} reload={reload} goto={goto} />}
    </>)
}

// ------------------------------------------------------------------ Design (colours + samples)
const KEYS = ['primary', 'text', 'strong', 'tint', 'white', 'rule', 'footerRule', 'tableAlt', 'tableBorder', 'onPrimary']
const PAGE_TYPES = [['index', 'Index'], ['body', 'Teaching content'], ['exercise', 'Exercise'], ['worksheet', 'Worksheet'], ['answers', 'Answer key'], ['mindmap', 'Mind map'], ['references', 'References'], ['glossary', 'Glossary'], ['end', 'End page']]
const CASE_LABELS = { eyebrow: 'Eyebrow (small line above a title)', title: 'Page and section titles', h2: 'Heading 2', h3: 'Heading 3', toc: 'Index entries', pill: 'Header pill' }
const CASE_DEFAULTS = { eyebrow: 'ORIGINAL', title: 'TITLE', h2: 'ORIGINAL', h3: 'TITLE', toc: 'TITLE', pill: 'UPPER' }
const PAIRS = [['misc', 'Common Misconceptions'], ['iit', 'IIT Foundation'], ['dyk', 'Did You Know?']]

function Sw({ theme, setC, k, label, sub }) {
  const v = sub ? theme[k][sub] : theme[k]
  const [txt, setTxt] = useState(v)
  useEffect(() => { setTxt(v) }, [v])
  return (
    <div className="swatch">
      <input type="color" value={v} onChange={e => setC(k, e.target.value.toUpperCase(), sub)} />
      <input type="text" value={txt} onChange={e => { setTxt(e.target.value); if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) setC(k, e.target.value.toUpperCase(), sub) }} />
      <span>{label}</span>
    </div>)
}

function Design({ p, reload, goto }) {
  const [theme, setTheme] = useState(p.theme)
  const [samples, setSamples] = useState(null)
  const [rules, setRules] = useState(null)
  const [tab, setTab] = useState('samples')
  const [dirty, setDirty] = useState(false)
  const [approved, setApproved] = useState(p.samples_approved)
  const [edit, setEdit] = useState('')
  const [labels, setLabels] = useState({})
  const [lay, setLay] = useState(null)
  const refRunning = p.reference_job?.state === 'running'
  usePoll(reload, refRunning, 2500)
  useEffect(() => { api(`/projects/${p.id}/samples`).then(setSamples); api(`/projects/${p.id}/rules`).then(r => { setRules(r); setEdit(r.prompt); setLabels(r.labels); setLay({ def: r.layout_default, names: r.type_labels, cur: r.layout }) }) }, [p.id, p.theme?.name])
  useEffect(() => { if (!dirty) { setTheme(p.theme); setApproved(p.samples_approved) } }, [p.theme?.name, p.reference?.pages_read])
  const setC = (k, v, sub) => { setDirty(true); setApproved(false); setTheme(sub ? { ...theme, [k]: { ...theme[k], [sub]: v } } : { ...theme, [k]: v }) }
  const save = async () => { await api(`/projects/${p.id}/theme`, { method: 'PUT', body: theme }); setDirty(false); const r = await api(`/projects/${p.id}/rules`); setRules(r); setEdit(r.prompt); reload() }
  const approve = async () => { if (dirty) await save(); await api(`/projects/${p.id}/approve-samples?approved=true`, { method: 'POST' }); setApproved(true); reload() }
  return (
    <div>
      {refRunning && <div className="banner info" style={{ marginBottom: 10 }}>Reading your reference design… {p.reference_job.message} The colours, fonts and page styles below will update when it finishes.<div className="bar"><i style={{ width: `${Math.max(5, (p.reference_job.progress || 0) * 100)}%` }} /></div></div>}
      {!refRunning && p.reference?.pages_read > 0 && <div className="banner info" style={{ marginBottom: 10 }}>Starting point taken from your reference design “{p.reference.name}”. Change anything below; to read the reference again go back to Setup.</div>}
      <div className="card">
        <h2>Colour scheme</h2>
        <div className="grid2">
          <div>{KEYS.slice(0, 5).map(k => <Sw key={k} theme={theme} setC={setC} k={k} label={labels[k] || k} />)}</div>
          <div>{KEYS.slice(5).map(k => <Sw key={k} theme={theme} setC={setC} k={k} label={labels[k] || k} />)}</div>
        </div>
        <label style={{ marginTop: 10 }}>Callout boxes (background / title colour)</label>
        <div className="grid2">{PAIRS.map(([k, l]) => <div key={k}><div className="small muted">{l}</div><Sw theme={theme} setC={setC} k={k} sub="bg" label="background" /><Sw theme={theme} setC={setC} k={k} sub="fg" label="title" /></div>)}</div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={!dirty} onClick={save}>Save colours</button>
          <button className="btn" onClick={() => { setTheme(p.theme); setDirty(false) }}>Revert</button>
        </div>
      </div>
      <div className="card">
        <h2>Page types</h2>
        <div className="muted small" style={{ marginBottom: 8 }}>Each kind of page can have its own background. Header pill, header line and text colours adjust automatically on dark backgrounds.</div>
        <div className="grid2">{PAGE_TYPES.map(([k, l]) => {
          const v = theme.pageTypes?.[k]?.bg || (k === 'body' ? theme.white : theme.tint)
          return <div key={k} className="swatch"><input type="color" value={v} onChange={e => { setDirty(true); setApproved(false); setTheme({ ...theme, pageTypes: { ...(theme.pageTypes || {}), [k]: { ...(theme.pageTypes?.[k] || {}), bg: e.target.value.toUpperCase() } } }) }} /><input type="text" value={v} readOnly /><span>{l}</span></div>
        })}</div>
      </div>
      {lay && <div className="card">
        <h2>Type scale and spacing</h2>
        <div className="muted small" style={{ marginBottom: 8 }}>Text sizes and line heights (in points) and the spacing between blocks. {p.reference?.pages_read > 0 ? 'Measured from your reference design; change any number.' : 'The app\'s defaults; change any number.'} Pages are laid out with these numbers.</div>
        {(() => {
          const L = { ...lay.cur, ...(theme.layout || {}), type: { ...lay.cur.type, ...(theme.layout?.type || {}) }, gap: { ...lay.cur.gap, ...(theme.layout?.gap || {}) } }
          const setT = (k, f, v) => { setDirty(true); setApproved(false); setTheme({ ...theme, layout: { ...L, type: { ...L.type, [k]: { ...L.type[k], [f]: parseFloat(v) || 0 } } } }) }
          const setG = (k, v) => { setDirty(true); setApproved(false); setTheme({ ...theme, layout: { ...L, gap: { ...L.gap, [k]: parseFloat(v) || 0 } } }) }
          const GAPN = { para: 'Between paragraphs', afterHeading: 'After a heading', beforeHeading: 'Before a large heading', beforeLabel: 'Before a small label', block: 'Around cards and tables', image: 'Around small pictures' }
          return <>
            <table className="t"><thead><tr><th>Text</th><th>Size</th><th>Line height</th></tr></thead><tbody>{Object.entries(lay.names).map(([k, n]) => <tr key={k}><td>{n}</td><td><input type="number" step="0.5" style={{ width: 70 }} value={L.type[k].size} onChange={e => setT(k, 'size', e.target.value)} /></td><td><input type="number" step="0.1" style={{ width: 70 }} value={L.type[k].lh} onChange={e => setT(k, 'lh', e.target.value)} /></td></tr>)}</tbody></table>
            <div className="grid2" style={{ marginTop: 10 }}>{Object.entries(GAPN).map(([k, n]) => <div key={k}><label>{n}</label><input type="number" step="1" style={{ width: 80 }} value={L.gap[k]} onChange={e => setG(k, e.target.value)} /></div>)}</div>
            <div className="small muted" style={{ marginTop: 8 }}>Page {L.page.w}×{L.page.h} · text column x {L.col.x}, width {L.col.w}, from y {L.col.top} to {L.col.bottom} · header line y {L.header.ruleY}, pill {L.header.pillW}×{L.header.pillH} · footer line y {L.footer.ruleY}</div>
            <div className="row" style={{ marginTop: 8 }}><button className="btn" onClick={() => { setDirty(true); setApproved(false); setTheme({ ...theme, layout: null }); setLay({ ...lay, cur: lay.def }) }}>Use the app's defaults</button></div>
          </>
        })()}
      </div>}
      <div className="card">
        <h2>Fonts</h2>
        <div className="muted small" style={{ marginBottom: 8 }}>The fonts used on the pages. Google Fonts are available in Figma by default. Leave blank to use the app's default fonts (Avenir and DIN Condensed). Page lengths are measured with the real fonts, so the font names must be spelled exactly as in Figma.</div>
        <div className="grid2">
          <div><label>Text font</label><input type="text" placeholder="Avenir (default)" value={theme.fonts?.text?.family || ''} onChange={e => { setDirty(true); setApproved(false); const f = { ...(theme.fonts || {}) }; if (e.target.value) f.text = { medium: 500, heavy: 800, black: 900, ...(f.text || {}), family: e.target.value }; else delete f.text; setTheme({ ...theme, fonts: f }) }} /></div>
          <div><label>Display font (titles)</label><input type="text" placeholder="DIN Condensed (default)" value={theme.fonts?.display?.family || ''} onChange={e => { setDirty(true); setApproved(false); const f = { ...(theme.fonts || {}) }; if (e.target.value) f.display = { weight: 700, ...(f.display || {}), family: e.target.value }; else delete f.display; setTheme({ ...theme, fonts: f }) }} /></div>
        </div>
      </div>
      <div className="card">
        <h2>Capitalisation</h2>
        <div className="muted small" style={{ marginBottom: 8 }}>How each kind of text is capitalised on the pages. The app applies this itself, so it still looks right if the doc is typed differently. Acronyms (IIT, NEET…) are never lowered. Only letter case changes, never the wording.</div>
        <div className="grid2">{Object.entries(CASE_LABELS).map(([k, l]) => <div key={k}><label>{l}</label>
          <select value={(theme.caseRules || {})[k] || CASE_DEFAULTS[k]} onChange={e => { setDirty(true); setApproved(false); setTheme({ ...theme, caseRules: { ...(theme.caseRules || {}), [k]: e.target.value } }) }}>
            <option value="ORIGINAL">Keep as typed in the doc</option><option value="TITLE">Title Case</option><option value="UPPER">UPPERCASE</option><option value="LOWER">lowercase</option>
          </select></div>)}</div>
        {p.reference?.typography?.length > 0 && <div style={{ marginTop: 12 }}><div className="small muted">Text styles found in the reference (for your information; the pages use the app's own fonts):</div>
          <table className="t"><thead><tr><th>Text</th><th>Font</th><th>Weight</th><th>Size</th></tr></thead><tbody>{p.reference.typography.map((x, i) => <tr key={i}><td>{x.role}</td><td>{x.font}</td><td>{x.weight}</td><td>{x.size}</td></tr>)}</tbody></table></div>}
      </div>
      <div className="tabs"><div className={'tab' + (tab === 'samples' ? ' on' : '')} onClick={() => setTab('samples')}>Sample pages</div><div className={'tab' + (tab === 'rules' ? ' on' : '')} onClick={() => setTab('rules')}>Design rules (prompt)</div></div>
      {tab === 'rules' && rules && <div className="card">
        <div className="muted small" style={{ marginBottom: 8 }}>Derived from the reference book and your colours. The AI review/judging steps receive this. {rules.custom ? 'You have customised it.' : ''}</div>
        <textarea style={{ minHeight: 420, fontFamily: 'ui-monospace,monospace', fontSize: 12 }} value={edit} onChange={e => setEdit(e.target.value)} />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn" onClick={async () => { const r = await api(`/projects/${p.id}/rules`, { method: 'PUT', body: { prompt: edit } }); setRules(r) }}>Save custom rules</button>
          <button className="btn" onClick={async () => { const r = await api(`/projects/${p.id}/rules`, { method: 'PUT', body: { prompt: null } }); setRules(r); setEdit(r.prompt) }}>Reset to generated</button>
        </div></div>}
      {tab === 'samples' && samples && <>
        <div className="banner info">Fixed sample content, one page for each kind of page in the book, in your colours. Check it, then approve to unlock the next step. Changing a colour resets the approval.</div>
        <div className="pages">{samples.pages.map((pg, i) => <div className="pg" key={i}><Page page={pg} theme={theme} meta={{ ...samples.meta, footer: p.meta.footer || `Grade ${p.meta.grade || ''} - ${p.meta.subject || 'Subject'} - Module ${p.meta.module || ''}` }} scale={0.55} /><div className="cap">{pg.label}</div></div>)}</div>
        <div className="row" style={{ margin: '14px 0' }}>
          {approved ? <><span className="ok-t">✓ Samples approved</span><button className="btn primary" onClick={() => goto('review')}>Continue to doc review →</button></> :
            <button className="btn ok" onClick={approve}>Approve these samples</button>}
        </div></>}
    </div>)
}

// ------------------------------------------------------------------ Review (scan + Q&A)
function FindingCard({ f, pid, onChange }) {
  const [note, setNote] = useState('')
  const [mode, setMode] = useState(null)
  const act = async (status, n) => { await api(`/projects/${pid}/findings/${f.id}`, { method: 'PATCH', body: { status, note: n ?? undefined } }); setMode(null); setNote(''); onChange() }
  const resolved = f.status !== 'open'
  const label = { done: 'Marked done', not_required: 'Not required', clarified: 'Clarified', auto: 'Skipped — handled automatically' }[f.status]
  return (
    <div className={`finding ${f.severity}${resolved ? ' resolved' : ''}`}>
      <div className="row" style={{ gap: 8 }}>
        <span className={`tag ${f.severity}`}>{f.severity === 'question' ? 'question' : f.severity}</span>
        {f.source === 'llm' && <span className="tag">AI review</span>}
        {!f.blocking && <span className="tag">non-blocking</span>}
        {resolved && <span className="tag" style={{ background: '#e4f5ea', color: 'var(--ok)' }}>{label}</span>}
        {f.doc_pages?.length > 0 && <span className="tag" style={{ background: '#fff4d6', color: '#7a5200' }}>Doc page {f.doc_pages.length > 2 ? `${f.doc_pages[0]}–${f.doc_pages[f.doc_pages.length - 1]}` : f.doc_pages.join(', ')}</span>}
        <span className="muted small">{f.blocks.slice(0, 3).join(', ')}</span>
      </div>
      <div style={{ margin: '6px 0' }}>{f.message}</div>
      {f.context?.map(c => <div className="ctx" key={c.id}><b className="small muted">{c.page ? `p.${c.page} · ` : ''}{c.id}</b> {c.text}</div>)}
      {f.suggestion && <div className="small"><b>Suggestion:</b> {f.suggestion}</div>}
      {f.fix?.length > 0 && (f.source === 'rule' || f.code === 'spelling') && <div className="small muted">Auto-fix available — applied only if you choose “Proceed anyway”.</div>}
      {f.fix?.length > 0 && f.source === 'llm' && f.code !== 'spelling' && <div className="small muted">Suggested wording is never applied automatically. Change it in the doc if you agree.</div>}
      {f.thread?.length > 0 && <div className="thread">{f.thread.map((m, i) => <div key={i} className={'msg ' + m.role}><b className="small">{m.role === 'app' ? 'Reviewer' : 'You'}:</b> {m.text}</div>)}</div>}
      {!resolved && !mode && <div className="row" style={{ marginTop: 8 }}>
        <button className="btn" onClick={() => act('done')}>✓ Done — I fixed it in the doc</button>
        <button className="btn" onClick={() => setMode('not_required')}>Not required…</button>
        <button className="btn" onClick={() => setMode('clarified')}>Answer / clarify…</button>
      </div>}
      {mode && <div style={{ marginTop: 8 }}>
        <textarea autoFocus placeholder={mode === 'not_required' ? 'Why is this not required? (e.g. this is intentional because…)' : 'Your answer or clarification'} value={note} onChange={e => setNote(e.target.value)} />
        <div className="row" style={{ marginTop: 6 }}><button className="btn primary" disabled={!note.trim()} onClick={() => act(mode, note)}>Submit</button><button className="btn" onClick={() => setMode(null)}>Cancel</button></div>
      </div>}
      {resolved && <div className="row" style={{ marginTop: 6 }}><button className="btn" onClick={() => act('open')}>Reopen</button></div>}
    </div>)
}

// Export the review comments as CSV (Statement, Doc page, Tag), filtered by kind.
function ExportCsv({ p, counts }) {
  const KINDS = [['error', 'Errors'], ['warning', 'Warnings'], ['question', 'Questions'], ['info', 'Info']]
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState(new Set(KINDS.map(k => k[0])))
  const all = sel.size === KINDS.length
  const toggle = k => { const n = new Set(sel); n.has(k) ? n.delete(k) : n.add(k); setSel(n) }
  const href = `/api/projects/${p.id}/findings.csv` + (all ? '' : `?severities=${[...sel].join(',')}`)
  const total = KINDS.filter(k => sel.has(k[0])).reduce((n, k) => n + (counts[k[0]] || 0), 0)
  return (
    <div style={{ position: 'relative' }}>
      <button className="btn" onClick={() => setOpen(!open)}>Export CSV ▾</button>
      {open && <div className="card" style={{ position: 'absolute', zIndex: 5, top: '110%', right: 0, minWidth: 220, padding: 10 }}>
        <label className="small" style={{ margin: 0, display: 'block' }}><input type="checkbox" checked={all} onChange={() => setSel(all ? new Set() : new Set(KINDS.map(k => k[0])))} /> All</label>
        {KINDS.map(([k, l]) => <label key={k} className="small" style={{ margin: 0, display: 'block' }}><input type="checkbox" checked={sel.has(k)} onChange={() => toggle(k)} /> {l} <span className="muted">({counts[k] || 0})</span></label>)}
        <div className="row" style={{ marginTop: 8 }}>
          <a className="btn primary" href={sel.size ? href : undefined} download onClick={() => setOpen(false)} style={{ textDecoration: 'none', opacity: sel.size ? 1 : 0.5, pointerEvents: sel.size ? 'auto' : 'none' }}>Download ({total})</a>
        </div>
        <div className="muted small" style={{ marginTop: 6 }}>Columns: statement, doc page, tag. No suggestions or internal ids.</div>
      </div>}
    </div>)
}

function Review({ p, reload, goto }) {
  const [data, setData] = useState(null)
  const [filter, setFilter] = useState('open')
  const [byPage, setByPage] = useState(false)
  const [err, setErr] = useState('')
  const load = useCallback(async () => setData(await api(`/projects/${p.id}/findings`)), [p.id])
  useEffect(() => { load() }, [load])
  const running = data?.job?.state === 'running'
  usePoll(load, running)
  useEffect(() => { if (data?.job?.state === 'done') reload() }, [data?.job?.state])
  const scan = async (llm = true) => { setErr(''); try { await api(`/projects/${p.id}/scan?refetch=true&use_llm=${llm}`, { method: 'POST' }); load() } catch (e) { setErr(e.message) } }
  const proceed = async () => { if (confirm('Skip the open items?\n\nSafe fixes (stray characters, double punctuation, renumbering, spelling) are applied automatically; everything else, including AI-suggested rewording, is copied exactly as written. The final report will list them as accepted.')) { await api(`/projects/${p.id}/proceed-anyway`, { method: 'POST' }); load(); reload() } }
  if (!data) return <div className="muted">Loading…</div>
  const fs = data.findings
  const shown = fs.filter(f => filter === 'all' ? true : filter === 'open' ? f.status === 'open' : f.status !== 'open').slice().sort(byPage ? (a, b) => (a.doc_pages?.[0] ?? 999) - (b.doc_pages?.[0] ?? 999) : () => 0)
  const scanned = !!p.last_scan
  const openB = data.open_blocking
  return (
    <div>
      {p.mode === 'create' && !p.samples_approved && <div className="banner warn">The sample pages are not approved yet. You can review the doc meanwhile, but generating needs the approval.</div>}
      <div className="card">
        <div className="row">
          <button className="btn primary" disabled={running} onClick={() => scan(true)}>{scanned ? '↻ Re-scan the doc' : 'Scan the doc'}</button>
          <button className="btn" disabled={running} onClick={() => scan(false)} title="Only the free rule-based checks">Quick check (no AI)</button>
          {fs.length > 0 && <ExportCsv p={p} counts={fs.reduce((m, f) => (m[f.severity] = (m[f.severity] || 0) + 1, m), {})} />}
          {running && <div style={{ flex: 1, minWidth: 200 }}><div className="small muted">{data.job.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (data.job.progress || 0) * 100)}%` }} /></div></div>}
          {data.job?.state === 'error' && <span className="err-t">{data.job.message}</span>}
        </div>
        <div className="muted small" style={{ marginTop: 6 }}>Re-scan re-reads your Google Doc, so edit the doc, mark the item done, then re-scan. Your earlier answers are kept.</div>
        {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
      </div>
      {scanned && (openB === 0
        ? <div className="banner ok"><b>All clear.</b> Nothing blocking is left, so you can continue. {p.mode === 'create' ? <button className="btn ok" style={{ marginLeft: 10 }} onClick={() => goto('structure')}>Continue to Structure →</button> : <button className="btn ok" style={{ marginLeft: 10 }} onClick={() => goto('report')}>Continue to the report →</button>}</div>
        : <div className="banner err"><b>{openB} item{openB > 1 ? 's' : ''} still need{openB > 1 ? '' : 's'} your answer.</b> Fix them in the doc and re-scan, or answer them below.{p.mode === 'create' && <button className="btn" style={{ marginLeft: 10 }} onClick={proceed}>Proceed anyway…</button>}</div>)}
      {scanned && <div className="tabs">{[['open', `Open (${fs.filter(f => f.status === 'open').length})`], ['resolved', `Resolved (${fs.filter(f => f.status !== 'open').length})`], ['all', 'All']].map(([k, l]) => <div key={k} className={'tab' + (filter === k ? ' on' : '')} onClick={() => setFilter(k)}>{l}</div>)}<div style={{ flex: 1 }} /><label style={{ margin: 0, alignSelf: 'center' }}><input type="checkbox" checked={byPage} onChange={e => setByPage(e.target.checked)} /> Order by doc page</label></div>}
      {shown.map(f => <FindingCard key={f.id} f={f} pid={p.id} onChange={load} />)}
      {scanned && shown.length === 0 && <div className="muted">Nothing in this list.</div>}
    </div>)
}


// Plain-language requests about the structure ("let Part 10 continue on page 57", "the worksheet is an exercise").
// Claude turns them into the same overrides as the checkboxes above, so the text on the pages never changes.
function StructureChat({ p, onChanged, version }) {
  const [turns, setTurns] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [spec, setSpec] = useState(null)
  const endRef = useRef(null)
  useEffect(() => { api(`/projects/${p.id}/structure/chat`).then(d => setTurns(d.turns)).catch(() => {}) }, [p.id])
  const wanted = [...new Set(turns.filter(t => t.role === 'assistant' && !t.undone).flatMap(t => t.show_pages || []))]
  useEffect(() => { if (wanted.length) api(`/projects/${p.id}/spec`).then(setSpec).catch(() => {}) }, [turns.length, p.id, version])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [turns.length, busy])
  const send = async () => {
    const text = msg.trim(); if (!text || busy) return
    setBusy(true); setErr(''); setMsg('')
    setTurns(t => [...t, { role: 'user', text }])
    try { const d = await api(`/projects/${p.id}/structure/chat`, { method: 'POST', body: { message: text } }); setTurns(d.turns); if (d.applied) await onChanged() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const undo = async () => { setBusy(true); setErr(''); try { const d = await api(`/projects/${p.id}/structure/chat/undo`, { method: 'POST' }); setTurns(d.turns); await onChanged() } catch (e) { setErr(e.message) } finally { setBusy(false) } }
  const lastChange = [...turns].reverse().find(t => t.role === 'assistant' && t.changes?.length)
  const pageOf = n => spec?.pages?.find(pg => pg.pageNo === n)
  return (
    <div style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 13, margin: '0 0 4px' }}>Ask for changes</h3>
      <div className="muted small" style={{ marginBottom: 8 }}>Describe what you want in plain language and refer to pages by their numbers in the Preview — e.g. “let Part 10 continue on page 57”, “move the table on page 8 to page 9 but keep the paragraph”, “the worksheet is an exercise, not teaching content”, “40 pt margins on both sides”, “no box behind the MCQs”, “use CHAPTER- 1 as the line above the index title”. Claude turns it into page starts (before any line, not only headings), roles, the front matter (eyebrow, title, index), component looks, colours and the page layout (margins, header/footer, type sizes) — never into text changes — and shows the pages it touched.</div>
      <div style={{ maxHeight: 420, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 8, padding: 10, background: '#fff' }}>
        {turns.length === 0 && <div className="muted small">No requests yet.</div>}
        {turns.map((t, i) => t.role === 'user'
          ? <div key={i} style={{ margin: '6px 0', textAlign: 'right' }}><span style={{ display: 'inline-block', background: 'var(--tint, #eef2f8)', borderRadius: 10, padding: '6px 10px', maxWidth: '80%', textAlign: 'left' }}>{t.text}</span></div>
          : <div key={i} style={{ margin: '6px 0' }}>
              <div style={{ display: 'inline-block', border: '1px solid var(--line)', borderRadius: 10, padding: '6px 10px', maxWidth: '90%' }}>
                <div>{t.text}</div>
                {t.changes?.length > 0 && <ul className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>{t.changes.map((c, j) => <li key={j}>{c}</li>)}</ul>}
                {t.undone && <div className="small muted" style={{ marginTop: 4 }}>Undone.</div>}
                {t === lastChange && <button className="btn" style={{ marginTop: 6 }} disabled={busy} onClick={undo}>Undo this change</button>}
              </div>
              {t.show_pages?.length > 0 && !t.undone && spec && <div className="row" style={{ gap: 10, marginTop: 6, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                {t.show_pages.map(n => pageOf(n) ? <div key={n}><div className="small muted">Page {n}</div><Page page={pageOf(n)} theme={spec.theme} meta={spec.meta} scale={0.42} /></div> : null)}
              </div>}
            </div>)}
        {busy && <div className="muted small" style={{ margin: '6px 0' }}>Claude is reading the current pages and your request…</div>}
        <div ref={endRef} />
      </div>
      {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
      <div className="row" style={{ marginTop: 8, gap: 8 }}>
        <input type="text" style={{ flex: 1 }} value={msg} disabled={busy} placeholder="What should change?" onChange={e => setMsg(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') send() }} />
        <button className="btn primary" disabled={busy || !msg.trim()} onClick={send}>Send</button>
      </div>
    </div>)
}

// ------------------------------------------------------------------ Structure (Claude reads the doc for meaning)
function StructureStep({ p, reload, goto }) {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const [roles, setRoles] = useState({})
  const [breaks, setBreaks] = useState({})
  const [showHeads, setShowHeads] = useState(false)
  const [ver, setVer] = useState(0)
  const load = useCallback(async () => { const d = await api(`/projects/${p.id}/structure`); setSt(d); setVer(v => v + 1); return d }, [p.id])
  useEffect(() => { load().catch(e => setErr(e.message)) }, [load])
  const running = st?.job?.state === 'running'
  usePoll(load, running, 2000)
  const [tjob, setTjob] = useState(null)
  const [wait, setWait] = useState(false)
  const loadT = useCallback(async () => { const x = await api(`/projects/${p.id}/tables`); setTjob(x.job); return x.job }, [p.id])
  usePoll(async () => { const j = await loadT(); if (j.state === 'done' || j.state === 'failed') { setWait(false); if (j.state === 'done') goto('generate') } }, wait, 2000)
  const proceed = async () => { try { setTjob(await api(`/projects/${p.id}/tables/prepare`, { method: 'POST' })); setWait(true) } catch (e) { setErr(e.message) } }
  const act = async fn => { setErr(''); try { await fn(); await load() } catch (e) { setErr(e.message) } }
  const read = force => act(() => api(`/projects/${p.id}/structure/read${force ? '?force=true' : ''}`, { method: 'POST' }))
  // hooks must all run before any early return (React keeps them in order between renders)
  useEffect(() => { if (st && !st.map && st.job?.state !== 'running' && st.job?.state !== 'failed') read(false) }, [st?.map, st?.job?.state])
  if (!st) return <div className="muted">Loading…</div>
  const apply = () => act(async () => { await api(`/projects/${p.id}/structure`, { method: 'PUT', body: { roles: { ...Object.fromEntries((st.map?.sections || []).filter(x => x.override).map(x => [x.src, x.override])), ...roles }, page_breaks: breaks } }); setRoles({}); setBreaks({}); reload() })
  const m = st.map
  const pg = x => x ? <span className="tag" style={{ background: '#fff4d6', color: '#7a5200' }}>doc p.{x}</span> : null
  const ROLE_NAMES = { body: 'Teaching content', exercise: 'Exercise', answers: 'Answer key', mindmap: 'Mind map', references: 'References', glossary: 'Glossary' }
  return (
    <div className="card">
      <h2>Structure</h2>
      <div className="muted small" style={{ marginBottom: 8 }}>Claude reads the whole document for meaning (no fixed template) and decides what is the index, where each part really starts, and what each part is (teaching content, exercise, answer key…). It only labels lines: every word on the pages still comes straight from your doc. Check the result, fix anything that looks off, then continue.</div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" disabled={running} onClick={() => read(!!m)}>{m ? '↻ Read again' : 'Read the document'}</button>
        {running && <div style={{ flex: 1, minWidth: 220 }}><div className="small muted">{st.job.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (st.job.progress || 0) * 100)}%` }} /></div></div>}
        {st.job?.state === 'failed' && <span className="err-t small">{st.job.error || st.job.message}</span>}
      </div>
      {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
      {!m && !running && st.job?.state === 'failed' && <div className="banner warn" style={{ marginTop: 8 }}>Claude could not read the document, so sections are guessed from heading names for now. Try again, or continue with the guess.</div>}
      {m && <>
        <div className="small" style={{ margin: '12px 0 4px' }}><b>Front matter:</b> {m.front.eyebrow ? `“${m.front.eyebrow}” · ` : ''}{m.front.title ? <>title “{m.front.title}”</> : 'no title found'}{m.front.index_heading ? <> · index “{m.front.index_heading}” with {m.index_entries} lines</> : ''}{m.front.index_table ? <> · index {m.front.index_table}</> : ''}</div>
        <h3 style={{ fontSize: 13, margin: '12px 0 6px' }}>Sections ({m.sections.length}) · {m.headings} headings inside them</h3>
        <div className="muted small" style={{ marginBottom: 6 }}>“New page” is Claude's decision for where a part begins at the top of a fresh page; untick it to let a part continue below the previous text. A part whose page type differs from the one before it (teaching content → exercise, exercise → answer key) always starts a page, because the page background changes.</div>
        {m.sections.map((x, i) => {
          const effRole = y => roles[y.src] ?? y.override ?? y.role
          const canFlow = i > 0 && effRole(m.sections[i - 1]) === effRole(x) && !['inline', 'ignore'].includes(effRole(x))
          const on = canFlow ? (breaks[x.src] ?? (x.new_page_eff ?? effRole(x) !== 'body')) : true
          return (
          <div key={x.src} className="row" style={{ padding: '4px 0', borderBottom: '1px solid var(--line)', gap: 8 }}>
            <select style={{ width: 170 }} value={effRole(x)} onChange={e => setRoles({ ...roles, [x.src]: e.target.value })}>
              {Object.entries(ROLE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              <option value="inline">Not a section (heading only)</option>
              <option value="ignore">Leave out</option>
            </select>
            <b style={{ flex: 1 }}>{x.title}</b>
            <label className="small" style={{ margin: 0, whiteSpace: 'nowrap', opacity: canFlow ? 1 : 0.5 }} title={canFlow ? '' : 'The page type changes here, so this always starts a page'}><input type="checkbox" checked={on} disabled={!canFlow} onChange={e => setBreaks({ ...breaks, [x.src]: e.target.checked })} /> new page</label>
            {pg(x.page)}
          </div>)
        })}
        {m.heading_breaks?.length > 0 && <div style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => setShowHeads(!showHeads)}>{showHeads ? 'Hide' : 'Show'} page starts inside sections ({m.heading_breaks.filter(h => breaks[h.src] ?? h.new_page).length} of {m.heading_breaks.length} headings start a new page)</button>
          {showHeads && <table className="t" style={{ marginTop: 6 }}><thead><tr><th>Heading</th><th>Level</th><th>Doc page</th><th>New page</th></tr></thead><tbody>
            {m.heading_breaks.map(h => <tr key={h.src}><td>{h.title}</td><td>H{h.level}</td><td>{h.page || ''}</td><td><input type="checkbox" checked={breaks[h.src] ?? h.new_page} onChange={e => setBreaks({ ...breaks, [h.src]: e.target.checked })} /></td></tr>)}
          </tbody></table>}
        </div>}
        {st.block_breaks?.length > 0 && <div style={{ marginTop: 10 }}>
          <div className="small"><b>Pages also start before these lines</b> <span className="muted">(asked for in the chat below; untick one to let that line flow on)</span></div>
          <table className="t" style={{ marginTop: 6 }}><thead><tr><th>Line</th><th>Doc page</th><th>New page</th></tr></thead><tbody>
            {st.block_breaks.map(b => <tr key={b.src}><td>{b.text}</td><td>{b.page || ''}</td><td><input type="checkbox" checked={breaks[b.src] ?? b.on} onChange={e => setBreaks({ ...breaks, [b.src]: e.target.checked })} /></td></tr>)}
          </tbody></table>
        </div>}
        <div className="row" style={{ marginTop: 8 }}><button className="btn" disabled={!Object.keys(roles).length && !Object.keys(breaks).length} onClick={apply}>Apply changes</button><span className="muted small">Pages update straight away.</span></div>
      </>}
      {st.checks.length > 0 && <div style={{ marginTop: 14 }}><h3 style={{ fontSize: 13, margin: '0 0 6px' }}>Things to check</h3>{st.checks.map((c, i) => <div key={i} className="small" style={{ margin: '4px 0' }}><span className={`tag ${c.severity === 'question' ? 'question' : c.severity === 'warning' ? 'warning' : 'info'}`}>{c.severity}</span> {c.message}</div>)}</div>}
      {st.checks.length === 0 && m && <div className="ok-t small" style={{ marginTop: 12 }}>No structural problems found.</div>}
      {m && <StructureChat p={p} onChanged={load} version={ver} />}
      {tjob?.state === 'running' && <div style={{ marginTop: 12 }}><div className="small muted">{tjob.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (tjob.progress || 0) * 100)}%` }} /></div></div>}
      {tjob?.state === 'failed' && <div className="banner err" style={{ marginTop: 8 }}>{tjob.error || tjob.message} You can still continue; table pictures stay placeholders.</div>}
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn ok" disabled={!m || tjob?.state === 'running'} onClick={proceed}>{tjob?.state === 'running' ? 'Reading tables…' : 'Continue to Preview →'}</button>
        {!m && st.job?.state === 'failed' && <button className="btn" onClick={() => goto('generate')}>Continue with the guess</button>}
        <span className="muted small">Pictures of tables are read into real tables first, so the Preview is laid out correctly.</span>
      </div>
    </div>)
}

// ------------------------------------------------------------------ Images & diagrams
function ImagesStep({ p, goto }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [showAll, setShowAll] = useState(false)
  const load = useCallback(async () => setD(await api(`/projects/${p.id}/images`)), [p.id])
  useEffect(() => { load().catch(e => setErr(e.message)) }, [load])
  const busy = d && (d.job?.state === 'running' || d.gen_job?.state === 'running' || Object.values(d.gen_jobs || {}).some(j => j.state === 'running'))
  usePoll(load, busy, 2000)
  const act = async (fn) => { setErr(''); try { await fn(); load() } catch (e) { setErr(e.message) } }
  if (!d) return <div className="muted">Loading…</div>
  const im = d.images
  const tables = im.filter(e => !e.tiny && (e.class === 'table' || e.mode === 'table'))
  const diagrams = im.filter(e => !tables.includes(e) && (['diagram', 'equation'].includes(e.class) || (e.mode !== 'placeholder' && !e.tiny)))
  const others = im.filter(e => !diagrams.includes(e) && !tables.includes(e) && !e.tiny)
  const tiny = im.filter(e => e.tiny)
  const analysed = im.some(e => e.class && e.class !== 'inline')
  const pgTxt = e => e.pages?.length ? `doc p.${e.pages.slice(0, 3).join(', ')}${e.pages.length > 3 ? '…' : ''}` : ''
  const toggle = e => act(() => api(`/projects/${p.id}/images/${e.hash}`, { method: 'PATCH', body: { mode: e.mode !== 'placeholder' ? 'placeholder' : e.class === 'table' ? 'table' : 'generate' } }))
  const gen = e => act(() => api(`/projects/${p.id}/images/${e.hash}/generate`, { method: 'POST' }))
  const Card = ({ e }) => {
    const j = d.gen_jobs?.[e.hash]
    const working = j?.state === 'running'
    return (
      <div className="finding" style={{ borderLeftColor: e.mode !== 'placeholder' ? '#2848a0' : undefined }}>
        <div className="row" style={{ gap: 8, marginBottom: 6 }}>
          <span className="tag">{e.class || 'not analysed'}</span>{e.complexity && <span className="tag">{e.complexity}</span>}<span className="muted small">{pgTxt(e)} · used {e.count}×</span>
          {e.status === 'generated' && e.match != null && <span className={'tag ' + (e.match >= 92 ? '' : 'warning')} style={e.match >= 92 ? { background: '#e4f5ea', color: 'var(--ok)' } : {}}>{e.match}% match</span>}
          <div style={{ flex: 1 }} />
          <label style={{ margin: 0 }}><input type="checkbox" checked={e.mode !== 'placeholder'} onChange={() => toggle(e)} /> {e.class === 'table' ? 'Build as a table' : e.class === 'equation' ? 'Rebuild as text + vector' : 'Draw as a diagram'}</label>
        </div>
        <div className="muted small" style={{ marginBottom: 6 }}>{e.reason}</div>
        <div className="row" style={{ alignItems: 'flex-start', gap: 14 }}>
          <div><div className="small muted">Original</div><img src={`/api/projects/${p.id}/media/${e.hash}`} style={{ maxWidth: 260, maxHeight: 220, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }} /></div>
          {e.table && <div style={{ maxWidth: 420, overflow: 'auto' }}><div className="small muted">Table as read (built in the theme)</div><table style={{ borderCollapse: 'collapse', fontSize: 11, background: '#fff' }}>{e.table.head.length > 0 && <thead><tr>{e.table.head.map((c, i) => <th key={i} style={{ border: '1px solid #D9D9D9', padding: '3px 6px', background: '#1E3A6E', color: '#fff' }}>{c}</th>)}</tr></thead>}<tbody>{e.table.rows.map((r, ri) => <tr key={ri}>{r.map((c, i) => <td key={i} style={{ border: '1px solid #D9D9D9', padding: '3px 6px', background: ri % 2 ? '#DCE6F4' : '#fff' }}>{c}</td>)}</tr>)}</tbody></table></div>}
          {e.has_svg && <div><div className="small muted">Generated drawing</div><img src={`/api/projects/${p.id}/diagrams/${e.hash}`} style={{ maxWidth: 260, maxHeight: 220, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }} /></div>}
          <div style={{ flex: 1, minWidth: 200 }}>
            {e.mode !== 'placeholder' && <button className="btn" disabled={working} onClick={() => gen(e)}>{working ? (j.message || 'Working…') : (e.has_svg || e.has_table) ? '↻ Redo' : e.mode === 'table' ? 'Read table' : 'Generate drawing'}</button>}
            {e.has_table && <div className="small muted" style={{ marginTop: 6 }}>Table read; it appears as a real table in the Preview.</div>}
            {e.status === 'failed' && <div className="err-t small" style={{ marginTop: 6 }}>{e.error}</div>}
            {e.issues?.length > 0 && <div className="small" style={{ marginTop: 8 }}><b>Notes from the check</b><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{e.issues.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          </div>
        </div>
      </div>)
  }
  return (
    <div>
      <div className="card">
        <h2>Pictures and diagrams</h2>
        <div className="muted small" style={{ marginBottom: 8 }}>Diagrams and equation pictures are rebuilt in Figma as editable text on top of vector shapes (lettering is never turned into vector). Tables have their own section below and are built as real tables in the theme. Only photos and artwork stay labelled placeholders. You can switch any picture either way.</div>
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => act(() => api(`/projects/${p.id}/images/analyse`, { method: 'POST' }))}>{analysed ? '↻ Analyse new pictures' : 'Analyse the pictures'}</button>
          {analysed && <button className="btn" disabled={busy} onClick={() => act(() => api(`/projects/${p.id}/images/generate-all`, { method: 'POST' }))}>Rebuild all missing pictures</button>}
          {busy && <div style={{ flex: 1, minWidth: 220 }}><div className="small muted">{d.job?.state === 'running' ? d.job.message : d.gen_job?.state === 'running' ? d.gen_job.message : 'Drawing…'}</div><div className="bar"><i style={{ width: `${Math.max(5, ((d.job?.state === 'running' ? d.job.progress : d.gen_job?.progress) || 0.1) * 100)}%` }} /></div></div>}
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>{d.summary.total} distinct pictures · {d.summary.tiny} tiny inline symbols (always placeholders) · {d.summary.diagrams} to be drawn · {d.summary.generated} drawn</div>
        {d.needs_media && <div className="banner warn" style={{ marginTop: 8 }}>The pictures of this document have not been loaded into the app yet (this project was made before diagrams existed). <button className="btn" style={{ marginLeft: 8 }} disabled={busy} onClick={() => act(async () => { await api(`/projects/${p.id}/fetch`, { method: 'POST' }); })}>Load the pictures (re-reads the doc)</button></div>}
        {!d.chrome && <div className="banner warn" style={{ marginTop: 8 }}>Chrome was not found on this computer, so drawings cannot be checked visually against the original before you see them.</div>}
        {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
        {!analysed && !busy && <div className="banner info" style={{ marginTop: 8 }}>Not analysed yet. If you skip this, every picture becomes a placeholder.</div>}
      </div>
      {tables.length > 0 && <><h3 style={{ margin: '14px 0 4px' }}>Tables ({tables.length})</h3><div className="muted small" style={{ marginBottom: 8 }}>These pictures are not treated as images or diagrams. Each one is read into cell text and built in Figma as a real, editable table in the theme (header colour, zebra rows, borders). Check the text read from the picture below.</div>{tables.map(e => <Card key={e.hash} e={e} />)}</>}
      {diagrams.length > 0 && <><h3 style={{ margin: '14px 0 8px' }}>Diagrams & equations ({diagrams.length})</h3>{diagrams.map(e => <Card key={e.hash} e={e} />)}</>}
      {others.length > 0 && <div className="card">
        <div className="row"><b>Other pictures ({others.length}): placeholders</b><span className="muted small">photos, artwork</span><div style={{ flex: 1 }} /><button className="btn" onClick={() => setShowAll(!showAll)}>{showAll ? 'Hide' : 'Review them'}</button></div>
        {showAll && <div className="row" style={{ marginTop: 10, gap: 10, alignItems: 'flex-start' }}>
          {others.slice(0, 80).map(e => <div key={e.hash} style={{ width: 150 }}><img src={`/api/projects/${p.id}/media/${e.hash}`} style={{ maxWidth: 150, maxHeight: 90, border: '1px solid var(--line)', background: '#fff' }} /><div className="small muted">{e.class} {pgTxt(e)}</div><label className="small" style={{ margin: 0 }}><input type="checkbox" checked={e.mode !== 'placeholder'} onChange={() => toggle(e)} /> rebuild</label></div>)}
          {others.length > 80 && <div className="muted small">…and {others.length - 80} more</div>}
        </div>}
      </div>}
      {tiny.length > 0 && <div className="muted small" style={{ margin: '8px 0' }}>{tiny.length} tiny inline pictures (symbols or equation pieces) are always placeholders.</div>}
      <div className="row" style={{ marginTop: 12 }}><button className="btn ok" onClick={() => goto('report')}>Continue to Report →</button></div>
    </div>)
}

// ------------------------------------------------------------------ Generate
function Generate({ p, reload, goto, status }) {
  const [spec, setSpec] = useState(null)
  const [err, setErr] = useState('')
  const [res, setRes] = useState(null)
  const [rep, setRep] = useState(null)
  useEffect(() => { api(`/projects/${p.id}/spec`).then(setSpec).catch(e => setErr(e.message)) }, [p.id])
  const poll = useCallback(async () => setRep(await api(`/projects/${p.id}/plugin-report`)), [p.id])
  const [genBusy, setGenBusy] = useState(false)
  // the plugin report belongs to the job it names: a report from an earlier Generate is not this job's result
  const built = rep?.sectionId && (!res || rep.job === res.job)
  const waiting = !!res && !built
  usePoll(poll, waiting, 2000)
  useEffect(() => { poll() }, [poll])
  const gen = async () => { setErr(''); setGenBusy(true); try { const r = await api(`/projects/${p.id}/generate`, { method: 'POST' }); setRes(r); reload() } catch (e) { setErr(e.message) } finally { setGenBusy(false) } }
  if (err && !spec) return <div className="banner err">{err}</div>
  if (!spec) return <div className="muted">Laying out the book…</div>
  const issues = spec.issues || []
  return (
    <div>
      <div className="card">
        {spec.font_warnings?.length > 0 && <div className="banner warn" style={{ marginBottom: 8 }}>{spec.font_warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}
        {status?.plugin?.known && status.plugin.ok === false && <div className="banner err" style={{ marginBottom: 8 }}>Figma runs the Book Builder plugin from <code>{status.plugin.path}</code>, which is not this app's plugin. In Figma: Plugins → Development → Import plugin from manifest… and pick <code>{status.plugin.expected}</code>, then run it again.</div>}
        {rep?.sectionId && spec.pluginVersion != null && rep.pluginVersion !== spec.pluginVersion && <div className="banner err" style={{ marginBottom: 8 }}>The last build in Figma was made by an older copy of the plugin ({rep.pluginVersion != null ? `version ${rep.pluginVersion}` : 'no version'}; the app is at version {spec.pluginVersion}). Import <code>figma-plugin/manifest.json</code> from this project in Figma (Plugins → Development → Import plugin from manifest…), run it again, then Load and Build.</div>}
        {p.generated_at && p.structure_changed > p.generated_at && <div className="banner warn" style={{ marginBottom: 8 }}>The structure changed after the last Generate. This preview is up to date, but the pages built in Figma are not: click Generate again and rebuild with the plugin.</div>}
        <h2>Preview: {spec.pages.length} pages{spec.diagrams ? ` · ${spec.diagrams} generated diagram${spec.diagrams > 1 ? 's' : ''}` : ''}</h2>
        <div className="muted small">Exactly what will be built. Content comes straight from your doc{spec.dropped.length ? '' : ' (nothing dropped)'}. Images are placeholders.</div>
        {spec.dropped.length > 0 && <div className="banner err" style={{ marginTop: 8 }}>{spec.dropped.length} doc blocks could not be placed: {spec.dropped.slice(0, 8).join(', ')}</div>}
        {spec.overflow.length > 0 && <div className="banner warn" style={{ marginTop: 8 }}>{spec.overflow.length} block(s) are taller than a page.</div>}
        <div className="pages" style={{ marginTop: 12 }}>{spec.pages.map((pg, i) => <div className="pg" key={i}><Page page={pg} theme={spec.theme} meta={spec.meta} scale={0.38} /><div className="cap">{pg.pageNo != null ? `Page ${pg.pageNo}` : 'TOC'} · {pg.kind}</div></div>)}</div>
      </div>
      <div className="card">
        <h2>Build in Figma</h2>
        <ol style={{ paddingLeft: 18, margin: '0 0 10px' }}>
          <li>One time: in Figma desktop choose <b>Plugins → Development → Import plugin from manifest…</b> and pick <code>figma-plugin/manifest.json</code> from this project.</li>
          <li>Click <b>Generate</b> below.</li>
          <li>In your Figma file run <b>Plugins → Development → Book Builder</b>, press <b>Load</b>, then <b>Build pages</b>.</li>
        </ol>
        {err && <div className="banner err">{err}</div>}
        <div className="row"><button className="btn primary" disabled={genBusy} onClick={gen}>{genBusy ? 'Laying out…' : res ? '↻ Generate again' : 'Generate'}</button>
          {waiting && <span className="ok-t">Design ready: {res.pages} pages{res.overflow?.length ? `, ${res.overflow.length} block(s) taller than a page` : ''}. Now in Figma: run the plugin, press <b>Load</b>, then <b>Build pages</b> — this page updates when it finishes.</span>}
          {built && <span className="ok-t">✓ Built {rep.pages.length} pages in Figma{rep.pages.some(x => x.overflow) ? ` — ${rep.pages.filter(x => x.overflow).length} page(s) overflow` : ''}{rep.errors?.length ? `, ${rep.errors.length} errors` : ''}.</span>}
        </div>
        {rep?.sectionId && <div style={{ marginTop: 10 }}><button className="btn ok" onClick={() => goto('report')}>Continue to analysis →</button></div>}
      </div>
    </div>)
}

// ------------------------------------------------------------------ Report
function Report({ p, reload }) {
  const [url, setUrl] = useState(p.figma_url || '')
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('todo')
  const [err, setErr] = useState('')
  const load = useCallback(async () => setData(await api(`/projects/${p.id}/report`)), [p.id])
  useEffect(() => { load() }, [load])
  const running = data?.job?.state === 'running'
  usePoll(load, running)
  const verify = async (llm = true) => { setErr(''); try { await api(`/projects/${p.id}/verify`, { method: 'POST', body: { figma_url: url, use_llm: llm } }); load() } catch (e) { setErr(e.message) } }
  const toggle = async (t, done) => { await api(`/projects/${p.id}/todos/${t.id}?done=${done}`, { method: 'PATCH' }); load() }
  const r = data?.report
  const open = r ? r.todos.filter(t => !t.user_done || t.still_open) : []
  const imgTodos = r ? r.todos.filter(t => t.type === 'image') : []
  return (
    <div>
      <div className="card">
        <h2>Compare Figma with the Google Doc</h2>
        <label>Link to the Figma section or page (select it → right-click → Copy link)</label>
        <input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.figma.com/design/…?node-id=…" />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" disabled={running || !url} onClick={() => verify(true)}>{r ? '↻ Verify again' : 'Verify'}</button>
          <button className="btn" disabled={running || !url} onClick={() => verify(false)} title="Skip the AI explanations">Verify (no AI notes)</button>
          {running && <div style={{ flex: 1, minWidth: 200 }}><div className="small muted">{data.job.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (data.job.progress || 0) * 100)}%` }} /></div></div>}
        </div>
        {(err || data?.job?.state === 'error') && <div className="banner err" style={{ marginTop: 10 }}>{err || data.job.message}</div>}
      </div>
      {r && <>
        <div className="card">
          <div className="row" style={{ gap: 24 }}>
            <div><div className={'score ' + (r.score === 100 ? 'ok-t' : r.score >= 98 ? 'warn-t' : 'err-t')}>{r.score}%</div><div className="muted small">content accuracy · run #{r.run}</div></div>
            <div className="small">
              <div>{r.stats.matched.toLocaleString()} of {r.stats.doc_tokens.toLocaleString()} doc words matched exactly</div>
              <div>{r.diffs.length} content difference{r.diffs.length === 1 ? '' : 's'} · {r.anomalies.length} layout warning{r.anomalies.length === 1 ? '' : 's'} · {r.case_total} capitalisation-only</div>
              <div>Images: {r.images.in_doc} in doc · {r.images.placeholders} placeholders left · {r.images.placed} images placed</div>
            </div>
            <div><a className="btn" href={`/api/projects/${p.id}/report.xlsx`} download>⬇ Export to Excel</a></div>
            <div className="small muted" style={{ minWidth: 160 }}>{data.history.map(h => <div key={h.run}>Run {h.run}: {h.score}%</div>)}</div>
          </div>
          {r.score === 100 && imgTodos.length === 0 && r.anomalies.length === 0 && <div className="banner ok" style={{ marginTop: 10 }}>🎉 100% — the Figma matches the doc, with no outstanding items.</div>}
          {r.score === 100 && (imgTodos.length > 0 || r.anomalies.length > 0) && <div className="banner info" style={{ marginTop: 10 }}>Text is 100% accurate. Remaining items are manual (images / layout).</div>}
        </div>
        <div className="tabs">{[['todo', `To-do (${open.length})`], ['diffs', `Differences (${r.diffs.length})`], ['layout', `Layout (${r.anomalies.length})`], ['case', `Capitalisation (${r.case_total})`], ['accepted', `Accepted (${r.accepted.length})`]].map(([k, l]) => <div key={k} className={'tab' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</div>)}</div>
        {tab === 'todo' && <div className="card">
          {r.todos.length === 0 && <div className="ok-t">Nothing to do.</div>}
          {r.todos.map(t => <div key={t.id} className={'todo' + (t.user_done && !t.still_open ? ' done' : '')}>
            <input type="checkbox" checked={!!t.user_done} onChange={e => toggle(t, e.target.checked)} />
            <div style={{ flex: 1 }}><span className={`tag ${t.severity === 'error' ? 'error' : t.severity === 'manual' ? 'question' : 'warning'}`}>{t.type}</span> {t.text}
              {t.still_open && <div className="small warn-t">You marked this done, but it is still detected.</div>}
              {t.link && <> <a className="small" href={t.link} target="_blank" rel="noreferrer">open in Figma ↗</a></>}</div>
          </div>)}
          {r.todos.length > 0 && <div className="muted small" style={{ marginTop: 10 }}>Tick items as you fix them, then press <b>Verify again</b>. The loop ends when the score is 100% and nothing is left.</div>}
        </div>}
        {tab === 'diffs' && <div className="card"><table className="t"><thead><tr><th>Type</th><th>Doc says</th><th>Figma has</th><th>Where / note</th></tr></thead><tbody>
          {r.diffs.map((d, i) => <tr key={i}><td><span className="tag error">{d.kind}</span></td><td>{d.doc}</td><td>{d.figma}</td><td className="small muted">{r.pages[d.page]?.name}{d.explanation ? <div style={{ color: 'var(--ink)' }}>{d.explanation}</div> : null}</td></tr>)}
          {r.diffs.length === 0 && <tr><td colSpan="4" className="ok-t">No differences.</td></tr>}</tbody></table></div>}
        {tab === 'layout' && <div className="card">{r.anomalies.map((a, i) => <div key={i} className="todo"><span className="tag warning">{a.kind}</span><div>{a.msg}</div></div>)}{r.anomalies.length === 0 && <div className="ok-t">No layout anomalies.</div>}</div>}
        {tab === 'case' && <div className="card"><div className="muted small">Same words, different capitalisation (e.g. a title typed in Title Case where the doc has capitals). Not counted against the score.</div><table className="t"><tbody>{r.case_warnings.map((c, i) => <tr key={i}><td>{c.doc}</td><td>{c.figma}</td><td className="small muted">{r.pages[c.page]?.name}</td></tr>)}</tbody></table></div>}
        {tab === 'accepted' && <div className="card">{r.accepted.length === 0 && <div className="muted">Nothing accepted.</div>}{r.accepted.map((a, i) => <div key={i} className="todo"><span className="tag">{a.status}</span><div>{a.message}{a.note && <div className="small muted">Your note: {a.note}</div>}</div></div>)}</div>}
      </>}
    </div>)
}

// ------------------------------------------------------------------ Project shell
export default function Project({ id, status, onExit, initialStep }) {
  const [p, setP] = useState(null)
  const [step, setStep] = useState(null)
  const reload = useCallback(async () => { const x = await api('/projects/' + id); setP(x); return x }, [id])
  useEffect(() => { reload().then(x => setStep(s => s || initialStep || (x.reference_job?.state === 'running' ? 'setup' : ({ setup: 'setup', theme: 'design', samples: 'design', scan: 'review', generated: 'generate', built: 'generate', report: 'report' }[x.stage] || 'setup')))).catch(() => onExit()) }, [id])
  if (!p || !step) return <div className="muted">Loading…</div>
  const steps = p.mode === 'audit' ? [['setup', 'Setup'], ['review', 'Review doc'], ['report', 'Report']] : [['setup', 'Setup'], ['design', 'Colours & samples'], ['review', 'Review doc'], ['structure', 'Structure'], ['generate', 'Preview & build'], ['images', 'Images & diagrams (optional)'], ['report', 'Report']]
  const doneMap = { setup: p.has_doc, design: p.samples_approved, review: !!p.last_scan, structure: !!p.has_structure, generate: ['built', 'report'].includes(p.stage), report: p.stage === 'report' }
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}><button className="btn" onClick={onExit}>← All books</button><h2 style={{ margin: 0 }}>{p.name}</h2><span className="tag">{p.mode === 'audit' ? 'audit mode' : 'book'}</span></div>
      <div className="steps">{steps.map(([k, l], i) => <div key={k} className={'step' + (step === k ? ' on' : doneMap[k] ? ' done' : '')} onClick={() => setStep(k)}>{doneMap[k] && step !== k ? '✓ ' : `${i + 1}. `}{l}</div>)}</div>
      {step === 'setup' && <Setup p={p} reload={reload} goto={setStep} />}
      {step === 'design' && <Design p={p} reload={reload} goto={setStep} />}
      {step === 'review' && <Review p={p} reload={reload} goto={setStep} />}
      {step === 'structure' && <StructureStep p={p} reload={reload} goto={setStep} />}
      {step === 'images' && <ImagesStep p={p} goto={setStep} />}
      {step === 'generate' && <Generate p={p} reload={reload} goto={setStep} status={status} />}
      {step === 'report' && <Report p={p} reload={reload} />}
    </>)
}
