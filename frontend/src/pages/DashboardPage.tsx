import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtTime } from "../lib/format";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { makeRate, useLiveEquity } from "../lib/liveEquity";
import { useAsync } from "../lib/useAsync";
import { netWorthByCurrency, useStore } from "../store";
import { useViewport } from "../lib/viewport";
import { isRealBook, useWorkspace, useWorkspaceFilter } from "../lib/workspace";
import { ResearchBadge } from "../components/ResearchBadge";
import { parseOcc } from "../lib/occ";
import { rgbaVar } from "../lib/highchartsTheme";
import { SymIcon } from "../components/SymIcon";
import type { BrokerageProvider, Portfolio } from "../types";
import { BrokerIcon } from "../components/BrokerIcon";
import { IconRefresh } from "../components/icons";
import { cashText, providerTotal } from "../lib/brokerage";
import { AsyncSection, EmptyState, StatusPill } from "../components/ui";
import { WatchRow } from "../components/WatchRow";

const lsGet = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

/* ── the morning desk card (POST-SOAK Phase 1): one glance = what needs me ── */
function MorningCard() {
  const setPage = useStore((s) => s.setPage);
  const [rep, setRep] = useState<import("../types").MorningReport | null>(null);
  useEffect(() => { api.deskMorning().then(setRep).catch(() => undefined); }, []);
  if (!rep) return null;
  const ny = rep.needsYou;
  const needs = ny.pendingProposals.length + ny.attention.length + ny.followUps.length;
  const armed = Object.values(rep.today.armedByTechnique)
    .reduce((a, c) => a + (c.armed ?? 0), 0);
  const goApprovals = () => { setPage("inbox"); useStore.getState().setPageTab("approvals"); };
  return (
    <div className="panel mb morning-card">
      <div className="panel-head">This morning
        <span className="sub">{rep.date} · {rep.overnight.tips.length} tip{rep.overnight.tips.length === 1 ? "" : "s"} overnight
          · {armed} plan{armed === 1 ? "" : "s"} armed
          {rep.today.rolled.length ? ` · ${rep.today.rolled.length} rolled` : ""}</span>
        {rep.soak && (
          <span className={`status-pill ${rep.soak.ready ? "ok" : "dim"}`} style={{ marginLeft: "auto" }}
            title="the nightly practice-soak scorecard — READY means the real-money bar is met">
            soak {rep.soak.ready ? "ready" : "in progress"}
          </span>
        )}
      </div>
      <div className="panel-body">
        {needs === 0 ? (
          <div className="muted" style={{ fontSize: 13 }}>Nothing needs you — the desk handled the night.</div>
        ) : (
          <div className="morning-rows">
            {ny.pendingProposals.map((p) => (
              <button key={p.id} className="morning-row" onClick={goApprovals}>
                <span className={`status-pill ${p.failClosed ? "bad" : "wait"}`}>
                  {p.failClosed ? "fail-closed" : "pending"}</span>
                <b>{p.symbol}</b>
                <span className="muted">{p.source ?? ""} — {p.why}</span>
              </button>
            ))}
            {ny.followUps.map((f, i) => (
              <button key={`f${i}`} className="morning-row" onClick={() => setPage("armed")}>
                <span className="status-pill wait">follow-up</span>
                <b>{f.symbol}</b>
                <span className="muted">{f.note}</span>
              </button>
            ))}
            {ny.attention.map((a) => (
              <button key={a.runId} className="morning-row" onClick={() => setPage("armed")}>
                <span className="status-pill bad">attention</span>
                <b>{a.symbol}</b>
                <span className="muted">{a.reasons.join("; ")}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ProviderCard({ provider }: { provider: BrokerageProvider }) {
  const openPortfolios = useStore((s) => s.openPortfolios);
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  const open = () => openPortfolios(provider.connectionId || provider.broker);
  const total = useMemo(
    () => providerTotal(provider.accounts, usdCad), [provider.accounts, usdCad]);

  // the pill earns its place only when something needs attention
  const warnPill = provider.disabled
    ? { cls: "bad", text: "disconnected" }
    : provider.type !== "trade" ? { cls: "dim", text: "read-only" } : null;

  return (
    <div className="panel provider-card" onClick={open}
      role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") open(); }}>
      <div className="panel-head">
        <BrokerIcon name={provider.broker} logoUrl={provider.logoUrl} />
        {provider.broker}
        {warnPill && <span className={`status-pill ${warnPill.cls}`}>{warnPill.text}</span>}
        <span className="prov-total">{total}</span>
      </div>
      <div className="panel-body">
        {provider.accounts.map((a) => {
          const invested = a.equity - a.cash;
          return (
            <div key={a.id} className="acct-block">
              <div className="acct-row">
                <span className="name" title={a.number ? `#${a.number}` : undefined}>{a.name}</span>
                <span className="ccy-chip">{a.currency}</span>
                {a.mismatch && (
                  <span className="status-pill wait"
                    title={`Computed ${fmtCcy(a.mismatch.computedEquity, a.currency)} vs broker ${fmtCcy(a.mismatch.brokerTotal, a.currency)} (${a.mismatch.pct > 0 ? "+" : ""}${a.mismatch.pct}%)`}>
                    Δ
                  </span>
                )}
                <span className="bal">{fmtCcy(a.equity, a.currency)}</span>
              </div>
              {a.mismatch && (
                <div className="acct-detail mismatch-note">
                  Δ {a.mismatch.pct > 0 ? "+" : ""}{a.mismatch.pct}% vs the broker's overnight total {fmtCcy(a.mismatch.brokerTotal, a.currency)}
                </div>
              )}
              {a.equity > 0.005 && (
                <div className="acct-detail">
                  invested {fmtCcy(invested, a.currency)} · cash {cashText(a)}
                </div>
              )}
            </div>
          );
        })}
        {provider.accounts.length === 0 && (
          <div className="metric-sub">no accounts synced yet</div>
        )}
      </div>
    </div>
  );
}

function PracticeCard() {
  const portfolios = useStore((s) => s.portfolios);
  const setPage = useStore((s) => s.setPage);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const sims = useMemo(
    () => portfolios.filter((p) => p.kind === "sim"),
    [portfolios]);
  if (sims.length === 0 || mode === "live") return null; // live board = real money only
  return (
    <div className="panel provider-card provider-card--practice"
      onClick={() => setPage("portfolios")}
      role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setPage("portfolios"); }}>
      <div className="panel-head">
        Practice <span className="status-pill dim">simulated — not real money</span>
      </div>
      <div className="panel-body">
        {sims.map((p) => (
          <div key={p.id} className="acct-row">
            <span className="name">{p.name}</span>
            <span className="ccy-chip">{p.baseCurrency ?? "USD"}</span>
            <span className="bal">{fmtCcy(p.equity ?? p.cash, p.baseCurrency ?? "USD")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Equity over time. Two fixes the old panel needed (user 2026-09-04):
    it only ever fetched the last ~2000 samples (≈16 h at one every 30 s), so
    the chart opened on "6 PM yesterday" with a dead flat overnight leg — and
    it drew the closed market at full width. Now the window is a real choice,
    and the axis is ORDINAL over extended-session samples only: 8 PM joins
    4 AM with no desert in between, while pre- and post-market moves (which
    the feed does carry) stay visible. */
const CURVE_RANGES = [
  { key: "1d", label: "1D", hours: 24, points: 320 },
  { key: "3d", label: "3D", hours: 72, points: 420 },
  { key: "1w", label: "1W", hours: 24 * 7, points: 520 },
  { key: "1m", label: "1M", hours: 24 * 30, points: 620 },
  { key: "all", label: "All", hours: 0, points: 720 },
] as const;
const ET_HM = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short" });
/** Keep only samples inside the extended session (04:00–20:00 ET, Mon–Fri). */
function inSession(ms: number): boolean {
  const parts = ET_HM.formatToParts(ms);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const wd = get("weekday");
  if (wd === "Sat" || wd === "Sun") return false;
  const mins = Number(get("hour")) * 60 + Number(get("minute"));
  return mins >= 240 && mins < 1200;
}

/** Equity samples for a window, session-filtered and flat-collapsed — the
    shape both the hero sparkline and the full curve draw from. */
function useEquityWindow(pids: string[], hours: number, points: number,
                         weights?: Record<string, number>) {
  const key = pids.join(",");
  // per-book multipliers: LIVE sums a CAD book and a USD book into one
  // display currency at today's rate (history at today's rate is a known
  // simplification; the footer says so). Practice books are all 1.
  const wkey = weights ? pids.map((p) => (weights[p] ?? 1).toFixed(4)).join(",") : "";
  // `since` must NOT be recomputed every render: as a memo dependency it made
  // the whole pipeline re-run continuously while the DATA sat still. It steps
  // once a minute, which is finer than the 30 s sample rate anyway.
  const [minute, setMinute] = useState(() => Math.floor(Date.now() / 60_000));
  useEffect(() => {
    const t = setInterval(() => setMinute(Math.floor(Date.now() / 60_000)), 30_000);
    return () => clearInterval(t);
  }, []);
  const since = hours ? minute * 60_000 - hours * 3600_000 : 0;

  const series = useAsync<[number, number][]>(async () => {
    if (!pids.length) return [];
    // samples land every ~30 s; `since`/`points` are honoured by newer servers,
    // an older one drops them — so the window and thinning are applied again here
    const limit = hours ? Math.ceil(hours * 140) : 200000;
    const q = `limit=${limit}&points=${points}` + (since ? `&since=${Math.round(since)}` : "");
    const all = await Promise.all(
      pids.map((pid) => api.get<[number, number][]>(`/api/portfolios/${pid}/equity?${q}`)));
    if (all.length === 1) {
      const w = weights?.[pids[0]] ?? 1;
      return w === 1 ? all[0] : all[0].map((p) => [p[0], Math.round(p[1] * w * 100) / 100] as [number, number]);
    }
    // Since 2026-09-07 each technique owns its own Practice book, so "equity" is
    // a SUM. The books sample independently, so walk the union of timestamps and
    // carry each book's last known value (seeded with its first sample, or a book
    // would read as 0 before its first point and the total would leap).
    const cursor = all.map(() => 0);
    const last = all.map((one) => one[0]?.[1] ?? 0);
    const stamps = [...new Set(all.flat().map((p) => p[0]))].sort((a, b) => a - b);
    return stamps.map((ts) => {
      let sum = 0;
      all.forEach((one, i) => {
        while (cursor[i] < one.length && one[cursor[i]][0] <= ts) { last[i] = one[cursor[i]][1]; cursor[i]++; }
        sum += last[i] * (weights?.[pids[i]] ?? 1);
      });
      return [ts, Math.round(sum * 100) / 100] as [number, number];
    });
  }, [key, wkey, hours, points, Math.floor(minute / REFETCH_MINUTES)]);

  // The server pushes an equity point per book every 30 s. Following that tape
  // is what makes the board live: the fetch above is history, these are the
  // samples that have landed since, summed the same way.
  const ticks = useStore((st) => st.equityTicks);
  const live = useMemo(() => {
    const stamps = [...new Set(pids.flatMap((p) => (ticks[p] ?? []).map((t) => t[0])))]
      .sort((a, b) => a - b);
    if (!stamps.length) return [] as [number, number][];
    const cursor = pids.map(() => 0);
    const last = pids.map((p) => ticks[p]?.[0]?.[1] ?? 0);
    return stamps.map((ts) => {
      let sum = 0;
      pids.forEach((p, i) => {
        const tape = ticks[p] ?? [];
        while (cursor[i] < tape.length && tape[cursor[i]][0] <= ts) { last[i] = tape[cursor[i]][1]; cursor[i]++; }
        sum += last[i] * (weights?.[pids[i]] ?? 1);
      });
      return [ts, Math.round(sum * 100) / 100] as [number, number];
    });
  }, [ticks, key, wkey]);

  const pts = useMemo(() => {
    const fetched = series.data ?? [];
    // splice: history up to its last sample, then everything the tape has since
    const edge = fetched.length ? fetched[fetched.length - 1][0] : 0;
    const tail = live.filter((p) => p[0] > edge);
    // one book's tape alone is not the total — only extend when every book has
    // reported past the seam, or the line would step down to a partial sum
    const complete = pids.every((p) => (ticks[p] ?? []).some((t) => t[0] > edge));
    let raw = complete && tail.length ? [...fetched, ...tail] : fetched;
    if (since) raw = raw.filter((p) => p[0] >= since);
    const open = raw.filter((p) => inSession(p[0]));
    let out = open.length >= 2 ? open : raw;
    // Collapse dead stretches. Pre/post-market samples are kept (they DO move
    // when the tape prints) but a book that sat at the same cent for four hours
    // gets one step, not four hours of width — the axis is ordinal, so dropping
    // the interior of a flat run is what actually removes the desert.
    out = out.filter((p, i) => {
      if (i === 0 || i === out.length - 1) return true;
      return !(p[1] === out[i - 1][1] && p[1] === out[i + 1][1]);
    });
    // Thin WITHOUT losing the range: every Nth sample drops the highs and lows,
    // so the same day showed a different high on each load — and the readout
    // under the chart printed whichever samples survived (2026-09-14).
    if (out.length > points) {
      const buckets = Math.max(1, Math.floor(points / 2));
      const step = out.length / buckets;
      const keep = new Set<number>([0, out.length - 1]);   // always keep the live point
      for (let b = 0; b < buckets; b++) {
        const lo = Math.floor(b * step), hi = Math.min(out.length, Math.floor((b + 1) * step));
        let minI = -1, maxI = -1;
        for (let i = lo; i < hi; i++) {
          if (minI < 0 || out[i][1] < out[minI][1]) minI = i;
          if (maxI < 0 || out[i][1] > out[maxI][1]) maxI = i;
        }
        if (minI >= 0) { keep.add(minI); keep.add(maxI); }
      }
      out = out.filter((_, i) => keep.has(i));
    }
    return out;
  }, [series.data, live, ticks, pids, key, since, points]);
  return { series, pts };
}
/** How often the fetched history is re-pulled. The live tape covers the gap in
    between, so this only needs to be often enough to heal a missed push. */
const REFETCH_MINUTES = 5;

/** Today's move across a set of books, from the server's own day anchor.

    This used to be derived from the chart's points, which are session-filtered,
    flat-collapsed and thinned — so the baseline was whichever sample survived
    thinning, and it changed on every reload. The headline beside it updated
    live over the websocket while the move stayed frozen at page-load, so a
    board that opened during a dip read RED all morning on a green day and went
    green on a refresh (user 2026-09-14). Now both read the same two numbers.

    `dayStart` is the previous session's close, which is how a day change is
    defined everywhere else in this app (CLAUDE.md) and by every broker. */
function dayMove(books: Portfolio[], liveEquity?: Record<string, number>,
                 toCcy?: string, rate?: (from: string, to: string) => number | null) {
  // `dayStart` is the anchor; `todayPct` carries the same one and has shipped
  // for longer, so a board loaded against an engine that has not restarted yet
  // still colours correctly (both arrive on the same 30 s push).
  const anchorOf = (p: Portfolio): number | null => {
    const eq = p.equity ?? p.cash;
    if (p.dayStart != null) return p.dayStart;
    if (p.todayPct != null && eq != null) return eq / (1 + p.todayPct / 100);
    // an empty account has nothing to price: it is priced, at zero
    if (eq === 0) return 0;
    return null;
  };
  const now = (p: Portfolio) => liveEquity?.[p.id] ?? p.equity ?? p.cash;
  // LIVE mixes a CAD book and a USD book — each is converted into the display
  // currency at today's rate BEFORE summing (a Webull book holding SPCX in
  // USD summed raw into CAD read as a −24% day, 2026-09-15)
  const fx = (p: Portfolio) => (toCcy && rate ? rate(p.baseCurrency || "USD", toCcy) : 1);
  const priced = books.filter((p) => anchorOf(p) != null && now(p) != null && fx(p) != null);
  const unpriced = books.filter((p) => !priced.includes(p)).map((p) => p.name);
  if (!priced.length) return null;
  const from = priced.reduce((t, p) => t + (anchorOf(p) as number) * (fx(p) as number), 0);
  const to = priced.reduce((t, p) => t + now(p) * (fx(p) as number), 0);
  if (!from) return null;
  return {
    abs: to - from, pct: ((to - from) / from) * 100, from, to,
    partial: unpriced.length > 0, unpriced,
  };
}
const ET_DAY_KEY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

/** The currency to show a set of books in: the one holding the most of the money. */
function dominantCurrency(books: Portfolio[], live: Record<string, number>): string {
  const by: Record<string, number> = {};
  for (const b of books) {
    const c = (b.baseCurrency || "USD").toUpperCase();
    by[c] = (by[c] ?? 0) + Math.abs(live[b.id] ?? b.equity ?? b.cash);
  }
  return Object.entries(by).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "USD";
}

/** Axis-sized money: "8.85k" beats "US$8,850.00" on a 40px gutter. */
function fmtCompact(v: number, ccy: string): string {
  const sym = ccy === "CAD" ? "C$" : ccy === "USD" ? "$" : "";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${sym}${(v / 1_000_000).toFixed(2)}M`;
  if (a >= 10_000) return `${sym}${(v / 1000).toFixed(1)}k`;
  if (a >= 1_000) return `${sym}${(v / 1000).toFixed(2)}k`;
  return `${sym}${v.toFixed(0)}`;
}

/** Put the current value ON the line. Everything else on the chart is history;
    the one number you always want is where it is right now. */
function withLastLabel(pts: [number, number][], col: string, ccy: string): any[] {
  if (pts.length < 2) return pts;
  const head = pts.slice(0, -1);
  const [x, y] = pts[pts.length - 1];
  return [...head, {
    x, y, marker: { enabled: true, radius: 3.5, fillColor: col },
    dataLabels: {
      enabled: true, align: "right", verticalAlign: "middle", x: -6, y: -10,
      style: { fontSize: "11px", fontWeight: "600", color: col, textOutline: "2px var(--surface-1)" },
      formatter(this: any) { return fmtCompact(this.y, ccy); },
    },
  }];
}

/** A bare sparkline — no axes, no grid: the shape of the day in 40px. */
function Spark({ pts, up }: { pts: [number, number][]; up: boolean }) {
  const d = useMemo(() => {
    const ys = pts.map((p) => p[1]);
    if (ys.length < 2) return null;
    const w = 128, h = 38, lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const step = w / (ys.length - 1);
    return ys.map((v, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)} ${(h - 2 - ((v - lo) / span) * (h - 5)).toFixed(1)}`).join(" ");
  }, [pts]);
  if (!d) return null;
  return (
    <svg className="dash-hero-spark" viewBox="0 0 128 38" preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
        stroke={up ? "var(--up)" : "var(--down)"} />
    </svg>
  );
}

function EquityCurvePanel() {
  const portfolios = useStore((s) => s.portfolios);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const [range, setRange] = useState<string>(() => lsGet("zargar_dash_curve", "1d"));
  const spec = CURVE_RANGES.find((r) => r.key === range) ?? CURVE_RANGES[0];
  // live mode charts your biggest real account; practice charts the sandbox
  // Every book the workspace's money lives in — four Practice books since the
  // per-technique split (2026-09-07), the real accounts in LIVE. Archived books
  // never arrive in the snapshot, so nothing extra to filter here.
  const books = useMemo(
    () => portfolios.filter((p) => (mode === "live"
      ? p.kind === "live" || p.kind === "paper"
      : p.kind === "sim") && !p.archived)
      .sort((a, b) => a.name.localeCompare(b.name)),
    [portfolios, mode]);
  const bookId = useStore((st) => st.dashBook);
  const setBookId = useStore((st) => st.setDashBook);
  const usdCad = useStore((st) => st.quotes["USDCAD=X"]?.last);
  const rate = useMemo(() => makeRate(usdCad), [usdCad]);
  const target = books.find((p) => p.id === bookId);
  const pids = useMemo(
    () => (target ? [target.id] : books.map((p) => p.id)), [target, books]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);

  const bookLive = useLiveEquity(pids);
  const ccy = target?.baseCurrency ?? dominantCurrency(books, bookLive);
  // LIVE: every book's series is converted into the display currency at
  // today's rate before the sum; practice books are all one currency
  const weights = useMemo(() => {
    const out: Record<string, number> = {};
    for (const b of (target ? [target] : books)) out[b.id] = rate(b.baseCurrency || "USD", ccy) ?? 1;
    return out;
  }, [books, target, ccy, rate]);
  const converted = Object.values(weights).some((w) => w !== 1);
  const { series, pts } = useEquityWindow(pids, spec.hours, spec.points, weights);
  const first = pts.length ? pts[0][1] : 0;
  const last = pts.length ? pts[pts.length - 1][1] : 0;
  const delta = last - first;
  const pct = first ? (delta / first) * 100 : 0;
  // The numbers you would otherwise hover for. On 1D the baseline is the real
  // day anchor (the previous close), so the panel and the headline agree; on a
  // longer range it is the first sample in the window.
  const stats = useMemo(() => {
    if (pts.length < 2) return null;
    const ys = pts.map((p) => p[1]);
    const hi = Math.max(...ys), lo = Math.min(...ys);
    // On 1D both ends come from the books themselves, so this panel and the
    // headline above it can never print two different numbers for the same day.
    const anchor = spec.key === "1d" ? dayMove(target ? [target] : books, bookLive, ccy, rate) : null;
    const open = anchor?.from ?? first;
    const now = anchor?.to ?? last;
    return { hi: Math.max(hi, now), lo: Math.min(lo, now), open, last: now,
             abs: now - open, pct: open ? ((now - open) / open) * 100 : 0 };
  }, [pts, spec.key, target, books, bookLive, ccy, rate, first, last]);

  const openAt = stats?.open ?? 0;

  useEffect(() => {
    if (!containerRef.current || pts.length === 0) return;
    const base = baseChartOptions();
    const up = (stats?.abs ?? delta) >= 0;
    const col = up ? cssVar("--up") : cssVar("--down");
    chartRef.current?.destroy();
    chartRef.current = Highcharts.stockChart(containerRef.current, {
      ...base,
      chart: { ...base.chart, height: 250 },
      navigator: { enabled: false },
      time: { timezone: "America/New_York" },
      // ordinal: the closed market takes no width at all
      xAxis: {
        ...(base.xAxis as any), ordinal: true,
        // a labelled crosshair means the time is readable at a glance, not
        // only inside a tooltip that has to be summoned
        crosshair: { width: 1, color: rgbaVar("--text-3", 0.45), dashStyle: "Dot",
          label: { enabled: true, format: "{value:%H:%M}", padding: 3,
            backgroundColor: cssVar("--surface-3"), borderRadius: 3,
            style: { color: cssVar("--text-2"), fontSize: "10px" } } },
        tickPixelInterval: 90,
        labels: { ...((base.xAxis as any)?.labels ?? {}), style: { fontSize: "10px", color: cssVar("--text-3") } },
      },
      yAxis: {
        ...(base.yAxis as any), opposite: true, startOnTick: false, endOnTick: false,
        // the panel used to show two gridlines and two numbers for a whole
        // session; six ticks is a scale you can actually read a level off
        tickAmount: 6, showLastLabel: true, gridLineDashStyle: "Dot",
        crosshair: { width: 1, color: rgbaVar("--text-3", 0.45), dashStyle: "Dot",
          label: { enabled: true, padding: 3, backgroundColor: cssVar("--surface-3"),
            borderRadius: 3, style: { color: cssVar("--text-2"), fontSize: "10px" },
            formatter(this: any) { return fmtCompact(this.value, ccy); } } },
        labels: { ...((base.yAxis as any)?.labels ?? {}), align: "left", x: 4,
          style: { fontSize: "10px", color: cssVar("--text-3") },
          formatter(this: any) { return fmtCompact(this.value, ccy); } },
        // where the day (or the window) started — the line that tells you
        // whether you are up without reading a single number
        plotLines: openAt ? [{
          value: openAt, width: 1, dashStyle: "Dash", zIndex: 2,
          color: rgbaVar("--text-3", 0.55),
          label: { text: spec.key === "1d" ? "prev close" : "start", align: "left", x: 4, y: -4,
            style: { color: cssVar("--text-3"), fontSize: "9px" } },
        }] : undefined,
      },
      // The readout used to be a large box that popped the instant the cursor
      // entered the panel and then sat on top of the line (user 2026-09-04).
      // Now: it only wakes when you are actually near the line (stickyTracking
      // off + a tight snap), it is one small line, and it parks in the top
      // corner AWAY from the cursor so it never covers what you are reading.
      tooltip: {
        ...(base.tooltip as any),
        shared: false, followPointer: false, snap: 8, hideDelay: 120,
        borderWidth: 0, shadow: false, padding: 6, useHTML: true,
        backgroundColor: rgbaVar("--surface-2", 0.94),
        style: { color: cssVar("--text-2"), fontSize: "11px" },
        // parked, not chasing: a readout that hops between corners as the
        // cursor moves is its own kind of noise. Top-right, always — where the
        // value axis already is, and clear of the line's left-hand history.
        positioner(this: any, w: number) {
          const c = this.chart;
          return { x: c.plotLeft + c.plotWidth - w - 4, y: c.plotTop + 2 };
        },
        formatter(this: any) {
          const when = Highcharts.dateFormat("%b %e, %H:%M", this.x);
          return `<b style="color:${cssVar("--text-1")}">${fmtCcy(this.y, target?.baseCurrency ?? "USD")}</b>`
            + `<span style="opacity:.7"> · ${when} ET</span>`;
        },
      } as any,
      series: [{
        type: "area", color: col, lineWidth: 2,
        name: target?.name ?? (books.length > 1 ? `all ${books.length} books` : books[0]?.name ?? "equity"),
        fillColor: { linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
          stops: [[0, rgbaVar(up ? "--up" : "--down", 0.22)], [1, rgbaVar(up ? "--up" : "--down", 0)]] },
        // an area series anchors its axis at 0 by default, which squashed a
        // 8.8k equity line into a hairline at the top of the panel
        threshold: null, data: withLastLabel(pts, col, ccy), marker: { enabled: false },
        stickyTracking: false,   // hovering empty space is not a question
      } as any],
    });
    return () => { chartRef.current?.destroy(); chartRef.current = null; };
  }, [pts, theme, target?.name, delta, stats?.abs, openAt, ccy, spec.key]);

  return (
    <div className="panel dash-curve">
      <div className="panel-head dash-curve-head">
        <span>Equity</span>
        {books.length > 1 && (
          <select className="dash-curve-book" value={bookId} aria-label="Which book"
            onChange={(e) => setBookId(e.target.value)}>
            <option value="all">All {books.length} books</option>
            {/* funded books only, like the chips; two accounts can share a name
                (Wealthsimple CAD and USD) so the currency disambiguates */}
            {books.filter((b) => (bookLive[b.id] ?? b.equity ?? b.cash) !== 0 || b.id === bookId).map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}{books.some((o) => o.id !== b.id && o.name === b.name) ? ` (${b.baseCurrency || "USD"})` : ""}
              </option>))}
          </select>
        )}
        {stats && (
          <span className={`dash-curve-delta ${stats.abs >= 0 ? "pos" : "neg"}`}>
            {stats.abs >= 0 ? "+" : "−"}{fmtCcy(Math.abs(stats.abs), ccy)}
            <span className="dash-curve-pct">{stats.abs >= 0 ? "+" : "−"}{Math.abs(stats.pct).toFixed(2)}%</span>
            <span className="muted"> {spec.key === "1d" ? "today" : `over the last ${spec.label}`}</span>
          </span>
        )}
        <div className="seg sm dash-curve-range" role="group" aria-label="Equity range">
          {CURVE_RANGES.map((r) => (
            <button key={r.key} className={range === r.key ? "on" : ""}
              onClick={() => { setRange(r.key); lsSet("zargar_dash_curve", r.key); }}>{r.label}</button>
          ))}
        </div>
      </div>
      <AsyncSection
        state={series}
        empty={<EmptyState title="No equity history yet"
          hint="Points accumulate every 30 seconds while the engine runs." />}
      >
        {() => <div ref={containerRef} />}
      </AsyncSection>
      {stats && (
        <div className="dash-curve-stats">
          <span><i>{spec.key === "1d" ? "prev close" : "start"}</i>{fmtCcy(stats.open, ccy)}</span>
          <span><i>high</i>{fmtCcy(stats.hi, ccy)}</span>
          <span><i>low</i>{fmtCcy(stats.lo, ccy)}</span>
          <span className="dash-curve-now"><i>now</i>{fmtCcy(stats.last, ccy)}</span>
        </div>
      )}
      <div className="dash-curve-foot muted">market hours only — nights and weekends are skipped
        {converted && <span title="Each book is converted at the current USD/CAD rate — history is not re-rated day by day"> · in {ccy} at today's FX</span>}
        <span className="dash-curve-live" title="Equity is pushed every 30 seconds — this updates on its own">live</span>
      </div>
    </div>
  );
}

function RecentActivity() {
  const { isPhone } = useViewport();
  const allOrders = useStore((s) => s.recentOrders);
  const allExecutions = useStore((s) => s.executions);
  const portfolios = useStore((s) => s.portfolios);
  const wsOk = useWorkspaceFilter();
  const [showResearch, setShowResearch] = useState(false);
  const kindOf = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p.kind])), [portfolios]);
  // research books trade constantly (54 shadow fills in a day the real books did
  // nothing) — they would drown the desk's own activity, so they are opt-in
  const keep = useMemo(
    () => (pid: string) => wsOk(kindOf[pid]) && (showResearch || isRealBook(kindOf[pid])),
    [wsOk, kindOf, showResearch]);
  const recentOrders = useMemo(() => allOrders.filter((o) => keep(o.portfolioId)), [allOrders, keep]);
  const executions = useMemo(() => allExecutions.filter((e) => keep(e.portfolioId)), [allExecutions, keep]);
  const hiddenResearch = useMemo(
    () => (showResearch ? 0 : allOrders.filter((o) => wsOk(kindOf[o.portfolioId]) && !isRealBook(kindOf[o.portfolioId])).length),
    [allOrders, wsOk, kindOf, showResearch]);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const setPage = useStore((s) => s.setPage);
  const [tab, setTab] = useState<"orders" | "fills">("orders");
  const pname = useMemo(
    () => Object.fromEntries(portfolios.map((p) => [p.id, p.name])), [portfolios]);
  const preal = useMemo(
    () => Object.fromEntries(portfolios.map(
      (p) => [p.id, p.kind === "live" || p.kind === "paper"])), [portfolios]);
  const goTrade = (symbol: string) => { setActiveSymbol(symbol); setPage("trade"); };
  const portfolioCell = (pid: string) => (
    <td className="muted">
      {pname[pid] ?? "—"}{" "}
      {isRealBook(kindOf[pid])
        ? <span className={`status-pill ${preal[pid] ? "bad" : "dim"}`}>{preal[pid] ? "real" : "practice"}</span>
        : <ResearchBadge compact />}
    </td>
  );

  return (
    <div className="panel dash-orders">
      <div className="panel-head panel-head--tabs">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "orders"}
            className={tab === "orders" ? "active" : ""} onClick={() => setTab("orders")}>
            Recent orders
          </button>
          <button role="tab" aria-selected={tab === "fills"}
            className={tab === "fills" ? "active" : ""} onClick={() => setTab("fills")}>
            Fills
          </button>
        </div>
        {(hiddenResearch > 0 || showResearch) && (
          <button className="link-btn dash-research-toggle" aria-pressed={showResearch}
            title="Research (shadow) books track each tip source's record — not money."
            onClick={() => setShowResearch((v) => !v)}>
            {showResearch ? "hide research" : `+ research (${hiddenResearch})`}
          </button>
        )}
      </div>
      <div className="scroll-x">
        {isPhone ? (
          <div className="bl-cards">
            {tab === "orders" && recentOrders.length === 0 && <EmptyState title="No orders this session" hint="Orders appear here the moment they are placed." />}
            {tab === "fills" && executions.length === 0 && <EmptyState title="No fills this session" />}
            {tab === "orders" && recentOrders.slice(0, 8).map((o) => (
              <button type="button" key={o.id} className="bl-card" onClick={() => goTrade(o.symbol)}>
                <span className="bl-card-l">
                  <span className="bl-card-sym"><span className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</span> {fmtQty(o.qty)} {o.symbol}</span>
                  <span className="bl-card-sub">{o.orderType} · {pname[o.portfolioId] ?? "—"} · {fmtTime(o.createdAt)}</span>
                </span>
                <span className="bl-card-r"><StatusPill status={o.status} /></span>
              </button>
            ))}
            {tab === "fills" && executions.slice(0, 8).map((e) => (
              <button type="button" key={e.id} className="bl-card" onClick={() => goTrade(e.symbol)}>
                <span className="bl-card-l">
                  <span className="bl-card-sym"><span className={e.side === "BUY" ? "pos" : "neg"}>{e.side}</span> {fmtQty(e.qty)} {e.symbol}</span>
                  <span className="bl-card-sub">@ {fmtMoney(e.price)} · {pname[e.portfolioId] ?? "—"} · {fmtTime(e.ts)}</span>
                </span>
              </button>
            ))}
          </div>
        ) : tab === "orders" ? (
          recentOrders.length === 0
            ? <EmptyState title="No orders this session"
                hint="Orders appear here the moment they are placed." />
            : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Time</th><th>Symbol</th><th>Side</th><th className="num">Qty</th>
                    <th>Type</th><th>Status</th><th>Portfolio</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.slice(0, 8).map((o) => (
                    <tr key={o.id} onClick={() => goTrade(o.symbol)} style={{ cursor: "pointer" }}>
                      <td className="muted">{fmtTime(o.createdAt)}</td>
                      <td>{o.symbol}</td>
                      <td className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</td>
                      <td className="num">{fmtQty(o.qty)}</td>
                      <td className="muted">{o.orderType}</td>
                      <td><StatusPill status={o.status} /></td>
                      {portfolioCell(o.portfolioId)}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
        ) : executions.length === 0
          ? <EmptyState title="No fills this session" />
          : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Time</th><th>Symbol</th><th>Side</th>
                  <th className="num">Qty</th><th className="num">Price</th><th>Portfolio</th>
                </tr>
              </thead>
              <tbody>
                {executions.slice(0, 8).map((e) => (
                  <tr key={e.id} onClick={() => goTrade(e.symbol)} style={{ cursor: "pointer" }}>
                    <td className="muted">{fmtTime(e.ts)}</td>
                    <td>{e.symbol}</td>
                    <td className={e.side === "BUY" ? "pos" : "neg"}>{e.side}</td>
                    <td className="num">{fmtQty(e.qty)}</td>
                    <td className="num">{fmtMoney(e.price)}</td>
                    {portfolioCell(e.portfolioId)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  );
}

/** The number the page exists for, at the top of the page (user 2026-09-04:
    "the equity should be the top thing"). The per-account breakdown folds in
    underneath instead of repeating itself in a second card, and the
    connection chips (snaptrade / ibkr / alpaca quotes) only appear when
    something is actually wrong — plumbing that always reads "fine" is just
    width. */
function EquityHero() {
  const portfolios = useStore((s) => s.portfolios);
  const brokerages = useStore((s) => s.brokerages);
  const halt = useStore((s) => s.halt);
  const broker = useStore((s) => s.broker);
  const applyBrokerages = useStore((s) => s.applyBrokerages);
  const toast = useStore((s) => s.toast);
  const setPage = useStore((s) => s.setPage);
  const [refreshing, setRefreshing] = useState(false);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const live = mode === "live";
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  const rate = useMemo(() => makeRate(usdCad), [usdCad]);
  const dashBook = useStore((s) => s.dashBook);
  const setDashBook = useStore((s) => s.setDashBook);
  const totals = useMemo(() => netWorthByCurrency(portfolios, brokerages), [portfolios, brokerages]);
  const liveTotals = useMemo(
    () => totals.filter((t) => t.brokerage > 0).map((t) => ({ currency: t.currency, total: t.brokerage })),
    [totals]);
  const sims = useMemo(
    () => portfolios.filter((p) => p.kind === "sim" && !p.archived), [portfolios]);
  // marked against the same quotes the rest of the board draws, so the headline
  // moves with the tape instead of stepping once every 30 s (2026-09-14)
  const simIds = useMemo(() => sims.map((p) => p.id), [sims]);
  const simLive = useLiveEquity(simIds);
  const practiceTotal = sims.reduce((sum, p) => sum + (simLive[p.id] ?? p.equity ?? p.cash), 0);
  const practiceCcy = sims[0]?.baseCurrency ?? "USD";
  const blended = useMemo(() => {
    if (!usdCad || usdCad <= 0 || liveTotals.length < 2) return null;
    let cad = 0;
    for (const t of liveTotals) {
      if (t.currency === "CAD") cad += t.total;
      else if (t.currency === "USD") cad += t.total * usdCad;
      else return null;
    }
    return cad;
  }, [liveTotals, usdCad]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      applyBrokerages(await api.refreshBrokerages());
      toast("success", "Brokerage data refreshed");
    } catch (e: any) { toast("error", e.message); }
    finally { setRefreshing(false); }
  };

  // accounts, as compact rows under the headline — one place, not two cards
  const accounts: { id: string; name: string; ccy: string; value: number; sub?: string }[] = live
    ? (brokerages?.providers ?? []).flatMap((p) => (p.accounts ?? []).map((a) => ({
        id: a.portfolioId, name: a.name, ccy: a.currency, value: a.equity, sub: p.broker })))
    : sims.map((p) => ({ id: p.id, name: p.name, ccy: p.baseCurrency ?? "USD",
        value: simLive[p.id] ?? p.equity ?? p.cash }));
  // an account holding nothing is a chip that says nothing — fold them into one
  const funded = accounts.filter((a) => a.value !== 0);
  const empty = accounts.filter((a) => a.value === 0);

  // the shape of the day, in the headline — the board's one real visual
  // the headline totals every book, so its move and its shape must too — it
  // used to sparkline ONE arbitrary sim book under a four-book total
  const wsBooks = useMemo(
    () => (live
      ? portfolios.filter((p) => (p.kind === "live" || p.kind === "paper") && !p.archived)
      : sims),
    [live, portfolios, sims]);
  // the board's selected book (the curve's picker, or a chip below) — the
  // headline shows THAT book, not the sum, when one is chosen (2026-09-15)
  const selected = wsBooks.find((p) => p.id === dashBook);
  const heroBooks = useMemo(() => (selected ? [selected] : wsBooks), [selected, wsBooks]);
  const heroPids = useMemo(() => heroBooks.map((p) => p.id), [heroBooks]);
  const heroLive = useLiveEquity(heroPids);
  // one display currency for the headline: the chosen book's, else the one
  // holding most of the money (CAD for this desk's real accounts)
  const heroCcy = selected ? (selected.baseCurrency || "USD") : live ? dominantCurrency(wsBooks, heroLive) : practiceCcy;
  const heroWeights = useMemo(() => {
    const out: Record<string, number> = {};
    for (const b of heroBooks) out[b.id] = rate(b.baseCurrency || "USD", heroCcy) ?? 1;
    return out;
  }, [heroBooks, heroCcy, rate]);
  const { pts } = useEquityWindow(heroPids, 24, 60, heroWeights);
  const move = dayMove(heroBooks, heroLive, heroCcy, rate);
  const upMove = (move?.abs ?? 0) >= 0;
  const heroTotal = heroBooks.reduce(
    (t, b) => t + (heroLive[b.id] ?? b.equity ?? b.cash) * (heroWeights[b.id] ?? 1), 0);
  return (
    <div className="panel dash-hero">
      <div className="dash-hero-top">
        <div className="dash-hero-main">
          <div className="dash-hero-lbl">
            {selected ? selected.name : live ? "Real money · all accounts" : "Practice book"}
            {!live && <span className="dash-hero-tag">simulated</span>}
            {selected && <> · <button className="link-btn dash-hero-all" onClick={() => setDashBook("all")}>all books</button></>}
          </div>
          <div className="dash-hero-num">
            {selected
              ? fmtCcy(heroTotal, heroCcy)
              : live
                ? (liveTotals.length ? liveTotals.map((t) => fmtCcy(t.total, t.currency)).join("  ·  ") : "—")
                : fmtCcy(practiceTotal, practiceCcy)}
          </div>
          {move && (
            <div className={`dash-hero-move ${upMove ? "pos" : "neg"}`}>
              {upMove ? "▲" : "▼"} {fmtCcy(Math.abs(move.abs), heroCcy)}
              <span className="dash-hero-pct">{upMove ? "+" : "−"}{Math.abs(move.pct).toFixed(2)}%</span>
              <span className="muted"
                title={`Since the previous session's close, ${fmtCcy(move.from, heroCcy)}`
                  + (live && !selected ? ` — each account converted to ${heroCcy} at today's USD/CAD` : "")
                  + (move.partial ? `. Not yet priced: ${move.unpriced.join(", ")}` : "")}>
                today{move.partial ? " (so far as priced)" : ""}</span>
            </div>
          )}
          {live && blended !== null && (
            <div className="dash-hero-sub" title={`Blended at live USD/CAD ${usdCad?.toFixed(4)}`}>
              ≈ {fmtCcy(blended, "CAD")} combined at today's FX
            </div>
          )}
        </div>
        {pts.length > 1 && <Spark pts={pts} up={upMove} />}
        <div className="dash-hero-side">
          {halt.engaged && <span className="status-pill bad">HALTED — nothing can trade</span>}
          {broker && broker.feedConnected === false && (
            <span className="status-pill bad">price feed down</span>
          )}
          {live && broker && !broker.snaptradeConnected && (
            <span className="status-pill warn">brokerage link down</span>
          )}
          {brokerages?.enabled && live && (
            <button className="link-btn dash-hero-sync" onClick={refresh} disabled={refreshing}
              title="Refresh brokerage balances now">
              {refreshing ? <span className="spinner" /> : <IconRefresh />}
              {brokerages?.lastSyncAt ? `synced ${fmtTime(brokerages.lastSyncAt)}` : "refresh"}
            </button>
          )}
        </div>
      </div>
      {/* one account restates the headline verbatim — only a real split is worth the row */}
      {accounts.length > 1 && (
        <div className="dash-hero-accts">
          {funded.map((a) => (
            <button key={a.id} className={"dash-acct" + (a.id === dashBook ? " on" : "")}
              aria-pressed={a.id === dashBook}
              onClick={() => setDashBook(a.id === dashBook ? "all" : a.id)}
              title={a.id === dashBook ? "Showing this book — click for all books" : "Show this book on the board"}>
              <span className="dash-acct-name">{a.name}{a.sub ? <span className="muted"> · {a.sub}</span> : null}</span>
              <span className="dash-acct-val">{fmtCcy(a.value, a.ccy)}</span>
            </button>
          ))}
          {empty.length > 0 && (
            <button className="dash-acct dash-acct-empty" onClick={() => setPage("portfolios")}
              title={`Nothing held: ${empty.map((a) => a.name).join(", ")} — open Portfolios`}>
              <span className="dash-acct-name">+{empty.length} empty</span>
            </button>
          )}
        </div>
      )}
      {live && (!brokerages || brokerages.providers.length === 0) && (
        <div className="dash-hero-accts">
          <EmptyState title="No brokerages connected"
            hint="Add SnapTrade credentials to backend/.env, enable SnapTrade, restart."
            action={<button className="link-btn" onClick={() => setPage("settings")}>
              open Settings → Brokerages</button>} />
        </div>
      )}
    </div>
  );
}

export function DashboardPage() {
  const setPage = useStore((s) => s.setPage);
  return (
    <div>
      <h2 className="page-title">Dashboard</h2>
      {/* order (user 2026-09-04): the money, then what the desk is doing about
          it, then the detail. The morning digest moved to the bottom — it is a
          once-a-day read, not the headline. */}
      <EquityHero />
      <ArmedFleetWidget />
      <div className="dash-grid">
        <EquityCurvePanel />
        <HoldingsWidget />
        <RecentActivity />
      </div>
      <MorningCard />
      <div className="dash-foot muted">
        <button className="link-btn" onClick={() => setPage("portfolios")}>accounts</button>
        <button className="link-btn" onClick={() => setPage("ledger")}>ledger</button>
        <button className="link-btn" onClick={() => setPage("watchlists")}>watchlists</button>
        <button className="link-btn" onClick={() => setPage("settings")}>settings</button>
      </div>
    </div>
  );
}


/** The day's plans, in one line you can act on. "Armed fleet · 63 plans" told
    you nothing (user 2026-09-04) — this says what they are, what they are
    doing, and which ones are about to happen. */
function ArmedFleetWidget() {
  const armed = useStore((s) => s.techniqueArmed);
  const setPage = useStore((s) => s.setPage);
  const active = armed.filter((a) => a.status === "armed" || a.status === "paused");
  if (!active.length) return null;
  const inTrade = active.filter((a) => a.openPositions > 0).length;
  const fired = active.reduce((n, a) => n + (a.trades ?? []).length, 0);
  const pnl = active.reduce((n, a) => n + (a.realizedPnl ?? 0), 0);
  const distOf = (a: typeof active[number]) =>
    Math.min(...((a.triggers ?? []).map((t) => Math.abs(t.distancePct ?? 99)).concat(99)));
  const waiting = active.filter((a) => a.openPositions === 0 && !(a.trades ?? []).length);
  const closest = waiting.slice().sort((x, y) => distOf(x) - distOf(y)).slice(0, 5);
  const busy = active.filter((a) => a.openPositions > 0 || (a.trades ?? []).length).slice(0, 3);
  return (
    <div className="panel dash-armed clickable" role="button" tabIndex={0}
      onClick={() => setPage("armed")}
      onKeyDown={(e) => e.key === "Enter" && setPage("armed")}
      title="Open the Armed page">
      <div className="panel-head">Plans watching the market
        <span className="sub">
          {active.length} armed · {waiting.length} still waiting
          {inTrade ? ` · ${inTrade} in a trade` : ""}{fired ? ` · ${fired} fired today` : ""}
        </span>
        {Math.abs(pnl) >= 0.005 && (
          <span className={"tq-head-right " + (pnl > 0 ? "pos" : "neg")}>
            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}</span>
        )}
      </div>
      <div className="panel-body dash-armed-rows">
        {busy.map((a) => (
          <span key={a.runId} className="dash-armed-chip busy">
            <b>{a.symbol}</b>
            <span className="muted small">{a.openPositions > 0 ? "in a trade" : "fired"}</span>
          </span>
        ))}
        {closest.length > 0 && <span className="dash-armed-lbl">closest to firing</span>}
        {closest.map((a) => {
          const d = distOf(a);
          return (
            <span key={a.runId} className={`dash-armed-chip${d <= 0.5 ? " near" : ""}`}>
              <b>{a.symbol}</b>
              <span className="muted small">{d < 99 ? `${d.toFixed(2)}% away` : "watching"}</span>
            </span>
          );
        })}
        {waiting.length > closest.length && (
          <span className="muted small">+{waiting.length - closest.length} more</span>
        )}
      </div>
    </div>
  );
}

/** What you actually hold — in THIS workspace. It used to hard-filter to
    live/paper accounts, so Practice showed real-account holdings that the
    workspace says you cannot even trade (user 2026-09-04). Replaces the
    watchlist on the board; the watchlist has its own page. */
function HoldingsWidget() {
  const positionsMap = useStore((s) => s.positions);
  const portfolios = useStore((s) => s.portfolios);
  const setPage = useStore((s) => s.setPage);
  const openTrade = useStore((s) => s.openTrade);
  const wsOk = useWorkspaceFilter();
  const kindOf = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p.kind])), [portfolios]);
  const nameOf = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p.name])), [portfolios]);
  const [showResearch, setShowResearch] = useState(false);
  // Research books are grouped SEPARATELY, never summed into the headline: the
  // balance above this panel counts real books only, so a list that mixed the
  // two could never add up to it (2026-09-07).
  const { rows, research } = useMemo(() => {
    // Each technique owns its own book now (2026-09-07), so a holding is folded
    // per (symbol, book) and names its book — "which desk is holding this?" is
    // the question the split exists to answer.
    const fold = (real: boolean) => {
      const by = new Map<string, { symbol: string; book: string; qty: number; value: number; pnl: number }>();
      for (const p of Object.values(positionsMap)) {
        const kind = kindOf[p.portfolioId];
        if (!wsOk(kind) || isRealBook(kind) !== real || Math.abs(p.qty) < 1e-9) continue;
        const book = nameOf[p.portfolioId] ?? "—";
        const k = `${p.symbol}@${book}`;
        const cur = by.get(k) ?? { symbol: p.symbol, book, qty: 0, value: 0, pnl: 0 };
        cur.qty += p.qty;
        cur.value += p.marketValue ?? 0;
        cur.pnl += p.unrealizedPnl ?? 0;
        by.set(k, cur);
      }
      return [...by.values()].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
    };
    return { rows: fold(true), research: fold(false) };
  }, [positionsMap, kindOf, nameOf, wsOk]);
  const ws = useWorkspace();
  const [all, setAll] = useState(false);
  const multiBook = new Set(rows.map((r) => r.book)).size > 1;
  const CAP = 8;
  const shown = all ? rows : rows.slice(0, CAP);
  const value = rows.reduce((t, r) => t + r.value, 0);
  return (
    <div className="panel dash-holdings">
      <div className="panel-head">My holdings
        <span className="sub">{rows.length} in the {ws === "live" ? "real accounts" : "practice book"}
          {rows.length > 0 ? ` · ${fmtCcy(value, "USD")}` : ""}</span>
        {research.length > 0 && (
          <button className="link-btn dash-research-toggle" aria-pressed={showResearch}
            title="Research (shadow) books track each tip source's record. They are not money and never count toward the balance."
            onClick={() => setShowResearch((v) => !v)}>
            {showResearch ? `hide research (${research.length})` : `+ research (${research.length})`}
          </button>
        )}
        <button className="link-btn tq-head-right" onClick={() => setPage("portfolios")}>portfolios →</button>
      </div>
      <div className="panel-body dash-holdings-rows">
        {rows.length === 0 && (
          <div className="muted small" style={{ padding: "10px 2px" }}>
            Nothing held in the {ws === "live" ? "real accounts" : "practice book"} right now.
            {research.length > 0 && ` ${research.length} research position${research.length === 1 ? "" : "s"} are tracked separately.`}
          </div>
        )}
        {shown.map((h) => {
          const occ = parseOcc(h.symbol);
          const short = h.qty < 0;
          return (
            <button key={`${h.symbol}@${h.book}`} className="dash-hold" onClick={() => openTrade(occ?.underlying ?? h.symbol)}
              title={`Open ${occ?.underlying ?? h.symbol} on the Trade page`}>
              <SymIcon sym={occ?.underlying ?? h.symbol} size={20} />
              <span className="dash-hold-sym">{occ?.display ?? h.symbol}
                <span className="muted">{short ? "short " : ""}{Math.abs(h.qty)}{occ ? "×" : " sh"}</span>
                {multiBook && <span className="dash-hold-book">{h.book}</span>}</span>
              <span className="dash-hold-val">{fmtCcy(Math.abs(h.value), "USD")}</span>
              <span className={`dash-hold-pnl ${h.pnl >= 0 ? "pos" : "neg"}`}>
                {h.pnl >= 0 ? "+" : "−"}{fmtCcy(Math.abs(h.pnl), "USD")}</span>
            </button>
          );
        })}
        {rows.length > CAP && (
          <button className="link-btn dash-hold-more" onClick={() => setAll(!all)}>
            {all ? "show the biggest 8" : `show all ${rows.length}`}
          </button>
        )}
        {showResearch && research.length > 0 && (
          <>
            <div className="dash-research-head">
              <ResearchBadge /> <span className="muted small">
                per-source track record · not money, not in the balance above</span>
            </div>
            {research.slice(0, 12).map((h) => {
              const occ = parseOcc(h.symbol);
              return (
                <button key={`r-${h.symbol}@${h.book}`} className="dash-hold dash-hold--research"
                  onClick={() => openTrade(occ?.underlying ?? h.symbol)}
                  title={`${occ?.underlying ?? h.symbol} — research book position`}>
                  <SymIcon sym={occ?.underlying ?? h.symbol} size={20} />
                  <span className="dash-hold-sym">{occ?.display ?? h.symbol}
                    <span className="muted">{h.qty < 0 ? "short " : ""}{Math.abs(h.qty)}{occ ? "×" : " sh"}</span></span>
                  <span className="dash-hold-val">{fmtCcy(Math.abs(h.value), "USD")}</span>
                  <span className={`dash-hold-pnl ${h.pnl >= 0 ? "pos" : "neg"}`}>
                    {h.pnl >= 0 ? "+" : "−"}{fmtCcy(Math.abs(h.pnl), "USD")}</span>
                </button>
              );
            })}
            {research.length > 12 && (
              <div className="muted small" style={{ padding: "4px 12px 2px" }}>
                +{research.length - 12} more research positions
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
