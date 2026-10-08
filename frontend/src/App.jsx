import { useEffect, useState } from 'react'
import { api, getToken, money, setToken, tone, useLive } from './api.js'
import Header from './components/Header.jsx'
import Login from './components/Login.jsx'
import { Catalog, MyStrategies } from './components/Strategies.jsx'
import { Candles, PnlChart } from './components/Charts.jsx'
import Tables from './components/Tables.jsx'
import DemoTools from './components/DemoTools.jsx'

function Stat({ label, children, sub }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-xl font-semibold mt-1 tabular-nums">{children}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  )
}

function Dashboard({ username, onLogout }) {
  const { snap, connected } = useLive(getToken())
  const [catalog, setCatalog] = useState(null)

  useEffect(() => {
    const load = () => api('/strategies').then(setCatalog).catch(() => {})
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [])

  const active = snap ? snap.subs.filter((s) => s.status === 'ACTIVE').length : 0
  const openOrders = snap ? snap.subs.reduce((a, s) => a + s.open_orders, 0) : 0
  const positions = snap ? Object.entries(snap.account_positions).filter(([, q]) => q !== 0) : []

  return (
    <div className="min-h-screen">
      <Header username={username} connected={connected} snap={snap} onLogout={onLogout} />
      <main className="max-w-7xl mx-auto px-4 py-6 space-y-5">
        {!snap ? <p className="text-sm text-slate-500">Connecting...</p> : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Stat label="Net P&L (after charges)"><span className={tone(snap.total_net)}>{money(snap.total_net)}</span></Stat>
              <Stat label="Active strategies" sub={`${snap.subs.length} subscribed`}>{active}</Stat>
              <Stat label="Open orders">{openOrders}</Stat>
              <Stat label="Account positions" sub="all strategies combined">
                {positions.length === 0 ? <span className="text-slate-400 text-base">flat</span>
                  : <span className="text-base">{positions.map(([s, q]) => `${s} ${q > 0 ? '+' : ''}${q}`).join('  ')}</span>}
              </Stat>
            </div>
            <MyStrategies snap={snap} />
            <Catalog catalog={catalog} />
            <div className="grid lg:grid-cols-2 gap-5">
              <PnlChart />
              <Candles snap={snap} />
            </div>
            <Tables snap={snap} />
            <DemoTools snap={snap} />
          </>
        )}
      </main>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(() => (getToken() ? localStorage.getItem('ts_user') || 'trader' : null))
  const onAuth = (r) => { localStorage.setItem('ts_user', r.username); setUser(r.username) }
  const logout = () => { setToken(''); setUser(null) }
  return user ? <Dashboard username={user} onLogout={logout} /> : <Login onAuth={onAuth} />
}
