"""Central settings. Everything can be overridden with environment variables (prefix TS_)."""
import os
from dataclasses import dataclass, field


def _f(name, default):
    return float(os.getenv(name, default))


@dataclass
class Settings:
    db_path: str = os.getenv("TS_DB_PATH", "tradeshield.db")
    broker_mode: str = os.getenv("TS_BROKER", "mock")          # "mock" or "021"
    symbols: list = field(default_factory=lambda: os.getenv("TS_SYMBOLS", "TCS,INFY,RELIANCE").split(","))

    # --- mock exchange pacing: 1 real second == time_scale simulated seconds
    time_scale: float = _f("TS_TIME_SCALE", 10)
    tick_interval: float = _f("TS_TICK_INTERVAL", 0.25)
    mock_state_path: str = os.getenv("TS_MOCK_STATE", "mock_exchange_state.json")

    # --- order handling
    order_timeout: float = _f("TS_ORDER_TIMEOUT", 2.0)           # seconds to wait for a broker ack
    max_send_attempts: int = int(os.getenv("TS_MAX_SEND_ATTEMPTS", "4"))
    retry_backoff: float = _f("TS_RETRY_BACKOFF", 0.3)
    sync_interval: float = _f("TS_SYNC_INTERVAL", 5.0)           # periodic order re-sync with the broker

    # --- kill switch
    kill_deadline: float = _f("TS_KILL_DEADLINE", 10.0)

    # --- charges model (used when the broker does not report charges itself)
    brokerage_pct: float = 0.0003
    brokerage_cap: float = 20.0
    stt_sell_pct: float = 0.00025
    exchange_pct: float = 0.0000345
    gst_pct: float = 0.18

    # --- 021 adapter (fill these in once you have the organisers' API docs)
    o21_base_url: str = os.getenv("O21_BASE_URL", "")
    o21_api_key: str = os.getenv("O21_API_KEY", "")
