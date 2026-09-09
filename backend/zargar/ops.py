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
    firing: list[str] = []            # R1: fire chains in flight (contract pick / critic / order) — not yet a trade
    alert_only = 0
    for tid, runner in (getattr(engine, "plan_runners", None) or {}).items():
        for ap in list((getattr(runner, "_armed", None) or {}).values()):
            if getattr(ap, "status", "") not in ("armed", "paused"):
                continue
            armed.append(f"{tid}:{ap.run_id}")
            money = getattr(getattr(ap, "config", None), "mode", "") in MONEY_MODES
            if not money:
                alert_only += 1
            in_flight = set((getattr(ap, "fire_tasks", None) or {}).keys())
            for tr in (getattr(ap, "trades", None) or {}).values():
                key = f"{tid}:{ap.symbol}:{tr.trigger_id}"
                if tr.status == "open":
                    open_trades.append(key)
                elif tr.status in ("working", "submitting"):
                    working_entries.append(key)
                elif tr.status == "fired" and money:
                    firing.append(key)              # fired, money mode, decision not yet made
                if tr.trigger_id in in_flight:
                    in_flight.discard(tr.trigger_id)
                    if key not in firing:
                        firing.append(key)          # a fire chain task is running for this trigger
                try:
                    if tr.pending_exit_qty > 1e-9:
                        pending_exits.append(key)
                except Exception:  # noqa: BLE001 - a malformed exit record must not break the check
                    pass
            for tid_ in sorted(in_flight):          # a chain task with no trade record yet
                firing.append(f"{tid}:{ap.symbol}:{tid_}")
    # venue orders: an order the venue has not acknowledged (or has partially filled) is IN FLIGHT - its
    # outcome is unknown across a restart; an ACCEPTED order is RESTING (a durable position's stop, a
    # resting limit): the sim book restores it and a live venue keeps it, so it is not a reason to
    # refuse - it is a thing the restoration check must find again, by id.
    inflight_orders: list[str] = []
    resting_orders: list[str] = []
    inventory_error: str | None = None
    orders = getattr(engine, "orders", None)
    if orders is not None:
        try:
            for o in await orders.list_orders(open_only=True, limit=500):
                key = f"{o.get('id')}:{o.get('symbol')}"
                if str(o.get("status")) == "ACCEPTED":
                    resting_orders.append(key)
                else:
                    inflight_orders.append(key)
        except Exception as exc:  # noqa: BLE001 - R1: an unknown inventory is reported, never treated as empty
            log.warning("restart_state: order book unavailable: %s", exc)
            inventory_error = f"{type(exc).__name__}: {exc}"[:160]
    managed_open = 0
    managed_positions: list[str] = []
    managed_closed: list[str] = []
    pm = getattr(engine, "position_manager", None)
    if pm is not None:
        try:
            for p_ in pm.positions():
                key = f"{p_.get('id')}:{p_.get('symbol')}"
                if p_.get("status") == "open":
                    managed_positions.append(key)
                else:
                    managed_closed.append(key)      # a legitimate close is explained by the position itself
            managed_open = len(managed_positions)
        except Exception as exc:  # noqa: BLE001
            inventory_error = (inventory_error + "; " if inventory_error else "") + f"positions: {exc}"[:160]
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
    q_until = int(getattr(engine, "quiesce_until_ms", 0) or 0)
    return {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "marketOpen": bool(is_market_minute(now)),
        "armed": sorted(armed),
        "alertOnly": alert_only,
        "openTrades": sorted(open_trades),
        "workingEntries": sorted(working_entries),
        "firing": sorted(firing),
        "pendingExits": sorted(pending_exits),
        "inflightOrders": sorted(inflight_orders),
        "restingOrders": sorted(resting_orders),
        "inventoryError": inventory_error,
        "managedOpen": managed_open,
        "managedPositions": sorted(managed_positions),
        "managedClosed": sorted(managed_closed),
        "inflightRuns": running,
        "proposalsPending": proposals_pending,
        "quiesced": q_until > now,
        "quiesceUntil": q_until or None,
    }


def readiness_from_state(state: dict) -> dict:
    """Safe = nothing a restart would interrupt. Armed plans, open managed positions and RESTING venue
    orders are write-ahead / venue-held and restore, so they are reported and restoration-checked,
    not blocking; anything with an order in the air or money mid-decision blocks."""
    reasons: list[str] = []
    if state.get("inventoryError"):
        # R1: missing evidence is not a safe inventory
        reasons.append(f"order/position inventory unavailable ({state['inventoryError']}) — unknown is not safe")
    if state.get("firing"):
        reasons.append(f"{len(state['firing'])} fire chain(s) in flight (contract pick / review / order not yet decided): "
                       + ", ".join(state["firing"][:5]))
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
                "firing": len(out["state"]["firing"]), "managedOpen": out["state"]["managedOpen"],
                "inventoryError": out["state"]["inventoryError"], "quiesced": out["state"]["quiesced"],
                "marketOpen": out["state"]["marketOpen"],
            })
        except Exception:  # noqa: BLE001 - the answer matters more than its record
            log.debug("restart check not journaled", exc_info=True)
    return out


ID_KEYS = ("armed", "openTrades", "workingEntries", "pendingExits", "restingOrders", "inflightOrders", "managedPositions")


def compare_states(before: dict, after: dict) -> dict:
    """The restoration check: what was armed / open / working / held before the restart must be there
    after it — by id. A managed position that is gone but shows up CLOSED afterwards is explained (a
    fill or an exit landed), not missing (review R2); an unexplained disappearance, or a lower open
    count when only counts are known, fails the check. Returns {ok, missing, explained, counts}."""
    missing: dict = {}
    explained: dict = {}
    for key in ID_KEYS:
        b = set(before.get(key) or [])
        a = set(after.get(key) or [])
        lost = sorted(b - a)
        if key == "managedPositions" and lost:
            closed = set(after.get("managedClosed") or [])
            expl = [x for x in lost if x in closed]
            lost = [x for x in lost if x not in closed]
            if expl:
                explained[key] = expl
        if lost:
            missing[key] = lost
    if "managedPositions" not in before and before.get("managedOpen") is not None:
        b_n, a_n = int(before.get("managedOpen") or 0), int(after.get("managedOpen") or 0)
        if a_n < b_n:
            missing["managedOpen"] = [f"{b_n} -> {a_n}"]
    counts = {key: f"{len(after.get(key) or [])}/{len(before.get(key) or [])}" for key in ID_KEYS}
    counts["managedOpen"] = f"{after.get('managedOpen', 0)}/{before.get('managedOpen', 0)}"
    return {"ok": not missing, "missing": missing, "explained": explained, "counts": counts}


def quiesce(engine, minutes: float = 5.0) -> int:
    """Suspend NEW entries (fire chains in money modes) while a restart is pending; exits keep running.
    Self-expiring so an aborted restart never leaves the desk frozen. Returns the expiry (epoch ms)."""
    until = now_ms() + int(max(0.5, float(minutes)) * 60_000)
    engine.quiesce_until_ms = until
    return until


def release_quiesce(engine) -> None:
    engine.quiesce_until_ms = 0


def is_quiesced(engine) -> bool:
    return int(getattr(engine, "quiesce_until_ms", 0) or 0) > now_ms()
