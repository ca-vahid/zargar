"""2026-10-02 Tips review: W1.5 (gateway head-of-line blocking), W1.6 (clock skew), W3.4 (intake paging).

No LLM calls: the extractor and the analyst are stubs; the clock-skew reference is a stubbed fetch."""
import asyncio
import datetime as dt
import email.utils
import json
import time
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from zargar import events as ev
from zargar.engine import Engine
from zargar.models import Event, Proposal, RawContent, Signal
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.tools.discord_gateway import Gateway

from .conftest import make_test_config, wait_for

SOURCE_TEXT = """ALERT: We are buying AAPL today. Entry at $231.50, stop loss $220, target $260.
Apple remains our top pick."""
CLOSE_TEXT = "Closing AAPL here, I'm out of the whole position."


def _open_signal():
    return TradeSignal(
        ticker="AAPL", direction="long", action="open",
        entry_price=231.50, target_price=260.0, stop_price=220.0,
        entry_type="limit", timeframe="swing", thesis_summary="Top pick.",
        evidence_quotes=["We are buying AAPL today", "Entry at $231.50, stop loss $220, target $260"],
        confidence="explicit_call", is_actionable=True)


def _close_signal():
    return TradeSignal(
        ticker="AAPL", direction="long", action="close", entry_type="market", timeframe="swing",
        thesis_summary="Source closed.", evidence_quotes=["Closing AAPL here"],
        confidence="explicit_call", is_actionable=True)


class _Extractor:
    available = True
    model = "stub"

    def __init__(self):
        self.calls = []

    async def extract(self, text, **kw):
        self.calls.append(text)
        if text.startswith("Closing AAPL"):
            return ExtractionResult(signals=[_close_signal()], source_type="trade_alert")
        return ExtractionResult(signals=[_open_signal()], source_type="trade_alert")


class _Analyst:
    """Stub `analyze_tip`: blocks until released (the slow appraisal the gateway used to wait for)."""

    def __init__(self, verdict="watch"):
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.calls = 0
        self.verdict = verdict

    async def __call__(self, eng, row, verification, policy, **kw):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return {"verdict": self.verdict, "rationale": "stub appraisal", "runId": None}


@pytest.fixture
async def rig(fresh_db, monkeypatch):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    svc = eng.signals_service
    svc.extractor = _Extractor()
    svc._analyst_client = object()               # analyst "available" (the stub never touches it)
    analyst = _Analyst()
    from zargar.techniques.tip import analyst as analyst_mod
    monkeypatch.setattr(analyst_mod, "analyze_tip", analyst)
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    yield eng, svc, analyst
    analyst.release.set()
    await svc.wait_deferred(5)
    await eng.stop()


async def _signal(eng, sid):
    async with eng.sf() as session:
        return await session.get(Signal, sid)


async def _proposals_for(eng, sid):
    async with eng.sf() as session:
        return (await session.execute(select(Proposal).where(Proposal.signal_id == sid))).scalars().all()


async def _events(eng, kind):
    async with eng.sf() as session:
        return (await session.execute(select(Event).where(Event.type == kind))).scalars().all()


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ------------------------------------------------------------------ W1.5 app side
async def test_async_ingest_returns_once_the_signal_is_recorded(rig):
    eng, svc, analyst = rig
    out = await asyncio.wait_for(svc.ingest_manual(SOURCE_TEXT, source_name="TestLetter", message_id="w15-1",
                                                   posted_at=_now_iso(), async_appraisal=True), 60)
    # the answer came back while the appraisal is still blocked
    assert out["appraisal"] == "deferred" and out["deferredSignals"] == 1
    [item] = out["signals"]
    sid = item["signal"]["id"]
    assert item["signal"]["status"] == "verified" and item["appraisal"] == "pending"
    row = await _signal(eng, sid)
    assert row.extraction["deferredStage"]["state"] == "pending"       # durable marker for the recovery sweep
    async with eng.sf() as session:
        assert (await session.get(RawContent, out["contentId"])).status == "extracted"   # the ACK point
    await asyncio.wait_for(analyst.started.wait(), 30)
    assert not await _proposals_for(eng, sid)                          # nothing decided yet
    analyst.release.set()
    await svc.wait_deferred(30)
    row = await _signal(eng, sid)
    assert row.extraction["analyst"]["verdict"] == "watch"
    assert row.extraction["deferredStage"]["state"] == "done"
    assert len(await _proposals_for(eng, sid)) == 1                     # the lane decision ran after
    assert await _events(eng, ev.TIP_APPRAISAL_DEFERRED)
    [done] = await _events(eng, ev.TIP_APPRAISAL_DEFERRED_DONE)
    assert done.payload["done"] == 1 and done.payload["failed"] == 0


