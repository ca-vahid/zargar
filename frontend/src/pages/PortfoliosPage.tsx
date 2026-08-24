import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { memo } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtPct, fmtQty, fmtSigned } from "../lib/format";
import { baseChartOptions, seriesPalette } from "../lib/highchartsTheme";
import { useAsync } from "../lib/useAsync";
import { groupPositions, useQuote, useStore } from "../store";
import type { BrokeragePosition, BrokerageProvider, Portfolio } from "../types";
import { BrokerIcon } from "../components/BrokerIcon";
import { IconRefresh } from "../components/icons";
import { LivePrice, ValuePill } from "../components/quotekit";
import { cashText, providerTotal } from "../lib/brokerage";
import { AsyncSection, EmptyState } from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  live: "Live", paper: "Paper", sim: "Practice", shadow: "Shadow",
};
const REAL_KINDS = new Set(["live", "paper"]);

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
            <span style={{ marginLeft: 8, verticalAlign: "middle" }}
              title="Equity change vs today's first quote-backed observation">
              <ValuePill value={p.todayPct}
                text={`${p.todayPct >= 0 ? "+" : ""}${p.todayPct.toFixed(2)}% today`} />
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
          {p.sourceName && p.sourceName !== "snaptrade" && <> · tracks "{p.sourceName}"</>}
        </div>
      </div>
    </div>
  );
}

