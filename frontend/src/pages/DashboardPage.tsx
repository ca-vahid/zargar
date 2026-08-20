import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtTime } from "../lib/format";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { useAsync } from "../lib/useAsync";
import { netWorthByCurrency, useStore } from "../store";
import type { BrokerageProvider } from "../types";
import { IconRefresh } from "../components/icons";
import { AsyncSection, EmptyState, StatusPill } from "../components/ui";
import { WatchRow } from "../components/WatchRow";

function ProviderCard({ provider }: { provider: BrokerageProvider }) {
  const setPage = useStore((s) => s.setPage);
  const pill = provider.disabled ? "bad" : provider.type === "trade" ? "ok" : "dim";
  const pillText = provider.disabled ? "disconnected" : provider.type === "trade" ? "trade" : "read-only";
  return (
    <div className="panel provider-card" onClick={() => setPage("portfolios")}
      role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setPage("portfolios"); }}>
      <div className="panel-head">
        {provider.broker}
        <span className={`status-pill ${pill}`}>{pillText}</span>
      </div>
      <div className="panel-body">
        {provider.accounts.map((a) => (
          <div key={a.id} className="acct-row">
            <span className="name" title={a.number ? `#${a.number}` : undefined}>{a.name}</span>
            <span className="ccy-chip">{a.currency}</span>
            <span className="bal">{fmtCcy(a.equity, a.currency)}</span>
          </div>
        ))}
        {provider.accounts.length === 0 && (
          <div className="metric-sub">no accounts synced yet</div>
        )}
      </div>
    </div>
  );
}

function SimCard() {
  const portfolios = useStore((s) => s.portfolios);
  const setPage = useStore((s) => s.setPage);
  const sims = useMemo(
    () => portfolios.filter((p) => p.kind === "sim" || p.kind === "paper"),
    [portfolios]);
  if (sims.length === 0) return null;
  return (
    <div className="panel provider-card" onClick={() => setPage("portfolios")}
      role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setPage("portfolios"); }}>
      <div className="panel-head">
        Simulation <span className="status-pill dim">virtual</span>
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
  const theme = useStore((s) => s.settings["ui.theme"] ?? "dark");
  const target = portfolios.find((p) => p.id === defaultPid) ?? portfolios[0];
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
  const recentOrders = useStore((s) => s.recentOrders);
  const executions = useStore((s) => s.executions);
  const portfolios = useStore((s) => s.portfolios);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const setPage = useStore((s) => s.setPage);
  const [tab, setTab] = useState<"orders" | "fills">("orders");
  const pname = useMemo(
    () => Object.fromEntries(portfolios.map((p) => [p.id, p.name])), [portfolios]);
  const goTrade = (symbol: string) => { setActiveSymbol(symbol); setPage("trade"); };

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
                      <td className="muted">{pname[o.portfolioId] ?? "—"}</td>
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
                    <td className="muted">{pname[e.portfolioId] ?? "—"}</td>
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
  const [refreshing, setRefreshing] = useState(false);

  const totals = useMemo(
    () => netWorthByCurrency(portfolios, brokerages), [portfolios, brokerages]);
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
      <div className="dash-grid">
        <div className="panel dash-networth">
          <div className="panel-body">
            <div className="networth-row">
              {totals.length === 0 && <span className="metric-lg">—</span>}
              {totals.map((t) => (
                <div key={t.currency}>
                  <div className="metric-lg">{fmtCcy(t.total, t.currency)}</div>
                  <div className="metric-sub">
                    {t.brokerage > 0 && `${fmtCcy(t.brokerage, t.currency)} brokerage`}
                    {t.brokerage > 0 && t.local > 0 && " · "}
                    {t.local > 0 && `${fmtCcy(t.local, t.currency)} local`}
                  </div>
                </div>
              ))}
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
                {brokerages?.lastSyncAt && (
                  <span className="metric-sub">synced {fmtDateTime(brokerages.lastSyncAt)}</span>
                )}
                {brokerages?.enabled && (
                  <button className="icon-btn" onClick={refresh} disabled={refreshing}
                    aria-label="Refresh brokerage data" title="Refresh brokerage data">
                    {refreshing ? <span className="spinner" /> : <IconRefresh />}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="dash-providers">
          {(brokerages?.providers ?? []).map((p) => (
            <ProviderCard key={p.connectionId || p.broker} provider={p} />
          ))}
          <SimCard />
          {(!brokerages || brokerages.providers.length === 0) && (
            <div className="panel">
              <div className="panel-body">
                <EmptyState
                  title="No brokerages connected"
                  hint="Add SnapTrade credentials to backend/.env, enable snaptrade in Settings, and restart."
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
              <EmptyState title="Watchlist is empty" hint="Add symbols in Settings." />
            )}
          </div>
        </div>

        <RecentActivity />
      </div>
    </div>
  );
}