async def test_setting_off_keeps_the_synchronous_ingest(rig):
    eng, svc, analyst = rig
    await eng.settings.set("techniques.tip.intake_async_appraisal", False)
    analyst.release.set()
    out = await svc.ingest_manual(SOURCE_TEXT, source_name="TestLetter", message_id="w15-2",
                                  posted_at=_now_iso(), async_appraisal=True)
    assert "appraisal" not in out and analyst.calls == 1
    [item] = out["signals"]
    assert item["proposal"] is not None
    assert "deferredStage" not in ((await _signal(eng, item["signal"]["id"])).extraction or {})


async def test_followup_recorded_while_the_appraisal_ran_blocks_the_card(rig):
    """Order at extraction is preserved (open recorded before close); the deferred card for the open must honour
    the close the source posted while the analyst was still thinking - a synchronous intake expired it."""
    eng, svc, analyst = rig
    o = await svc.ingest_manual(SOURCE_TEXT, source_name="TestLetter", message_id="w15-3a",
                                posted_at=_now_iso(), async_appraisal=True)
    sid = o["signals"][0]["signal"]["id"]
    await asyncio.wait_for(analyst.started.wait(), 30)
    c = await asyncio.wait_for(svc.ingest_manual(CLOSE_TEXT, source_name="TestLetter", message_id="w15-3b",
                                                 posted_at=_now_iso(), async_appraisal=True), 60)
    assert c["signals"][0]["signal"]["action"] == "close"
    analyst.release.set()
    await svc.wait_deferred(30)
    assert not await _proposals_for(eng, sid)
    refused = [e for e in await _events(eng, ev.TIP_LANE_DECIDED)
               if e.aggregate_id == sid and e.payload.get("lane") == "refused"]
    assert refused and "close" in refused[0].payload["reason"]


async def test_recovery_sweep_resumes_an_orphaned_stage_once(rig):
    eng, svc, analyst = rig
    out = await svc.ingest_manual(SOURCE_TEXT, source_name="TestLetter", message_id="w15-4",
                                  posted_at=_now_iso(), async_appraisal=True)
    sid = out["signals"][0]["signal"]["id"]
    await asyncio.wait_for(analyst.started.wait(), 30)
    # the process "dies" mid-appraisal: the task is cancelled, the marker stays pending
    for t in list(svc.__dict__.get("_deferred_tasks") or ()):
        t.cancel()
    await svc.wait_deferred(5)
    assert (await _signal(eng, sid)).extraction["deferredStage"]["state"] == "pending"
    assert sid not in svc._deferred_inflight()
    async with eng.sf() as session:                    # old enough to be an orphan, young enough to resume
        row = await session.get(Signal, sid)
        row.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=120)
        await session.commit()
    analyst.release.set()
    res = await svc.recover_deferred_stages()
    assert res == {"resumed": 1, "abandoned": 0}
    await svc.wait_deferred(30)
    row = await _signal(eng, sid)
    assert row.extraction["deferredStage"]["state"] == "done"
    assert row.extraction["analyst"]["verdict"] == "watch"
    assert len(await _proposals_for(eng, sid)) == 1
    # a second sweep finds nothing to do (and never mints a second card)
    assert await svc.recover_deferred_stages() == {"resumed": 0, "abandoned": 0}
    assert len(await _proposals_for(eng, sid)) == 1


