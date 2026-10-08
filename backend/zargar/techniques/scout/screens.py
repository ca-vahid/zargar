"""S1 (opportunistic insider cluster) and S2 (earnings reaction) - pure, deterministic screens.

Both are preregistered (PLAN.md 2.1): thresholds come from settings, every run snapshots
them, nothing here reads a database or the network.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from ...marketstructure import market_calendar as mcal
from .classify import OPPORTUNISTIC, UNCLASSIFIED, Classification
from .form4 import ET

S1_KIND = "s1_insider"
S1_UNCLASSIFIED_KIND = "s1_unclassified"     # same cluster rule, counting unclassified insiders (tracked apart)
S2_KIND = "s2_earnings"


# --------------------------------------------------------------------------- sessions
def entry_session_after(ts: dt.datetime) -> str:
    """The first regular session whose OPEN (09:30 ET) is strictly after `ts`."""
    et = ts.astimezone(ET)
    d = et.date()
    if mcal.is_trading_day(d) and et.time() < dt.time(9, 30):
        return d.isoformat()
    return mcal.next_trading_day(d).isoformat()


def reaction_day0(ts: dt.datetime) -> str:
    """Earnings day 0 = the session that first trades on the news: the same session when
    the release is accepted before that day's close, else the next session."""
    et = ts.astimezone(ET)
    d = et.date()
    if mcal.is_trading_day(d):
        close_min = mcal.session_close_minutes(d)
        if et.hour * 60 + et.minute < close_min:
            return d.isoformat()
    return mcal.next_trading_day(d).isoformat()


def add_sessions(day: str, n: int) -> str:
    d = dt.date.fromisoformat(day)
    for _ in range(n):
        d = mcal.next_trading_day(d)
    return d.isoformat()


def knowable_at(row: Mapping) -> tuple[dt.datetime | None, bool]:
    """When a filing became public: acceptance time, else (dataset rows) the END of the
    filing date - conservative, never earlier than the truth. -> (ts, approximate?)."""
    ts = row.get("acceptance_ts")
    if isinstance(ts, dt.datetime):
        return ts.astimezone(ET), False
    fd = row.get("filed_date")
    if fd:
        d = dt.date.fromisoformat(str(fd)[:10])
        return dt.datetime.combine(d, dt.time(23, 59), ET), True
    return None, True


# --------------------------------------------------------------------------- S1
@dataclass(frozen=True)
class S1Params:
    window_days: int = 10
    min_insiders: int = 2
    min_value_usd: float = 100_000.0
    roles: tuple[str, ...] = ("officer", "director")


@dataclass
class S1Hit:
    kind: str
    issuer_cik: str
    ticker: str | None
    signal_ts: dt.datetime
    signal_time_approx: bool
    entry_date: str
    anchor_date: str
    insiders: list[dict]
    rows: list[dict]
    total_value: float
    window: tuple[str, str]
    classifications: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.issuer_cik}:{self.window[0]}"


def _role_ok(r: Mapping, roles: Sequence[str]) -> bool:
    return ("officer" in roles and bool(r.get("is_officer"))) or ("director" in roles and bool(r.get("is_director")))


def s1_purchases(rows: Iterable[Mapping], p: S1Params) -> list[dict]:
    """Open-market purchases (code P, original Form 4 - amendments excluded so a 4/A never
    double counts) by an officer or director, with a positive value."""
    out = []
    for r in rows:
        if r.get("trans_code") != "P" or str(r.get("form_type") or "4") != "4":
            continue
        if not _role_ok(r, p.roles) or not r.get("trans_date"):
            continue
        if (r.get("acq_disp") or "A") != "A":
            continue
        out.append(dict(r))
    return out


