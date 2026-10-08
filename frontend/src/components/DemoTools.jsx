import { useEffect, useState } from 'react'
import { api } from '../api.js'

const SWITCHES = [
  { key: 'error_rate', on: 0.5, off: 0, label: 'Network errors', hint: '50% of orders never reach the exchange' },
  { key: 'ack_loss_rate', on: 0.5, off: 0, label: 'Lost acknowledgements', hint: 'exchange takes the order, reply is lost' },
  { key: 'reject_rate', on: 0.3, off: 0, label: 'Rejections', hint: '30% of orders rejected' },
  { key: 'fill_probability', on: 0.15, off: 1, label: 'Slow fills', hint: 'orders stay open longer (partial fills)' },
]

export default function DemoTools({ snap }) {
  const [chaos, setChaos] = useState(null)
  const [out, setOut] = useState('')
  const [busy, setBusy] = useState('')
  const [subId, setSubId] = useState('')

  const load = () => api('/admin/chaos').then(setChaos).catch(() => setChaos(null))
  useEffect(() => { load() }, [])

  const flip = async (sw) => {
    const isOn = chaos && chaos[sw.key] !== sw.off
    setChaos(await api('/admin/chaos', { method: 'POST', body: { [sw.key]: isOn ? sw.off : sw.on } }))
  }
  const run = async (name, fn) => {
    setBusy(name); setOut('')
    try { setOut(JSON.stringify(await fn(), null, 2)) } catch (e) { setOut(e.message) }
    setBusy('')
  }
  const sid = Number(subId || snap.subs[0]?.id || 0)

  return (
    <details className="card">
      <summary className="px-4 py-3 font-medium cursor-pointer select-none">Demo and test tools</summary>
      <div className="px-4 pb-4 space-y-4 border-t border-slate-100 pt-3">
        <p className="text-xs text-slate-500">Break things on purpose to show the platform stays safe. Failure injection works with the mock exchange only.</p>
        <div className="flex flex-wrap gap-2">
          {SWITCHES.map((sw) => {
            const isOn = chaos && chaos[sw.key] !== sw.off
            return (
              <button key={sw.key} title={sw.hint} disabled={!chaos} onClick={() => flip(sw)}
                className={`btn ${isOn ? '!bg-amber-50 !border-amber-300 !text-amber-800' : ''}`}>{sw.label}: {isOn ? 'on' : 'off'}</button>
            )
          })}
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <button className="btn" disabled={!!busy} onClick={() => run('crash', () => api('/admin/simulate-crash', { method: 'POST', body: { downtime: 3 } }))}>
            {busy === 'crash' ? 'Recovering...' : 'Simulate server crash'}
          </button>
          <button className="btn" disabled={!!busy} onClick={() => run('rec', () => api('/admin/reconcile', { method: 'POST' }))}>Reconcile now</button>
          <span className="text-slate-300">|</span>
          <select className="input" value={subId} onChange={(e) => setSubId(e.target.value)}>
            {snap.subs.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button className="btn" disabled={!!busy || !sid} onClick={() => run('dup', () => api('/admin/duplicate-test', { method: 'POST', body: { subscription_id: sid } }))}>
            Send same order twice
          </button>
        </div>
        {out && <pre className="text-xs bg-slate-50 border border-slate-200 rounded p-3 overflow-auto max-h-60">{out}</pre>}
      </div>
    </details>
  )
}
