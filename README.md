# TradeShield: algo trading platform where risk limits always hold (PS-06)

```
backend/   FastAPI + asyncio platform (risk engine, order gateway, candles, ledger, recovery)
frontend/  React + Tailwind + Recharts dashboard
```

## Run it (about 5 minutes)

```bash
# 1) backend  (Python 3.10+)
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests -v                  # 24 tests, stdlib only, should all pass
uvicorn tradeshield.app:app --port 8000

# 2) frontend (new terminal, Node 18+)
cd frontend
npm install
npm run dev                                              # open http://localhost:5173
```
Single-server option: `npm run build` in `frontend/`, then the backend serves the UI at http://localhost:8000.
Docker: `docker build -t tradeshield . && docker run -p 8000:8000 tradeshield`.

By default the platform trades against a **built-in mock exchange** (`backend/tradeshield/broker/mock.py`).
Time runs 10x faster (a "1-minute" candle closes in about 6 seconds) so you can demo quickly. Change with `TS_TIME_SCALE`.

## Plugging in the real 021 sandbox  (DO THIS FIRST at the hackathon)

Open `backend/tradeshield/broker/o21.py`. Every line marked `TODO` is a placeholder (I could not find public 021 docs).
Fill in: auth header, order/cancel/get-order/positions endpoints, field names, and the tick feed. Then:
```bash
export TS_BROKER=021 O21_BASE_URL=... O21_API_KEY=...
```
Nothing else changes: the platform only talks to the `Broker` interface (`broker/base.py`).
Things to confirm in the 021 docs: does it accept a client order id (idempotency)? does it push fills or must you poll?
does it report charges per fill (if so set `Fill.charges`; otherwise the charges model in `config.py` is used)?

## How the requirements map to code

| Requirement | Where |
|---|---|
| Accounts, strategy subscription | `db.py`, `app.py` (/api/register, /api/subscriptions) |
| 1m and 5m candles from raw ticks (+ custom 15m, 1h, tick candles) | `candles.py` |
| Orders on sandbox, fills tracked, partial fills, rejections | `gateway.py`, `broker/` |
| Position in sync with account, exact trades, net P&L after charges | `ledger.py`, `gateway.apply_fill`, `recovery.py` |
| Max daily loss / max position / max orders per minute, enforced by platform | `risk.py` (strategies only emit `Signal`s, see `strategies.py`) |
| Kill switch: stop all, cancel orders, close positions within 10 s | `engine.kill_switch` |
| 3+ strategies at once, own P&L/position, long and short same stock | `strategies.py`, per-strategy rows in `positions` table |
| Dashboard | `frontend/` |
| Crash recovery and reconciliation | `recovery.py` |
| Idempotent order gateway | `gateway.py` (`client_order_id`, ask-before-resend, `fill_id` de-dup) |
| Adaptive Risk Shield | `risk.effective_limits` (50% of loss budget used => limits x0.5, 75% => x0.25) |
| What-If Risk Simulator | deliberately NOT built (kept for the next round) |

## Design decisions to explain in the viva

1. **Strategies are untrusted.** They can only return `Signal`s. Every order goes `Signal -> RiskEngine -> Gateway -> Broker`.
   A crashing strategy is caught and halted (`HALTED_ERROR`); a spamming one is blocked and auto-halted (runaway detector).
2. **Position limits count pending orders** (worst case: everything fills). Without this a runaway strategy could exceed the limit
   by firing many orders before the first fill returns. (Found by a failing test.)
3. **Orders are saved BEFORE they are sent**, with a unique `client_order_id`. On a timeout the gateway first asks the broker
   "do you have this id?" and only resends (same id) if the answer is no.
4. **Each fill is applied exactly once** (`fill_id` is unique), so replays/recovery can never double-count.
5. **Per-strategy sub-ledgers.** The account has one real position per stock; the platform tracks a virtual position per strategy.
   Reconciliation compares the SUM of sub-ledgers with the broker.
6. **Reconciliation fails safe**: if it cannot reach the broker, trading stays paused. Differences it cannot attribute go to an
   "Unattributed" bucket so the account still matches the broker.
7. **Daily-loss breach** halts the strategy AND closes its positions. Kill switch blocks new orders first, then cancels and
   flattens in parallel and repeats until flat or 10 s.
8. **Config-driven**: limits and strategy settings (candle interval, qty) are editable live in the UI, which helps with the live change request.

## Demo script (2 minutes)

1. Register, subscribe to all four strategies (one is the deliberately broken "Runaway" one).
2. Watch Runaway get blocked by the risk engine (Activity log), then halted. Others keep trading.
3. Open *Demo and test tools*: turn on **Lost acknowledgements** and **Network errors**: orders still appear exactly once.
4. **Send same order twice**: result shows `orders_created: 1`.
5. **Simulate server crash** while orders are open: Activity log shows what was recovered and corrected.
6. Settings on a strategy: set max position to 5, watch orders get blocked with the reason.
7. Press **Kill switch**: banner shows elapsed seconds and that positions are flat.

## Known limitations (be upfront about these)

* The HTTP layer (`app.py`) and the React UI could not be run where this code was written (no internet there); the core
  (risk, gateway, ledger, recovery, candles, kill switch) is covered by the 24 unit tests and an end-to-end run against the mock exchange.
  Expect to fix small typos on first launch.
* Database is **SQLite** (zero setup); the proposal says PostgreSQL. All SQL is in `db.py`. Rate limiting is in memory (no Redis).
  Either tell the judges "SQLite for the prototype" or swap `db.py`.
* One broker account is assumed; all users share it. Strategy state (candle history) is not persisted, so strategies warm up again after a restart.
* The sample strategies are simple on purpose: profitability is not judged.
