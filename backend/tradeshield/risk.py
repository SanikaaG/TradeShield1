"""Platform-owned risk engine. Strategies can NOT bypass it: they only produce Signals, and every
order - no matter what the strategy does - is evaluated here before it can reach the broker.

Checks (in order): kill switch -> reconciling -> strategy halted -> daily loss -> position size -> orders/min.
Adaptive Risk Shield: the more of the daily-loss budget a strategy has burnt, the tighter its limits get.
"""
import time
from collections import defaultdict, deque

from .models import Decision

# (fraction of daily-loss budget used, position multiplier, orders/min multiplier)
SHIELD_TIERS = [(0.50, 0.50, 0.50), (0.75, 0.25, 0.25)]
RUNAWAY_BLOCKS_PER_MIN = 20          # this many blocked orders in a minute => strategy is runaway => halt it


class RiskEngine:
    def __init__(self, db, ledger, events, state, clock=time.time, shield_enabled=True):
        self.db, self.ledger, self.events, self.state, self.clock = db, ledger, events, state, clock
        self.shield_enabled = shield_enabled
        self._allowed = defaultdict(deque)     # sub_id -> timestamps of allowed orders
        self._blocked = defaultdict(deque)     # sub_id -> timestamps of blocked orders
        self.on_loss_halt = None               # callback(sub_id): engine uses it to flatten the strategy

    # ------------------------------------------------------------ halting
    def halt(self, sub_id, status, reason):
        sub = self.db.get_sub(sub_id)
        if sub and sub["status"] == "ACTIVE":
            self.db.update_sub(sub_id, status=status, halt_reason=reason)
            self.events.log("incident", status, f"Strategy #{sub_id} ({sub['strategy_key']}) halted: {reason}", sub_id)

    # ------------------------------------------------- adaptive risk shield
    def effective_limits(self, sub, day_pnl):
        loss_frac = max(0.0, -day_pnl) / sub["max_daily_loss"] if sub["max_daily_loss"] > 0 else 0.0
        tier, pm, rm = 0, 1.0, 1.0
        if self.shield_enabled:
            for i, (threshold, p, r) in enumerate(SHIELD_TIERS):
                if loss_frac >= threshold:
                    tier, pm, rm = i + 1, p, r
        limits = {"max_position": max(1, int(sub["max_position"] * pm)),
                  "max_orders": max(1, int(sub["max_orders_per_min"] * rm)),
                  "tier": tier, "loss_frac": loss_frac}
        if tier != sub["shield_tier"]:
            self.db.update_sub(sub["id"], shield_tier=tier)
            verb = "tightened" if tier > sub["shield_tier"] else "relaxed"
            self.events.log(
                "incident", "SHIELD", f"Adaptive Risk Shield {verb} strategy #{sub['id']} ({sub['strategy_key']}): "
                f"tier {sub['shield_tier']}->{tier}; position limit {sub['max_position']}->{limits['max_position']}, "
                f"orders/min {sub['max_orders_per_min']}->{limits['max_orders']} "
                f"(loss Rs{max(0, -day_pnl):.0f} = {loss_frac * 100:.0f}% of Rs{sub['max_daily_loss']:.0f} budget)",
                sub["id"], {"tier": tier})
        return limits

    # ------------------------------------------------------------ evaluate
    def evaluate(self, sub_id, signal, force=False):
        if force:
            return Decision(True, "FORCED", "platform-initiated order (kill switch)")
        sub = self.db.get_sub(sub_id)
        if sub is None:
            return Decision(False, "NO_SUBSCRIPTION", "subscription not found")
        if self.state.killed:
            return self._block(sub_id, "KILL_SWITCH", "kill switch is active - all trading stopped")
        if self.state.paused:
            return self._block(sub_id, "RECONCILING", f"platform paused: {self.state.pause_reason}")
        if sub["status"] != "ACTIVE":
            return self._block(sub_id, "STRATEGY_HALTED", f"strategy is {sub['status']} ({sub['halt_reason'] or 'stopped'})")

        day_pnl = self.ledger.pnl(sub_id)["day_net"]
        lim = self.effective_limits(sub, day_pnl)

        if day_pnl <= -sub["max_daily_loss"]:
            self.halt(sub_id, "HALTED_RISK", f"daily loss limit hit (Rs{-day_pnl:.0f} >= Rs{sub['max_daily_loss']:.0f}); closing its positions")
            if self.on_loss_halt:
                self.on_loss_halt(sub_id)
            return self._block(sub_id, "DAILY_LOSS", f"daily loss Rs{-day_pnl:.0f} reached limit Rs{sub['max_daily_loss']:.0f}")

        pos = self.db.get_position(sub_id, signal.symbol)["qty"]
        # Worst case: assume every live (unfilled) order also fills. A runaway strategy therefore cannot
        # blow through the limit by sending many orders before the first fill comes back.
        if signal.side == "BUY":
            pending = self.db.pending_qty(sub_id, signal.symbol, "BUY")
            projected = pos + pending + signal.qty
            breach = projected > lim["max_position"]
        else:
            pending = self.db.pending_qty(sub_id, signal.symbol, "SELL")
            projected = pos - pending - signal.qty
            breach = projected < -lim["max_position"]
        if breach:
            tag = f" (shield tier {lim['tier']})" if lim["tier"] else ""
            note = f" incl. {pending} pending" if pending else ""
            return self._block(sub_id, "POSITION_LIMIT",
                               f"position would be {projected}{note}, max allowed {lim['max_position']}{tag}")

        now = self.clock()
        window = self._allowed[sub_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= lim["max_orders"]:
            tag = f" (shield tier {lim['tier']})" if lim["tier"] else ""
            return self._block(sub_id, "RATE_LIMIT", f"{len(window)} orders in the last minute, max {lim['max_orders']}{tag}")

        window.append(now)
        return Decision(True, "ALLOWED", f"position {pos}->{projected} (max {lim['max_position']}), "
                        f"orders {len(window)}/{lim['max_orders']} per min, day P&L Rs{day_pnl:.0f} "
                        f"(loss limit Rs{sub['max_daily_loss']:.0f})")

    def _block(self, sub_id, code, message):
        now = self.clock()
        q = self._blocked[sub_id]
        q.append(now)
        while q and now - q[0] > 60:
            q.popleft()
        if code in ("POSITION_LIMIT", "RATE_LIMIT") and len(q) >= RUNAWAY_BLOCKS_PER_MIN:
            self.halt(sub_id, "HALTED_RISK", f"runaway strategy detected ({len(q)} blocked orders in 60s)")
        return Decision(False, code, message)
