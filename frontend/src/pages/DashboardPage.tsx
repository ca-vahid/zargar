import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtTime } from "../lib/format";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { useAsync } from "../lib/useAsync";
import { netWorthByCurrency, useStore } from "../store";
import { useWorkspaceFilter } from "../lib/workspace";
import type { BrokerageProvider } from "../types";
import { BrokerIcon } from "../components/BrokerIcon";
import { IconRefresh } from "../components/icons";
import { cashText, providerTotal } from "../lib/brokerage";
import { AsyncSection, EmptyState, StatusPill } from "../components/ui";
import { WatchRow } from "../components/WatchRow";

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

function EquityCurvePanel() {
  const portfolios = useStore((s) => s.portfolios);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  // live mode charts your biggest real account; practice charts the sandbox
  const target = useMemo(() => {
    if (mode === "live") {
      const real = portfolios.filter((p) => p.kind === "live" || p.kind === "paper");
      if (real.length > 0) {
        return real.reduce((best, p) =>
          (p.equity ?? p.cash) > (best.equity ?? best.cash) ? p : best);
      }
    }
    return portfolios.find((p) => p.id === defaultPid) ?? portfolios[0];
  }, [mode, portfolios, defaultPid]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);

  const series = useAsync<[number, number][]>(
    () => (target ? api.get(`/api/portfolios/${target.id}/equity?limit=2000`) : Promise.resolve([])),
    [target?.id],
  );

  useEffect(() => {
    if (!containerRef.current || !series.data || series.data.length === 0) return;
    chartRef.current?.destroy();
    chartRef.current = Highcharts.stockChart(containerRef.current, {
      ...baseChartOptions(),
      chart: { ...baseChartOptions().chart, height: 240 },
      navigator: { enabled: false },
      series: [{
        type: "line",
        name: target?.name ?? "equity",
        color: cssVar("--accent"),
        lineWidth: 2,
        data: series.data,
      }],
    });
    return () => { chartRef.current?.destroy(); chartRef.current = null; };
  }, [series.data, theme, target?.name]);

  return (
    <div className="panel dash-curve">
      <div className="panel-head">
        Equity <span className="sub">{target?.name ?? ""}</span>
      </div>
      <AsyncSection
        state={series}
        empty={<EmptyState title="No equity history yet"
          hint="Points accumulate every 30 seconds while the engine runs." />}
      >
        {() => <div ref={containerRef} />}
      </AsyncSection>
    </div>
  );
}

