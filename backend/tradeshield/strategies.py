"""Example strategies. A strategy only READS candles/positions and returns Signals.
It never touches the broker - the platform's risk engine and gateway stand in between.
(Profitability is irrelevant for this problem; these exist to exercise the platform.)
"""
import statistics
from .models import Signal


class Ctx:
    """What a strategy is allowed to see."""
    def __init__(self, engine, sub):
        self._e, self.sub, self.params = engine, sub, sub["params"]

    def candles(self, symbol, interval, n=None):
        return self._e.candles.history(symbol, interval, n)

    def position(self, symbol):
        return self._e.db.get_position(self.sub["id"], symbol)["qty"]

    def price(self, symbol):
        return self._e.prices.get(symbol)


class Strategy:
    key, name, description = "", "", ""
    symbols = []
    demo = False
    default_limits = {"max_daily_loss": 5000.0, "max_position": 30, "max_orders_per_min": 10}
    default_params = {}

    def required_intervals(self, params):
        return []

    def on_candle(self, candle, ctx):
        return []


def _ema(values, n):
    k, e = 2 / (n + 1), values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


class TrendBreakout(Strategy):
    key, name = "trend_breakout", "Trend Breakout"
    description = "5-min EMA trend + 1-min breakout entry (uses 1m and 5m candles). Goes long or short."
    symbols = ["TCS"]
    default_params = {"qty": 10}

    def required_intervals(self, params):
        return ["1m", "5m"]

    def on_candle(self, c, ctx):
        if c.interval != "1m":
            return []
        five = [x.close for x in ctx.candles(c.symbol, "5m")]
        one = ctx.candles(c.symbol, "1m")
        if len(five) < 4 or len(one) < 6:
            return []
        trend = _ema(five, 2) - _ema(five, 4)
        prev = one[-6:-1]
        pos, qty = ctx.position(c.symbol), int(ctx.params.get("qty", 10))
        if pos == 0 and trend > 0 and c.close > max(x.high for x in prev):
            return [Signal(c.symbol, "BUY", qty, "5m uptrend + 1m breakout above 5-bar high")]
        if pos == 0 and trend < 0 and c.close < min(x.low for x in prev):
            return [Signal(c.symbol, "SELL", qty, "5m downtrend + 1m breakdown below 5-bar low")]
        if pos > 0 and trend < 0:
            return [Signal(c.symbol, "SELL", pos, "exit long: 5m trend turned down")]
        if pos < 0 and trend > 0:
            return [Signal(c.symbol, "BUY", -pos, "exit short: 5m trend turned up")]
        return []


class MeanReversion(Strategy):
    key, name = "mean_reversion", "Mean Reversion"
    description = "Fades stretched moves (z-score). Candle interval is configurable (default 1m). Same stock as Trend Breakout, so it is often on the opposite side."
    symbols = ["TCS"]
    default_params = {"interval": "1m", "qty": 10, "lookback": 10}

    def required_intervals(self, params):
        return [params.get("interval", "1m")]

    def on_candle(self, c, ctx):
        n = int(ctx.params.get("lookback", 10))
        closes = [x.close for x in ctx.candles(c.symbol, c.interval, n)]
        if len(closes) < n:
            return []
        sd = statistics.pstdev(closes)
        if sd == 0:
            return []
        z, pos, qty = (c.close - statistics.mean(closes)) / sd, ctx.position(c.symbol), int(ctx.params.get("qty", 10))
        if pos == 0 and z > 1.5:
            return [Signal(c.symbol, "SELL", qty, f"z-score {z:.2f} > 1.5: price stretched up, fade it")]
        if pos == 0 and z < -1.5:
            return [Signal(c.symbol, "BUY", qty, f"z-score {z:.2f} < -1.5: price stretched down, fade it")]
        if pos > 0 and z > -0.3:
            return [Signal(c.symbol, "SELL", pos, "exit long: back to the mean")]
        if pos < 0 and z < 0.3:
            return [Signal(c.symbol, "BUY", -pos, "exit short: back to the mean")]
        return []


class TickMomentum(Strategy):
    key, name = "tick_momentum", "Tick Momentum"
    description = "Three rising/falling candles in a row. Defaults to 40-tick candles (tick-based interval)."
    symbols = ["INFY"]
    default_params = {"interval": "40t", "qty": 10, "hold": 3}

    def __init__(self):
        self.held = 0

    def required_intervals(self, params):
        return [params.get("interval", "40t")]

    def on_candle(self, c, ctx):
        h = [x.close for x in ctx.candles(c.symbol, c.interval, 3)]
        pos, qty = ctx.position(c.symbol), int(ctx.params.get("qty", 10))
        if pos != 0:
            self.held += 1
            if self.held >= int(ctx.params.get("hold", 3)):
                self.held = 0
                return [Signal(c.symbol, "SELL" if pos > 0 else "BUY", abs(pos), "time exit after holding N candles")]
            return []
        self.held = 0
        if len(h) < 3:
            return []
        if h[0] < h[1] < h[2]:
            return [Signal(c.symbol, "BUY", qty, "3 rising candles")]
        if h[0] > h[1] > h[2]:
            return [Signal(c.symbol, "SELL", qty, "3 falling candles")]
        return []


class RunawayTest(Strategy):
    key, name = "runaway_test", "Runaway (stress test)"
    description = "DELIBERATELY BROKEN: spams 40 buy orders on every candle. Use it to prove that platform limits still hold."
    symbols = ["RELIANCE"]
    demo = True
    default_limits = {"max_daily_loss": 3000.0, "max_position": 20, "max_orders_per_min": 5}
    default_params = {"interval": "1m"}

    def required_intervals(self, params):
        return [params.get("interval", "1m")]

    def on_candle(self, c, ctx):
        return [Signal(c.symbol, "BUY", 10, "runaway loop") for _ in range(40)]


REGISTRY = {cls.key: cls for cls in (TrendBreakout, MeanReversion, TickMomentum, RunawayTest)}


def catalog():
    return [{"key": c.key, "name": c.name, "description": c.description, "symbols": c.symbols, "demo": c.demo,
             "default_limits": c.default_limits, "default_params": c.default_params}
            for c in REGISTRY.values()]
