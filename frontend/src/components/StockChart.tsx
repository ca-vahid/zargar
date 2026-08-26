import { useEffect, useRef } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import "highcharts/esm/indicators/indicators.js"; // registers sma + ema
import "highcharts/esm/indicators/bollinger-bands.js";
import "highcharts/esm/modules/accessibility.js";
import "highcharts/esm/modules/hollowcandlestick.js";
import { api } from "../lib/api";
import { cssVar, rgbaVar } from "../lib/highchartsTheme";
import { onBar, watchSymbol } from "../lib/ws";
import { useStore } from "../store";
import type { ArmedPlan, Quote } from "../types";

export type Indicator = "sma50" | "ema20" | "bb";
export type ChartType = "candlestick" | "ohlc" | "line";
export type ChartView = "candles" | "zones" | "panes";
export type ChartSession = "eth" | "rth";

const INTRADAY = new Set(["1m", "5m", "15m", "1h"]);

/** UTC ms for h:m ET on the given YYYY-MM-DD, DST-safe (tries both offsets). */
const ET_HM_FMT = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const ET_DAY_FMT = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
function etToUtcMs(dateStr: string, h: number, m: number): number {
  const hh = String(h).padStart(2, "0"), mm = String(m).padStart(2, "0");
  for (const off of ["-04:00", "-05:00"]) {
    const t = new Date(`${dateStr}T${hh}:${mm}:00${off}`).getTime();
    if (ET_HM_FMT.format(t) === `${hh}:${mm}`) return t;
  }
  return new Date(`${dateStr}T${hh}:${mm}:00-04:00`).getTime();
}
function etMinutes(ts: number): number {
  const [h, m] = ET_HM_FMT.format(ts).split(":").map(Number);
  return h * 60 + m;
}

const TF_MS: Record<string, number> = {
  "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "1d": 86_400_000,
};

/** Live bars/ticks are only appended during the extended session (04:00–20:00
 * ET, weekdays) — overnight the feed just repeats the close, and drawing that
 * produces the flat "01:00–09:00" line brokers never show. */
function inExtendedSession(ts: number): boolean {
  const et = new Date(new Date(ts).toLocaleString("en-US", { timeZone: "America/New_York" }));
  const dow = et.getDay();
  if (dow === 0 || dow === 6) return false;
  const mins = et.getHours() * 60 + et.getMinutes();
  return mins >= 4 * 60 && mins < 20 * 60;
}

interface Props {
  symbol: string;
  tf: string;
  range: string; // Yahoo range key: 1d | 5d | 1mo | 3mo | 6mo | 1y | 5y
  chartType: ChartType;
  indicators: Indicator[];
  showVolume: boolean;
  /** armed-parity view: candles (hollow) / zones (armed risk-reward bands) / panes (+range buttons, P&L pane) */
  view?: ChartView;
  /** eth shows the whole extended tape with pre/post shading; rth folds it away */
  session?: ChartSession;
  /** the armed plan for this symbol, when one exists — draws its levels */
  armed?: ArmedPlan | null;
  /** your position: average-cost line with live P&L context */
  avgCost?: { price: number; qty: number } | null;
  /** phone: no navigator, pinch-zoom + pan, touch-following tooltip, bigger labels */
  phone?: boolean;
}

