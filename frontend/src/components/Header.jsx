import { useState } from 'react'
import { api } from '../api.js'

export default function Header({ username, connected, snap, onLogout }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const kill = async () => {
    if (!window.confirm('Kill switch: stop ALL strategies, cancel open orders and close all positions?')) return
    setBusy(true)
    setResult(null)
    try { setResult(await api('/kill', { method: 'POST' })) } catch (e) { setResult({ error: e.message }) }
    setBusy(false)
  }
  const reset = async () => { await api('/kill/reset', { method: 'POST' }); setResult(null) }

  return (
    <>
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-slate-800">TradeShield</span>
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className={`inline-block w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-slate-300'}`} />
              {connected ? 'Live' : 'Reconnecting'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500 hidden sm:inline">{username}</span>
            <button className="btn" onClick={onLogout}>Sign out</button>
            <button className="px-3 py-1.5 text-sm rounded-md border border-rose-300 text-rose-700 bg-white hover:bg-rose-50 disabled:opacity-50"
              onClick={kill} disabled={busy || snap?.killed}>
              {busy ? 'Stopping...' : 'Kill switch'}
            </button>
          </div>
        </div>
      </header>

      {snap?.killed && (
        <div className="bg-rose-50 border-b border-rose-200 text-rose-800 text-sm">
          <div className="max-w-7xl mx-auto px-4 py-2 flex items-center justify-between gap-3">
            <span>
              Kill switch is active: trading is stopped.
              {result && !result.error && ` Finished in ${result.elapsed_seconds}s, positions flat: ${result.flat ? 'yes' : 'no'}.`}
              {result?.error && ` ${result.error}`}
            </span>
            <button className="btn" onClick={reset}>Reset kill switch</button>
          </div>
        </div>
      )}
      {snap?.paused && !snap?.killed && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-800 text-sm">
          <div className="max-w-7xl mx-auto px-4 py-2">Trading paused: {snap.pause_reason || 'reconciling'}...</div>
        </div>
      )}
    </>
  )
}
