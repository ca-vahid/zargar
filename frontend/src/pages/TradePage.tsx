import { useEffect, useState } from "react";
import { Blotter } from "../components/Blotter";
import { IconCandles, IconLine, IconWarn } from "../components/icons";
import { DeltaPill, ExtendedHoursChip, TickArrow } from "../components/quotekit";
import { OrderTicket } from "../components/OrderTicket";
import { StockChart, type ChartType, type Indicator } from "../components/StockChart";
import { api } from "../lib/api";
import { fmtMoney } from "../lib/format";
import { useDaySeries } from "../lib/useDaySeries";
import { watchSymbol } from "../lib/ws";
import { useQuote, useStore } from "../store";

const TFS = ["1m", "5m", "15m", "1h", "1d"];
/** Chart ranges (Yahoo keys) and the timeframes Yahoo serves for each. */
const RANGES: { key: string; label: string; tfs: string[]; def: string }[] = [
  { key: "1d", label: "1D", tfs: ["1m", "5m", "15m", "1h"], def: "1m" },
  { key: "5d", label: "5D", tfs: ["1m", "5m", "15m", "1h", "1d"], def: "5m" },
  { key: "1mo", label: "1M", tfs: ["5m", "15m", "1h", "1d"], def: "1h" },
  { key: "3mo", label: "3M", tfs: ["1h", "1d"], def: "1d" },
  { key: "6mo", label: "6M", tfs: ["1h", "1d"], def: "1d" },
  { key: "1y", label: "1Y", tfs: ["1h", "1d"], def: "1d" },
  { key: "5y", label: "5Y", tfs: ["1d"], def: "1d" },
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

  return (
    <div className={`trade-grid ${ticketCollapsed ? "trade-grid--tc" : ""}`}>
      <div className="panel chart-area">
        <div className="quote-head">
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
                onClick={() => setChartType(t)} title={t}>
                {t === "candlestick" ? <IconCandles size={13} /> : <IconLine size={13} />}
              </button>
            ))}
            <span className="sep" aria-hidden="true" />
            {RANGES.map((r) => (
              <button key={r.key} className={range === r.key ? "active" : ""}
                onClick={() => pickRange(r.key)} title={`Show the last ${r.label}`}>
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
          </div>
        </div>
        <StockChart symbol={symbol} tf={tf} range={range} chartType={chartType}
          indicators={indicators} showVolume={showVolume} />
      </div>
      <OrderTicket symbol={symbol} collapsed={ticketCollapsed}
        onToggleCollapse={toggleTicket} />
      <Blotter />
    </div>
  );
}
