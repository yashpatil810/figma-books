import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api.js'
import Project from './Project.jsx'

function Settings({ status, reload, onClose }) {
  const [token, setToken] = useState('')
  const [models, setModels] = useState(status.models)
  const [bin, setBin] = useState('')
  const save = async () => {
    await api('/settings', { method: 'PUT', body: { models, ...(token ? { figma_token: token } : {}), ...(bin ? { claude_bin: bin } : {}) } })
    setToken(''); reload(); onClose()
  }
  const opts = ['haiku', 'sonnet', 'opus']
  return (
    <div className="card">
      <h2>Settings</h2>
      <div className="grid2">
        <div>
          <label>Claude Code CLI (uses your Max plan, no API key)</label>
          <div className={status.claude.ok ? 'ok-t' : 'err-t'}>{status.claude.ok ? `Connected · ${status.claude.version}` : status.claude.error}</div>
          <div className="muted small">{status.claude.bin}</div>
          <label>Custom path to the claude binary (optional)</label>
          <input type="text" value={bin} onChange={e => setBin(e.target.value)} placeholder="/path/to/claude" />
          <label>Figma access token {status.figma_token ? '(saved)' : '(missing)'}</label>
          <input type="text" value={token} onChange={e => setToken(e.target.value)} placeholder="figd_… (leave blank to keep the saved one)" />
          <div className="small muted" style={{ marginTop: 6 }}>Fonts on this computer: Avenir {status.fonts.avenir ? '✓' : '✗'} · DIN Condensed {status.fonts.din_condensed ? '✓' : '✗'}</div>
        </div>
        <div>
          <label>Models by task</label>
          {[['scan', 'Doc review (accuracy)'], ['judge', 'Judging differences / your answers'], ['spelling', 'Spelling triage'], ['structure', 'Structure fallbacks'], ['rules', 'Rules drafting']].map(([k, l]) => (
            <div className="row" key={k} style={{ marginBottom: 4 }}><span style={{ width: 230 }} className="small">{l}</span>
              <select style={{ width: 120 }} value={models[k]} onChange={e => setModels({ ...models, [k]: e.target.value })}>{opts.map(o => <option key={o}>{o}</option>)}</select></div>))}
          <div className="muted small" style={{ marginTop: 8 }}>Exact text comparison and the score are plain code, not the model.</div>
        </div>
      </div>
      <div className="row" style={{ marginTop: 12 }}><button className="btn primary" onClick={save}>Save</button><button className="btn" onClick={onClose}>Close</button></div>
    </div>)
}

function NewProject({ mode, onCreated, onCancel }) {
  const [f, setF] = useState({ name: '', doc_url: '', figma_url: '', subject: '', module: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF({ ...f, [k]: e.target.value })
  const go = async () => {
    setBusy(true); setErr('')
    try {
      const p = await api('/projects', { method: 'POST', body: { name: f.name || (mode === 'audit' ? 'Audit' : 'New book'), mode, doc_url: f.doc_url, figma_url: f.figma_url, meta: { subject: f.subject, module: f.module } } })
      await api(`/projects/${p.id}/fetch`, { method: 'POST' })
      onCreated(p.id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="card">
      <h2>{mode === 'audit' ? 'Audit an existing Figma against its Google Doc' : 'New book from a Google Doc'}</h2>
      <label>Name</label><input type="text" value={f.name} onChange={set('name')} placeholder="e.g. Physics Grade 7 – Electricity" />
      <label>Google Doc link (set to “Anyone with the link can view”)</label><input type="url" value={f.doc_url} onChange={set('doc_url')} placeholder="https://docs.google.com/document/d/…" />
      {mode === 'audit' && <><label>Figma link (select the section or page in Figma → right-click → Copy link)</label><input type="url" value={f.figma_url} onChange={set('figma_url')} placeholder="https://www.figma.com/design/…?node-id=…" /></>}
      <div className="grid2">
        <div><label>Subject (used in the footer, e.g. Physics)</label><input type="text" value={f.subject} onChange={set('subject')} /></div>
        <div><label>Module / chapter number (e.g. 2)</label><input type="text" value={f.module} onChange={set('module')} /></div>
      </div>
      {err && <div className="banner err" style={{ marginTop: 10 }}>{err}</div>}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={busy || !f.doc_url || (mode === 'audit' && !f.figma_url)} onClick={go}>{busy ? 'Reading the doc…' : 'Create and read the doc'}</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>)
}

export default function App() {
  const [status, setStatus] = useState(null)
  const [projects, setProjects] = useState([])
  const [open, setOpen] = useState(() => location.hash.slice(1).split('/')[0] || null)
  const [initialStep] = useState(() => location.hash.slice(1).split('/')[1] || null)
  const [creating, setCreating] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const reload = useCallback(async () => { setStatus(await api('/status')); setProjects(await api('/projects')) }, [])
  useEffect(() => { reload().catch(() => setStatus({ offline: true })) }, [reload])
  useEffect(() => { location.hash = open || '' }, [open])
  if (!status) return <div className="wrap muted">Loading…</div>
  if (status.offline) return <div className="wrap"><div className="banner err">Cannot reach the backend on port 8765. Start it with ./run.sh</div></div>
  return (
    <>
      <div className="top">
        <h1 onClick={() => { setOpen(null); setCreating(null); reload() }}>📚 Book Builder</h1>
        <span className={status.claude.ok ? 'tag' : 'tag error'}>{status.claude.ok ? 'Claude connected' : 'Claude not connected'}</span>
        {!status.figma_token && <span className="tag warning">Figma token missing</span>}
        <div className="sp" />
        <button className="btn" onClick={() => setShowSettings(!showSettings)}>Settings</button>
      </div>
      <div className="wrap">
        {showSettings && <Settings status={status} reload={reload} onClose={() => setShowSettings(false)} />}
        {open ? <Project id={open} initialStep={initialStep} status={status} onExit={() => { setOpen(null); reload() }} /> :
          creating ? <NewProject mode={creating} onCancel={() => setCreating(null)} onCreated={id => { setCreating(null); setOpen(id) }} /> :
            <>
              <div className="row" style={{ marginBottom: 14 }}>
                <button className="btn primary" onClick={() => setCreating('create')}>＋ New book from Google Doc</button>
                <button className="btn" onClick={() => setCreating('audit')}>Audit an existing Figma</button>
              </div>
              <div className="card"><h2>Your books</h2>
                {projects.length === 0 && <div className="muted">Nothing yet. Start with “New book”.</div>}
                {projects.map(p => (
                  <div key={p.id} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                    <a href={'#' + p.id} onClick={() => setOpen(p.id)} style={{ flex: 1, cursor: 'pointer', color: 'var(--brand)', fontWeight: 600 }}>{p.name}</a>
                    <span className="tag">{p.mode === 'audit' ? 'audit' : 'book'}</span><span className="muted small">{p.stage}</span>
                    <button className="btn danger" onClick={async () => { if (confirm('Delete this project and its data?')) { await api('/projects/' + p.id, { method: 'DELETE' }); reload() } }}>Delete</button>
                  </div>))}
              </div></>}
      </div>
    </>)
}
