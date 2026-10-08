import { useState } from 'react'
import { clock, money, usePoll } from '../api.js'

const ST = {
  FILLED: 'text-emerald-700', PARTIAL: 'text-slate-700', OPEN: 'text-slate-700', SENT: 'text-slate-500',
  NEW: 'text-slate-500', UNKNOWN: 'text-amber-700', BLOCKED: 'text-rose-700', REJECTED: 'text-rose-700',
  FAILED: 'text-rose-700', CANCELLED: 'text-slate-500', EXPIRED: 'text-slate-500',
}

export default function Tables({ snap }) {
  const [tab, setTab] = useState('activity')
  const [cat, setCat] = useState('')
  const orders = usePoll('/orders?limit=60', 2000, tab === 'orders')
  const trades = usePoll('/trades?limit=60', 2000, tab === 'trades')
  const events = usePoll(`/events?limit=80${cat ? `&category=${cat}` : ''}`, 2000, tab === 'activity')
  const name = (id) => snap.subs.find((s) => s.id === id)?.name || (id === 0 ? 'Unattributed' : `#${id}`)

  const Tab = ({ id, children }) => (
    <button onClick={() => setTab(id)} className={`px-3 py-3 text-sm border-b-2 ${tab === id ? 'border-slate-700 text-slate-800' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>{children}</button>
  )

  return (
    <section className="card">
      <div className="px-4 border-b border-slate-100 flex items-center gap-2">
        <Tab id="activity">Activity log</Tab><Tab id="orders">Orders</Tab><Tab id="trades">Trades</Tab>
        {tab === 'activity' && (
          <select className="input ml-auto" value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All</option><option value="decision">Order decisions</option><option value="incident">Incidents</option>
          </select>
        )}
      </div>
      <div className="overflow-x-auto max-h-96 overflow-y-auto">
        {tab === 'activity' && (
          <table className="w-full"><tbody>
            {(events || []).map((e) => (
              <tr key={e.id} className="border-t border-slate-100 first:border-0">
                <td className="td text-slate-400 tabular-nums">{clock(e.ts)}</td>
                <td className="td"><span className={`text-xs border rounded px-1.5 py-0.5 ${e.category === 'incident' ? 'border-amber-200 bg-amber-50 text-amber-800' : e.kind === 'BLOCK' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-600'}`}>{e.kind}</span></td>
                <td className="td whitespace-normal text-slate-700">{e.message}</td>
              </tr>
            ))}
            {events && events.length === 0 && <tr><td className="td text-slate-500">Nothing yet.</td></tr>}
          </tbody></table>
        )}
        {tab === 'orders' && (
          <table className="w-full tabular-nums">
            <thead><tr>{['Time', 'Strategy', 'Side', 'Symbol', 'Qty', 'Filled', 'Avg', 'Status', 'Why'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>
              {(orders || []).map((o) => (
                <tr key={o.client_order_id} className="border-t border-slate-100">
                  <td className="td text-slate-400">{clock(o.created_ts)}</td><td className="td">{name(o.sub_id)}</td>
                  <td className="td">{o.side}</td><td className="td">{o.symbol}</td><td className="td">{o.qty}</td>
                  <td className="td">{o.filled_qty}</td><td className="td">{o.avg_price ? o.avg_price.toFixed(2) : '-'}</td>
                  <td className={`td ${ST[o.status] || ''}`}>{o.status}</td>
                  <td className="td text-xs text-slate-500 max-w-md truncate" title={o.reason}>{o.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === 'trades' && (
          <table className="w-full tabular-nums">
            <thead><tr>{['Time', 'Strategy', 'Side', 'Symbol', 'Qty', 'Price', 'Charges', 'Realised (gross)', 'Net of charges'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>
              {(trades || []).map((f) => (
                <tr key={f.fill_id} className="border-t border-slate-100">
                  <td className="td text-slate-400">{clock(f.ts)}</td><td className="td">{name(f.sub_id)}</td>
                  <td className="td">{f.side}</td><td className="td">{f.symbol}</td><td className="td">{f.qty}</td>
                  <td className="td">{f.price.toFixed(2)}</td><td className="td">{money(f.charges)}</td>
                  <td className="td">{money(f.realized_pnl)}</td><td className="td">{money(f.realized_pnl - f.charges)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
