"""Recorded order-layer double whose acknowledged reports are durable in PostgreSQL."""
from zargar.models import Order

from .test_position_chaos import FakeOrders


class RecordedOrders(FakeOrders):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine

    async def place(self, intent):
        if intent.order_type == "STP":
            self.script.setdefault(self.n, {"status": "ACCEPTED"})
        result = await super().place(intent)
        async with self.engine.sf() as session, session.begin():
            session.add(Order(id=result["id"], portfolio_id=intent.portfolio_id, symbol=intent.symbol,
                              sec_type=intent.sec_type, side=intent.side, qty=intent.qty,
                              order_type=intent.order_type, limit_price=intent.limit_price,
                              stop_price=intent.stop_price, tif=intent.tif, technique=intent.technique_id,
                              tags=list(intent.tags), status=result["status"],
                              filled_qty=result["filledQty"], avg_fill_price=result.get("avgFillPrice")))
        return result

    async def cancel(self, order_id):
        result = await super().cancel(order_id)
        async with self.engine.sf() as session, session.begin():
            order = await session.get(Order, order_id)
            if order and order.status not in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED", "REJECTED_RISK"):
                order.status = "CANCELLED"
        return result
