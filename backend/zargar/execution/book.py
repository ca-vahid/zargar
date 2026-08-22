"""The lifecycle record for one managed position, shared by the listener and
the exit planner. A technique's own trade object can either *be* a ManagedTrade
or expose the same fields (the exit planner reads a small view, below)."""
from __future__ import annotations

from dataclasses import dataclass, field

# The book's 30 / 40 / 15 scale-out at TP1 / TP2 / TP3; the rest rides as a
# runner. Shared so every technique ladders the same way.
EXIT_LADDER = (0.30, 0.40, 0.15)

# A working exit that has not filled after this many *closed* bars is stale — the
# price has moved past our limit; cancel and re-send at market. Keeps a stop from
# sitting un-filled at a delayed bid while the position bleeds.
EXIT_REPRICE_BARS = 2

# terminal statuses (no more management)
CLOSED_STATES = ("closed", "cancelled", "failed", "critic_killed", "skipped", "alert", "proposal")


@dataclass
class ExitLeg:
    kind: str                    # tp1 | tp2 | tp3 | stop | flatten | disarm | loss_halt
    qty: float
    order_id: str | None = None
    status: str | None = None
    filled_qty: float = 0.0
    price: float | None = None
    ts: int = 0
    bar_index: int | None = None   # closed-bar index the exit was sent on (re-price timeout)
    error: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "qty": self.qty, "orderId": self.order_id, "status": self.status,
                "filledQty": self.filled_qty, "price": self.price, "ts": self.ts,
                "barIndex": self.bar_index, "error": self.error}


@dataclass
class ManagedTrade:
    """Generic execution state. A technique subclass adds its own fields (which
    trigger fired, the option contract, etc.)."""
    key: str                     # unique within the plan (e.g. the trigger id)
    symbol: str                  # what is managed against (the underlying for options)
    entry: float
    stop: float
    targets: list[float] = field(default_factory=list)
    sec_type: str = "STK"
    order_symbol: str | None = None      # what is actually traded (OCC for options)
    multiplier: float = 1.0
    status: str = "fired"
    reason: str = ""
    entry_order_id: str | None = None
    limit_price: float | None = None
    qty: float = 0.0
    filled_qty: float = 0.0
    avg_fill: float | None = None
    remaining: float = 0.0
    trims_done: int = 0
    exit_order_ids: list[str] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    realized_pnl: float = 0.0
    last_price: float | None = None
    errors: list[str] = field(default_factory=list)
    opened_ts: int | None = None
    closed_ts: int | None = None
    fire_bar_index: int | None = None

    @property
    def open(self) -> bool:
        return self.status in ("working", "open")

    @property
    def pending_exit_qty(self) -> float:
        """Contracts/shares already committed to a working (un-resolved) exit —
        never send another exit for these or we oversell."""
        total = 0.0
        for e in self.exits:
            st = e.get("status")
            if st in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED", "ERROR", "FILLED"):
                continue
            total += float(e.get("qty") or 0) - float(e.get("filledQty") or 0)
        return max(0.0, total)
