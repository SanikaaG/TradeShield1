"""Adapter for the REAL 021 developer APIs.

>>> I could not find public documentation for the 021 APIs, so every endpoint, header and field name
>>> below is a PLACEHOLDER. Open the organisers' API docs, then fix the lines marked TODO.
>>> Nothing else in the platform needs to change - it only ever talks to the Broker interface.
"""
import asyncio
import json

import httpx

from .base import Broker, BrokerRejected
from ..models import Tick, Fill, BrokerOrder, OrderRequest


class O21Broker(Broker):
    def __init__(self, base_url, api_key, symbols, poll_interval=1.0):
        self.base, self.symbols, self.poll = base_url.rstrip("/"), symbols, poll_interval
        self.http = httpx.AsyncClient(base_url=self.base, timeout=5.0,
                                      headers={"Authorization": f"Bearer {api_key}"})  # TODO auth scheme
        self._tick_cbs, self._fill_cbs, self._tasks = [], [], []
        self._seen_fills = set()

    async def start(self):
        self._tasks = [asyncio.create_task(self._tick_loop()), asyncio.create_task(self._fill_poll_loop())]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await self.http.aclose()

    # ------------------------------------------------------------- orders
    def _to_order(self, d) -> BrokerOrder:
        # TODO map the API's response fields to BrokerOrder
        o = BrokerOrder(d["client_order_id"], d["symbol"], d["side"], int(d["quantity"]),
                        d.get("order_type", "MARKET"), d.get("price"))
        o.status = d["status"].upper()                      # must end up as OPEN/PARTIAL/FILLED/CANCELLED/REJECTED
        o.filled_qty = int(d.get("filled_quantity", 0))
        o.avg_price = float(d.get("average_price") or 0)
        o.fills = [Fill(f["id"], o.client_order_id, o.symbol, o.side, int(f["quantity"]), float(f["price"]),
                        0.0, f.get("charges")) for f in d.get("fills", [])]
        return o

    async def place_order(self, req: OrderRequest) -> BrokerOrder:
        r = await self.http.post("/orders", json={            # TODO endpoint + payload
            "client_order_id": req.client_order_id, "symbol": req.symbol, "side": req.side,
            "quantity": req.qty, "order_type": req.order_type, "price": req.limit_price})
        if r.status_code in (400, 422):
            raise BrokerRejected(r.text)
        r.raise_for_status()
        return self._to_order(r.json())

    async def cancel_order(self, client_order_id):
        r = await self.http.delete(f"/orders/{client_order_id}")   # TODO
        return self._to_order(r.json()) if r.status_code == 200 else None

    async def get_order(self, client_order_id):
        r = await self.http.get(f"/orders/{client_order_id}")      # TODO
        return None if r.status_code == 404 else self._to_order(r.raise_for_status() or r.json())

    async def get_open_orders(self):
        r = await self.http.get("/orders", params={"status": "open"})   # TODO
        r.raise_for_status()
        return [self._to_order(d) for d in r.json()]

    async def get_positions(self):
        r = await self.http.get("/positions")                      # TODO
        r.raise_for_status()
        return {p["symbol"]: int(p["net_quantity"]) for p in r.json() if int(p["net_quantity"]) != 0}

    # ------------------------------------------------- ticks and fills
    def subscribe_ticks(self, cb): self._tick_cbs.append(cb)
    def unsubscribe_ticks(self, cb): self._tick_cbs.remove(cb) if cb in self._tick_cbs else None
    def subscribe_fills(self, cb): self._fill_cbs.append(cb)
    def unsubscribe_fills(self, cb): self._fill_cbs.remove(cb) if cb in self._fill_cbs else None

    async def _tick_loop(self):
        """TODO: replace with the real tick feed (WebSocket or polling)."""
        while True:
            for sym in self.symbols:
                r = await self.http.get(f"/ticks/{sym}")           # TODO
                if r.status_code == 200:
                    d = r.json()
                    tick = Tick(sym, float(d["price"]), float(d["timestamp"]), int(d.get("size", 1)))
                    for cb in list(self._tick_cbs):
                        cb(tick)
            await asyncio.sleep(self.poll)

    async def _fill_poll_loop(self):
        """If 021 has no fill push-stream, poll open orders and emit fills we have not seen yet."""
        while True:
            try:
                for o in await self.get_open_orders():
                    for f in o.fills:
                        if f.fill_id not in self._seen_fills:
                            self._seen_fills.add(f.fill_id)
                            for cb in list(self._fill_cbs):
                                cb(f)
            except Exception:
                pass
            await asyncio.sleep(self.poll)