function RecentActivity() {
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
        {tab === "orders" ? (
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

export function DashboardPage() {
  const portfolios = useStore((s) => s.portfolios);
  const brokerages = useStore((s) => s.brokerages);
  const halt = useStore((s) => s.halt);
  const broker = useStore((s) => s.broker);
  const watchlists = useStore((s) => s.watchlists);
  const applyBrokerages = useStore((s) => s.applyBrokerages);
  const toast = useStore((s) => s.toast);
  const setPage = useStore((s) => s.setPage);
  const [refreshing, setRefreshing] = useState(false);

  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const totals = useMemo(
    () => netWorthByCurrency(portfolios, brokerages), [portfolios, brokerages]);
  const practiceTotal = useMemo(() => portfolios
    .filter((p) => p.kind === "sim")
    .reduce((sum, p) => sum + (p.equity ?? p.cash), 0), [portfolios]);
  const practiceCcy = portfolios.find((p) => p.kind === "sim")?.baseCurrency ?? "USD";
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  // In LIVE mode the headline is REAL money only — practice never mixes in.
  const liveTotals = useMemo(
    () => totals.filter((t) => t.brokerage > 0)
      .map((t) => ({ currency: t.currency, total: t.brokerage })),
    [totals]);
  const blended = useMemo(() => {
    if (!usdCad || usdCad <= 0 || liveTotals.length < 2) return null;
    let cad = 0;
    for (const t of liveTotals) {
      if (t.currency === "CAD") cad += t.total;
      else if (t.currency === "USD") cad += t.total * usdCad;
      else return null; // unknown currency — no blended figure
    }
    return cad;
  }, [liveTotals, usdCad]);
  const watchSymbols = watchlists[0]?.symbols ?? [];

  const refresh = async () => {
    setRefreshing(true);
    try {
      applyBrokerages(await api.refreshBrokerages());
      toast("success", "Brokerage data refreshed");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div>
      <h2 className="page-title">Dashboard</h2>
      <ArmedFleetWidget />
      <div className="dash-grid">
        <HoldingsWidget />
        <div className="panel dash-networth">
          <div className="panel-body">
            <div className="networth-row">
              {mode === "practice" ? (
                <>
                  {/* practice mode: the sandbox number leads, real money steps back */}
                  <div>
                    <div className="metric-lg">
                      {fmtCcy(practiceTotal, practiceCcy)}
                      <span className="status-pill dim" style={{ marginLeft: 8, verticalAlign: "middle" }}>
                        practice
                      </span>
                    </div>
                    <div className="metric-sub">simulated equity — no real money moves in this mode</div>
                  </div>
                  <div>
                    <div className="metric-sub" style={{ marginTop: 6 }}>
                      real accounts live in the <b>LIVE</b> workspace (switch next to HALT)
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {/* LIVE: real money only — practice lives on the Portfolios page */}
                  {liveTotals.length === 0 && <span className="metric-lg">—</span>}
                  {liveTotals.map((t) => (
                    <div key={t.currency}>
                      <div className="metric-lg">{fmtCcy(t.total, t.currency)}</div>
                      <div className="metric-sub">real {t.currency} across brokerages</div>
                    </div>
                  ))}
                  {blended !== null && (
                    <div title={`Blended at live USD/CAD ${usdCad?.toFixed(4)} — approximate`}>
                      <div className="metric-lg muted">≈ {fmtCcy(blended, "CAD")}</div>
                      <div className="metric-sub">real total, live FX</div>
                    </div>
                  )}
                </>
              )}
              <div className="networth-badges">
                <span className={`status-pill ${halt.engaged ? "bad" : "ok"}`}>
                  {halt.engaged ? "HALTED" : "trading"}
                </span>
                {broker?.snaptradeConnected && (
                  <span className="status-pill ok">snaptrade</span>
                )}
                {broker?.ibkrConnected && <span className="status-pill ok">ibkr</span>}
                {broker?.quoteSource && (
                  <span className="status-pill dim">{broker.quoteSource} quotes</span>
                )}
                {brokerages?.enabled && (
                  <button className="icon-btn" onClick={refresh} disabled={refreshing}
                    aria-label="Refresh brokerage data"
                    title="Refresh brokerage data now"
                    style={{ gap: 6, fontSize: "var(--fs-1)" }}>
                    {refreshing ? <span className="spinner" /> : <IconRefresh />}
                    {brokerages?.lastSyncAt && (
                      <span>synced {fmtDateTime(brokerages.lastSyncAt)}</span>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="dash-providers">
          {mode === "live" && (brokerages?.providers ?? []).map((p) => (
            <ProviderCard key={p.connectionId || p.broker} provider={p} />
          ))}
          <PracticeCard />
          {mode === "live" && (!brokerages || brokerages.providers.length === 0) && (
            <div className="panel">
              <div className="panel-body">
                <EmptyState
                  title="No brokerages connected"
                  hint="Add SnapTrade credentials to backend/.env, enable SnapTrade, restart."
                  action={<button className="link-btn" onClick={() => setPage("settings")}>
                    open Settings → Brokerages</button>}
                />
              </div>
            </div>
          )}
        </div>

        <EquityCurvePanel />

        <div className="panel dash-watch">
          <div className="panel-head">
            Watchlist <span className="sub">{watchlists[0]?.name ?? ""}</span>
          </div>
          <div style={{ overflowY: "auto", maxHeight: 260 }}>
            {watchSymbols.map((sym) => <WatchRow key={sym} symbol={sym} />)}
            {watchSymbols.length === 0 && (
              <EmptyState title="Watchlist is empty"
                action={<button className="link-btn" onClick={() => setPage("settings")}>
                  add symbols in Settings</button>} />
            )}
          </div>
        </div>

        <RecentActivity />
      </div>
    </div>
  );
}


/* ---- Armed fleet on the dashboard (A5): the day's plans greet you ---- */
function ArmedFleetWidget() {
  const armed = useStore((s) => s.techniqueArmed);
  const setPage = useStore((s) => s.setPage);
  const active = armed.filter((a) => a.status === "armed" || a.status === "paused");
  if (!active.length) return null;
  const inTrade = active.filter((a) => a.openPositions > 0).length;
  const fired = active.reduce((n, a) => n + (a.trades ?? []).length, 0);
  const pnl = active.reduce((n, a) => n + (a.realizedPnl ?? 0), 0);
  const top = active.slice().sort((x, y) =>
    (y.openPositions - x.openPositions) || ((y.trades?.length ?? 0) - (x.trades?.length ?? 0))
    || Math.abs(x.triggers?.[0]?.distancePct ?? 99) - Math.abs(y.triggers?.[0]?.distancePct ?? 99)).slice(0, 6);
  return (
    <div className="panel dash-armed clickable" role="button" tabIndex={0}
      onClick={() => setPage("armed")}
      onKeyDown={(e) => e.key === "Enter" && setPage("armed")}
      title="Open the Armed page">
      <div className="panel-head">Armed fleet
        <span className="sub">{active.length} plan(s) · {inTrade} in trade · {fired} fired</span>
        <span className={"tq-head-right " + (pnl > 0 ? "pos" : pnl < 0 ? "neg" : "muted")}>
          {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}</span>
      </div>
      <div className="panel-body dash-armed-rows">
        {top.map((a) => (
          <span key={a.runId} className="dash-armed-chip">
            <b>{a.symbol}</b>
            {a.grade ? <span className={"tq-grade g" + a.grade}>{a.grade}</span> : null}
            <span className="muted small">
              {a.openPositions > 0 ? "in trade" : (a.trades?.length ?? 0) > 0 ? "fired" : "watching"}
            </span>
          </span>
        ))}
        {active.length > top.length && <span className="muted small">+{active.length - top.length} more</span>}
      </div>
    </div>
  );
}

/* ---- Holdings, moved off the sidebar and into the dashboard ---- */
function HoldingsWidget() {
  const positionsMap = useStore((s) => s.positions);
  const portfolios = useStore((s) => s.portfolios);
  const setPage = useStore((s) => s.setPage);
  const holdings = useMemo(() => {
    const real = new Set(portfolios
      .filter((p) => p.kind === "live" || p.kind === "paper").map((p) => p.id));
    const syms = new Set<string>();
    for (const p of Object.values(positionsMap)) {
      if (real.has(p.portfolioId) && Math.abs(p.qty) > 1e-9) syms.add(p.symbol);
    }
    return [...syms].sort();
  }, [positionsMap, portfolios]);
  if (!holdings.length) return null;
  return (
    <div className="panel dash-holdings">
      <div className="panel-head">My holdings
        <span className="holdings-dot" title="Live positions in your real accounts" />
        <button className="link-btn tq-head-right" onClick={() => setPage("watchlists")}>watchlists →</button>
      </div>
      <div className="panel-body dash-holdings-rows">
        {holdings.map((sym) => <WatchRow key={sym} symbol={sym} />)}
      </div>
    </div>
  );
}