/** Live-priced row: the sync price is only the fallback — quotes stream in. */
const LiveBrokerageRow = memo(function LiveBrokerageRow({
  pos,
  accountCurrency,
}: {
  pos: BrokeragePosition;
  accountCurrency: string;
}) {
  const quote = useQuote(pos.symbol);
  const openTrade = useStore((s) => s.openTrade);
  const live = quote?.last && quote.last > 0 ? quote.last : pos.price ?? 0;
  const ccy = pos.currency ?? accountCurrency;
  const pnlPct = pos.avgCost > 0 ? (live / pos.avgCost - 1) * 100 : null;
  return (
    <tr onClick={() => openTrade(pos.symbol)} style={{ cursor: "pointer" }}
      title={`Open ${pos.symbol} in Trade`}>
      <td className="sym-cell">{pos.symbol}</td>
      <td className="num">{fmtQty(pos.qty)}</td>
      <td className="num">{fmtMoney(pos.avgCost)}</td>
      <td className="num"><LivePrice symbol={pos.symbol} fallback={live || undefined} /></td>
      <td className="num">
        {pnlPct !== null ? <ValuePill value={pnlPct} text={fmtPct(pnlPct)} /> : "—"}
      </td>
      <td className="num">{live ? fmtCcy(pos.qty * live, ccy) : "—"}</td>
    </tr>
  );
});

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
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  const total = providerTotal(provider.accounts, usdCad);
  const warnPill = provider.disabled
    ? { cls: "bad", text: "disconnected" }
    : provider.type !== "trade" ? { cls: "dim", text: "read-only" } : null;
  return (
    <div className="panel mb" id={`provider-${provider.connectionId || provider.broker}`}>
      <div className="panel-head">
        <BrokerIcon name={provider.broker} logoUrl={provider.logoUrl} />
        {provider.broker}
        {warnPill && <span className={`status-pill ${warnPill.cls}`}>{warnPill.text}</span>}
        <span className="sub">synced {lastSyncAt ? fmtDateTime(lastSyncAt) : "never"}</span>
        <span className="prov-total">{total}</span>
        <button className="icon-btn" onClick={onRefresh}
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
                  title={`Our live-priced equity ${fmtCcy(a.mismatch.computedEquity, a.currency)} vs the broker's total ${fmtCcy(a.mismatch.brokerTotal, a.currency)} (${a.mismatch.pct > 0 ? "+" : ""}${a.mismatch.pct}%). The broker total comes from SnapTrade's overnight sync${a.brokerSyncedAt ? ` (${fmtDateTime(a.brokerSyncedAt)})` : ""} — small drift is price/FX vintage; large drift means something is missing. Details: Journal → Broker.`}>
                  Δ mismatch
                </span>
              )}
              <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", textAlign: "right" }}>
                <b>{fmtCcy(a.equity, a.currency)}</b>
                {a.equity > 0.005 && (
                  <span className="metric-sub">
                    {" "}· invested {fmtCcy(a.equity - a.cash, a.currency)} · cash {cashText(a)}
                  </span>
                )}
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
                      <th className="num">Avg cost</th><th className="num">Live</th>
                      <th className="num">P&L</th><th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.positions.map((pos) => (
                      <LiveBrokerageRow key={pos.symbol} pos={pos}
                        accountCurrency={a.currency} />
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
  const setPage = useStore((s) => s.setPage);
  const theme = useStore((s) => s.settings["ui.theme"]);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<Highcharts.Chart | null>(null);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [refreshing, setRefreshing] = useState(false);

  const byPortfolio = useMemo(() => groupPositions(positionsMap), [positionsMap]);
  const portfolioIds = portfolios.map((p) => p.id).join(",");
  const snaptradePids = useMemo(() => new Set(
    (brokerages?.providers ?? []).flatMap((pr) => pr.accounts.map((a) => a.portfolioId))),
    [brokerages]);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const ibkrConnected = useStore((s) => !!s.broker?.ibkrConnected);
  // brokerage-backed portfolios render inside their provider section — the
  // card grid carries only what's left. The empty IBKR placeholder hides
  // until the gateway actually connects or holds money.
  const realCards = useMemo(
    () => portfolios.filter((p) => REAL_KINDS.has(p.kind) && !snaptradePids.has(p.id)
      && (ibkrConnected || (p.equity ?? p.cash) > 0.005)),
    [portfolios, snaptradePids, ibkrConnected]);
  const practiceCards = useMemo(
    () => portfolios.filter((p) => !REAL_KINDS.has(p.kind)),
    [portfolios]);
  const showPractice = mode !== "live"; // live board = real money only
  const [chartScope, setChartScope] = useState<"all" | "real" | "practice">(
    mode === "live" ? "real" : "all");
  const chartScopeRef = useRef(chartScope);
  chartScopeRef.current = chartScope;
  const portfoliosFocus = useStore((s) => s.portfoliosFocus);
  const clearPortfoliosFocus = useStore((s) => s.clearPortfoliosFocus);
  useEffect(() => {
    if (!portfoliosFocus) return;
    document.getElementById(`provider-${portfoliosFocus}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
    clearPortfoliosFocus();
  }, [portfoliosFocus, clearPortfoliosFocus]);

  const applyChartScope = (scope: "all" | "real" | "practice") => {
    setChartScope(scope);
    const chart = chartInstance.current;
    if (!chart) return;
    for (const p of portfolios) {
      const isReal = REAL_KINDS.has(p.kind);
      const visible = !hidden[p.id]
        && (scope === "all" || (scope === "real") === isReal);
      (chart.get(p.id) as Highcharts.Series | undefined)?.setVisible(visible, false);
    }
    chart.redraw();
  };

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
      series: curves.data
        // live mode: practice series don't even enter the chart or legend
        .filter((s) => REAL_KINDS.has(s.portfolio.kind) === (mode === "live"))
        .map((s, i) => {
          const isReal = REAL_KINDS.has(s.portfolio.kind);
          const scope = chartScopeRef.current;
          return {
            type: "line" as const,
            id: s.portfolio.id,
            name: s.portfolio.name,
            color: palette[i % palette.length],
            data: s.points,
            visible: !hidden[s.portfolio.id]
              && (scope === "all" || (scope === "real") === isReal),
          };
        }),
    });
    return () => { chartInstance.current?.destroy(); chartInstance.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curves.data, theme, showPractice]);

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

      {mode === "live" && (
        <div className="section-head">
          Real accounts <span className="status-pill bad">real money</span>
        </div>
      )}
      {mode === "live" && (brokerages?.providers ?? []).map((provider) => (
        <BrokerageSection key={provider.connectionId || provider.broker}
          provider={provider} onRefresh={refresh} refreshing={refreshing}
          lastSyncAt={brokerages?.lastSyncAt ?? null} />
      ))}
      {mode === "live" && realCards.length > 0 && (
        <div className="settings-grid mb">
          {realCards.map((p) => (
            <PortfolioCard key={p.id} portfolio={p}
              positionCount={(byPortfolio[p.id] ?? []).length}
              visible={!hidden[p.id]}
              onToggle={(v) => toggleVisible(p.id, v)} />
          ))}
        </div>
      )}
      {mode === "live" && (brokerages?.providers ?? []).length === 0 && realCards.length === 0 && (
        <div className="panel mb"><div className="panel-body">
          <EmptyState title="No real accounts connected"
            hint="Add SnapTrade credentials to backend/.env and enable SnapTrade."
            action={<button className="link-btn" onClick={() => setPage("settings")}>
              open Settings → Brokerages</button>} />
        </div></div>
      )}

      {showPractice && (
        <>
          <div className="section-head">
            Practice environment <span className="status-pill dim">simulated fills</span>
          </div>
          <div className="settings-grid mb">
            {practiceCards.map((p) => (
              <PortfolioCard key={p.id} portfolio={p}
                positionCount={(byPortfolio[p.id] ?? []).length}
                visible={!hidden[p.id]}
                onToggle={(v) => toggleVisible(p.id, v)} />
            ))}
            {practiceCards.length === 0 && (
              <div className="panel"><div className="panel-body">
                <EmptyState title="No practice portfolios"
                  hint="The engine seeds one on first start." />
              </div></div>
            )}
          </div>
        </>
      )}

      <div className="panel">
        <div className="panel-head">
          Equity curves
          <span className="sub">
            {showPractice ? "your practice books over time" : "your real accounts over time"}
          </span>
        </div>
        <AsyncSection state={curves}
          empty={<EmptyState title="No equity history yet" />}>
          {() => <div ref={chartRef} />}
        </AsyncSection>
      </div>
    </div>
  );
}
