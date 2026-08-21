/** The chosen live-quote design system (mock F): day sparkline, delta pill,
 * arrow-pulse tick indicator. Used across sidebar, blotter, tables, headers. */
import { memo, useRef } from "react";
import { fmtMoney } from "../lib/format";
import { usePrevLast, useQuote, useStore } from "../store";

/** Day-shaped mini chart: no axes, no labels, tinted by day direction. */
export const Sparkline = memo(function Sparkline({
  closes,
  live,
  open,
  height = 22,
}: {
  closes: number[];
  live?: number | null;
  open: number | null;
  height?: number;
}) {
  const series = live && live > 0 ? [...closes, live] : closes;
  if (series.length < 2 || open === null) return <span className="spark spark--empty" />;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = Math.max(max - min, open * 0.0005);
  const n = series.length;
  const pts = series
    .map((v, k) => {
      const x = (k / (n - 1)) * 100;
      const y = height - 2 - ((v - min) / span) * (height - 4);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const dir = series[n - 1] >= open ? "up" : "down";
  return (
    <svg className="spark" viewBox={`0 0 100 ${height}`} preserveAspectRatio="none"
      aria-hidden="true">
      <polyline points={pts} stroke={dir === "up" ? "var(--up)" : "var(--down)"}
        vectorEffect="non-scaling-stroke" />
    </svg>
  );
});

/** Day change vs session open — click anywhere toggles % ↔ $ globally. */
export function DeltaPill({
  price,
  open,
  size = "sm",
  interactive = true,
}: {
  price: number | null | undefined;
  open: number | null;
  size?: "sm" | "md";
  interactive?: boolean;
}) {
  const chgDollar = useStore((s) => s.chgDollar);
  const toggleChgMode = useStore((s) => s.toggleChgMode);
  if (!price || price <= 0 || !open || open <= 0) {
    return <span className={`delta-pill delta-pill--${size} dim`}>—</span>;
  }
  const abs = price - open;
  const pct = (abs / open) * 100;
  const up = abs >= 0;
  const sign = up ? "+" : "−";
  const text = chgDollar
    ? `${sign}$${Math.abs(abs).toFixed(2)}`
    : `${sign}${Math.abs(pct).toFixed(2)}%`;
  return (
    <button
      className={`delta-pill delta-pill--${size} ${up ? "up" : "down"}`}
      onClick={interactive ? (e) => { e.stopPropagation(); toggleChgMode(); } : undefined}
      title="Today vs session open — click to switch % / $"
      tabIndex={interactive ? 0 : -1}
    >
      <span className="a">{up ? "▲" : "▼"}</span>{text}
    </button>
  );
}

/** Static pill for non-day values (e.g. unrealized P&L%): same look, no toggle. */
export function ValuePill({ value, text, size = "sm" }: {
  value: number; text: string; size?: "sm" | "md";
}) {
  return (
    <span className={`delta-pill delta-pill--${size} ${value >= 0 ? "up" : "down"}`}>
      <span className="a">{value >= 0 ? "▲" : "▼"}</span>{text}
    </span>
  );
}

/** Resting arrow beside a price that pulses bright in each tick's direction. */
export const TickArrow = memo(function TickArrow({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const prev = usePrevLast(symbol);
  const lastDir = useRef<"up" | "down">("up");
  if (quote && prev !== undefined) {
    if (quote.last > prev) lastDir.current = "up";
    else if (quote.last < prev) lastDir.current = "down";
  }
  const ticked = quote && prev !== undefined && quote.last !== prev;
  return (
    <span
      key={ticked ? quote?.ts ?? 0 : 0}
      className={`tick-arrow ${lastDir.current} ${ticked ? "tick" : ""}`}
      aria-hidden="true"
    />
  );
});

/** Small live price with the tick arrow — the standard "price cell". */
export function LivePrice({ symbol, fallback }: { symbol: string; fallback?: number }) {
  const quote = useQuote(symbol);
  const last = quote?.last && quote.last > 0 ? quote.last : fallback;
  return (
    <span className="price-live">
      <TickArrow symbol={symbol} />
      <span>{last ? fmtMoney(last) : "…"}</span>
    </span>
  );
}
