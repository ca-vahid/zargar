import { useEffect, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { api } from "../lib/api";
import { fmtSigned, fmtUsd } from "../lib/format";
import { positionsFor, useStore } from "../store";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const KIND_LABEL: Record<string, string> = {
  live: "Live", paper: "Paper", sim: "Simulation", shadow: "Shadow",
};

export function PortfoliosPage() {
  const portfolios = useStore((s) => s.portfolios);
  const state = useStore();
  const theme = useStore((s) => s.settings["ui.theme"]);
  const chartRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    async function build() {
      if (!chartRef.current) return;
      const shown = portfolios.filter((p) => visible[p.id] !== false);
      const seriesData = await Promise.all(
        shown.map(async (p) => ({
          portfolio: p,
          points: await api.get<[number, number][]>(`/api/portfolios/${p.id}/equity?limit=2000`),
        })),
      );
      if (cancelled || !chartRef.current) return;
      const palette = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`));
      Highcharts.stockChart(chartRef.current, {
        chart: { backgroundColor: cssVar("--surface-1"), animation: false, height: 320,
          style: { fontFamily: "inherit" } },
        time: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
        credits: { enabled: false },
        rangeSelector: { enabled: false },
        navigator: { enabled: false },
        scrollbar: { enabled: false },
        legend: {
          enabled: true, itemStyle: { color: cssVar("--text-2"), fontSize: "12px" },
          itemHoverStyle: { color: cssVar("--text-1") },
        },
        xAxis: { lineColor: cssVar("--grid"), tickColor: cssVar("--grid"),
          labels: { style: { color: cssVar("--text-3") } } },
        yAxis: { gridLineColor: cssVar("--grid"),
          labels: { style: { color: cssVar("--text-3") }, format: "${value:,.0f}" } },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border"),
          style: { color: cssVar("--text-2") }, shared: true, split: false,
          valueDecimals: 2, valuePrefix: "$",
        },
        plotOptions: { series: { animation: false, marker: { enabled: false }, lineWidth: 2 } },
        series: seriesData.map((s, i) => ({
          type: "line" as const,
          name: s.portfolio.name,
          color: palette[i % palette.length],
          data: s.points,
        })),
      });
    }
    build().catch(() => undefined);
    return () => { cancelled = true; };
  }, [portfolios.map((p) => p.id).join(","), JSON.stringify(visible), theme]);

  return (
    <div>
      <h2 className="page-title">Portfolios</h2>
      <div className="settings-grid mb">
        {portfolios.map((p) => {
          const positions = positionsFor(state, p.id);
          const equity = p.equity ?? p.cash;
          const pnl = equity - p.startingCash;
          return (
            <div key={p.id} className="panel">
              <div className="panel-head">
                {p.name}
                <span className={`status-pill ${p.kind === "live" ? "bad" : p.kind === "shadow" ? "dim" : "ok"}`}>
                  {KIND_LABEL[p.kind] ?? p.kind}
                </span>
                <label className="switch" style={{ marginLeft: "auto" }}
                  title="Show on equity chart">
                  <input type="checkbox" checked={visible[p.id] !== false}
                    onChange={(e) => setVisible({ ...visible, [p.id]: e.target.checked })} />
                  <span className="track" />
                </label>
              </div>
              <div className="panel-body">
                <div style={{ fontSize: 22, fontWeight: 700 }}>{fmtUsd(equity)}</div>
                <div className={pnl >= 0 ? "pos" : "neg"} style={{ fontSize: 13 }}>
                  {fmtSigned(pnl)} since start
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  cash {fmtUsd(p.cash)} · {positions.length} position{positions.length === 1 ? "" : "s"}
                  {p.sourceName && <> · tracks “{p.sourceName}”</>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="panel">
        <div className="panel-head">
          Equity curves <span className="sub">live vs simulation vs shadow — the “what would have happened” view</span>
        </div>
        <div ref={chartRef} />
      </div>
    </div>
  );
}
