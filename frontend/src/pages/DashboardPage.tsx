import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtTime } from "../lib/format";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { useAsync } from "../lib/useAsync";
import { netWorthByCurrency, useStore } from "../store";
import { useViewport } from "../lib/viewport";
import { useWorkspace, useWorkspaceFilter } from "../lib/workspace";
import { parseOcc } from "../lib/occ";
import { rgbaVar } from "../lib/highchartsTheme";
import { SymIcon } from "../components/SymIcon";
import type { BrokerageProvider } from "../types";
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

function EquityCurvePanel() {
  const portfolios = useStore((s) => s.portfolios);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const [range, setRange] = useState<string>(() => lsGet("zargar_dash_curve", "1d"));
  const spec = CURVE_RANGES.find((r) => r.key === range) ?? CURVE_RANGES[0];
  // live mode charts your biggest real account; practice charts the sandbox
  const target = useMemo(() => {
    if (mode === "live") {
      const real = portfolios.filter((p) => p.kind === "live" || p.kind === "paper");
      if (real.length > 0) {
        return real.reduce((best, p) =>
          (p.equity ?? p.cash) > (best.equity ?? best.cash) ? p : best);
      }
    }
    return portfolios.find((p) => p.id === defaultPid && p.kind === "sim")
      ?? portfolios.find((p) => p.kind === "sim") ?? portfolios[0];
  }, [mode, portfolios, defaultPid]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);

  const since = spec.hours ? Date.now() - spec.hours * 3600_000 : 0;
  const series = useAsync<[number, number][]>(() => {
    if (!target) return Promise.resolve([]);
    // samples land every ~30 s; ask for the window plus headroom. `since` and
    // `points` are honoured by newer servers — an older one drops them silently,
    // which is why the window and the thinning are applied again below.
    const limit = spec.hours ? Math.ceil(spec.hours * 140) : 200000;
    return api.get(`/api/portfolios/${target.id}/equity?limit=${limit}&points=${spec.points}`
      + (since ? `&since=${Math.round(since)}` : ""));
  }, [target?.id, spec.key]);

  const pts = useMemo(() => {
    let raw = series.data ?? [];
    if (since) raw = raw.filter((p) => p[0] >= since);
    const open = raw.filter((p) => inSession(p[0]));
    // a book that only ever moved outside the session still deserves a line
    let out = open.length >= 2 ? open : raw;
    // Collapse dead stretches. Pre/post-market samples are kept (they DO move
    // when the tape prints) but a book that sat at the same cent for four hours
    // gets one step, not four hours of width — the axis is ordinal, so dropping
    // the interior of a flat run is what actually removes the desert.
    out = out.filter((p, i) => {
      if (i === 0 || i === out.length - 1) return true;
      return !(p[1] === out[i - 1][1] && p[1] === out[i + 1][1]);
    });
    if (out.length > spec.points) {           // thin evenly, always keep the last
      const step = out.length / spec.points;
      const keep = new Set<number>([out.length - 1]);
      for (let i = 0; i < spec.points; i++) keep.add(Math.min(out.length - 1, Math.round(i * step)));
      out = out.filter((_, i) => keep.has(i));
    }
    return out;
  }, [series.data, since, spec.points]);
  const first = pts.length ? pts[0][1] : 0;
  const last = pts.length ? pts[pts.length - 1][1] : 0;
  const delta = last - first;

  useEffect(() => {
    if (!containerRef.current || pts.length === 0) return;
    const base = baseChartOptions();
    const up = delta >= 0;
    const col = up ? cssVar("--up") : cssVar("--down");
    chartRef.current?.destroy();
    chartRef.current = Highcharts.stockChart(containerRef.current, {
      ...base,
      chart: { ...base.chart, height: 250 },
      navigator: { enabled: false },
      time: { timezone: "America/New_York" },
      // ordinal: the closed market takes no width at all
      xAxis: { ...(base.xAxis as any), ordinal: true },
      yAxis: { ...(base.yAxis as any), opposite: true, startOnTick: false, endOnTick: false },
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
        type: "area", name: target?.name ?? "equity", color: col, lineWidth: 2,
        fillColor: { linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
          stops: [[0, rgbaVar(up ? "--up" : "--down", 0.22)], [1, rgbaVar(up ? "--up" : "--down", 0)]] },
        // an area series anchors its axis at 0 by default, which squashed a
        // 8.8k equity line into a hairline at the top of the panel
        threshold: null, data: pts, marker: { enabled: false },
        stickyTracking: false,   // hovering empty space is not a question
      } as any],
    });
    return () => { chartRef.current?.destroy(); chartRef.current = null; };
  }, [pts, theme, target?.name, delta]);

  return (
    <div className="panel dash-curve">
      <div className="panel-head dash-curve-head">
        <span>Equity</span>
        {pts.length > 1 && (
          <span className={`dash-curve-delta ${delta >= 0 ? "pos" : "neg"}`}>
            {delta >= 0 ? "+" : "−"}{fmtCcy(Math.abs(delta), target?.baseCurrency ?? "USD")}
            <span className="muted"> over {spec.label === "All" ? "all time" : `the last ${spec.label}`}</span>
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
      <div className="dash-curve-foot muted">market hours only — nights and weekends are skipped</div>
    </div>
  );
}

function RecentActivity() {
  const { isPhone } = useViewport();
  const allOrders = useStore((s) => s.recentOrders);
  const allExecutions = useStore((s) => s.executions);
  const portfolios = useStore((s) => s.portfolios);
  const wsOk = useWorkspaceFilter();
  const kindOf = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p.kind])), [portfolios]);
  const recentOrders = useMemo(() => allOrders.filter((o) => wsOk(kindOf[o.portfolioId])), [allOrders, wsOk, kindOf]);
  const executions = useMemo(() => allExecutions.filter((e) => wsOk(kindOf[e.portfolioId])), [allExecutions, wsOk, kindOf]);
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
      <span className={`status-pill ${preal[pid] ? "bad" : "dim"}`}>
        {preal[pid] ? "real" : "practice"}
      </span>
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
  const totals = useMemo(() => netWorthByCurrency(portfolios, brokerages), [portfolios, brokerages]);
  const liveTotals = useMemo(
    () => totals.filter((t) => t.brokerage > 0).map((t) => ({ currency: t.currency, total: t.brokerage })),
    [totals]);
  const sims = useMemo(() => portfolios.filter((p) => p.kind === "sim"), [portfolios]);
  const practiceTotal = sims.reduce((sum, p) => sum + (p.equity ?? p.cash), 0);
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
  const accounts: { name: string; ccy: string; value: number; sub?: string }[] = live
    ? (brokerages?.providers ?? []).flatMap((p) => (p.accounts ?? []).map((a) => ({
        name: a.name, ccy: a.currency, value: a.equity, sub: p.broker })))
    : sims.map((p) => ({ name: p.name, ccy: p.baseCurrency ?? "USD", value: p.equity ?? p.cash }));

  return (
    <div className="panel dash-hero">
      <div className="dash-hero-top">
        <div className="dash-hero-main">
          <div className="dash-hero-lbl">
            {live ? "Real money · all accounts" : "Practice book · simulated money"}
          </div>
          <div className="dash-hero-num">
            {live
              ? (liveTotals.length ? liveTotals.map((t) => fmtCcy(t.total, t.currency)).join("  ·  ") : "—")
              : fmtCcy(practiceTotal, practiceCcy)}
          </div>
          {live && blended !== null && (
            <div className="dash-hero-sub" title={`Blended at live USD/CAD ${usdCad?.toFixed(4)}`}>
              ≈ {fmtCcy(blended, "CAD")} combined at today's FX
            </div>
          )}
          {!live && (
            <div className="dash-hero-sub">
              nothing here is real money — your accounts live in the <b>LIVE</b> workspace
            </div>
          )}
        </div>
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
          {accounts.map((a, i) => (
            <button key={i} className="dash-acct" onClick={() => setPage("portfolios")}
              title="Open Portfolios">
              <span className="dash-acct-name">{a.name}{a.sub ? <span className="muted"> · {a.sub}</span> : null}</span>
              <span className="dash-acct-val">{fmtCcy(a.value, a.ccy)}</span>
            </button>
          ))}
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
  const rows = useMemo(() => {
    const by = new Map<string, { qty: number; value: number; pnl: number }>();
    for (const p of Object.values(positionsMap)) {
      if (!wsOk(kindOf[p.portfolioId]) || Math.abs(p.qty) < 1e-9) continue;
      const cur = by.get(p.symbol) ?? { qty: 0, value: 0, pnl: 0 };
      cur.qty += p.qty;
      cur.value += p.marketValue ?? 0;
      cur.pnl += p.unrealizedPnl ?? 0;
      by.set(p.symbol, cur);
    }
    return [...by.entries()].map(([symbol, v]) => ({ symbol, ...v }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  }, [positionsMap, kindOf, wsOk]);
  const ws = useWorkspace();
  const [all, setAll] = useState(false);
  const CAP = 8;
  const shown = all ? rows : rows.slice(0, CAP);
  const value = rows.reduce((t, r) => t + r.value, 0);
  return (
    <div className="panel dash-holdings">
      <div className="panel-head">My holdings
        <span className="sub">{rows.length} in the {ws === "live" ? "real accounts" : "practice book"}
          {rows.length > 0 ? ` · ${fmtCcy(value, "USD")}` : ""}</span>
        <button className="link-btn tq-head-right" onClick={() => setPage("portfolios")}>portfolios →</button>
      </div>
      <div className="panel-body dash-holdings-rows">
        {rows.length === 0 && (
          <div className="muted small" style={{ padding: "10px 2px" }}>
            Nothing held in the {ws === "live" ? "real accounts" : "practice book"} right now.
          </div>
        )}
        {shown.map((h) => {
          const occ = parseOcc(h.symbol);
          const short = h.qty < 0;
          return (
            <button key={h.symbol} className="dash-hold" onClick={() => openTrade(occ?.underlying ?? h.symbol)}
              title={`Open ${occ?.underlying ?? h.symbol} on the Trade page`}>
              <SymIcon sym={occ?.underlying ?? h.symbol} size={20} />
              <span className="dash-hold-sym">{occ?.display ?? h.symbol}
                <span className="muted">{short ? "short " : ""}{Math.abs(h.qty)}{occ ? "×" : " sh"}</span></span>
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
      </div>
    </div>
  );
}