async def test_recovery_abandons_a_stale_orphan(rig):
    eng, svc, analyst = rig
    out = await svc.ingest_manual(SOURCE_TEXT, source_name="TestLetter", message_id="w15-5",
                                  posted_at=_now_iso(), async_appraisal=True)
    sid = out["signals"][0]["signal"]["id"]
    await asyncio.wait_for(analyst.started.wait(), 30)
    for t in list(svc.__dict__.get("_deferred_tasks") or ()):
        t.cancel()
    await svc.wait_deferred(5)
    async with eng.sf() as session:
        row = await session.get(Signal, sid)
        row.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        await session.commit()
    assert await svc.recover_deferred_stages() == {"resumed": 0, "abandoned": 1}
    assert (await _signal(eng, sid)).extraction["deferredStage"]["state"] == "abandoned"
    assert not await _proposals_for(eng, sid)


# ------------------------------------------------------------------ W1.5 gateway side
def _gateway(tmp_path, **kw) -> Gateway:
    gw = Gateway("tok", "http://app", "", tmp_path / "dms.jsonl", ingest=True, dump=False, bots_only=False,
                 author_id="", channel_id="", **kw)
    gw._watch = {"c1": {"channelId": "c1", "enabled": True, "sourceName": "src1", "botsOnly": False},
                 "c2": {"channelId": "c2", "enabled": True, "sourceName": "src2", "botsOnly": False}}
    gw._queue = asyncio.Queue(50)
    return gw


def _msg(mid, cid="c1", text="BUY TEST"):
    return {"id": mid, "channel_id": cid, "guild_id": "g", "content": text,
            "timestamp": "2026-10-02T14:00:00+00:00", "author": {"id": "a1", "username": "alice", "bot": True}}


class _FakeApp:
    """The app as the gateway sees it: `asyncAppraisal` answers after the (short) record step and appraises in a
    background task; without it the (long) appraisal is part of the answer - the pre-W1.5 behaviour."""

    def __init__(self, record_s=0.02, appraise_s=0.6):
        self.record_s, self.appraise_s = record_s, appraise_s
        self.log: list[tuple[str, str, float]] = []     # (event, mid, t)
        self.bodies: list[dict] = []
        self.tasks: set = set()

    async def _appraise(self, mid):
        await asyncio.sleep(self.appraise_s)
        self.log.append(("appraised", mid, time.monotonic()))

    async def post(self, url, json=None, **kw):
        if url.endswith("/api/ingest/manual"):
            mid = json["messageId"]
            self.bodies.append(json)
            self.log.append(("extract", mid, time.monotonic()))
            await asyncio.sleep(self.record_s)
            self.log.append(("recorded", mid, time.monotonic()))
            if json.get("asyncAppraisal"):
                t = asyncio.create_task(self._appraise(mid))
                self.tasks.add(t)
            else:
                await self._appraise(mid)
            return NS(status_code=200, json=lambda: {"signals": [], "contentId": mid})
        return NS(status_code=200, json=lambda: {})


async def _drain(gw, app):
    workers = [asyncio.create_task(gw._worker(app, {})) for _ in range(gw.workers)]
    await asyncio.wait_for(gw._queue.join(), 10)
    for w in workers:
        w.cancel()
    if app.tasks:
        await asyncio.wait(app.tasks, timeout=10)


def test_gateway_defaults_to_six_workers_and_async_appraisal(tmp_path):
    gw = _gateway(tmp_path)
    assert gw.workers == 6 and gw.async_appraisal is True
    assert _gateway(tmp_path, workers=3).workers == 3


async def test_appraisal_no_longer_blocks_the_next_message_in_the_channel(tmp_path):
    gw = _gateway(tmp_path)
    app = _FakeApp()
    for mid in ("101", "102", "103"):
        gw._enqueue("create", _msg(mid))
    await _drain(gw, app)
    assert all(b["asyncAppraisal"] is True for b in app.bodies)
    ext = [m for e, m, _ in app.log if e == "extract"]
    assert ext == ["101", "102", "103"]                          # per-channel ORDER at extraction preserved
    t = {(e, m): ts for e, m, ts in app.log}
    # each next message was extracted only after the previous one was RECORDED...
    assert t[("extract", "102")] >= t[("recorded", "101")] and t[("extract", "103")] >= t[("recorded", "102")]
    # ...but long before the previous one's appraisal finished
    assert t[("extract", "102")] < t[("appraised", "101")] and t[("extract", "103")] < t[("appraised", "101")]
    assert gw._store.counts() == (0, 0)                          # every envelope ACKed
    assert gw._store.cursors.get("c1") == "103"


