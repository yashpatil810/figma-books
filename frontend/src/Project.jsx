import React, { useEffect, useState, useCallback, useRef } from 'react'
import { api } from './api.js'
import { Page } from './Page.jsx'

function usePoll(fn, active, ms = 1500) {
  useEffect(() => { if (!active) return; const t = setInterval(fn, ms); return () => clearInterval(t) }, [active, fn, ms])
}

const ROLE_LABEL = { body: 'Normal content (new page)', exercise: 'Exercise / questions', answers: 'Answers / solutions', mindmap: 'Mind map', references: 'References', glossary: 'Glossary', inline: 'Just a heading (no new page)', ignore: 'Leave out' }

function StructurePanel({ p, reload }) {
  const [st, setSt] = useState(null)
  const [roles, setRoles] = useState({})
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const load = useCallback(async () => { const d = await api(`/projects/${p.id}/structure`); setSt(d); setRoles(Object.fromEntries(d.candidates.filter(c => c.role).map(c => [c.src, c.role]))) }, [p.id])
  useEffect(() => { load().catch(() => {}) }, [load])
  if (!st) return null
  const save = async (extra = {}) => { setBusy(true); try { setSt(await api(`/projects/${p.id}/structure`, { method: 'PUT', body: { roles, ...extra } })); reload() } finally { setBusy(false) } }
  const pg = x => x ? <span className="tag" style={{ background: '#fff4d6', color: '#7a5200' }}>doc p.{x}</span> : null
  return (
    <div className="card">
      <h2>How I read your document</h2>
      <div className="muted small" style={{ marginBottom: 8 }}>Your documents don't all share one layout. Sections like synopsis, key ideas or tests are only used when the doc has them. Check this reading and correct anything that looks off.</div>
      <div className="row">
        <label style={{ margin: 0 }}>Layout</label>
        <select style={{ width: 300 }} value={st.chosen} onChange={e => save({ profile: e.target.value })}>
          <option value="auto">Auto-detect (found: {st.detected === 'synopsis' ? 'synopsis template' : 'generic chapter'})</option>
          <option value="synopsis">Synopsis template (key ideas, synopses, tests)</option>
          <option value="generic">Generic chapter (follows your headings)</option>
        </select>
        <span className="tag">{st.profile === 'synopsis' ? 'reading as: synopsis template' : 'reading as: generic chapter'}</span>
      </div>
      <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>Sections found</h3>
      {st.outline.map((o, i) => <div key={i} className="row" style={{ padding: '4px 0', borderBottom: '1px solid var(--line)', gap: 8 }}><span className="tag">{o.kind}</span><b style={{ flex: 1 }}>{o.title}</b>{pg(o.page)}<span className="muted small">{o.blocks} blocks</span></div>)}
      {st.outline.length === 0 && <div className="muted small">Sections come from the synopsis template reading.</div>}
      {st.notes.length > 0 && <div style={{ marginTop: 10 }}>{st.notes.map((n, i) => <div key={i} className="small" style={{ margin: '3px 0' }}><span className={`tag ${n.severity === 'question' ? 'question' : 'info'}`}>{n.severity}</span> {n.message}</div>)}</div>}
      {st.ignored.length > 0 && <div className="small muted" style={{ marginTop: 8 }}>Left out of the pages: {st.ignored.slice(0, 6).map(x => `“${x.text || x.id}” (${x.reason})`).join('; ')}{st.ignored.length > 6 ? '…' : ''}</div>}
      <div style={{ marginTop: 10 }}><button className="btn" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Adjust'} how headings are read ({st.candidates.length} headings)</button></div>
      {open && <div style={{ marginTop: 8 }}>
        <table className="t"><thead><tr><th>Heading</th><th>Level</th><th>Doc page</th><th>Treat it as</th></tr></thead><tbody>
          {st.candidates.map(c => <tr key={c.src}><td>{c.text}</td><td>H{c.level}</td><td>{c.page || ''}</td><td>
            <select value={roles[c.src] || ''} onChange={e => setRoles({ ...roles, [c.src]: e.target.value })}>
              <option value="">Automatic{(st.dividers.find(d => d.src === c.src)?.role) ? ` (${ROLE_LABEL[st.dividers.find(d => d.src === c.src).role]})` : ' (heading inside the page)'}</option>
              {st.roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select></td></tr>)}
        </tbody></table>
        <div className="row" style={{ marginTop: 8 }}><button className="btn primary" disabled={busy} onClick={() => save()}>{busy ? 'Applying…' : 'Apply'}</button><span className="muted small">Page and section order update right away. Re-scan the doc afterwards.</span></div>
      </div>}
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
    {p.has_doc && <StructurePanel p={p} reload={reload} />}
    </>)
}

// ------------------------------------------------------------------ Design (colours + samples)
const KEYS = ['primary', 'text', 'strong', 'tint', 'white', 'rule', 'footerRule', 'tableAlt', 'tableBorder', 'onPrimary']
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
  useEffect(() => { api(`/projects/${p.id}/samples`).then(setSamples); api(`/projects/${p.id}/rules`).then(r => { setRules(r); setEdit(r.prompt); setLabels(r.labels) }) }, [p.id])
  const setC = (k, v, sub) => { setDirty(true); setApproved(false); setTheme(sub ? { ...theme, [k]: { ...theme[k], [sub]: v } } : { ...theme, [k]: v }) }
  const save = async () => { await api(`/projects/${p.id}/theme`, { method: 'PUT', body: theme }); setDirty(false); const r = await api(`/projects/${p.id}/rules`); setRules(r); setEdit(r.prompt); reload() }
  const approve = async () => { if (dirty) await save(); await api(`/projects/${p.id}/approve-samples?approved=true`, { method: 'POST' }); setApproved(true); reload() }
  return (
    <div>
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
          {running && <div style={{ flex: 1, minWidth: 200 }}><div className="small muted">{data.job.message}</div><div className="bar"><i style={{ width: `${Math.max(5, (data.job.progress || 0) * 100)}%` }} /></div></div>}
          {data.job?.state === 'error' && <span className="err-t">{data.job.message}</span>}
        </div>
        <div className="muted small" style={{ marginTop: 6 }}>Re-scan re-reads your Google Doc, so edit the doc, mark the item done, then re-scan. Your earlier answers are kept.</div>
        {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
      </div>
      {scanned && (openB === 0
        ? <div className="banner ok"><b>All clear.</b> Nothing blocking is left, so you can continue. {p.mode === 'create' ? <button className="btn ok" style={{ marginLeft: 10 }} onClick={() => goto('images')}>Continue to Images →</button> : <button className="btn ok" style={{ marginLeft: 10 }} onClick={() => goto('report')}>Continue to the report →</button>}</div>
        : <div className="banner err"><b>{openB} item{openB > 1 ? 's' : ''} still need{openB > 1 ? '' : 's'} your answer.</b> Fix them in the doc and re-scan, or answer them below.{p.mode === 'create' && <button className="btn" style={{ marginLeft: 10 }} onClick={proceed}>Proceed anyway…</button>}</div>)}
      {scanned && <div className="tabs">{[['open', `Open (${fs.filter(f => f.status === 'open').length})`], ['resolved', `Resolved (${fs.filter(f => f.status !== 'open').length})`], ['all', 'All']].map(([k, l]) => <div key={k} className={'tab' + (filter === k ? ' on' : '')} onClick={() => setFilter(k)}>{l}</div>)}<div style={{ flex: 1 }} /><label style={{ margin: 0, alignSelf: 'center' }}><input type="checkbox" checked={byPage} onChange={e => setByPage(e.target.checked)} /> Order by doc page</label></div>}
      {shown.map(f => <FindingCard key={f.id} f={f} pid={p.id} onChange={load} />)}
      {scanned && shown.length === 0 && <div className="muted">Nothing in this list.</div>}
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
  const diagrams = im.filter(e => e.class === 'diagram' || (e.mode === 'generate' && !e.tiny))
  const others = im.filter(e => !diagrams.includes(e) && !e.tiny)
  const tiny = im.filter(e => e.tiny)
  const analysed = im.some(e => e.class && e.class !== 'inline')
  const pgTxt = e => e.pages?.length ? `doc p.${e.pages.slice(0, 3).join(', ')}${e.pages.length > 3 ? '…' : ''}` : ''
  const toggle = e => act(() => api(`/projects/${p.id}/images/${e.hash}`, { method: 'PATCH', body: { mode: e.mode === 'generate' ? 'placeholder' : 'generate' } }))
  const gen = e => act(() => api(`/projects/${p.id}/images/${e.hash}/generate`, { method: 'POST' }))
  const Card = ({ e }) => {
    const j = d.gen_jobs?.[e.hash]
    const working = j?.state === 'running'
    return (
      <div className="finding" style={{ borderLeftColor: e.mode === 'generate' ? '#2848a0' : undefined }}>
        <div className="row" style={{ gap: 8, marginBottom: 6 }}>
          <span className="tag">{e.class || 'not analysed'}</span>{e.complexity && <span className="tag">{e.complexity}</span>}<span className="muted small">{pgTxt(e)} · used {e.count}×</span>
          {e.status === 'generated' && e.match != null && <span className={'tag ' + (e.match >= 92 ? '' : 'warning')} style={e.match >= 92 ? { background: '#e4f5ea', color: 'var(--ok)' } : {}}>{e.match}% match</span>}
          <div style={{ flex: 1 }} />
          <label style={{ margin: 0 }}><input type="checkbox" checked={e.mode === 'generate'} onChange={() => toggle(e)} /> Draw as a diagram</label>
        </div>
        <div className="muted small" style={{ marginBottom: 6 }}>{e.reason}</div>
        <div className="row" style={{ alignItems: 'flex-start', gap: 14 }}>
          <div><div className="small muted">Original</div><img src={`/api/projects/${p.id}/media/${e.hash}`} style={{ maxWidth: 260, maxHeight: 220, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }} /></div>
          {e.has_svg && <div><div className="small muted">Generated drawing</div><img src={`/api/projects/${p.id}/diagrams/${e.hash}`} style={{ maxWidth: 260, maxHeight: 220, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }} /></div>}
          <div style={{ flex: 1, minWidth: 200 }}>
            {e.mode === 'generate' && <button className="btn" disabled={working || !d.chrome && false} onClick={() => gen(e)}>{working ? (j.message || 'Drawing…') : e.has_svg ? '↻ Redraw' : 'Generate drawing'}</button>}
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
        <div className="muted small" style={{ marginBottom: 8 }}>Real diagrams (geometric figures, graphs, circuits, experiment set-ups…) are drawn for you as editable vector shapes in Figma. Everything else (equations, photos, artwork) stays a labelled placeholder that you replace by hand. You can switch any picture either way.</div>
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => act(() => api(`/projects/${p.id}/images/analyse`, { method: 'POST' }))}>{analysed ? '↻ Analyse new pictures' : 'Analyse the pictures'}</button>
          {analysed && <button className="btn" disabled={busy} onClick={() => act(() => api(`/projects/${p.id}/images/generate-all`, { method: 'POST' }))}>Draw all missing diagrams</button>}
          {busy && <div style={{ flex: 1, minWidth: 220 }}><div className="small muted">{d.job?.state === 'running' ? d.job.message : d.gen_job?.state === 'running' ? d.gen_job.message : 'Drawing…'}</div><div className="bar"><i style={{ width: `${Math.max(5, ((d.job?.state === 'running' ? d.job.progress : d.gen_job?.progress) || 0.1) * 100)}%` }} /></div></div>}
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>{d.summary.total} distinct pictures · {d.summary.tiny} tiny inline symbols (always placeholders) · {d.summary.diagrams} to be drawn · {d.summary.generated} drawn</div>
        {d.needs_media && <div className="banner warn" style={{ marginTop: 8 }}>The pictures of this document have not been loaded into the app yet (this project was made before diagrams existed). <button className="btn" style={{ marginLeft: 8 }} disabled={busy} onClick={() => act(async () => { await api(`/projects/${p.id}/fetch`, { method: 'POST' }); })}>Load the pictures (re-reads the doc)</button></div>}
        {!d.chrome && <div className="banner warn" style={{ marginTop: 8 }}>Chrome was not found on this computer, so drawings cannot be checked visually against the original before you see them.</div>}
        {err && <div className="banner err" style={{ marginTop: 8 }}>{err}</div>}
        {!analysed && !busy && <div className="banner info" style={{ marginTop: 8 }}>Not analysed yet. If you skip this, every picture becomes a placeholder.</div>}
      </div>
      {diagrams.length > 0 && <><h3 style={{ margin: '14px 0 8px' }}>Diagrams ({diagrams.length})</h3>{diagrams.map(e => <Card key={e.hash} e={e} />)}</>}
      {others.length > 0 && <div className="card">
        <div className="row"><b>Other pictures ({others.length}): placeholders</b><span className="muted small">equations, photos, artwork</span><div style={{ flex: 1 }} /><button className="btn" onClick={() => setShowAll(!showAll)}>{showAll ? 'Hide' : 'Review them'}</button></div>
        {showAll && <div className="row" style={{ marginTop: 10, gap: 10, alignItems: 'flex-start' }}>
          {others.slice(0, 80).map(e => <div key={e.hash} style={{ width: 150 }}><img src={`/api/projects/${p.id}/media/${e.hash}`} style={{ maxWidth: 150, maxHeight: 90, border: '1px solid var(--line)', background: '#fff' }} /><div className="small muted">{e.class} {pgTxt(e)}</div><label className="small" style={{ margin: 0 }}><input type="checkbox" checked={e.mode === 'generate'} onChange={() => toggle(e)} /> draw as diagram</label></div>)}
          {others.length > 80 && <div className="muted small">…and {others.length - 80} more</div>}
        </div>}
      </div>}
      {tiny.length > 0 && <div className="muted small" style={{ margin: '8px 0' }}>{tiny.length} tiny inline pictures (symbols or equation pieces) are always placeholders.</div>}
      <div className="row" style={{ marginTop: 12 }}><button className="btn ok" onClick={() => goto('generate')}>Continue to Generate →</button></div>
    </div>)
}

// ------------------------------------------------------------------ Generate
function Generate({ p, reload, goto }) {
  const [spec, setSpec] = useState(null)
  const [err, setErr] = useState('')
  const [res, setRes] = useState(null)
  const [rep, setRep] = useState(null)
  useEffect(() => { api(`/projects/${p.id}/spec`).then(setSpec).catch(e => setErr(e.message)) }, [p.id])
  const poll = useCallback(async () => setRep(await api(`/projects/${p.id}/plugin-report`)), [p.id])
  usePoll(poll, !!res && !rep?.sectionId, 2000)
  useEffect(() => { poll() }, [poll])
  const gen = async () => { setErr(''); try { setRes(await api(`/projects/${p.id}/generate`, { method: 'POST' })); reload() } catch (e) { setErr(e.message) } }
  if (err && !spec) return <div className="banner err">{err}</div>
  if (!spec) return <div className="muted">Laying out the book…</div>
  const issues = spec.issues || []
  return (
    <div>
      <div className="card">
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
        <div className="row"><button className="btn primary" onClick={gen}>Generate</button>
          {res && !rep?.sectionId && <span className="muted">Design ready ({res.pages} pages). Waiting for the plugin to build it in Figma…</span>}
          {rep?.sectionId && <span className="ok-t">✓ Built {rep.pages.length} pages in Figma{rep.pages.some(x => x.overflow) ? ` — ${rep.pages.filter(x => x.overflow).length} page(s) overflow` : ''}{rep.errors?.length ? `, ${rep.errors.length} errors` : ''}.</span>}
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
  useEffect(() => { reload().then(x => setStep(s => s || initialStep || ({ setup: 'setup', theme: 'design', samples: 'design', scan: 'review', generated: 'generate', built: 'generate', report: 'report' }[x.stage] || 'setup'))).catch(() => onExit()) }, [id])
  if (!p || !step) return <div className="muted">Loading…</div>
  const steps = p.mode === 'audit' ? [['setup', 'Setup'], ['review', 'Review doc'], ['report', 'Report']] : [['setup', 'Setup'], ['design', 'Colours & samples'], ['review', 'Review doc'], ['images', 'Images & diagrams'], ['generate', 'Generate'], ['report', 'Report']]
  const doneMap = { setup: p.has_doc, design: p.samples_approved, review: !!p.last_scan, generate: ['built', 'report'].includes(p.stage), report: p.stage === 'report' }
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}><button className="btn" onClick={onExit}>← All books</button><h2 style={{ margin: 0 }}>{p.name}</h2><span className="tag">{p.mode === 'audit' ? 'audit mode' : 'book'}</span></div>
      <div className="steps">{steps.map(([k, l], i) => <div key={k} className={'step' + (step === k ? ' on' : doneMap[k] ? ' done' : '')} onClick={() => setStep(k)}>{doneMap[k] && step !== k ? '✓ ' : `${i + 1}. `}{l}</div>)}</div>
      {step === 'setup' && <Setup p={p} reload={reload} goto={setStep} />}
      {step === 'design' && <Design p={p} reload={reload} goto={setStep} />}
      {step === 'review' && <Review p={p} reload={reload} goto={setStep} />}
      {step === 'images' && <ImagesStep p={p} goto={setStep} />}
      {step === 'generate' && <Generate p={p} reload={reload} goto={setStep} />}
      {step === 'report' && <Report p={p} reload={reload} />}
    </>)
}
