import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtSigned } from "../lib/format";
import { baseChartOptions, seriesPalette } from "../lib/highchartsTheme";
import { useAsync } from "../lib/useAsync";
import { groupPositions, useStore } from "../store";
import type { BrokerageProvider, Portfolio } from "../types";
import { IconRefresh } from "../components/icons";
import { AsyncSection, EmptyState } from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  live: "Live", paper: "Paper", sim: "Simulation", shadow: "Shadow",
};

function PortfolioCard({
  portfolio,
  positionCount,
  visible,
  onToggle,
}: {
  portfolio: Portfolio;
  positionCount: number;
  visible: boolean;
  onToggle: (v: boolean) => void;
}) {
  const p = portfolio;
  const ccy = p.baseCurrency ?? "USD";
  const equity = p.equity ?? p.cash;
  const pnl = equity - p.startingCash;
  return (
    <div className="panel">
      <div className="panel-head">
        {p.name}
        <span className={`status-pill ${p.kind === "live" ? "bad" : p.kind === "shadow" ? "dim" : "ok"}`}>
          {KIND_LABEL[p.kind] ?? p.kind}
        </span>
        {p.venue === "snaptrade" && <span className="status-pill dim">snaptrade</span>}
        <label className="switch" style={{ marginLeft: "auto" }} title="Show on equity chart">
          <input type="checkbox" checked={visible}
            onChange={(e) => onToggle(e.target.checked)} />
          <span className="track" />
        </label>
      </div>
      <div className="panel-body">
        <div className="metric-lg">
          {fmtCcy(equity, ccy)}
          {p.todayPct !== null && p.todayPct !== undefined && (
            <span className={`status-pill ${p.todayPct >= 0 ? "ok" : "bad"}`}
              style={{ marginLeft: 8, verticalAlign: "middle" }}
              title="Equity change vs today's first quote-backed observation">
              {p.todayPct >= 0 ? "+" : ""}{p.todayPct.toFixed(2)}% today
            </span>
          )}
        </div>
        {p.kind !== "live" && (
          <div className={pnl >= 0 ? "pos" : "neg"} style={{ fontSize: "var(--fs-2)" }}>
            {fmtSigned(pnl)} since start
          </div>
        )}
        <div className="metric-sub" style={{ marginTop: 6 }}>
          cash {fmtCcy(p.cash, ccy)} · {positionCount} position{positionCount === 1 ? "" : "s"}
          {p.sourceName && p.sourceName !== "snaptrade" && <> · tracks “{p.sourceName}”</>}
        </div>
      </div>
    </div>
  );
}

