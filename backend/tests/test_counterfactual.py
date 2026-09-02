"""Counterfactual ledger (PLATFORM-RULES 2026-09-02): a bug-missed trade replayed
through the runner's exit rules on real bars. Pure replay cases + the persisted
path (row + journal event) via the walk-forward rig; never a portfolio fill."""
import datetime as dt

from sqlalchemy import func, select

from zargar.domain import Bar
from zargar.execution import counterfactual as cf
from zargar.models import Event
from zargar.technique.rulebook import ET

from .test_technique_walkforward import rig  # noqa: F401

SESSION = "2026-09-02"
MIN = 60_000


def _ms(h: int, m: int) -> int:
    return int(dt.datetime(2026, 9, 2, h, m, tzinfo=ET).timestamp() * 1000)


def _bar(sym: str, ts: int, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(symbol=sym, tf="1m", ts=ts, open=o, high=h, low=lo, close=c, volume=100)


def _underlying(path: list[tuple[int, float, float, float, float]]) -> list[Bar]:
    return [_bar("NOW", ts, o, h, lo, c) for ts, o, h, lo, c in path]


def _contract(prints: dict[int, float]) -> list[Bar]:
    return [_bar("NOW260904P00140000", ts, px, px, px, px) for ts, px in sorted(prints.items())]


def test_short_put_fills_then_exits_in_full_at_tp2():
    # the NOW 2026-09-02 shape: reject at 141.69, stop 142.40, fired on the 09:30 close
    u = _underlying([
        (_ms(9, 31), 140.8, 142.0, 140.5, 141.1), (_ms(9, 32), 141.1, 141.9, 140.8, 141.7),
        (_ms(9, 33), 141.4, 142.6, 141.2, 142.57),   # closes through the stop BEFORE the fill: no position yet
        (_ms(9, 34), 142.5, 142.6, 141.9, 142.24), (_ms(9, 36), 142.1, 142.2, 140.5, 140.55),
        (_ms(9, 38), 140.2, 140.4, 140.10, 140.18),  # TP1 touch (140.10): 1 contract -> nothing yet
        (_ms(10, 17), 138.9, 138.9, 138.62, 138.71),  # TP2 touch (138.71): exit in full
        (_ms(10, 30), 138.8, 139.0, 138.7, 139.0),
    ])
    c = _contract({_ms(9, 31): 2.36, _ms(9, 32): 2.25, _ms(9, 34): 1.93, _ms(9, 35): 2.06,
                   _ms(9, 37): 2.85, _ms(10, 17): 3.44})
    r = cf.replay(direction="short", entry=141.69, stop=142.3984, targets=[140.102, 138.7125, 137.72],
                  fired_ts=_ms(9, 30), limit_price=2.03, qty=1, multiplier=100, underlying=u, contract=c,
                  session=SESSION, fee_per_unit_side=1.04)
    assert r["status"] == "win" and r["fillTs"] == _ms(9, 34) and r["fillPrice"] == 1.93
    assert [e["kind"] for e in r["exits"]] == ["tp2"] and r["exits"][0]["price"] == 3.44
    assert r["grossPnl"] == 151.0 and r["fees"] == 2.08 and r["pnl"] == 148.92
    assert r["rUnderlying"] > 4.0            # TP2 is 4.2R on the plan geometry


def test_stop_on_close_after_fill_and_stale_print_is_flagged():
    u = _underlying([(_ms(9, 31), 141.0, 141.5, 140.9, 141.2), (_ms(9, 33), 141.3, 142.7, 141.2, 142.55)])
    c = _contract({_ms(9, 31): 2.00})       # only one print: the stop exit reuses it, flagged stale
    r = cf.replay(direction="short", entry=141.69, stop=142.40, targets=[140.1, 138.7, 137.7],
                  fired_ts=_ms(9, 30), limit_price=2.03, qty=1, multiplier=100, underlying=u, contract=c, session=SESSION)
    assert r["status"] == "scratch" and r["exits"][0]["kind"] == "stop" and r["exits"][0]["price"] == 2.0
    assert any("stale" in n for n in r["notes"])


def test_not_filled_inside_the_entry_window_and_flatten_before_close():
    c = _contract({_ms(9, 31): 2.5, _ms(9, 45): 1.5})    # the dip comes after the 12-bar window
    u = _underlying([(_ms(9, 31), 141, 141.5, 140.9, 141.2)])
    r = cf.replay(direction="short", entry=141.69, stop=142.40, targets=[140.1, 138.7, 137.7],
                  fired_ts=_ms(9, 30), limit_price=2.03, qty=1, multiplier=100, underlying=u, contract=c, session=SESSION)
    assert r["status"] == "not_filled" and r["exits"] == []
    # shares long, 10 units: 30/40/15 ladder then a flatten of the runner at 15:55
    u = _underlying([(_ms(9, 31), 100, 100.2, 99.9, 100.1), (_ms(9, 40), 100.1, 101.0, 100.0, 100.9),
                     (_ms(9, 50), 100.9, 102.0, 100.8, 101.9), (_ms(15, 55), 101.5, 101.6, 101.4, 101.5)])
    r = cf.replay(direction="long", entry=100.0, stop=99.5, targets=[101.0, 102.0, 103.0],
                  fired_ts=_ms(9, 30), limit_price=100.05, qty=10, multiplier=1, underlying=u, contract=u, session=SESSION)
    assert [(e["kind"], e["qty"]) for e in r["exits"]] == [("tp1", 3.0), ("tp2", 4.0), ("flatten", 3.0)]
    assert r["status"] == "win" and r["remaining"] == 0


async def test_reconstruct_persists_a_row_and_a_journal_event_never_a_fill(rig, monkeypatch):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.sessions[rig.close_day][-1].ts, plan=True, wait=True)
    plan = run["result"]["plan"]
    trig = plan["triggers"][0]
    entry, stop = float(trig["entry"]["price"]), float(trig["stop"]["price"])
    day = dt.date.fromisoformat(plan["planFor"])
    t0 = int(dt.datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp() * 1000)
    tp = float(trig["targets"][1]["price"] if isinstance(trig["targets"][1], dict) else trig["targets"][1])
    bars = [_bar("TEST", t0 + MIN, entry, entry + 0.01, entry - 0.01, entry),
            _bar("TEST", t0 + 2 * MIN, entry, max(entry, tp) + 0.5, min(entry, tp) - 0.5, entry),
            _bar("TEST", t0 + 3 * MIN, entry, entry, entry, entry)]

    async def fake_fetch(symbol, tf, date, **kw):
        return bars
    monkeypatch.setattr(cf, "fetch_session", fake_fetch)
    cash_before = {p["id"]: p["cash"] for p in rig.eng.positions.portfolios()}
    kwargs = {"order_symbol": "TEST260904C00100000"}   # option path: 1 contract exits in full at TP2
    row = await cf.reconstruct(rig.eng, run["id"], trig["id"], reason="test bug", limit_price=entry + 0.02,
                               qty=1, fired_ts=t0, **kwargs)
    assert row["runId"] == run["id"] and row["status"] in ("win", "loss", "scratch")
    assert (await cf.list_rows(rig.eng))[0]["id"] == row["id"]
    async with rig.eng.sf() as s:
        n = (await s.execute(select(func.count(Event.id)).where(Event.type == "TechniqueCounterfactual"))).scalar()
    assert n == 1
    assert {p["id"]: p["cash"] for p in rig.eng.positions.portfolios()} == cash_before   # never a fill
