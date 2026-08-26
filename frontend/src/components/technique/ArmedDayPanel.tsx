import { useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import "highcharts/esm/modules/accessibility.js";
import "highcharts/esm/modules/hollowcandlestick.js";
import { api } from "../../lib/api";
import { cssVar, rgbaVar } from "../../lib/highchartsTheme";
import { onBar, watchSymbol } from "../../lib/ws";
import { useStore } from "../../store";
import type { ArmedPlan, Quote } from "../../types";

function fmt(n: number | null | undefined, d = 2) { return n === null || n === undefined ? "—" : Number(n).toFixed(d); }

const ET_FMT = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
function etTime(ts: number) { return ET_FMT.format(ts) + " ET"; }

/** UTC ms for h:m ET on the given YYYY-MM-DD, DST-safe (tries both offsets). */
function etToUtcMs(dateStr: string, h: number, m: number): number {
  const hh = String(h).padStart(2, "0"), mm = String(m).padStart(2, "0");
  for (const off of ["-04:00", "-05:00"]) {
    const t = new Date(`${dateStr}T${hh}:${mm}:00${off}`).getTime();
    if (ET_FMT.format(t) === `${hh}:${mm}`) return t;
  }
  return new Date(`${dateStr}T${hh}:${mm}:00-04:00`).getTime();
}

/** One timeline row; consecutive observed_midday events are grouped. */
interface TimelineRow { ts: number; tsEnd?: number; icon: string; cls: string; text: string; n?: number }

const EVENT_ICON: Record<string, [string, string]> = {
  restored: ["⚡", "muted"], armed: ["⚡", "muted"], skipped: ["⛔", "warn"],
  observed_midday: ["👁", "muted"], fired: ["▲", "pos"], entry: ["▲", "pos"],
  exit: ["▼", "neg"], flatten: ["▼", "neg"], paused: ["⏸", "muted"], resumed: ["▶", "muted"],
  error: ["✖", "neg"], critic_killed: ["✖", "warn"], expired: ["·", "muted"],
};

function buildTimeline(a: ArmedPlan): TimelineRow[] {
  const rows: TimelineRow[] = [];
  for (const e of a.events ?? []) {
    const [icon, cls] = EVENT_ICON[e.event] ?? ["·", "muted"];
    let text: string = e.text || e.event;
    if (e.event === "skipped") text = `break attempt refused — ${String(e.text).replace(/^k?\w*:\s*/, "")}${e.close ? ` (close ${fmt(e.close)})` : ""}`;
    if (e.event === "observed_midday") text = `touched the level — mid-day is watch-only (R6.3)${e.close ? ` (close ${fmt(e.close)})` : ""}`;
    if (e.event === "restored") text = `armed and watching (${e.text})`;
    const prev = rows[rows.length - 1];
    if (e.event === "observed_midday" && prev && prev.icon === "👁") {
      prev.n = (prev.n ?? 1) + 1;
      prev.tsEnd = e.ts;
      prev.text = `touched the level ${prev.n}× — mid-day is watch-only (R6.3)`;
      continue;
    }
    rows.push({ ts: e.ts, icon, cls, text });
  }
  return rows;
}

/** What each still-waiting trigger needs before it can fire, in one sentence. */
function waitingFor(t: any, windowNow: string | null | undefined): string {
  const inPrime = windowNow === "prime_open" || windowNow === "prime_close";
  const windowBit = inPrime ? "" : windowNow === "midday"
    ? " — mid-day is watch-only, next chance 14:45–16:00 ET"
    : windowNow === "extended" ? " — market closed" : "";
  if (t.kind === "bounce") return `waiting for price to trade down into ${fmt(t.entry)} on adequate volume${windowBit}`;
  if (t.kind === "reject") return `waiting for price to trade UP into ${fmt(t.entry)} on adequate volume — short via a put${windowBit}`;
  if (t.kind === "breakdown") return `waiting for a 1m bar to CLOSE below ${fmt(t.entry)} with a volume surge, a decisive bearish candle and follow-through — short via a put${windowBit}`;
  return `waiting for a 1m bar to CLOSE above ${fmt(t.entry)} with a real volume surge, a decisive candle, then hold${windowBit}`;
}

/** The day view for one armed plan: live 1m chart with the trigger levels,
 * prime-window shading and event markers, plus a plain-language timeline of
 * what happened, what was refused and why, and what we're still waiting for. */
type ChartStyle = "classic" | "zones" | "panes";

export function ArmedDayPanel({ a }: { a: ArmedPlan }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Highcharts.Chart | null>(null);
  const lastBarTs = useRef<number>(0);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const [style, setStyleRaw] = useState<ChartStyle>(() => {
    try { return (localStorage.getItem("zargar_armed_chartstyle") as ChartStyle) || "classic"; }
    catch { return "classic"; }
  });
  const setStyle = (v: ChartStyle) => {
    setStyleRaw(v);
    try { localStorage.setItem("zargar_armed_chartstyle", v); } catch { /* private mode */ }
  };
  const timeline = useMemo(() => buildTimeline(a), [a.events]);
  const waiting = (a.triggers ?? []).filter((t: any) => t.status === "waiting" || t.status === "observed");

  useEffect(() => {
    let cancelled = false;
    watchSymbol(a.symbol);
    const up = cssVar("--up") || "#0ca30c";
    const down = cssVar("--down") || "#d03b3b";
    const warn = cssVar("--warn") || "#c88a1f";
    const accent = cssVar("--accent") || "#5b8cff";
    const text3 = cssVar("--text-3");
    const grid = cssVar("--grid");
    const surface = cssVar("--surface-1");

    const dayStart = etToUtcMs(a.planFor, 9, 25);
    const dayEnd = etToUtcMs(a.planFor, 16, 5);
    const bands = [
      { from: etToUtcMs(a.planFor, 9, 30), to: etToUtcMs(a.planFor, 10, 30), color: rgbaVar("--up", 0.12),
        label: { text: "● prime open — can fire", style: { color: up, fontSize: "10px", fontWeight: "700" } } },
      { from: etToUtcMs(a.planFor, 10, 30), to: etToUtcMs(a.planFor, 14, 45), color: rgbaVar("--warn", 0.10),
        label: { text: "⏸ mid-day — watch only (R6.3)", style: { color: warn, fontSize: "10px", fontWeight: "600" } } },
      { from: etToUtcMs(a.planFor, 14, 45), to: etToUtcMs(a.planFor, 16, 0), color: rgbaVar("--up", 0.12),
        label: { text: "● prime close — can fire", style: { color: up, fontSize: "10px", fontWeight: "700" } } },
    ];

    const plotLines: Highcharts.YAxisPlotLinesOptions[] = [];
    const priceBands: Highcharts.YAxisPlotBandsOptions[] = [];
    for (const t of a.triggers ?? []) {
      if (style === "zones") {
        // the method thinks in zones: risk and first-reward become bands
        priceBands.push({ from: Math.min(t.entry, t.stop), to: Math.max(t.entry, t.stop),
          color: rgbaVar("--down", 0.09),
          label: { text: `${t.id} risk ${fmt(t.stop)} to ${fmt(t.entry)}`, align: "left",
            style: { color: down, fontSize: "9px" } } });
        if (t.targets?.length) {
          priceBands.push({ from: t.entry, to: t.targets[0], color: rgbaVar("--up", 0.08),
            label: { text: `first reward to ${fmt(t.targets[0])}`, align: "left",
              style: { color: up, fontSize: "9px" } } });
        }
        plotLines.push({ value: t.entry, color: accent, width: 1.2, zIndex: 4,
          label: { text: `${t.id} fires ${fmt(t.entry)}`, align: "right", style: { color: accent, fontSize: "10px", fontWeight: "600" } } });
        for (const [i, tp] of (t.targets ?? []).entries())
          plotLines.push({ value: tp, color: up, width: 0, zIndex: 3,
            label: { text: `TP${i + 1} ${fmt(tp)}`, align: "right", style: { color: up, fontSize: "9px" } } });
      } else if (style === "classic") {
        // edge labels, not full-width dashed lines: the old lines were the
        // "weird zoomed-out smear"
        plotLines.push({ value: t.entry, color: rgbaVar("--accent", 0.5), width: 1.2, zIndex: 4,
          label: { text: `${t.id} fires ${fmt(t.entry)}`, align: "right", style: { color: accent, fontSize: "10px", fontWeight: "600" } } });
        plotLines.push({ value: t.stop, color: rgbaVar("--down", 0.0), width: 0, zIndex: 4,
          label: { text: `stop ${fmt(t.stop)}`, align: "right", style: { color: down, fontSize: "9px", fontWeight: "600" } } });
        for (const [i, tp] of (t.targets ?? []).entries())
          plotLines.push({ value: tp, color: rgbaVar("--up", 0.0), width: 0, zIndex: 3,
            label: { text: `TP${i + 1} ${fmt(tp)}`, align: "right", style: { color: up, fontSize: "9px" } } });
      } else {
        plotLines.push({ value: t.entry, color: accent, width: 1.2, zIndex: 4,
          label: { text: `${t.id} fires ${fmt(t.entry)}`, align: "left", style: { color: accent, fontSize: "10px", fontWeight: "600" } } });
        plotLines.push({ value: t.stop, color: down, width: 1, dashStyle: "Dash", zIndex: 4,
          label: { text: `stop ${fmt(t.stop)}`, align: "left", style: { color: down, fontSize: "9px" } } });
        for (const [i, tp] of (t.targets ?? []).entries())
          plotLines.push({ value: tp, color: up, width: 1, dashStyle: "Dot", zIndex: 3,
            label: { text: `TP${i + 1} ${fmt(tp)}`, align: "right", style: { color: up, fontSize: "9px" } } });
      }
    }

    const markerFor = (e: any) => {
      if (e.event === "skipped") return { symbol: "triangle-down", fillColor: warn, radius: 6 };
      if (e.event === "observed_midday") return { symbol: "circle", fillColor: text3, radius: 3.5 };
      if (e.event === "fired" || e.event === "entry") return { symbol: "triangle", fillColor: up, radius: 7 };
      if (e.event === "exit" || e.event === "flatten") return { symbol: "square", fillColor: down, radius: 6 };
      return { symbol: "diamond", fillColor: text3, radius: 4 };
    };
    const eventPoints = (a.events ?? [])
      .filter((e: any) => e.close && e.ts >= dayStart && e.ts <= dayEnd)
      .map((e: any) => ({ x: e.ts, y: e.close, marker: markerFor(e),
        custom: { what: e.event === "skipped" ? `refused: ${e.text}` : e.event === "observed_midday" ? "touched (watch-only, R6.3)" : e.text } }));

    async function build() {
      const data = await api.get<{ bars: number[][] }>(`/api/chart/${a.symbol}?tf=1m&range=1d&limit=500`);
      if (cancelled || !containerRef.current) return;
      const inDay = data.bars.filter((b) => b[0] >= dayStart && b[0] <= dayEnd);
      const ohlc = inDay.map((b) => [b[0], b[1], b[2], b[3], b[4]]);
      // volume colored by bar direction; it was painted in the hairline grid
      // color before, i.e. invisible
      const volume = inDay.map((b) => ({ x: b[0], y: b[5],
        color: b[4] >= b[1] ? rgbaVar("--up", 0.45) : rgbaVar("--down", 0.45) }));
      // live trade-R pane (panes style): underlying R since the first fire
      const trade = (a.trades ?? []).find((t: any) => t.firedTs && t.entry && t.stop);
      const risk = trade ? Math.abs(trade.entry - trade.stop) : 0;
      const rSeries = style === "panes" && trade && risk > 0
        ? inDay.filter((b) => b[0] >= (trade.firedTs as number))
            .map((b) => ({ x: b[0], y: (b[4] - trade.entry) / risk,
              color: b[4] >= trade.entry ? rgbaVar("--up", 0.6) : rgbaVar("--down", 0.6) }))
        : [];
      lastBarTs.current = ohlc.length ? ohlc[ohlc.length - 1][0] : 0;
      chartRef.current?.destroy();
      chartRef.current = Highcharts.stockChart(containerRef.current, {
        chart: { backgroundColor: surface, animation: false, spacing: [8, 8, 4, 8],
          height: style === "panes" ? 400 : 340, style: { fontFamily: "inherit" } },
        time: { timezone: "America/New_York" },
        credits: { enabled: false },
        rangeSelector: style === "panes"
          ? { enabled: true, inputEnabled: false,
              buttons: [{ type: "minute", count: 30, text: "30m" }, { type: "minute", count: 60, text: "1h" },
                        { type: "all", text: "day" }], selected: 2,
              buttonTheme: { fill: "transparent", style: { color: text3 },
                states: { select: { fill: rgbaVar("--accent", 0.15), style: { color: accent } } } } } as any
          : { enabled: false },
        navigator: { enabled: false }, scrollbar: { enabled: false },
        xAxis: { lineColor: grid, tickColor: grid, min: dayStart, max: dayEnd, ordinal: false,
          labels: { style: { color: text3, fontSize: "10px" } }, plotBands: bands as any,
          crosshair: { color: grid, dashStyle: "Dash" } },
        yAxis: style === "panes" ? [
          { labels: { style: { color: text3, fontSize: "10px" } }, gridLineColor: grid, height: "58%", lineWidth: 0, plotLines },
          { labels: { enabled: false }, gridLineWidth: 0, top: "60%", height: "16%", offset: 0 },
          { labels: { style: { color: text3, fontSize: "9px" }, format: "{value}R" }, gridLineColor: grid,
            top: "78%", height: "22%", offset: 0,
            plotLines: [{ value: 0, color: grid, width: 1 }] },
        ] : [
          { labels: { style: { color: text3, fontSize: "10px" } }, gridLineColor: grid, height: "80%", lineWidth: 0,
            plotLines, plotBands: priceBands },
          { labels: { enabled: false }, gridLineWidth: 0, top: "82%", height: "18%", offset: 0 },
        ],
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border"),
          style: { color: cssVar("--text-2"), fontSize: "12px" }, split: false, shared: false,
          hideDelay: 120,
          // quiet hover: only the event markers speak; candles/volume just get the crosshair
          formatter(this: any) {
            const p = this.point ?? this;
            if (p?.series?.options?.id !== "ev") return false;
            return `<b>${etTime(p.x)}</b><br/>${p.custom?.what ?? ""}`;
          },
        },
        legend: { enabled: false },
        plotOptions: {
          series: { animation: false,
            // dataGrouping keeps zoomed-out candles readable instead of a smear
            dataGrouping: { enabled: true, groupPixelWidth: 4 },
            states: { inactive: { opacity: 1 } } },
          candlestick: { pointPadding: 0.12, maxPointWidth: 7 },
          hollowcandlestick: { pointPadding: 0.12, maxPointWidth: 7 } as any,
        },
        series: [
          { type: style === "classic" ? "hollowcandlestick" : "candlestick", id: "main", name: a.symbol, data: ohlc,
            color: down, upColor: up, lineColor: down, upLineColor: up } as any,
          { type: "column", id: "vol", name: "Volume", data: volume, yAxis: 1, borderWidth: 0,
            dataGrouping: { enabled: true, approximation: "sum" },
            enableMouseTracking: false } as any,
          ...(style === "panes" ? [{ type: "column", id: "r", name: "Trade R", data: rSeries, yAxis: 2,
            borderWidth: 0, enableMouseTracking: false } as any] : []),
          { type: "scatter", id: "ev", name: "events", data: eventPoints, zIndex: 6,
            dataGrouping: { enabled: false },
            marker: { enabled: true }, states: { hover: { enabled: true } } } as any,
        ],
      });
    }
    build().catch(() => undefined);

    const offBar = onBar((msg) => {
      const chart = chartRef.current;
      if (!chart || msg.symbol !== a.symbol) return;
      const [ts, o, h, l, c, v] = msg.bar;
      if (ts <= lastBarTs.current || ts < dayStart || ts > dayEnd) return;
      lastBarTs.current = ts;
      (chart.get("main") as Highcharts.Series | undefined)?.addPoint([ts, o, h, l, c] as any, false);
      (chart.get("vol") as Highcharts.Series | undefined)?.addPoint([ts, v], false);
      chart.redraw(false);
    });
    const unsub = useStore.subscribe((state, prevState) => {
      const q: Quote | undefined = state.quotes[a.symbol];
      if (!q || q === prevState.quotes[a.symbol] || !chartRef.current) return;
      const main = chartRef.current.get("main") as any;
      if (!main?.points?.length) return;
      const bucket = Math.floor(q.ts / 60_000) * 60_000;
      const lastPoint = main.points[main.points.length - 1];
      if (bucket <= lastPoint.x) {
        lastPoint.update({ high: Math.max(lastPoint.high, q.last), low: Math.min(lastPoint.low, q.last), close: q.last }, false);
        chartRef.current.redraw(false);
      } else if (bucket > lastBarTs.current && bucket >= dayStart && bucket <= dayEnd) {
        lastBarTs.current = bucket;
        main.addPoint([bucket, q.last, q.last, q.last, q.last], false);
        chartRef.current.redraw(false);
      }
    });
    return () => { cancelled = true; offBar(); unsub(); chartRef.current?.destroy(); chartRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a.symbol, a.planFor, a.events?.length, a.triggers?.length, theme, style]);

  return (
    <div className="tq-armed-day">
      <div className="tq-armed-day-now">
        <b>Now:</b>{" "}
        {waiting.length
          ? waiting.map((t: any) => <span key={t.id}><span className="tq-chip">{t.id}</span> {waitingFor(t, a.sessionWindowNow)}{t.distancePct !== undefined ? ` · ${t.distancePct > 0 ? "+" : ""}${t.distancePct.toFixed(2)}% away` : ""}. </span>)
          : <span>{a.summary}</span>}
      </div>
      <div className="tq-chartstyle seg" role="group" aria-label="Chart style">
        <button className={style === "classic" ? "on" : ""} title="Hollow candles, slim direction-colored volume, level labels at the right edge"
          onClick={() => setStyle("classic")}>candles</button>
        <button className={style === "zones" ? "on" : ""} title="Risk and reward as translucent bands, the way the plan thinks"
          onClick={() => setStyle("zones")}>zones</button>
        <button className={style === "panes" ? "on" : ""} title="Price / volume / trade-R panes with 30m, 1h and day range buttons"
          onClick={() => setStyle("panes")}>panes</button>
      </div>
      <div ref={containerRef} className="tq-armed-day-chart" />
      <div className="tq-armed-day-tl">
        <div className="tq-label">Today, in order <span className="muted">— every decision, including the ones NOT taken</span></div>
        {timeline.length === 0 && <div className="muted small">Nothing yet — the plan is watching. Touches, refused break attempts, fires and exits will appear here as they happen.</div>}
        <ul>
          {timeline.map((r, i) => (
            <li key={i} className={r.cls}>
              <span className="muted tq-armed-day-t">{etTime(r.ts)}{r.tsEnd ? `–${ET_FMT.format(r.tsEnd)}` : ""}</span>
              <span className="tq-armed-day-ic">{r.icon}</span>
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
