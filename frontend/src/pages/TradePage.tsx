import { useEffect, useMemo, useState } from "react";
import { Blotter } from "../components/Blotter";
import { IconCandles, IconLine, IconWarn } from "../components/icons";
import { DeltaPill, ExtendedHoursChip, TickArrow } from "../components/quotekit";
import { OrderTicket } from "../components/OrderTicket";
import { StockChart, type ChartSession, type ChartType, type ChartView, type Indicator } from "../components/StockChart";
import { api } from "../lib/api";
import { fmtMoney } from "../lib/format";
import { canGoBack } from "../lib/routing";
import { useDaySeries } from "../lib/useDaySeries";
import { watchSymbol } from "../lib/ws";
import { useQuote, useStore } from "../store";
import { useViewport } from "../lib/viewport";
import { ChartSettingsSheet } from "../components/trade/ChartSettingsSheet";

const TFS = ["1m", "5m", "15m", "1h", "1d"];
/** Chart ranges: `fetch` is the Yahoo range key, `clip` trims it to specific
 * ET trading days (2D/3D, this week, last week, last two weeks) client-side,
 * and `tfs` are the timeframes Yahoo serves for that fetch window. */
const RANGES: { key: string; label: string; title: string; fetch: string; clip?: string; tfs: string[]; def: string }[] = [
  { key: "1d", label: "1D", title: "Today", fetch: "1d", tfs: ["1m", "5m", "15m", "1h"], def: "1m" },
  { key: "2d", label: "2D", title: "Last 2 trading days", fetch: "5d", clip: "d2", tfs: ["1m", "5m", "15m", "1h"], def: "1m" },
  { key: "3d", label: "3D", title: "Last 3 trading days", fetch: "5d", clip: "d3", tfs: ["1m", "5m", "15m", "1h"], def: "5m" },
  { key: "5d", label: "5D", title: "Last 5 trading days", fetch: "5d", tfs: ["1m", "5m", "15m", "1h", "1d"], def: "5m" },
  { key: "tw", label: "TW", title: "This week (Monday to now)", fetch: "5d", clip: "tw", tfs: ["1m", "5m", "15m", "1h"], def: "5m" },
  { key: "lw", label: "LW", title: "Last week (Mon-Fri)", fetch: "1mo", clip: "lw", tfs: ["5m", "15m", "1h", "1d"], def: "5m" },
  { key: "2w", label: "2W", title: "Last two weeks, up to now", fetch: "1mo", clip: "2w", tfs: ["5m", "15m", "1h", "1d"], def: "15m" },
  { key: "1mo", label: "1M", title: "Last month", fetch: "1mo", tfs: ["5m", "15m", "1h", "1d"], def: "1h" },
  { key: "3mo", label: "3M", title: "Last 3 months", fetch: "3mo", tfs: ["1h", "1d"], def: "1d" },
  { key: "6mo", label: "6M", title: "Last 6 months", fetch: "6mo", tfs: ["1h", "1d"], def: "1d" },
  { key: "1y", label: "1Y", title: "Last year", fetch: "1y", tfs: ["1h", "1d"], def: "1d" },
  { key: "5y", label: "5Y", title: "Last 5 years", fetch: "5y", tfs: ["1d"], def: "1d" },
];
const INDICATORS: { key: Indicator; label: string }[] = [
  { key: "ema20", label: "EMA 20" },
  { key: "sma50", label: "SMA 50" },
  { key: "bb", label: "Bollinger" },
];

