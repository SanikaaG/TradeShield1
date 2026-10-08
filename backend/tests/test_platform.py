"""Run with:  python -m unittest discover -s tests -v      (standard library only, no setup needed)"""
import asyncio
import time
import unittest

from tradeshield.broker.mock import MockExchange
from tradeshield.candles import CandleBuilder, CandleEngine, parse_spec
from tradeshield.config import Settings
from tradeshield.engine import Engine
from tradeshield.ledger import apply_fill_to_position, compute_charges
from tradeshield.models import Signal, Tick, Candle
from tradeshield import strategies as strat_mod
from tradeshield.recovery import reconcile

SYMS = ["TCS", "INFY", "RELIANCE"]


def make_engine(**over):
    s = Settings(db_path=":memory:", mock_state_path="", order_timeout=0.5, retry_backoff=0.02,
                 max_send_attempts=4, kill_deadline=10.0)
    for k, v in over.items():
        setattr(s, k, v)
    ex = MockExchange(SYMS, seed=7, tick_interval=0.01)
    ex.chaos.partial_fills = False
    e = Engine(s, broker=ex)
    ex.subscribe_fills(e.gateway.on_fill)
    ex.subscribe_ticks(e.on_tick)
    e.prices.update(ex.prices)
    uid = e.db.create_user("samira", "pw")
    return e, ex, uid


async def fill_all(ex, rounds=10):
    for _ in range(rounds):
        await ex.process_fills_once()


class CandleTests(unittest.TestCase):
    def test_one_and_five_minute_candles(self):
        eng = CandleEngine(["TCS"], ("1m", "5m"))
        closed = []
        t0 = 1_700_000_040 - 1_700_000_040 % 300            # aligned to a 5-minute boundary
        for i in range(0, 600, 10):                          # 10 minutes of ticks, one every 10s
            closed += eng.on_tick(Tick("TCS", 100 + i / 10, t0 + i))
        ones = [c for c in closed if c.interval == "1m"]
        fives = [c for c in closed if c.interval == "5m"]
        self.assertEqual(len(ones), 9)                       # the 10th minute is still open
        self.assertEqual(len(fives), 1)
        c = ones[0]
        self.assertEqual((c.open, c.high, c.low, c.close, c.ticks), (100, 105, 100, 105, 6))

    def test_tick_and_custom_intervals(self):
        b = CandleBuilder("TCS", "50t")
        out = [b.on_tick(Tick("TCS", 100 + i, i)) for i in range(120)]
        self.assertEqual(len([c for c in out if c]), 2)
        self.assertEqual(parse_spec("15m"), ("time", 900))
        self.assertEqual(parse_spec("1h"), ("time", 3600))
        for bad in ("0m", "abc", "1t", "99999999m", ""):
            with self.assertRaises(ValueError):
                parse_spec(bad)


class LedgerTests(unittest.TestCase):
    def test_add_reduce_flip(self):
        self.assertEqual(apply_fill_to_position(0, 0, "BUY", 10, 100), (10, 100, 0))
        self.assertEqual(apply_fill_to_position(10, 100, "BUY", 10, 110), (20, 105, 0))
        q, a, r = apply_fill_to_position(20, 105, "SELL", 5, 115)
        self.assertEqual((q, a, r), (15, 105, 50))
        q, a, r = apply_fill_to_position(15, 105, "SELL", 25, 100)       # flips long -> short
        self.assertEqual((q, round(a, 2), r), (-10, 100, -75))
        q, a, r = apply_fill_to_position(-10, 100, "BUY", 10, 90)         # short covered at a profit
        self.assertEqual((q, r), (0, 100))

    def test_charges(self):
        cfg = Settings()
        buy, sell = compute_charges("BUY", 100, 1000, cfg), compute_charges("SELL", 100, 1000, cfg)
        self.assertGreater(sell, buy)                                      # STT only on sells
        self.assertLessEqual(buy, 20 * 1.18 + 100 * 1000 * cfg.exchange_pct * 1.18 + 0.01)


class PlatformTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.e, self.ex, self.uid = make_engine()

    def sub(self, key="mean_reversion"):
        return self.e.subscribe(self.uid, key)

    # ---- mandatory: live trading, partial fills, rejections, exact P&L ---------------------------
    async def test_partial_fills_and_net_pnl(self):
        sid = self.sub()
        self.ex.chaos.partial_fills = True
        self.e.update_limits(sid, 5000, 100, 10)
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 100, "t"))
        self.assertEqual(o["status"], "OPEN")
        await fill_all(self.ex)
        o = self.e.db.get_order(o["client_order_id"])
        self.assertEqual((o["status"], o["filled_qty"]), ("FILLED", 100))
        self.assertGreater(len(self.e.db.list_fills()), 1)                 # really arrived in pieces
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 100)
        self.assertEqual(self.e.db.net_positions(), await self.ex.get_positions())
        # price moves up 10, we sell everything: net P&L must equal gross minus every charge
        self.ex.prices["TCS"] += 10
        self.e.prices["TCS"] = self.ex.prices["TCS"]
        await self.e.gateway.submit(sid, Signal("TCS", "SELL", 100, "t"))
        await fill_all(self.ex)
        fills = self.e.db.list_fills()
        gross = sum(f["realized_pnl"] for f in fills)
        charges = sum(f["charges"] for f in fills)
        pnl = self.e.ledger.pnl(sid)
        self.assertAlmostEqual(pnl["realized_net"], gross - charges, places=2)
        self.assertGreater(charges, 0)
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 0)

    async def test_rejection_is_recorded(self):
        sid = self.sub()
        self.ex.chaos.reject_rate = 1.0
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        self.assertEqual(o["status"], "REJECTED")
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 0)

    # ---- mandatory: multiple strategies, own P&L and position, long AND short same stock ---------
    async def test_three_strategies_independent_ledgers(self):
        a, b, c = self.sub("trend_breakout"), self.sub("mean_reversion"), self.sub("tick_momentum")
        await self.e.gateway.submit(a, Signal("TCS", "BUY", 10, "long"))
        await self.e.gateway.submit(b, Signal("TCS", "SELL", 10, "short"))        # opposite side, same stock
        await self.e.gateway.submit(c, Signal("INFY", "BUY", 10, "long"))
        await fill_all(self.ex)
        db = self.e.db
        self.assertEqual(db.get_position(a, "TCS")["qty"], 10)
        self.assertEqual(db.get_position(b, "TCS")["qty"], -10)
        self.assertEqual(db.get_position(c, "INFY")["qty"], 10)
        self.assertEqual(await self.ex.get_positions(), {"INFY": 10})             # TCS nets to zero at the broker
        self.assertEqual(db.net_positions().get("TCS", 0), 0)
        self.ex.prices["TCS"] += 20                                               # price up: A gains, B loses
        self.e.prices["TCS"] = self.ex.prices["TCS"]
        pa, pb = self.e.ledger.pnl(a)["unrealized"], self.e.ledger.pnl(b)["unrealized"]
        self.assertGreater(pa, 0)
        self.assertLess(pb, 0)

    # ---- mandatory: risk limits enforced by the PLATFORM ------------------------------------------
    async def test_position_limit_blocks(self):
        sid = self.sub()
        self.e.update_limits(sid, 5000, 15, 10)
        ok = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        bad = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        await fill_all(self.ex)
        self.assertEqual(ok["status"], "OPEN")
        self.assertEqual(bad["status"], "BLOCKED")
        self.assertIn("position would be 20", bad["reason"])
        self.assertEqual(len(self.ex.orders), 1)                                  # blocked order never reached broker

    async def test_reducing_orders_always_allowed(self):
        sid = self.sub()
        self.e.update_limits(sid, 5000, 10, 10)
        await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        await fill_all(self.ex)
        o = await self.e.gateway.submit(sid, Signal("TCS", "SELL", 10, "exit"))
        self.assertNotEqual(o["status"], "BLOCKED")

    async def test_orders_per_minute_limit(self):
        sid = self.sub()
        self.e.update_limits(sid, 5000, 1000, 3)
        res = [await self.e.gateway.submit(sid, Signal("TCS", "BUY", 1, "t")) for _ in range(5)]
        self.assertEqual([r["status"] == "BLOCKED" for r in res], [False, False, False, True, True])
        self.assertIn("max 3", res[3]["reason"])

    async def test_daily_loss_limit_halts_strategy(self):
        sid = self.sub()
        self.e.update_limits(sid, 1000, 100, 10)
        self.e.db.set_position(sid, "TCS", 100, 3800.0)
        self.e.prices["TCS"] = 3780.0                                              # unrealized -2000
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 1, "t"))
        self.assertEqual(o["status"], "BLOCKED")
        self.assertEqual(self.e.db.get_sub(sid)["status"], "HALTED_RISK")
        o2 = await self.e.gateway.submit(sid, Signal("TCS", "SELL", 1, "t"))
        self.assertEqual(o2["status"], "BLOCKED")                                  # stays halted
        await asyncio.sleep(0.05)                                                  # its position is closed by the platform
        closes = [x for x in self.e.db.list_orders() if x["is_close"]]
        self.assertEqual((len(closes), closes[0]["side"], closes[0]["qty"]), (1, "SELL", 100))

    async def test_runaway_strategy_cannot_break_limits(self):
        sid = self.sub("runaway_test")                                             # limits: position 20, 5/min
        for _ in range(60):
            await self.e.gateway.submit(sid, Signal("RELIANCE", "BUY", 10, "spam"))
        await fill_all(self.ex)
        self.assertLessEqual(len(self.ex.orders), 2)                               # position limit 20 => 2 orders max
        self.assertLessEqual(abs(self.e.db.get_position(sid, "RELIANCE")["qty"]), 20)
        self.assertEqual(self.e.db.get_sub(sid)["status"], "HALTED_RISK")          # runaway detector halted it

    async def test_strategy_crash_is_contained(self):
        class Bomb(strat_mod.Strategy):
            key, name, symbols = "bomb", "Bomb", ["TCS"]
            def required_intervals(self, p): return ["1m"]
            def on_candle(self, c, ctx): raise RuntimeError("boom")
        strat_mod.REGISTRY["bomb"] = Bomb
        try:
            sid = self.e.db.create_sub(self.uid, "bomb", Bomb.default_limits, {})
            self.e._dispatch_candle(Candle("TCS", "1m", 0, 1, 1, 1, 1))
            self.assertEqual(self.e.db.get_sub(sid)["status"], "HALTED_ERROR")
        finally:
            del strat_mod.REGISTRY["bomb"]

    # ---- extra: adaptive risk shield --------------------------------------------------------------
    async def test_adaptive_shield_tightens_limits(self):
        sid = self.sub()
        self.e.update_limits(sid, 2000, 30, 10)
        view = self.e.sub_view(self.e.db.get_sub(sid))
        self.assertEqual(view["effective"]["max_position"], 30)
        self.e.db.set_position(sid, "TCS", 10, 3800.0)
        self.e.prices["TCS"] = 3680.0                                              # -1200 = 60% of budget
        view = self.e.sub_view(self.e.db.get_sub(sid))
        self.assertEqual((view["effective"]["shield_tier"], view["effective"]["max_position"]), (1, 15))
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))        # would reach 20 > 15
        self.assertEqual(o["status"], "BLOCKED")
        self.assertIn("shield tier 1", o["reason"])
        self.e.prices["TCS"] = 3650.0                                              # -1500 = 75% -> tier 2
        view = self.e.sub_view(self.e.db.get_sub(sid))
        self.assertEqual((view["effective"]["shield_tier"], view["effective"]["max_position"]), (2, 7))
        self.assertTrue(any(ev["kind"] == "SHIELD" for ev in self.e.db.list_events(20)))

    # ---- extra: idempotent order gateway ------------------------------------------------------------
    async def test_lost_ack_never_creates_duplicate(self):
        sid = self.sub()
        self.ex.chaos.ack_loss_rate = 1.0                      # broker takes the order, the reply is lost
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        self.assertEqual(len(self.ex.orders), 1)               # NOT resent
        self.assertEqual(o["status"], "OPEN")
        self.assertTrue(any(ev["kind"] == "ORDER_FOUND" for ev in self.e.db.list_events(20)))

    async def test_network_error_retries_with_same_id(self):
        sid = self.sub()
        self.ex.chaos.error_rate = 1.0
        async def heal():
            await asyncio.sleep(0.05)
            self.ex.chaos.error_rate = 0.0
        asyncio.create_task(heal())
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        self.assertEqual(len(self.ex.orders), 1)
        self.assertGreater(o["attempts"], 1)
        self.assertEqual(list(self.ex.orders)[0], o["client_order_id"])

    async def test_duplicate_submission_same_id_processed_once(self):
        sid = self.sub()
        s = Signal("TCS", "BUY", 10, "t")
        r1 = await self.e.gateway.submit(sid, s, coid="TS-fixed")
        r2 = await self.e.gateway.submit(sid, s, coid="TS-fixed")
        await fill_all(self.ex)
        self.assertEqual(r1["client_order_id"], r2["client_order_id"])
        self.assertEqual(len(self.ex.orders), 1)
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 10)

    async def test_replayed_fill_applied_once(self):
        sid = self.sub()
        o = await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        await fill_all(self.ex)
        fill = self.ex.orders[o["client_order_id"]].fills[0]
        self.assertFalse(self.e.gateway.apply_fill(fill))                          # replay is ignored
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 10)

    # ---- extra: crash recovery & reconciliation --------------------------------------------------------
    async def test_reconcile_recovers_fills_missed_during_crash(self):
        sid = self.sub()
        self.ex.chaos.partial_fills = True
        self.e.update_limits(sid, 5000, 200, 10)
        await self.e.gateway.submit(sid, Signal("TCS", "BUY", 100, "t"))           # BUY 100
        await self.ex.process_fills_once()                                         # some shares fill: platform sees them
        got = self.e.db.get_position(sid, "TCS")["qty"]
        self.assertTrue(0 < got < 100)
        self.ex.unsubscribe_fills(self.e.gateway.on_fill)                          # --- server crashes ---
        await fill_all(self.ex)                                                    # rest fills while we are down
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], got)           # platform is out of date
        self.assertEqual((await self.ex.get_positions())["TCS"], 100)
        self.ex.subscribe_fills(self.e.gateway.on_fill)                            # --- restart ---
        rep = await reconcile(self.e, "startup")
        self.assertGreater(rep["fills_recovered"], 0)
        self.assertEqual(self.e.db.get_position(sid, "TCS")["qty"], 100)           # attributed to the right strategy
        self.assertEqual(rep["position_fixes"], [])
        self.assertEqual(self.e.db.get_order(list(self.ex.orders)[0])["status"], "FILLED")
        self.assertFalse(self.e.state.paused)

    async def test_reconcile_fixes_position_mismatch_and_expires_ghost_orders(self):
        sid = self.sub()
        await self.e.gateway.submit(sid, Signal("TCS", "BUY", 10, "t"))
        await fill_all(self.ex)
        self.e.db.set_position(sid, "TCS", 100, 3800.0)                            # platform believes +100, broker says +10
        self.e.db.insert_order({"client_order_id": "ghost", "sub_id": sid, "symbol": "TCS", "side": "BUY", "qty": 5,
                                "order_type": "MARKET", "status": "SENT", "ts": time.time()})
        rep = await reconcile(self.e, "manual")
        self.assertEqual(self.e.db.net_positions()["TCS"], 10)
        self.assertEqual(rep["position_fixes"][0]["platform_said"], 100)
        self.assertEqual(self.e.db.get_order("ghost")["status"], "EXPIRED")

    async def test_orphan_broker_order_is_cancelled(self):
        from tradeshield.models import OrderRequest
        await self.ex.place_order(OrderRequest("not-ours", "TCS", "BUY", 10))
        rep = await reconcile(self.e, "manual")
        self.assertEqual(rep["orphans_cancelled"], 1)
        self.assertEqual(self.ex.orders["not-ours"].status, "CANCELLED")

    # ---- mandatory: kill switch --------------------------------------------------------------------------
    async def test_kill_switch_flattens_everything_within_10_seconds(self):
        await self.ex.start()                                  # real fill loop running
        try:
            a, b = self.sub("trend_breakout"), self.sub("tick_momentum")
            self.ex.chaos.partial_fills = True
            await self.e.gateway.submit(a, Signal("TCS", "BUY", 20, "t"))
            await self.e.gateway.submit(b, Signal("INFY", "SELL", 20, "t"))
            await asyncio.sleep(0.4)
            await self.e.gateway.submit(a, Signal("TCS", "BUY", 5, "t"))               # leave an order open
            t0 = time.monotonic()
            res = await self.e.kill_switch()
            self.assertLess(time.monotonic() - t0, 10)
            self.assertTrue(res["within_deadline"] and res["flat"])
            self.assertEqual(await self.ex.get_positions(), {})
            self.assertEqual(self.e.db.net_positions(), {k: v for k, v in self.e.db.net_positions().items() if v == 0})
            self.assertEqual(self.e.db.open_orders(), [])
            self.assertEqual(self.e.db.get_sub(a)["status"], "HALTED_KILL")
            o = await self.e.gateway.submit(a, Signal("TCS", "BUY", 1, "t"))
            self.assertEqual(o["status"], "BLOCKED")                                   # nothing trades after the kill
            self.e.reset_kill()
            self.e.resume(a)
            self.assertEqual(self.e.db.get_sub(a)["status"], "ACTIVE")
        finally:
            await self.ex.stop()

    async def test_snapshot_shape(self):
        self.sub("trend_breakout")
        snap = self.e.snapshot(self.uid)
        self.assertEqual(snap["subs"][0]["strategy_key"], "trend_breakout")
        self.assertIn("1m", snap["intervals"])

    async def test_custom_interval_flow(self):
        sid = self.sub("mean_reversion")
        self.e.update_params(sid, {"interval": "15m"})
        self.assertIn("15m", self.e.candles.specs)
        with self.assertRaises(ValueError):
            self.e.add_interval("banana")


if __name__ == "__main__":
    unittest.main()