async def test_sync_mode_still_serialises_on_the_appraisal(tmp_path):
    """The rollback (`--sync-appraisal`) is the old behaviour: the channel waits for the appraisal."""
    gw = _gateway(tmp_path)
    gw.async_appraisal = False
    app = _FakeApp(appraise_s=0.2)
    for mid in ("201", "202"):
        gw._enqueue("create", _msg(mid))
    await _drain(gw, app)
    t = {(e, m): ts for e, m, ts in app.log}
    assert t[("extract", "202")] >= t[("appraised", "201")]


async def test_process_last_message_keeps_the_synchronous_report(tmp_path):
    gw = _gateway(tmp_path)
    app = _FakeApp(appraise_s=0.0)
    await gw._ingest_message(app, {}, _msg("301"), "src1", async_appraisal=False)
    assert app.bodies[-1]["asyncAppraisal"] is False


# ------------------------------------------------------------------ W1.6 clock skew
class _Settings(dict):
    def get(self, k, default=None):
        return super().get(k, default)


class _Journal:
    def __init__(self):
        self.rows = []

    async def append(self, kind, payload, **kw):
        self.rows.append((kind, payload, kw))


def _fake_eng(**settings):
    return NS(settings=_Settings(settings), journal=_Journal(), bus=NS(publish=lambda *a, **k: None))


def _fetch_with_offset(offset_s: float):
    async def fetch(url):
        t0 = time.time()
        t1 = t0 + 0.04
        return t0, t1, email.utils.formatdate((t0 + t1) / 2 - offset_s, usegmt=True)
    return fetch


def test_skew_from_is_signed_and_uses_the_date_midpoint():
    from zargar.clockskew import skew_from
    t = 1_790_000_000.0                                  # whole second
    hdr = email.utils.formatdate(t, usegmt=True)
    skew, rtt = skew_from(t + 10.4, t + 10.6, hdr)       # host 10.5 s AHEAD of Date+0.5
    assert skew == pytest.approx(10000.0, abs=1) and rtt == pytest.approx(200.0, abs=1)
    skew, _ = skew_from(t - 4.0, t - 4.0, hdr)           # host behind
    assert skew < -4000


async def test_clock_skew_above_threshold_is_journaled_and_escalated(monkeypatch):
    from zargar import clockskew, desk_alert
    sent = []

    async def fake_escalate(eng, title, text, **kw):
        sent.append((title, text, kw))
        return {"toast": True, "push": True, "telegram": True}
    monkeypatch.setattr(desk_alert, "escalate", fake_escalate)
    eng = _fake_eng(**{"ops.clock_skew_alert_ms": 2000, "ops.clock_skew_references": ["https://ref.example"]})
    m = await clockskew.check(eng, fetch=_fetch_with_offset(10.0), trigger="startup")   # host 10 s ahead
    assert m["ok"] and m["alert"] and 9000 <= m["skewMs"] <= 11000
    assert m["reference"] == "https://ref.example"
    assert eng.clock_skew is m
    [(kind, payload, _)] = eng.journal.rows
    assert kind == ev.CLOCK_SKEW == "ClockSkew"
    assert payload["skewMs"] == m["skewMs"] and payload["reference"] == "https://ref.example"
    assert sent and sent[0][2]["tag"] == "clock-skew"


async def test_small_skew_and_failed_probe_do_not_alert(monkeypatch):
    from zargar import clockskew, desk_alert
    sent = []

    async def fake_escalate(*a, **kw):
        sent.append(a)
        return {}
    monkeypatch.setattr(desk_alert, "escalate", fake_escalate)
    eng = _fake_eng(**{"ops.clock_skew_alert_ms": 2000})
    m = await clockskew.check(eng, fetch=_fetch_with_offset(0.0))
    assert m["ok"] and not m["alert"] and abs(m["skewMs"]) < 1600

    async def down(url):
        raise OSError("offline")
    m = await clockskew.check(eng, fetch=down)
    assert not m["ok"] and not m["alert"] and m["skewMs"] is None and len(m["errors"]) == 2
    assert not sent
    assert [k for k, _, _ in eng.journal.rows] == ["ClockSkew", "ClockSkew"]