export function TradePage() {
  const symbol = useStore((s) => s.activeSymbol);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const settings = useStore((s) => s.settings);
  const quote = useQuote(symbol);
  const [tf, setTf] = useState<string>(settings["ui.chart.tf"] ?? "1m");
  const [range, setRange] = useState<string>(
    () => localStorage.getItem("zargar_chart_range") ?? "1d");
  const rangeDef = RANGES.find((r) => r.key === range) ?? RANGES[0];
  // render with a tf the range can serve even before the corrective effect
  // lands — the one-frame mismatch fired a doomed 400 chart request (1m + 1mo)
  const chartTf = rangeDef.tfs.includes(tf) ? tf : rangeDef.def;
  const pickRange = (key: string) => {
    localStorage.setItem("zargar_chart_range", key);
    setRange(key);
    const r = RANGES.find((x) => x.key === key) ?? RANGES[0];
    if (!r.tfs.includes(tf)) setTf(r.def); // keep the timeframe Yahoo can serve
  };
  useEffect(() => {
    if (!rangeDef.tfs.includes(tf)) setTf(rangeDef.def);
  }, [rangeDef, tf]);
  const [chartType, setChartType] = useState<ChartType>(settings["ui.chart.type"] ?? "candlestick");
  const [view, setViewRaw] = useState<ChartView>(
    () => (localStorage.getItem("zargar_trade_view") as ChartView) || "candles");
  const setView = (v: ChartView) => { localStorage.setItem("zargar_trade_view", v); setViewRaw(v); };
  const [chSession, setChSessionRaw] = useState<ChartSession>(
    () => (localStorage.getItem("zargar_trade_session") as ChartSession) || "eth");
  const setChSession = (v: ChartSession) => { localStorage.setItem("zargar_trade_session", v); setChSessionRaw(v); };
  // the armed plan watching this symbol (if any) and your live position in it
  const armedPlan = useStore((s) => s.techniqueArmed.find(
    (a) => a.symbol === symbol && (a.status === "armed" || a.status === "paused")) ?? null);
  const openArmedPlan = useStore((s) => s.openArmedPlan);
  const positionsMap = useStore((s) => s.positions);
  const position = useMemo(() => {
    let qty = 0, cost = 0;
    for (const pos of Object.values(positionsMap)) {
      if (pos.symbol !== symbol || pos.secType === "OPT" || Math.abs(pos.qty) < 1e-9) continue;
      qty += pos.qty; cost += pos.qty * pos.avgCost;
    }
    return qty !== 0 ? { price: cost / qty, qty } : null;
  }, [positionsMap, symbol]);
  const [indicators, setIndicators] = useState<Indicator[]>(
    (settings["ui.chart.indicators"] ?? ["ema20"]).filter((i: string) =>
      ["ema20", "sma50", "bb"].includes(i)) as Indicator[]);
  const showVolume = settings["ui.chart.show_volume"] ?? true;
  const quoteSource = useStore((s) => s.broker?.quoteSource);
  const day = useDaySeries(symbol);
  const [symInput, setSymInput] = useState(symbol);
  const [ticketCollapsed, setTicketCollapsed] = useState(
    () => localStorage.getItem("zargar_ticket_collapsed") === "1");
  const toggleTicket = () => setTicketCollapsed((v) => {
    localStorage.setItem("zargar_ticket_collapsed", v ? "0" : "1");
    return !v;
  });

  useEffect(() => setSymInput(symbol), [symbol]);
  useEffect(() => {
    if (symbol) {
      watchSymbol(symbol);
      // fire-and-forget: watch registration has no user-visible result
      api.post("/api/watch", { symbol }).catch(() => undefined);
    }
  }, [symbol]);

  const commitSymbol = () => {
    const s = symInput.trim().toUpperCase();
    if (s && s !== symbol) setActiveSymbol(s);
  };

  const toggleIndicator = (key: Indicator) =>
    setIndicators((cur) =>
      cur.includes(key) ? cur.filter((i) => i !== key) : [...cur, key]);

  const { isPhone, landscape } = useViewport();
  const [chartSettings, setChartSettings] = useState(false);
  const [ticket, setTicket] = useState<null | "BUY" | "SELL">(null);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const exitOnly = useStore((s) => s.settings["mobile.exit_only"] ?? true) as boolean;
  const entriesBlocked = isPhone && mode === "live" && exitOnly;

  if (isPhone) {
    const PHONE_RANGES = RANGES.filter((r) => ["1d", "5d", "1mo", "1y"].includes(r.key));
    return (
      <div className={`trade-phone ${landscape ? "trade-phone--land" : ""}`}>
        <div className="panel chart-area trade-phone-chart">
          <div className="quote-head quote-head--phone">
            {canGoBack() && (
              <button type="button" className="ghost-btn trade-back" onClick={() => window.history.back()}
                aria-label="Back">←</button>
            )}
            <input className="symbol-input" value={symInput}
              onChange={(e) => setSymInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && commitSymbol()}
              onBlur={commitSymbol}
              enterKeyHint="go" autoCapitalize="characters" autoCorrect="off"
              spellCheck={false} aria-label="Symbol" />
            {quote && (
              <>
                <span className="last"><TickArrow symbol={symbol} /> {fmtMoney(quote.last)}</span>
                <DeltaPill quote={quote} fallbackOpen={day.open} size="md" />
              </>
            )}
            {quote && (
              <div className="quote-head-sub">
                <ExtendedHoursChip quote={quote} fallbackOpen={day.open} />
                <span className="ba">bid {fmtMoney(quote.bid)} · ask {fmtMoney(quote.ask)}</span>
                {quote.halted && <span className="halted">HALTED</span>}
                {quoteSource === "yahoo" && <span className="status-pill dim">indicative</span>}
              </div>
            )}
          </div>
          <div className="trade-phone-tools">
            <div className="seg" role="group" aria-label="Range">
              {PHONE_RANGES.map((r) => (
                <button key={r.key} type="button" className={range === r.key ? "on" : ""} onClick={() => pickRange(r.key)}>{r.label}</button>
              ))}
            </div>
            <span className="trade-phone-tf">{tf} bars</span>
            <button type="button" className="ghost-btn trade-phone-more" onClick={() => setChartSettings(true)}
              aria-label="Chart settings">⋯</button>
          </div>
          {armedPlan && (
            <button className="trade-armed-chip" onClick={() => openArmedPlan(armedPlan.runId)}>
              <span className="zap">⚡</span> ARMED
              {armedPlan.grade ? <span className={`tq-grade g${armedPlan.grade}`}>{armedPlan.grade}</span> : null}
              <span className="muted">{armedPlan.summary ?? armedPlan.status}</span>
              <span className="go">open →</span>
            </button>
          )}
          <StockChart symbol={symbol} tf={chartTf} range={rangeDef.fetch} clip={rangeDef.clip} chartType={chartType}
            indicators={indicators.slice(0, 1)} showVolume={false}
            view={view} session={chSession} armed={armedPlan} avgCost={position} phone />
        </div>
        <Blotter />
        <div className="trade-phone-bar">
          {position && <span className="trade-phone-pos">{position.qty > 0 ? "long" : "short"} {Math.abs(position.qty)} @ {fmtMoney(position.price)}</span>}
          <button type="button" className="submit-btn buy" disabled={entriesBlocked && !(position && position.qty < 0)}
            onClick={() => setTicket("BUY")}>
            BUY
          </button>
          <button type="button" className="submit-btn sell" onClick={() => setTicket("SELL")}>SELL</button>
        </div>
        {entriesBlocked && (
          <div className="trade-phone-note">Phone is exit-only for LIVE — buys to open are blocked (Settings → Mobile).</div>
        )}
        {chartSettings && (
          <ChartSettingsSheet onClose={() => setChartSettings(false)}
            chartType={chartType} setChartType={setChartType} tf={tf} setTf={setTf} rangeDef={rangeDef} tfs={TFS}
            indicators={indicators} toggleIndicator={toggleIndicator} indicatorDefs={INDICATORS}
            view={view} setView={setView} session={chSession} setSession={setChSession} hasArmed={!!armedPlan} />
        )}
        {ticket && (
          <OrderTicket symbol={symbol} asSheet initialSide={ticket} onClose={() => setTicket(null)} />
        )}
      </div>
    );
  }

  return (
    <div className={`trade-grid ${ticketCollapsed ? "trade-grid--tc" : ""}`}>
      <div className="panel chart-area">
        <div className="quote-head">
          {canGoBack() && (
            <button type="button" className="ghost-btn trade-back" onClick={() => window.history.back()}
              title="Back to the page you came from" aria-label="Back">←</button>
          )}
          <input className="symbol-input" value={symInput}
            onChange={(e) => setSymInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitSymbol()}
            onBlur={commitSymbol}
            spellCheck={false} />
          {quote && (
            <>
              <span className="last"><TickArrow symbol={symbol} /> {fmtMoney(quote.last)}</span>
              <DeltaPill quote={quote} fallbackOpen={day.open} size="md" />
              <ExtendedHoursChip quote={quote} fallbackOpen={day.open} />
              <span className="ba">
                bid {fmtMoney(quote.bid)} × {quote.bidSize} &nbsp;·&nbsp; ask {fmtMoney(quote.ask)} × {quote.askSize}
              </span>
              {quote.halted && <span className="halted">HALTED</span>}
              {quoteSource === "yahoo" && (
                <span className="status-pill dim" title="Yahoo Finance quotes — ~1-2s delayed, indicative">
                  <IconWarn size={11} /> indicative
                </span>
              )}
            </>
          )}
          <div className="tf-row">
            {(["candlestick", "line"] as ChartType[]).map((t) => (
              <button key={t} className={chartType === t ? "active" : ""}
                onClick={() => setChartType(t)} title={t} aria-label={t === "candlestick" ? "Candlestick chart" : "Line chart"}>
                {t === "candlestick" ? <IconCandles size={13} /> : <IconLine size={13} />}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {RANGES.map((r) => (
              <button key={r.key} className={range === r.key ? "active" : ""}
                onClick={() => pickRange(r.key)} title={r.title}>
                {r.label}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {TFS.map((t) => (
              <button key={t} className={tf === t ? "active" : ""}
                disabled={!rangeDef.tfs.includes(t)}
                title={rangeDef.tfs.includes(t) ? `${t} bars` : `${t} bars aren't available for ${rangeDef.label}`}
                onClick={() => setTf(t)}>
                {t}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {INDICATORS.map((i) => (
              <button key={i.key} className={indicators.includes(i.key) ? "active" : ""}
                onClick={() => toggleIndicator(i.key)}>
                {i.label}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {(["candles", "zones", "panes"] as ChartView[]).map((v) => (
              <button key={v} className={view === v ? "active" : ""}
                disabled={v === "zones" && !armedPlan}
                title={v === "candles" ? "Hollow candles, colored volume, level labels"
                  : v === "zones" ? (armedPlan ? "The armed plan's risk/reward as bands" : "Zones need an armed plan on this symbol")
                  : "Adds range buttons and a P&L-vs-avg-cost pane when you hold a position"}
                onClick={() => setView(v)}>
                {v}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {(["eth", "rth"] as ChartSession[]).map((v) => (
              <button key={v} className={chSession === v ? "active" : ""}
                title={v === "eth" ? "Show pre-market and after-hours (shaded)" : "Regular session only - 9:30 to 4:00 ET"}
                onClick={() => setChSession(v)}>
                {v.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {armedPlan && (
          <button className="trade-armed-chip" onClick={() => openArmedPlan(armedPlan.runId)}
            title="This symbol has an armed plan watching it - open its card on the Armed page">
            <span className="zap">⚡</span> ARMED
            {armedPlan.grade ? <span className={`tq-grade g${armedPlan.grade}`}>{armedPlan.grade}</span> : null}
            <span className="muted">{armedPlan.summary ?? armedPlan.status}</span>
            <span className="go">open card →</span>
          </button>
        )}
        <StockChart symbol={symbol} tf={chartTf} range={rangeDef.fetch} clip={rangeDef.clip} chartType={chartType}
          indicators={indicators} showVolume={showVolume}
          view={view} session={chSession} armed={armedPlan} avgCost={position} />
      </div>
      <OrderTicket symbol={symbol} collapsed={ticketCollapsed}
        onToggleCollapse={toggleTicket} />
      <Blotter />
    </div>
  );
}
