export async function api(path, opts = {}) {
  const r = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined })
  const text = await r.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!r.ok) throw new Error((data && (data.detail?.[0]?.msg || data.detail)) || r.statusText)
  return data
}