function BrokerageSection({
  provider,
  onRefresh,
  refreshing,
  lastSyncAt,
}: {
  provider: BrokerageProvider;
  onRefresh: () => void;
  refreshing: boolean;
  lastSyncAt: string | null;
}) {
  const pill = provider.disabled ? "bad" : provider.type === "trade" ? "ok" : "dim";
  const pillText = provider.disabled ? "disconnected" : provider.type === "trade" ? "trade" : "read-only";
  return (
    <div className="panel mb">
      <div className="panel-head">
        {provider.broker}
        <span className={`status-pill ${pill}`}>{pillText}</span>
        <span className="sub">synced {lastSyncAt ? fmtDateTime(lastSyncAt) : "never"}</span>
        <button className="icon-btn" style={{ marginLeft: "auto" }} onClick={onRefresh}
          disabled={refreshing} aria-label={`Refresh ${provider.broker}`}
          title="Refresh brokerage data">
          {refreshing ? <span className="spinner" /> : <IconRefresh />}
        </button>
      </div>
      <div className="panel-body">
        {provider.accounts.map((a) => (
          <div key={a.id} className="mb">
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
              <strong>{a.name}</strong>
              {a.number && <span className="metric-sub">#{a.number}</span>}
              <span className="ccy-chip">{a.currency}</span>
              {a.mismatch && (
                <span className="status-pill wait"
                  title={`Our computed equity ${fmtCcy(a.mismatch.computedEquity, a.currency)} differs from the broker's total ${fmtCcy(a.mismatch.brokerTotal, a.currency)} by ${a.mismatch.pct}% — see Journal (broker)`}>
                  Δ mismatch
                </span>
              )}
              <span style={{ marginLeft: "auto", fontFamily: "var(--mono)" }}>
                {fmtCcy(a.equity, a.currency)}
                <span className="metric-sub"> · cash {fmtCcy(a.cash, a.currency)}</span>
              </span>
            </div>
            {a.positions.length === 0 ? (
              <div className="metric-sub">no positions</div>
            ) : (
              <div className="scroll-x">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Symbol</th><th className="num">Qty</th>
                      <th className="num">Avg cost</th><th className="num">Price</th>
                      <th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.positions.map((pos) => (
                      <tr key={pos.symbol}>
                        <td>{pos.symbol}</td>
                        <td className="num">{fmtQty(pos.qty)}</td>
                        <td className="num">{fmtMoney(pos.avgCost)}</td>
                        <td className="num">{pos.price ? fmtMoney(pos.price) : "—"}</td>
                        <td className="num">
                          {pos.price ? fmtCcy(pos.qty * pos.price, a.currency) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PortfoliosPage() {
  const portfolios = useStore((s) => s.portfolios);
  const positionsMap = useStore((s) => s.positions);
  const brokerages = useStore((s) => s.brokerages);
  const applyBrokerages = useStore((s) => s.applyBrokerages);
  const toast = useStore((s) => s.toast);
  const theme = useStore((s) => s.settings["ui.theme"]);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<Highcharts.Chart | null>(null);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [refreshing, setRefreshing] = useState(false);

  const byPortfolio = useMemo(() => groupPositions(positionsMap), [positionsMap]);
  const portfolioIds = portfolios.map((p) => p.id).join(",");

  const curves = useAsync(
    async () => {
      const series = await Promise.all(portfolios.map(async (p) => ({
        portfolio: p,
        points: await api.get<[number, number][]>(`/api/portfolios/${p.id}/equity?limit=2000`),
      })));
      return series;
    },
    [portfolioIds],
  );

  // build once per portfolio set / theme; visibility toggles reuse the instance
  useEffect(() => {
    if (!chartRef.current || !curves.data) return;
    const palette = seriesPalette();
    chartInstance.current?.destroy();
    chartInstance.current = Highcharts.stockChart(chartRef.current, {
      ...baseChartOptions(),
      chart: { ...baseChartOptions().chart, height: 320 },
      navigator: { enabled: false },
      legend: { ...baseChartOptions().legend, enabled: true },
      tooltip: { ...baseChartOptions().tooltip, valueDecimals: 2 },
      series: curves.data.map((s, i) => ({
        type: "line" as const,
        id: s.portfolio.id,
        name: s.portfolio.name,
        color: palette[i % palette.length],
        data: s.points,
        visible: !hidden[s.portfolio.id],
      })),
    });
    return () => { chartInstance.current?.destroy(); chartInstance.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curves.data, theme]);

  const toggleVisible = (pid: string, visible: boolean) => {
    setHidden((h) => ({ ...h, [pid]: !visible }));
    const series = chartInstance.current?.get(pid) as Highcharts.Series | undefined;
    series?.setVisible(visible, true);
  };

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
      <h2 className="page-title">Portfolios</h2>

      {(brokerages?.providers ?? []).map((provider) => (
        <BrokerageSection key={provider.connectionId || provider.broker}
          provider={provider} onRefresh={refresh} refreshing={refreshing}
          lastSyncAt={brokerages?.lastSyncAt ?? null} />
      ))}

      <div className="settings-grid mb">
        {portfolios.map((p) => (
          <PortfolioCard key={p.id} portfolio={p}
            positionCount={(byPortfolio[p.id] ?? []).length}
            visible={!hidden[p.id]}
            onToggle={(v) => toggleVisible(p.id, v)} />
        ))}
        {portfolios.length === 0 && (
          <div className="panel"><div className="panel-body">
            <EmptyState title="No portfolios yet"
              hint="The engine seeds a simulation portfolio on first start." />
          </div></div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          Equity curves <span className="sub">live vs simulation vs shadow — the “what would have happened” view</span>
        </div>
        <AsyncSection state={curves}
          empty={<EmptyState title="No equity history yet" />}>
          {() => <div ref={chartRef} />}
        </AsyncSection>
      </div>
    </div>
  );
}
