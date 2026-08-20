import Highcharts from "highcharts/esm/highstock.js";

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function seriesPalette(): string[] {
  return [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`));
}

/** Token color with alpha, e.g. rgbaVar("--series-4", 0.06). */
export function rgbaVar(name: string, alpha: number): string {
  const value = cssVar(name);
  try {
    return Highcharts.color(value).setOpacity(alpha).get("rgba") as string;
  } catch {
    return value;
  }
}

/** Shared chart chrome derived from the design tokens (read at call time). */
export function baseChartOptions(): Highcharts.Options {
  const text2 = cssVar("--text-2");
  const text3 = cssVar("--text-3");
  const grid = cssVar("--grid");
  return {
    chart: {
      backgroundColor: cssVar("--surface-1"),
      animation: false,
      style: { fontFamily: "inherit" },
    },
    time: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
    credits: { enabled: false },
    rangeSelector: { enabled: false },
    scrollbar: { enabled: false },
    xAxis: {
      lineColor: grid,
      tickColor: grid,
      labels: { style: { color: text3, fontSize: "11px" } },
    },
    yAxis: {
      gridLineColor: grid,
      labels: { style: { color: text3, fontSize: "11px" } },
    },
    tooltip: {
      backgroundColor: cssVar("--surface-2"),
      borderColor: cssVar("--border"),
      style: { color: text2, fontSize: "12px" },
      split: false,
      shared: true,
    },
    legend: {
      enabled: false,
      itemStyle: { color: text2, fontSize: "12px" },
      itemHoverStyle: { color: cssVar("--text-1") },
    },
    plotOptions: {
      series: { animation: false, marker: { enabled: false } },
    },
  };
}
