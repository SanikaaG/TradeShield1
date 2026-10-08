import { useState } from 'react'
import { api, money, tone } from '../api.js'

const STATUS = {
  ACTIVE: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  STOPPED: 'bg-slate-100 text-slate-600 border-slate-200',
  HALTED_RISK: 'bg-rose-50 text-rose-700 border-rose-200',
  HALTED_ERROR: 'bg-rose-50 text-rose-700 border-rose-200',
  HALTED_KILL: 'bg-amber-50 text-amber-700 border-amber-200',
}
const LABEL = { ACTIVE: 'Active', STOPPED: 'Paused', HALTED_RISK: 'Halted by risk', HALTED_ERROR: 'Halted (error)', HALTED_KILL: 'Halted (kill switch)' }

function Bar({ pct, warn }) {
  return (
    <div className="h-1.5 w-24 bg-slate-100 rounded">
      <div className={`h-1.5 rounded ${warn ? 'bg-amber-500' : 'bg-slate-400'}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  )
}

function Row({ s, intervals }) {
  const [open, setOpen] = useState(false)
  const [lim, setLim] = useState(s.limits)
  const [interval, setInterval_] = useState(s.params.interval || '')
  const [qty, setQty] = useState(s.params.qty ?? 10)
  const [msg, setMsg] = useState('')

  const run = async (fn) => { try { setMsg(''); await fn(); setMsg('Saved') } catch (e) { setMsg(e.message) } }
  const toggle = () => run(() => (s.status === 'ACTIVE'
    ? api(`/subscriptions/${s.id}`, { method: 'DELETE' })
    : api(`/subscriptions/${s.id}/resume`, { method: 'POST' })))
  const saveLimits = () => run(() => api(`/subscriptions/${s.id}/limits`, {
    method: 'PUT', body: { max_daily_loss: Number(lim.max_daily_loss), max_position: Number(lim.max_position), max_orders_per_min: Number(lim.max_orders_per_min) } }))
  const saveParams = () => run(() => api(`/subscriptions/${s.id}/params`, {
    method: 'PUT', body: { params: { ...(interval ? { interval } : {}), qty: Number(qty) } } }))

  const eff = s.effective
  return (
    <>
      <tr className="border-t border-slate-100 align-top">
        <td className="td">
          <div className="font-medium text-slate-800">{s.name}</div>
          <div className="text-xs text-slate-500">{s.symbols.join(', ')}{s.params.interval ? ` · ${s.params.interval} candles` : ''}</div>
        </td>
        <td className="td">
          <span className={`inline-block text-xs border rounded-full px-2 py-0.5 ${STATUS[s.status] || STATUS.STOPPED}`}>{LABEL[s.status] || s.status}</span>
          {s.halt_reason && s.status !== 'ACTIVE' && <div className="text-xs text-slate-500 mt-1 max-w-[220px] whitespace-normal">{s.halt_reason}</div>}
        </td>
        <td className="td tabular-nums">
          {s.positions.length === 0 ? <span className="text-slate-400">flat</span> : s.positions.map((p) => (
            <div key={p.symbol}>{p.symbol} <span className={tone(p.qty)}>{p.qty > 0 ? '+' : ''}{p.qty}</span> <span className="text-xs text-slate-400">@ {p.avg_price}</span></div>
          ))}
        </td>
        <td className="td tabular-nums">
          <div className={`font-medium ${tone(s.pnl.total_net)}`}>{money(s.pnl.total_net)}</div>
          <div className="text-xs text-slate-400">realised {money(s.pnl.realized_net)} · charges {money(s.pnl.charges)}</div>
        </td>
        <td className="td">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Bar pct={eff.loss_used_pct} warn={eff.loss_used_pct >= 50} /> loss {eff.loss_used_pct}% of {money(s.limits.max_daily_loss)}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            orders {s.orders_last_min}/{eff.max_orders_per_min} per min · max pos {eff.max_position}
            {eff.shield_tier > 0 && <span className="ml-2 text-amber-700 border border-amber-200 bg-amber-50 rounded px-1">shield tier {eff.shield_tier}</span>}
          </div>
        </td>
        <td className="td text-right">
          <button className="btn mr-2" onClick={toggle}>{s.status === 'ACTIVE' ? 'Pause' : 'Resume'}</button>
          <button className="btn" onClick={() => setOpen(!open)}>{open ? 'Close' : 'Settings'}</button>
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-50 border-t border-slate-100">
          <td className="td" colSpan={6}>
            <div className="flex flex-wrap gap-6 items-end">
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1">Risk limits (enforced by the platform)</div>
                <div className="flex gap-2 items-end">
                  {[['max_daily_loss', 'Max daily loss'], ['max_position', 'Max position'], ['max_orders_per_min', 'Max orders/min']].map(([k, label]) => (
                    <label key={k} className="text-xs text-slate-500">{label}
                      <input className="input w-28 block" type="number" value={lim[k]} onChange={(e) => setLim({ ...lim, [k]: e.target.value })} />
                    </label>
                  ))}
                  <button className="btn-primary" onClick={saveLimits}>Save limits</button>
                </div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1">Strategy settings</div>
                <div className="flex gap-2 items-end">
                  {s.params.interval !== undefined && (
                    <label className="text-xs text-slate-500">Candle interval
                      <select className="input block w-28" value={interval} onChange={(e) => setInterval_(e.target.value)}>
                        {[...new Set([interval, ...intervals])].filter(Boolean).map((i) => <option key={i}>{i}</option>)}
                      </select>
                    </label>
                  )}
                  <label className="text-xs text-slate-500">Order qty
                    <input className="input w-24 block" type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
                  </label>
                  <button className="btn-primary" onClick={saveParams}>Save</button>
                </div>
              </div>
              {msg && <span className="text-xs text-slate-500">{msg}</span>}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function MyStrategies({ snap }) {
  return (
    <section className="card overflow-x-auto">
      <div className="px-4 py-3 border-b border-slate-100 font-medium">My strategies</div>
      {snap.subs.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">You are not subscribed to anything yet. Pick a strategy below.</p>
      ) : (
        <table className="w-full">
          <thead><tr>{['Strategy', 'Status', 'Position', 'Net P&L', 'Risk usage', ''].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{snap.subs.map((s) => <Row key={s.id} s={s} intervals={snap.intervals} />)}</tbody>
        </table>
      )}
    </section>
  )
}

export function Catalog({ catalog }) {
  const [err, setErr] = useState('')
  const subscribe = async (key) => { try { setErr(''); await api('/subscriptions', { method: 'POST', body: { strategy_key: key } }) } catch (e) { setErr(e.message) } }
  if (!catalog) return null
  return (
    <section className="card">
      <div className="px-4 py-3 border-b border-slate-100 font-medium">Available strategies</div>
      <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        {catalog.map((c) => (
          <div key={c.key} className="border border-slate-200 rounded-md p-3 flex flex-col">
            <div className="font-medium text-sm">{c.name}{c.demo && <span className="ml-2 text-xs text-slate-500 border border-slate-200 rounded px-1">stress test</span>}</div>
            <p className="text-xs text-slate-500 mt-1 flex-1">{c.description}</p>
            <div className="text-xs text-slate-400 mt-2">Limits: loss {money(c.default_limits.max_daily_loss)} · pos {c.default_limits.max_position} · {c.default_limits.max_orders_per_min}/min</div>
            <button className="btn mt-3" onClick={() => subscribe(c.key)}>{c.subscription_id ? 'Re-activate' : 'Subscribe'}</button>
          </div>
        ))}
      </div>
      {err && <p className="px-4 pb-3 text-sm text-rose-700">{err}</p>}
    </section>
  )
}
