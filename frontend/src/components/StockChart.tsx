import { useEffect, useRef } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import "highcharts/esm/indicators/indicators.js"; // registers sma + ema
import "highcharts/esm/indicators/bollinger-bands.js";
import "highcharts/esm/modules/accessibility.js";
import { api } from "../lib/api";
import { cssVar, rgbaVar } from "../lib/highchartsTheme";
import { onBar, watchSymbol } from "../lib/ws";
import { useStore } from "../store";
import type { Quote } from "../types";

export type Indicator = "sma50" | "ema20" | "bb";
export type ChartType = "candlestick" | "ohlc" | "line";

const TF_MS: Record<string, number> = { "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000 };

interface Props {
  symbol: string;
  tf: string;
  chartType: ChartType;
  indicators: Indicator[];
  showVolume: boolean;
}

export function StockChart({ symbol, tf, chartType, indicators, showVolume }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);
  const lastBarTs = useRef<number>(0);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "dark");

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

    async function build() {
      const data = await api.get<{ bars: number[][] }>(
        `/api/chart/${symbol}?tf=${tf}&limit=500`,
      );
      if (cancelled || !containerRef.current) return;
      const ohlc = data.bars.map((b) => [b[0], b[1], b[2], b[3], b[4]]);
      const volume = data.bars.map((b) => [b[0], b[5]]);
      lastBarTs.current = ohlc.length ? ohlc[ohlc.length - 1][0] : 0;

      const yAxes: Highcharts.YAxisOptions[] = [
        {
          labels: { style: { color: text3, fontSize: "11px" } },
          gridLineColor: grid,
          height: showVolume ? "78%" : "100%",
          lineWidth: 0,
          crosshair: { color: grid, dashStyle: "Dash" },
        },
      ];
      if (showVolume) {
        yAxes.push({
          labels: { enabled: false },
          gridLineWidth: 0,
          top: "80%",
          height: "20%",
          offset: 0,
        });
      }

      const mainSeries: Highcharts.SeriesOptionsType =
        chartType === "line"
          ? { type: "line", id: "main", name: symbol, color: series1, lineWidth: 2,
              data: ohlc.map((b) => [b[0], b[4]]) }
          : {
              type: chartType, id: "main", name: symbol, data: ohlc,
              color: down, upColor: up, lineColor: down, upLineColor: up,
              // @ts-ignore — lastPrice is a stock option missing from some type versions
              lastPrice: { enabled: true, color: text3, label: { enabled: false } },
            };

      const series: Highcharts.SeriesOptionsType[] = [mainSeries];
      if (showVolume) {
        series.push({
          type: "column", id: "vol", name: "Volume", data: volume, yAxis: 1,
          color: grid, borderWidth: 0,
          tooltip: { valueDecimals: 0 },
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
          spacing: [8, 8, 4, 8],
          style: { fontFamily: "inherit" },
        },
        time: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
        credits: { enabled: false },
        rangeSelector: { enabled: false },
        navigator: {
          enabled: true, height: 28,
          outlineColor: grid, maskFill: rgbaVar("--text-3", 0.12),
          series: { color: series1, lineWidth: 1 },
          xAxis: { labels: { style: { color: text3 } } },
        },
        scrollbar: { enabled: false },
        xAxis: {
          lineColor: grid, tickColor: grid,
          labels: { style: { color: text3, fontSize: "11px" } },
          crosshair: { color: grid, dashStyle: "Dash" },
        },
        yAxis: yAxes,
        tooltip: {
          backgroundColor: cssVar("--surface-2"),
          borderColor: cssVar("--border"),
          style: { color: text2, fontSize: "12px" },
          split: false,
          shared: true,
        },
        legend: { enabled: false },
        plotOptions: {
          series: { animation: false, dataGrouping: { enabled: false } },
          candlestick: { pointPadding: 0.08 },
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
      if (ts <= lastBarTs.current) return;
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
      } else if (bucket > lastPoint.x && bucket > lastBarTs.current) {
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
  }, [symbol, tf, chartType, indicators.join(","), showVolume, theme]);

  return <div ref={containerRef} style={{ flex: 1, minHeight: 320 }} />;
}
