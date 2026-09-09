"""Operational state for restarts (2026-09-09, after the F75 review).

"No open positions" was never the right restart test: an armed plan mid-fire, a working entry, a
resting exit, a venue order the book has not heard back about, a paid analyst read — all of those
die with the process or come back wrong. `restart_state` enumerates what is in flight across EVERY
technique (the `engine.plan_runners` registry) plus the shared order book and analyst runs;
`restart_readiness` turns that into a yes/no with reasons. `scripts/start.ps1` (the one door every
restart path goes through, including the scheduler's `ZargarRestart` task) asks before it stops
anything and refuses unless overridden, then compares the state after the restart with the state
before it (restoration check) — see PLATFORM-RULES 2026-09-09.
"""
from __future__ import annotations

import datetime as dt
import logging

from .domain import now_ms
from .marketstructure.market_calendar import is_market_minute

log = logging.getLogger("zargar.ops")

MONEY_MODES = ("proposal", "auto")


async def restart_state(engine) -> dict:
    """Everything a restart could interrupt, by id, so a before/after comparison is exact."""
    armed: list[str] = []
    open_trades: list[str] = []
    working_entries: list[str] = []
    pending_exits: list[str] = []
    alert_only = 0
    for tid, runner in (getattr(engine, "plan_runners", None) or {}).items():
        for ap in list((getattr(runner, "_armed", None) or {}).values()):
            if getattr(ap, "status", "") not in ("armed", "paused"):
                continue
            armed.append(f"{tid}:{ap.run_id}")
            money = getattr(getattr(ap, "config", None), "mode", "") in MONEY_MODES
            if not money:
                alert_only += 1
            for tr in (getattr(ap, "trades", None) or {}).values():
                key = f"{tid}:{ap.symbol}:{tr.trigger_id}"
                if tr.status == "open":
                    open_trades.append(key)
                elif tr.status in ("working", "submitting"):
                    working_entries.append(key)
                try:
                    if tr.pending_exit_qty > 1e-9:
                        pending_exits.append(key)
                except Exception:  # noqa: BLE001 - a malformed exit record must not break the check
                    pass
    # venue orders: an order the venue has not acknowledged (or has partially filled) is IN FLIGHT - its
    # outcome is unknown across a restart; an ACCEPTED order is RESTING (a durable position's stop, a
    # resting limit): the sim book restores it and a live venue keeps it, so it is not a reason to
    # refuse - it is a thing the restoration check must find again, by id.
    inflight_orders: list[str] = []
    resting_orders: list[str] = []
    orders = getattr(engine, "orders", None)
    if orders is not None:
        try:
            for o in await orders.list_orders(open_only=True, limit=500):
                key = f"{o.get('id')}:{o.get('symbol')}"
                if str(o.get("status")) == "ACCEPTED":
                    resting_orders.append(key)
                else:
                    inflight_orders.append(key)
        except Exception:  # noqa: BLE001
            log.debug("restart_state: order book unavailable", exc_info=True)
    managed_open = 0
    pm = getattr(engine, "position_manager", None)
    if pm is not None:
        try:
            managed_open = len(pm.positions(status="open"))
        except Exception:  # noqa: BLE001
            pass
    running = 0
    svc = getattr(engine, "technique", None)
    if svc is not None:
        try:
            st = await svc.status()
            running = len(st.get("running") or [])
        except Exception:  # noqa: BLE001
            pass
    proposals_pending = 0
    props = getattr(engine, "proposals", None)
    if props is not None and hasattr(props, "list_pending"):
        try:
            proposals_pending = len(await props.list_pending())
        except Exception:  # noqa: BLE001
            pass
    now = now_ms()
    return {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "marketOpen": bool(is_market_minute(now)),
        "armed": sorted(armed),
        "alertOnly": alert_only,
        "openTrades": sorted(open_trades),
        "workingEntries": sorted(working_entries),
        "pendingExits": sorted(pending_exits),
        "inflightOrders": sorted(inflight_orders),
        "restingOrders": sorted(resting_orders),
        "managedOpen": managed_open,
        "inflightRuns": running,
        "proposalsPending": proposals_pending,
    }


def readiness_from_state(state: dict) -> dict:
    """Safe = nothing a restart would interrupt. Armed plans, open managed positions and RESTING venue
    orders are write-ahead / venue-held and restore, so they are reported and restoration-checked,
    not blocking; anything with an order in the air or money mid-decision blocks."""
    reasons: list[str] = []
    if state.get("inflightRuns"):
        reasons.append(f"{state['inflightRuns']} analyst run(s) in flight (they cost money)")
    if state.get("workingEntries"):
        reasons.append(f"{len(state['workingEntries'])} technique entry order(s) working: " + ", ".join(state["workingEntries"][:5]))
    if state.get("pendingExits"):
        reasons.append(f"{len(state['pendingExits'])} technique exit order(s) pending: " + ", ".join(state["pendingExits"][:5]))
    if state.get("openTrades"):
        reasons.append(f"{len(state['openTrades'])} open technique trade(s) being managed: " + ", ".join(state["openTrades"][:5]))
    if state.get("inflightOrders"):
        reasons.append(f"{len(state['inflightOrders'])} venue order(s) in flight (submitted / partially filled, outcome unknown): "
                       + ", ".join(state["inflightOrders"][:5]))
    return {"safe": not reasons, "reasons": reasons, "state": state}


async def restart_readiness(engine, *, journal: bool = True, caller: str = "") -> dict:
    out = readiness_from_state(await restart_state(engine))
    if journal:
        try:
            from . import events as ev
            await engine.journal.append(ev.OPS_RESTART_CHECK, {
                "safe": out["safe"], "reasons": out["reasons"], "caller": caller or "",
                "armed": len(out["state"]["armed"]), "openTrades": len(out["state"]["openTrades"]),
                "inflightOrders": len(out["state"]["inflightOrders"]), "restingOrders": len(out["state"]["restingOrders"]),
                "marketOpen": out["state"]["marketOpen"],
            })
        except Exception:  # noqa: BLE001 - the answer matters more than its record
            log.debug("restart check not journaled", exc_info=True)
    return out


def compare_states(before: dict, after: dict) -> dict:
    """The restoration check: what was armed / open / working before the restart must be armed /
    open / working after it. Returns {ok, missing: {...}, counts: {...}}."""
    missing = {}
    for key in ("armed", "openTrades", "pendingExits", "restingOrders", "inflightOrders"):
        b = set(before.get(key) or [])
        a = set(after.get(key) or [])
        lost = sorted(b - a)
        if lost:
            missing[key] = lost
    counts = {key: f"{len(after.get(key) or [])}/{len(before.get(key) or [])}"
              for key in ("armed", "openTrades", "pendingExits", "restingOrders", "inflightOrders")}
    return {"ok": not missing, "missing": missing, "counts": counts}