export function StockChart({ symbol, tf, range, chartType, indicators, showVolume,
                             view = "candles", session = "eth", armed = null, avgCost = null , phone = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);
  const lastBarTs = useRef<number>(0);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");

  useEffect(() => {
    let cancelled = false;
    watchSymbol(symbol);

    const up = cssVar("--up") || "#0ca30c";
    const down = cssVar("--down") || "#d03b3b";
    const text2 = cssVar("--text-2");
    const text3 = cssVar("--text-3");
    const grid = cssVar("--grid");
    const surface = cssVar("--surface-1");
    const series1 = cssVar("--series-1");
    const series7 = cssVar("--series-7");
    const series4 = cssVar("--series-4");

    const accent = cssVar("--accent") || "#5b8cff";
    const intraday = INTRADAY.has(tf);

    async function build() {
      const data = await api.get<{ bars: number[][] }>(
        `/api/chart/${symbol}?tf=${tf}&range=${range}&limit=500`,
      );
      if (cancelled || !containerRef.current) return;
      let bars = data.bars;
      if (session === "rth" && intraday) {
        bars = bars.filter((b) => { const m = etMinutes(b[0]); return m >= 570 && m < 960; });
      }
      const ohlc = bars.map((b) => [b[0], b[1], b[2], b[3], b[4]]);
      // volume colored by bar direction (a flat hairline color made it invisible)
      const volume = bars.map((b) => ({ x: b[0], y: b[5],
        color: b[4] >= b[1] ? rgbaVar("--up", 0.45) : rgbaVar("--down", 0.45) }));
      lastBarTs.current = ohlc.length ? ohlc[ohlc.length - 1][0] : 0;

      // pre/post session shading: one tinted band per day outside 09:30-16:00 ET
      const sessionBands: Highcharts.XAxisPlotBandsOptions[] = [];
      if (session === "eth" && intraday && ohlc.length) {
        const days = [...new Set(bars.map((b) => ET_DAY_FMT.format(b[0])))];
        for (const d of days) {
          sessionBands.push({ from: etToUtcMs(d, 4, 0), to: etToUtcMs(d, 9, 30),
            color: rgbaVar("--series-4", 0.07),
            label: days.length <= 2 ? { text: "pre", style: { color: text3, fontSize: "9px" } } : undefined });
          sessionBands.push({ from: etToUtcMs(d, 16, 0), to: etToUtcMs(d, 20, 0),
            color: rgbaVar("--series-4", 0.07),
            label: days.length <= 2 ? { text: "after", style: { color: text3, fontSize: "9px" } } : undefined });
        }
      }

      // levels: your average cost + the armed plan's triggers
      const priceLines: Highcharts.YAxisPlotLinesOptions[] = [];
      const priceBands: Highcharts.YAxisPlotBandsOptions[] = [];
      if (avgCost && avgCost.qty !== 0) {
        priceLines.push({ value: avgCost.price, color: accent, width: 1.2, dashStyle: "Dash", zIndex: 5,
          label: { text: `avg ${avgCost.price.toFixed(2)} × ${avgCost.qty}`, align: "right",
            style: { color: accent, fontSize: "10px", fontWeight: "600" } } });
      }
      for (const t of armed?.triggers ?? []) {
        if (view === "zones") {
          priceBands.push({ from: Math.min(t.entry, t.stop), to: Math.max(t.entry, t.stop),
            color: rgbaVar("--down", 0.08),
            label: { text: `${t.id} risk`, align: "left", style: { color: down, fontSize: "9px" } } });
          if (t.targets?.length) priceBands.push({ from: t.entry, to: t.targets[0],
            color: rgbaVar("--up", 0.07),
            label: { text: "first reward", align: "left", style: { color: up, fontSize: "9px" } } });
        }
        priceLines.push({ value: t.entry, color: rgbaVar("--accent", 0.55), width: 1, zIndex: 4,
          label: { text: `⚡ ${t.id} ${t.entry.toFixed(2)}`, align: "right",
            style: { color: accent, fontSize: "9px", fontWeight: "600" } } });
        if (view !== "zones") {
          priceLines.push({ value: t.stop, width: 0, zIndex: 4,
            label: { text: `stop ${t.stop.toFixed(2)}`, align: "right", style: { color: down, fontSize: "9px" } } });
          for (const [i, tp] of (t.targets ?? []).entries())
            priceLines.push({ value: tp, width: 0, zIndex: 3,
              label: { text: `TP${i + 1} ${tp.toFixed(2)}`, align: "right", style: { color: up, fontSize: "9px" } } });
        }
      }

      // panes view: P&L pane in % vs your average cost (only with a position)
      const pnlPane = view === "panes" && avgCost && avgCost.qty !== 0;
      const pnlData = pnlPane
        ? bars.map((b) => ({ x: b[0], y: (b[4] - avgCost!.price) / avgCost!.price * 100,
            color: b[4] >= avgCost!.price ? rgbaVar("--up", 0.6) : rgbaVar("--down", 0.6) }))
        : [];

      const priceH = pnlPane ? (showVolume ? "56%" : "74%") : (showVolume ? "78%" : "100%");
      const yAxes: Highcharts.YAxisOptions[] = [
        {
          labels: { style: { color: text3, fontSize: "11px" } },
          gridLineColor: grid,
          height: priceH,
          lineWidth: 0,
          crosshair: { color: grid, dashStyle: "Dash" },
          plotLines: priceLines,
          plotBands: priceBands,
        },
      ];
      if (showVolume) {
        yAxes.push({
          labels: { enabled: false },
          gridLineWidth: 0,
          top: pnlPane ? "58%" : "80%",
          height: pnlPane ? "16%" : "20%",
          offset: 0,
        });
      }
      if (pnlPane) {
        yAxes.push({
          labels: { style: { color: text3, fontSize: "9px" }, format: "{value}%" },
          gridLineColor: grid,
          top: "76%", height: "24%", offset: 0,
          plotLines: [{ value: 0, color: grid, width: 1 }],
        });
      }

      const mainSeries: Highcharts.SeriesOptionsType =
        chartType === "line"
          ? { type: "line", id: "main", name: symbol, color: series1, lineWidth: 2,
              data: ohlc.map((b) => [b[0], b[4]]) }
          : {
              type: chartType === "candlestick" && view === "candles" ? "hollowcandlestick" : chartType,
              id: "main", name: symbol, data: ohlc,
              color: down, upColor: up, lineColor: down, upLineColor: up,
              // @ts-ignore — lastPrice is a stock option missing from some type versions
              lastPrice: { enabled: true, color: text3, label: { enabled: false } },
            };

      const series: Highcharts.SeriesOptionsType[] = [mainSeries];
      if (showVolume) {
        series.push({
          type: "column", id: "vol", name: "Volume", data: volume, yAxis: 1,
          borderWidth: 0,
          dataGrouping: { enabled: true, approximation: "sum" },
          tooltip: { valueDecimals: 0 },
        } as Highcharts.SeriesOptionsType);
      }
      if (pnlPane) {
        series.push({
          type: "column", id: "pnl", name: "P&L vs avg cost", data: pnlData,
          yAxis: showVolume ? 2 : 1, borderWidth: 0,
          tooltip: { valueDecimals: 2, valueSuffix: "%" },
        } as Highcharts.SeriesOptionsType);
      }
      if (chartType !== "line") {
        if (indicators.includes("ema20"))
          series.push({ type: "ema", linkedTo: "main", params: { period: 20 },
            color: series1, lineWidth: 1.5, marker: { enabled: false } } as any);
        if (indicators.includes("sma50"))
          series.push({ type: "sma", linkedTo: "main", params: { period: 50 },
            color: series7, lineWidth: 1.5, marker: { enabled: false } } as any);
        if (indicators.includes("bb"))
          series.push({ type: "bb", linkedTo: "main",
            color: series4, lineWidth: 1, fillColor: rgbaVar("--series-4", 0.06),
            marker: { enabled: false } } as any);
      }

      chartRef.current?.destroy();
      chartRef.current = Highcharts.stockChart(containerRef.current, {
        chart: {
          backgroundColor: surface,
          animation: false,
          spacing: phone ? [6, 4, 2, 4] : [8, 8, 4, 8],
          style: { fontFamily: "inherit" },
          ...(phone ? { zooming: { type: "x", pinchType: "x" }, panning: { enabled: true, type: "x" } } : {}),
        } as any,
        // market time, not wall-clock time: the whole method (sessions, windows,
        // fills) speaks ET, and the armed chart already does
        time: { timezone: "America/New_York" },
        credits: { enabled: false },
        rangeSelector: view === "panes"
          ? { enabled: true, inputEnabled: false,
              buttons: [{ type: "minute", count: 30, text: "30m" }, { type: "minute", count: 60, text: "1h" },
                        { type: "day", count: 1, text: "1d" }, { type: "all", text: "all" }],
              selected: 3,
              buttonTheme: { fill: "transparent", style: { color: text3 },
                states: { select: { fill: rgbaVar("--accent", 0.15), style: { color: accent } } } } } as any
          : { enabled: false },
        navigator: {
          enabled: !phone, height: 28,
          outlineColor: grid, maskFill: rgbaVar("--text-3", 0.12),
          series: { color: series1, lineWidth: 1 },
          xAxis: { labels: { style: { color: text3 } } },
        },
        scrollbar: { enabled: false },
        xAxis: {
          lineColor: grid, tickColor: grid,
          labels: { style: { color: text3, fontSize: "11px" } },
          crosshair: { color: grid, dashStyle: "Dash" },
          plotBands: sessionBands,
        },
        yAxis: yAxes,
        tooltip: {
          backgroundColor: cssVar("--surface-2"),
          borderColor: cssVar("--border"),
          style: { color: text2, fontSize: phone ? "13px" : "12px" },
          split: false,
          shared: true,
          ...(phone ? { followTouchMove: true, outside: false } : {}),
        },
        legend: { enabled: false },
        plotOptions: {
          // dataGrouping aggregates candles when they'd be subpixel — the old
          // "weird lines when zoomed out" was hundreds of 1px candles
          series: { animation: false, dataGrouping: { enabled: true, groupPixelWidth: 4 } },
          candlestick: { pointPadding: 0.08 },
          hollowcandlestick: { pointPadding: 0.08 } as any,
        },
        series,
      });
    }

    build().catch(() => undefined);

    // closed bars from the server (1m base) — append when the timeframe matches
    const offBar = onBar((msg) => {
      const chart = chartRef.current;
      if (!chart || msg.symbol !== symbol) return;
      if (tf !== "1m") return; // higher TFs rebuilt from quote stream below
      const main = chart.get("main") as Highcharts.Series | undefined;
      if (!main) return;
      const [ts, o, h, l, c, v] = msg.bar;
      if (ts <= lastBarTs.current || !inExtendedSession(ts)) return;
      lastBarTs.current = ts;
      const point = chartType === "line" ? [ts, c] : [ts, o, h, l, c];
      main.addPoint(point as any, false, main.data.length > 600);
      (chart.get("vol") as Highcharts.Series | undefined)?.addPoint([ts, v], false);
      chart.redraw(false);
    });

    // forming bar from the conflated quote stream
    const step = TF_MS[tf] ?? 60_000;
    const unsub = useStore.subscribe((state, prevState) => {
      const q: Quote | undefined = state.quotes[symbol];
      const prevQ: Quote | undefined = prevState.quotes[symbol];
      if (!q || q === prevQ || !chartRef.current) return;
      const chart = chartRef.current;
      const main = chart.get("main") as any;
      if (!main || !main.points || main.points.length === 0) return;
      const bucket = Math.floor(q.ts / step) * step;
      const price = q.last;
      const lastPoint = main.points[main.points.length - 1];
      if (!lastPoint) return;
      if (bucket <= lastPoint.x) {
        if (chartType === "line") lastPoint.update({ y: price }, false);
        else
          lastPoint.update({
            high: Math.max(lastPoint.high, price),
            low: Math.min(lastPoint.low, price),
            close: price,
          }, false);
        chart.redraw(false);
      } else if (bucket > lastPoint.x && bucket > lastBarTs.current && inExtendedSession(q.ts)) {
        lastBarTs.current = bucket;
        const point = chartType === "line" ? [bucket, price] : [bucket, price, price, price, price];
        main.addPoint(point, false, main.data.length > 600);
        chart.redraw(false);
      }
    });

    return () => {
      cancelled = true;
      offBar();
      unsub();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [symbol, tf, range, chartType, indicators.join(","), showVolume, theme, phone,
      view, session, armed?.runId, (armed?.triggers ?? []).length, avgCost?.price, avgCost?.qty]);

  return <div ref={containerRef} style={{ flex: 1, minHeight: phone ? 300 : 320 }} className={phone ? "stock-chart--phone" : undefined} />;
}