async def test_ntp_quorum_is_preferred_and_http_date_is_the_fallback(monkeypatch):
    from zargar import clockskew, desk_alert

    async def fake_escalate(*a, **kw):
        return {}
    monkeypatch.setattr(desk_alert, "escalate", fake_escalate)
    eng = _fake_eng(**{"ops.clock_skew_alert_ms": 2000, "ops.clock_skew_ntp_servers": ["a", "b", "c"]})
    # NTP: host 10.5 s BEHIND (positive NTP offset) -> skewMs -10500, alert
    quorum = {"offsetMs": 10500.0, "agreed": True, "worstUncertaintyMs": 12.0,
              "servers": [{"server": s} for s in ("a", "b", "c")]}
    m = await clockskew.check(eng, ntp=lambda servers: quorum, fetch=_fetch_with_offset(0.0))
    assert m["skewMs"] == -10500.0 and m["alert"] and m["reference"].startswith("ntp:3")
    # a disagreeing quorum is not trusted: the HTTP Date reading is used, the reason kept
    bad = {**quorum, "agreed": False, "why": "the servers disagree"}
    m = await clockskew.check(eng, ntp=lambda servers: bad, fetch=_fetch_with_offset(0.0))
    assert m["reference"] == clockskew.DEFAULT_REFERENCES[0] and not m["alert"]
    assert m["ntpNote"] == "the servers disagree"
    assert eng.journal.rows[-1][1]["ntpNote"] == "the servers disagree"


async def test_health_reports_the_last_clock_skew(fresh_db):
    import httpx

    from zargar.api.app import create_app
    eng = Engine(make_test_config())
    await eng.start()
    try:
        assert "clock_skew_check" not in {j["name"] for j in eng.scheduler.status()}   # the probe is off in tests
        eng.clock_skew = {"ok": True, "skewMs": -10500.0, "reference": "https://www.google.com",
                          "at": _now_iso(), "thresholdMs": 2000, "alert": True}
        app = create_app(eng.config, eng)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get("/api/health")).json()
        assert body["local"]["clockSkewMs"] == -10500.0
        assert body["local"]["clockSkew"]["alert"] is True
    finally:
        await eng.stop()


def test_clock_skew_registers_startup_check_and_daily_job():
    from zargar import clockskew
    jobs, tasks = {}, []
    eng = NS(config=NS(clock_skew_probe=True), settings=_Settings({"ops.clock_skew_at": "08:00"}),
             scheduler=NS(register=lambda name, at, fn, **kw: jobs.update({name: (at, kw)})), _tasks=tasks)

    async def go():
        clockskew.register(eng)
        for t in tasks:
            t.cancel()
    asyncio.run(go())
    assert jobs == {"clock_skew_check": ("08:00", {"weekdays_only": False})} and len(tasks) == 1


# ------------------------------------------------------------------ W3.4 intake paging
RTH = dt.datetime(2026, 10, 1, 14, 0, tzinfo=dt.timezone.utc)          # Thu 10:00 ET
AFTER = dt.datetime(2026, 10, 1, 21, 0, tzinfo=dt.timezone.utc)        # Thu 17:00 ET


def _status(now, *, frame_age, status_age=5, state="connected"):
    return {"pid": 1, "state": state, "at": (now - dt.timedelta(seconds=status_age)).isoformat(),
            "lastFrameAt": (now - dt.timedelta(seconds=frame_age)).isoformat(),
            "connectedAt": (now - dt.timedelta(hours=1)).isoformat()}


