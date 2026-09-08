import { useEffect, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import "highcharts/esm/indicators/indicators.js";
import "highcharts/esm/modules/accessibility.js";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { useStore } from "../store";

type Daily = { session: string; open: number; high: number; low: number; close: number; volume: number };
type Levels = { trigger: number; invalidation: number; targets: number[] };

export function CartelPlanChart({ daily, plan }: { daily: Daily[]; plan?: Levels }) {
  const element = useRef<HTMLDivElement>(null);
  const [windowSize, setWindowSize] = useState(30);
  const theme = useStore(s => s.settings["ui.theme"]);
  useEffect(() => {
    if (!element.current || !daily.length) return;
    const host = element.current;
    const visible = windowSize ? daily.slice(-windowSize) : daily;
    const candles = daily.map(b => [Date.parse(b.session + "T00:00:00Z"), b.open, b.high, b.low, b.close]);
    const levels = plan ? [{value: plan.trigger, name:"Reviewed trigger", color:cssVar("--accent")},
      {value: plan.invalidation, name:"Invalidation", color:cssVar("--down")},
      ...plan.targets.map((value, i) => ({value, name:`Target ${i+1}`, color:cssVar("--up")}))] : [];
    const chart = Highcharts.stockChart(host, {
      ...baseChartOptions(),
      chart: {...baseChartOptions().chart, height:420},
      time: {timezone:"UTC"},
      title: {text:undefined},
      navigator: {enabled:false},
      rangeSelector: {enabled:false},
      scrollbar: {enabled:false},
      accessibility: {description:"Saved completed daily candles, volume and 8, 21, 50 EMAs. Reviewed plan levels are reference lines."},
      xAxis: {...baseChartOptions().xAxis, min: Date.parse(visible[0].session+"T00:00:00Z")},
      yAxis: [{height:"72%", min:Math.min(...visible.map(b => b.low), ...levels.map(l => l.value))*.98,
        max:Math.max(...visible.map(b => b.high), ...levels.map(l => l.value))*1.02,
        labels:{align:"right"}, plotLines:levels.map(l => ({
        value:l.value, color:l.color, width:1, dashStyle:"ShortDash", label:{
          text:l.name.startsWith("Target") ? undefined : `${l.name} ${l.value.toFixed(2)}`, align:l.name === "Invalidation" ? "right" : "left",
          y:l.name === "Invalidation" ? 16 : -4,
          x:l.name === "Invalidation" ? -5 : 10, style:{color:l.color}}}))},
        {top:"78%", height:"22%", offset:0, title:{text:"Volume"}}],
      series: [
        {type:"candlestick", id:"cartel-saved-price", name:"Saved daily price", data:candles,
          color:cssVar("--down"), upColor:cssVar("--up"), dataGrouping:{enabled:false}},
        ...[8,21,50].map((period, i) => ({type:"ema" as const, name:`EMA ${period}`, linkedTo:"cartel-saved-price",
          params:{period}, color:cssVar(`--series-${i+1}`), lineWidth:1, dataGrouping:{enabled:false}})),
        {type:"column", name:"Volume", yAxis:1, data:daily.map(b => [Date.parse(b.session+"T00:00:00Z"), b.volume]),
          color:cssVar("--text-3"), dataGrouping:{enabled:false}}
      ]
    });
    return () => { chart.destroy(); host.replaceChildren(); };
  }, [daily, plan, theme, windowSize]);
  if (!daily.length) return <p>No completed daily candles available for this record.</p>;
  return <section aria-label="Saved Cartel chart">
    <div className="cartel-row"><h3>Saved daily context</h3><div className="cartel-actions" role="group" aria-label="Chart window">
      {[30,60,0].map(n => <button className="ghost-btn" key={n} aria-pressed={windowSize === n} onClick={() => setWindowSize(n)}>{n ? `${n} sessions` : "All saved sessions"}</button>)}
    </div></div>
    <p>Showing {windowSize ? Math.min(windowSize, daily.length) : daily.length} of {daily.length} saved sessions, through {daily[daily.length-1].session}. This chart does not update with live prices. Invalidation is the reviewed pre-entry level; the selected entry rule determines the actual initial stop.</p>
    {plan && <p className="muted">Reference targets: {plan.targets.map((n,i) => `T${i+1} ${n.toFixed(2)}`).join(" · ")}</p>}
    <div ref={element} className="cartel-chart-host"/>
  </section>;
}