def screen_s1(purchases: Iterable[Mapping], classify, p: S1Params, *,
              include_unclassified: bool = False) -> list[S1Hit]:
    """Clusters of >= `min_insiders` distinct qualifying insiders buying within `window_days`
    calendar days (trans dates), total value >= `min_value_usd`.

    `classify(insider_cik, year) -> Classification` (start-of-year label, past data only).
    Opportunistic insiders qualify; with `include_unclassified` unclassified ones count too
    and the hit is the separately tracked `s1_unclassified` kind (only when at least one
    unclassified insider was needed to reach the count). Routine insiders never count.

    Point in time: filings are replayed in the order they became public; the cluster
    fires at the acceptance of the filing that completes it (signal time), entry the next
    regular session. After a hit, the issuer's next cluster must start after the hit's
    last purchase date (one candidate per cluster)."""
    by_issuer: dict[str, list[dict]] = defaultdict(list)
    for r in purchases:
        ts, approx = knowable_at(r)
        if ts is None:
            continue
        by_issuer[str(r["issuer_cik"])].append({**r, "_known": ts, "_approx": approx})
    hits: list[S1Hit] = []
    for issuer, lst in by_issuer.items():
        lst.sort(key=lambda r: (r["_known"], r["trans_date"], r.get("row_key") or ""))
        last_hit_through: str | None = None
        known: list[dict] = []
        i = 0
        while i < len(lst):
            t = lst[i]["_known"]
            batch = []
            while i < len(lst) and lst[i]["_known"] == t:         # everything public at the same instant
                batch.append(lst[i])
                i += 1
            known.extend(batch)
            for anchor in sorted({b["trans_date"] for b in batch}, reverse=True):
                lo = (dt.date.fromisoformat(anchor) - dt.timedelta(days=p.window_days - 1)).isoformat()
                if last_hit_through and lo <= last_hit_through:
                    lo = (dt.date.fromisoformat(last_hit_through) + dt.timedelta(days=1)).isoformat()
                members = [r for r in known if lo <= r["trans_date"] <= anchor]
                labels: dict[str, Classification] = {}
                opp: set[str] = set()
                unc: set[str] = set()
                for r in members:
                    cik = str(r["insider_cik"])
                    c = classify(cik, int(r["trans_date"][:4]))
                    labels[cik] = c
                    if c.label == OPPORTUNISTIC:
                        opp.add(cik)
                    elif c.label == UNCLASSIFIED:
                        unc.add(cik)
                qualifying = opp | (unc if include_unclassified else set())
                if len(qualifying) < p.min_insiders:
                    continue
                if include_unclassified and len(opp) >= p.min_insiders:
                    continue                                       # that is a plain S1 hit, not the tracked variant
                rows = [r for r in members if str(r["insider_cik"]) in qualifying]
                seen_rows: set[str] = set()
                total = 0.0
                for r in rows:
                    rk = r.get("row_key") or id(r)
                    if rk in seen_rows:
                        continue
                    seen_rows.add(rk)
                    total += float(r.get("value") or 0.0)
                if total < p.min_value_usd:
                    continue
                ticker = next((r.get("ticker") for r in sorted(rows, key=lambda r: r["_known"], reverse=True)
                               if r.get("ticker")), None)
                approx = any(r["_approx"] for r in batch)
                first = min(r["trans_date"] for r in rows)
                insiders = []
                for cik in sorted(qualifying):
                    mine = [r for r in rows if str(r["insider_cik"]) == cik]
                    insiders.append({
                        "insiderCik": cik, "name": mine[0].get("insider_name"),
                        "officer": bool(mine[0].get("is_officer")), "director": bool(mine[0].get("is_director")),
                        "title": mine[0].get("officer_title"), "class": labels[cik].label,
                        "classReason": labels[cik].reason,
                        "value": round(sum(float(r.get("value") or 0) for r in mine), 2),
                    })
                hits.append(S1Hit(
                    kind=S1_UNCLASSIFIED_KIND if include_unclassified else S1_KIND,
                    issuer_cik=issuer, ticker=ticker, signal_ts=t, signal_time_approx=approx,
                    entry_date=entry_session_after(t), anchor_date=anchor, insiders=insiders,
                    rows=[{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
                    total_value=round(total, 2), window=(first, anchor),
                    classifications={k: v.label for k, v in labels.items()},
                ))
                last_hit_through = anchor
                break
    hits.sort(key=lambda h: h.signal_ts)
    return hits


# --------------------------------------------------------------------------- S2
@dataclass(frozen=True)
class S2Params:
    top_pct: float = 10.0
    volume_mult: float = 2.0
    volume_avg_days: int = 20
    entry_offset_sessions: int = 2         # entry on day +2


@dataclass
class S2Reaction:
    ticker: str
    accession: str
    acceptance_ts: dt.datetime
    day0: str
    day1: str
    abnormal_return: float | None
    stock_return: float | None
    bench_return: float | None
    volume_ratio: float | None
    why: str | None = None                 # set when the reaction could not be measured


def _closes(bars: Sequence) -> dict[str, tuple[float, float]]:
    """daily bars -> {ET date: (close, volume)} - accepts Bar objects or dicts."""
    out = {}
    for b in bars:
        ts = b.ts if hasattr(b, "ts") else b["ts"]
        close = b.close if hasattr(b, "close") else b["close"]
        vol = b.volume if hasattr(b, "volume") else b.get("volume", 0)
        d = dt.datetime.fromtimestamp(ts / 1000, ET).date().isoformat()
        out[d] = (float(close), float(vol or 0))
    return out


def measure_reaction(event: Mapping, bars: Sequence, bench: Sequence, p: S2Params) -> S2Reaction:
    """Day 0..+1 abnormal return vs the benchmark (close[d+1]/close[d-1]) and day-0 volume
    over its `volume_avg_days`-session average ending day -1."""
    ts = event["acceptance_ts"]
    d0 = reaction_day0(ts)
    d1 = add_sessions(d0, 1)
    dm1 = mcal.previous_trading_day(d0).isoformat()
    base = dict(ticker=event["ticker"], accession=event["accession"], acceptance_ts=ts, day0=d0, day1=d1)
    s, b = _closes(bars), _closes(bench)
    if dm1 not in s or d1 not in s or d0 not in s:
        return S2Reaction(**base, abnormal_return=None, stock_return=None, bench_return=None, volume_ratio=None,
                          why=f"missing daily bars ({dm1}..{d1})")
    if dm1 not in b or d1 not in b:
        return S2Reaction(**base, abnormal_return=None, stock_return=None, bench_return=None, volume_ratio=None,
                          why="missing benchmark bars")
    r_s = s[d1][0] / s[dm1][0] - 1.0
    r_b = b[d1][0] / b[dm1][0] - 1.0
    prior = sorted(d for d in s if d < d0)[-p.volume_avg_days:]
    vol_ratio = None
    if len(prior) >= p.volume_avg_days:
        avg = sum(s[d][1] for d in prior) / len(prior)
        vol_ratio = round(s[d0][1] / avg, 3) if avg > 0 else None
    return S2Reaction(**base, abnormal_return=round(r_s - r_b, 6), stock_return=round(r_s, 6),
                      bench_return=round(r_b, 6), volume_ratio=vol_ratio,
                      why=None if vol_ratio is not None else f"fewer than {p.volume_avg_days} sessions of volume history")


@dataclass
class S2Hit:
    reaction: S2Reaction
    rank: int
    of: int
    cutoff_rank: int
    entry_date: str
    signal_ts: dt.datetime

    @property
    def key(self) -> str:
        return f"{S2_KIND}:{self.reaction.accession}"


def screen_s2(reactions: Iterable[S2Reaction], p: S2Params) -> tuple[list[S2Hit], list[dict]]:
    """Per day 0: rank the measured events by abnormal return; the top ceil(n * top_pct%)
    with a POSITIVE abnormal return and day-0 volume >= volume_mult x average are hits.
    -> (hits, per-event verdicts for the record)."""
    by_day: dict[str, list[S2Reaction]] = defaultdict(list)
    verdicts: list[dict] = []
    for r in reactions:
        if r.abnormal_return is None:
            verdicts.append({"accession": r.accession, "ticker": r.ticker, "day0": r.day0, "selected": False,
                             "why": r.why or "unmeasured"})
            continue
        by_day[r.day0].append(r)
    hits: list[S2Hit] = []
    for d0, lst in by_day.items():
        lst.sort(key=lambda r: (-r.abnormal_return, r.ticker))
        cutoff = max(1, math.ceil(len(lst) * p.top_pct / 100.0))
        for rank, r in enumerate(lst, start=1):
            reasons = []
            if rank > cutoff:
                reasons.append(f"rank {rank}/{len(lst)} outside top {cutoff}")
            if r.abnormal_return <= 0:
                reasons.append("abnormal return not positive")
            if r.volume_ratio is None:
                reasons.append(r.why or "no volume ratio")
            elif r.volume_ratio < p.volume_mult:
                reasons.append(f"volume {r.volume_ratio:.2f}x < {p.volume_mult}x")
            ok = not reasons
            verdicts.append({"accession": r.accession, "ticker": r.ticker, "day0": d0, "rank": rank, "of": len(lst),
                             "abnormalReturn": r.abnormal_return, "volumeRatio": r.volume_ratio,
                             "selected": ok, "why": "; ".join(reasons) or "top-decile reaction on volume"})
            if ok:
                close_d1 = dt.datetime.combine(dt.date.fromisoformat(r.day1), dt.time(16, 0), ET)
                hits.append(S2Hit(reaction=r, rank=rank, of=len(lst), cutoff_rank=cutoff,
                                  entry_date=add_sessions(d0, p.entry_offset_sessions), signal_ts=close_d1))
    hits.sort(key=lambda h: (h.reaction.day0, h.rank))
    return hits, verdicts
