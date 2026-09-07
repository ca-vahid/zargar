import { useEffect, useRef } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import "highcharts/esm/indicators/indicators.js";
import "highcharts/esm/modules/accessibility.js";
import { baseChartOptions, cssVar } from "../lib/highchartsTheme";
import { useStore } from "../store";

type Daily = { session: string; open: number; high: number; low: number; close: number; volume: number };
type Levels = { trigger: number; invalidation: number; targets: number[] };

export function CartelPlanChart({ daily, plan }: { daily: Daily[]; plan?: Levels }) {
  const element = useRef<HTMLDivElement>(null);
  const theme = useStore(s => s.settings["ui.theme"]);
  useEffect(() => {
    if (!element.current || !daily.length) return;
    const candles = daily.map(b => [Date.parse(b.session + "T00:00:00Z"), b.open, b.high, b.low, b.close]);
    const levels = plan ? [{value: plan.trigger, name:"Reviewed trigger", color:cssVar("--accent")},
      {value: plan.invalidation, name:"Invalidation", color:cssVar("--down")},
      ...plan.targets.map((value, i) => ({value, name:`Target ${i+1}`, color:cssVar("--up")}))] : [];
    const chart = Highcharts.stockChart(element.current, {
      ...baseChartOptions(),
      chart: {...baseChartOptions().chart, height:420},
      time: {timezone:"UTC"},
      title: {text:undefined},
      navigator: {enabled:false},
      rangeSelector: {enabled:false},
      scrollbar: {enabled:false},
      accessibility: {description:"Saved completed daily candles, volume and 8, 21, 50 EMAs. Reviewed plan levels are reference lines."},
      yAxis: [{height:"72%", min:Math.min(...daily.map(b => b.low), ...levels.map(l => l.value))*.98,
        max:Math.max(...daily.map(b => b.high), ...levels.map(l => l.value))*1.02,
        labels:{align:"right"}, plotLines:levels.map(l => ({
        value:l.value, color:l.color, width:1, dashStyle:"ShortDash", label:{
          text:`${l.name} ${l.value.toFixed(2)}`, align:l.name === "Invalidation" ? "right" : "left",
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
    return () => chart.destroy();
  }, [daily, plan, theme]);
  if (!daily.length) return <p>No completed daily candles available for this record.</p>;
  return <section aria-label="Saved Cartel chart"><h3>Saved daily context</h3>
    <p>Completed bars from this record’s inputs, through {daily[daily.length-1].session}. This chart does not update with live prices. Invalidation is the reviewed pre-entry level; the selected entry rule determines the actual initial stop.</p>
    <div ref={element}/>
  </section>;
}
