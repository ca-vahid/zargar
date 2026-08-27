import Highcharts from "highcharts/esm/highstock.js";

/**
 * Phone gestures for Highstock charts (verified against Highcharts 12.6 Pointer.js).
 *
 * - `tooltip.followTouchMove` must be OFF: with it on, a single finger drives the
 *   crosshair and Highcharts explicitly never pans (`pointer.initiated = false`);
 *   with it off a one-finger drag fires `touchpan` → `chart.transform` (a real pan),
 *   two fingers pinch-zoom, and a tap still shows the tooltip.
 * - `touch-action: pan-y` on the container leaves vertical scrolling to the browser,
 *   so a chart that sits in a scrolling page never traps the finger. Highcharts only
 *   `preventDefault()`s once a pinch has "initiated" the pointer; we clear that flag at
 *   the end of every gesture so one pinch doesn't leave the chart swallowing vertical
 *   drags for the rest of the session.
 * - The readout is pinned to the top-left corner — a finger covers what it points at.
 */
export function phoneChartOptions(): { chart: Highcharts.ChartOptions; tooltip: Highcharts.TooltipOptions } {
  return {
    chart: {
      zooming: { type: "x", pinchType: "x", singleTouch: false },
      panning: { enabled: true, type: "x" },
      style: { fontFamily: "inherit", "touch-action": "pan-y" } as Highcharts.CSSObject,
    },
    tooltip: {
      followTouchMove: false,
      outside: false,
      shadow: false,
      positioner() {
        const c = (this as unknown as { chart: Highcharts.Chart }).chart;
        return { x: c.plotLeft + 4, y: c.plotTop + 4 };
      },
    },
  };
}

export interface PhoneTouch {
  /** show the last `bars` bars (default: sized to the plot width) and follow the live edge again */
  fit(bars?: number): void;
  /** call after appending a point at `ts` (before the redraw): keeps the live edge in view unless the user panned away */
  onAppend(ts: number): void;
  detach(): void;
}

/** Window + live-edge policy for a phone chart: open on the last screenful of bars,
 * keep following new bars until the user pans/zooms away from the right edge,
 * double-tap to fit again. */
export function attachPhoneTouch(chart: Highcharts.Chart, barMs: number): PhoneTouch {
  const axis = chart.xAxis[0];
  (chart.container.parentElement as unknown as { __zargarChart?: Highcharts.Chart } | null)!.__zargarChart = chart; // audit/Playwright handle
  let follow = true;
  let lastTap = 0;
  let down: { x: number; y: number } | null = null;
  // Highcharts 12 keeps series data in a DataTable: `series.xData` is gone, read the x column
  const xs = (): number[] => {
    const main = chart.get("main") as unknown as { getColumn?: (id: string) => ArrayLike<number> } | undefined;
    return main?.getColumn ? Array.from(main.getColumn("x")) : [];
  };

  const fit = (bars?: number) => {
    const data = xs();
    const n = data.length;
    if (!n) return;
    const k = bars ?? Math.max(40, Math.min(240, Math.round(chart.plotWidth / 7)));
    axis.setExtremes(data[Math.max(0, n - k)], data[n - 1], true, false);
    follow = true;
  };

  const unbind = [
    // our own setExtremes calls carry no trigger; every gesture does (touchmove, pan, zoom, rangeSelectorButton…)
    Highcharts.addEvent(axis, "afterSetExtremes", (e: { trigger?: string; max: number }) => {
      if (!e.trigger) return;
      const data = xs();
      const last = data[data.length - 1];
      follow = last === undefined || e.max >= last - barMs / 2;
    }),
    Highcharts.addEvent(chart.container, "touchstart", (e: TouchEvent) => {
      const t = e.touches[0];
      down = e.touches.length === 1 && t ? { x: t.clientX, y: t.clientY } : null;
    }),
    Highcharts.addEvent(chart.container, "touchend", (e: TouchEvent) => {
      const pointer = chart.pointer as unknown as { initiated?: boolean } | undefined;
      if (pointer) pointer.initiated = false;
      if (e.touches.length) return;
      const t = e.changedTouches[0];
      const moved = !down || !t || Math.hypot(t.clientX - down.x, t.clientY - down.y) > 12;
      const now = Date.now();
      if (!moved && now - lastTap < 320) { fit(); lastTap = 0; } else lastTap = moved ? 0 : now;
    }),
  ];

  return {
    fit,
    onAppend(ts) {
      if (!follow) return;
      const { min, max } = axis;
      if (min == null || max == null || ts <= max) return;
      axis.setExtremes(ts - (max - min), ts, false);
    },
    detach: () => unbind.forEach((u) => u()),
  };
}
