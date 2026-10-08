import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, clock, money, usePoll } from '../api.js'

const AXIS = { fontSize: 11, fill: '#94a3b8' }

export function PnlChart() {
  const data = usePoll('/pnl-history', 3000)
  const pts = (data || []).map((p) => ({ t: clock(p.ts), total: p.total }))
  return (
    <section className="card">
      <div className="px-4 py-3 border-b border-slate-100 font-medium">Net P&amp;L over time</div>
      <div className="h-56 p-3">
        {pts.length < 2 ? <p className="text-sm text-slate-500 p-2">Collecting data...</p> : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pts}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="t" tick={AXIS} minTickGap={40} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} width={60} axisLine={false} tickLine={false} />
              <ReferenceLine y={0} stroke="#cbd5e1" />
              <Tooltip formatter={(v) => money(v)} />
              <Line type="monotone" dataKey="total" stroke="#475569" strokeWidth={1.8} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}

export function Candles({ snap }) {
  const symbols = Object.keys(snap.prices)
  const [symbol, setSymbol] = useState('')
  const [interval, setIv] = useState('1m')
  const [custom, setCustom] = useState('')
  const [msg, setMsg] = useState('')
  const sym = symbol || symbols[0] || ''
  const data = usePoll(`/candles?symbol=${sym}&interval=${interval}&n=60`, 2000, !!sym)

  const rows = data ? [...data.candles, ...(data.current ? [data.current] : [])] : []
  const pts = rows.map((c) => ({ t: c.interval.endsWith('t') ? `#${c.ticks}` : clock(c.start_ts), close: c.close }))

  const add = async () => {
    try {
      const r = await api('/intervals', { method: 'POST', body: { interval: custom } })
      setIv(r.interval); setCustom(''); setMsg(`Added ${r.interval}`)
    } catch (e) { setMsg(e.message) }
  }

  return (
    <section className="card">
      <div className="px-4 py-3 border-b border-slate-100 flex flex-wrap items-center gap-3">
        <span className="font-medium">Candles</span>
        <select className="input" value={sym} onChange={(e) => setSymbol(e.target.value)}>{symbols.map((s) => <option key={s}>{s}</option>)}</select>
        <select className="input" value={interval} onChange={(e) => setIv(e.target.value)}>{snap.intervals.map((i) => <option key={i}>{i}</option>)}</select>
        <span className="text-sm text-slate-500 tabular-nums">{sym && money(snap.prices[sym])}</span>
        <div className="ml-auto flex items-center gap-2">
          <input className="input w-36" placeholder="15m, 1h, 100t" value={custom} onChange={(e) => setCustom(e.target.value)} />
          <button className="btn" onClick={add} disabled={!custom}>Add interval</button>
        </div>
      </div>
      {msg && <p className="px-4 pt-2 text-xs text-slate-500">{msg}</p>}
      <div className="grid lg:grid-cols-3 gap-0">
        <div className="lg:col-span-2 h-56 p-3">
          {pts.length < 2 ? <p className="text-sm text-slate-500 p-2">Waiting for candles to close ({interval})...</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={pts}>
                <CartesianGrid stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="t" tick={AXIS} minTickGap={40} axisLine={false} tickLine={false} />
                <YAxis tick={AXIS} width={60} domain={['auto', 'auto']} axisLine={false} tickLine={false} />
                <Tooltip />
                <Line type="monotone" dataKey="close" stroke="#475569" strokeWidth={1.6} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="p-3 overflow-auto max-h-56">
          <table className="w-full text-xs tabular-nums">
            <thead><tr>{['Time', 'O', 'H', 'L', 'C'].map((h) => <th key={h} className="th px-1">{h}</th>)}</tr></thead>
            <tbody>
              {rows.slice(-8).reverse().map((c, i) => (
                <tr key={c.start_ts + '-' + i} className="border-t border-slate-100">
                  <td className="px-1 py-1 text-slate-500">{c.interval.endsWith('t') ? `${c.ticks}t` : clock(c.start_ts)}</td>
                  <td className="px-1">{c.open}</td><td className="px-1">{c.high}</td><td className="px-1">{c.low}</td><td className="px-1">{c.close}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