def test_idle_seconds_and_rth_window():
    from zargar.techniques.tip.intake_liveness import idle_seconds, in_rth
    assert idle_seconds(None, RTH) is None
    assert idle_seconds(_status(RTH, frame_age=10), RTH) == pytest.approx(10)
    assert idle_seconds(_status(RTH, frame_age=10, status_age=400), RTH) == pytest.approx(400)   # process gone
    assert idle_seconds(_status(RTH, frame_age=250, state="disconnected"), RTH) == pytest.approx(250)
    assert in_rth(RTH) and not in_rth(AFTER)
    assert not in_rth(dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.timezone.utc))                  # Saturday
    assert not in_rth(dt.datetime(2026, 10, 1, 13, 15, tzinfo=dt.timezone.utc))                 # 09:15 ET


def test_pager_pages_once_per_stall_and_recovers():
    from zargar.techniques.tip.intake_liveness import StallPager
    p = StallPager()
    thr = 180.0
    assert p.observe(RTH, 60, threshold_s=thr, rth=True) is None
    assert p.observe(RTH, 200, threshold_s=thr, rth=True) == "page"
    for idle in (230, 600, 4000):                                           # debounced: one page per stall
        assert p.observe(RTH, idle, threshold_s=thr, rth=True) is None
    assert p.observe(RTH, 5, threshold_s=thr, rth=True) == "recover"
    assert p.observe(RTH, 5, threshold_s=thr, rth=True) is None             # no repeat recovery
    assert p.observe(AFTER, 9999, threshold_s=thr, rth=False) is None       # outside RTH nothing new pages
    assert p.observe(RTH, 9999, threshold_s=0, rth=True) is None            # 0 = off


async def test_page_tick_escalates_and_journals_stall_then_recovery(tmp_path, monkeypatch):
    from zargar import desk_alert
    from zargar.techniques.tip import intake_liveness as il
    sent = []

    async def fake_escalate(eng, title, text, **kw):
        sent.append((title, kw["level"], kw["tag"]))
        return {"toast": True, "push": True, "telegram": True}
    monkeypatch.setattr(desk_alert, "escalate", fake_escalate)
    eng = _fake_eng(**{"techniques.tip.intake_page_idle_minutes": 3})
    pager = il.StallPager()
    f = tmp_path / il.STATUS_FILE

    def write(st):
        f.write_text(json.dumps(st), encoding="utf-8")
    write(_status(RTH, frame_age=30))
    assert await il.page_tick(eng, pager, now=RTH, base=tmp_path) is None
    write(_status(RTH, frame_age=200))                                      # 3.3 min without a frame
    assert await il.page_tick(eng, pager, now=RTH, base=tmp_path) == "page"
    assert await il.page_tick(eng, pager, now=RTH + dt.timedelta(minutes=5), base=tmp_path) is None
    later = RTH + dt.timedelta(minutes=40)
    write(_status(later, frame_age=2))
    assert await il.page_tick(eng, pager, now=later, base=tmp_path) == "recover"
    assert sent == [("Tips intake DOWN", "critical", "tip-intake-stall"),
                    ("Tips intake recovered", "info", "tip-intake-stall")]
    phases = [p["phase"] for k, p, _ in eng.journal.rows if k == ev.TIP_INTAKE_PAGED]
    assert phases == ["stalled", "recovered"]


async def test_escalate_reaches_toast_push_and_telegram_once():
    from zargar import bus as topics
    from zargar.desk_alert import escalate
    published, pushes, tgs = [], [], []

    async def push_send(title, body, **kw):
        pushes.append((title, kw))
        return 1

    async def tg_send(text, *a):
        tgs.append(text)
    eng = NS(bus=NS(publish=lambda topic, msg: published.append((topic, msg))),
             push=NS(send=push_send), telegram=NS(send=tg_send))
    out = await escalate(eng, "Tips intake DOWN", "no frames <5 min>", tag="tip-intake-stall")
    assert out == {"toast": True, "push": True, "telegram": True}
    [(topic, msg)] = published
    assert topic == topics.TECHNIQUE and msg["kind"] == "alert" and msg["pushed"] is True
    assert pushes[0][1]["tag"] == "tip-intake-stall" and pushes[0][1]["level"] == "critical"
    assert "&lt;5 min&gt;" in tgs[0]                                        # Telegram HTML-escaped
