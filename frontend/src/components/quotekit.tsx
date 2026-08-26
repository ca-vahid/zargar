/** The chosen live-quote design system (mock F): day sparkline, delta pill,
 * arrow-pulse tick indicator. Used across sidebar, blotter, tables, headers. */
import { memo, useEffect, useRef } from "react";
import { fmtMoney } from "../lib/format";
import { usePrevLast, useQuote, useStore } from "../store";
import type { Quote } from "../types";
import { useViewport } from "../lib/viewport";

export interface DayChange {
  abs: number;
  pct: number;
  basis: number;   // previous close (or today's open when the feed has no prev close)
  price: number;   // the price the change is measured at (regular-session price)
  ext: { abs: number; pct: number; price: number } | null; // pre/after-hours move
  session: string;
  basisKind: "prevClose" | "open";
}

/** The day change exactly as brokers quote it: regular-session price vs the
 * PREVIOUS close. Outside regular hours the extended-session move is reported
 * separately (like Webull's "after-hours" line) instead of blended in. */
export function dayChange(quote: Quote | undefined, fallbackOpen: number | null): DayChange | null {
  if (!quote) return null;
  const prevClose = quote.prevClose ?? 0;
  const basisKind = prevClose > 0 ? "prevClose" : "open";
  const basis = prevClose > 0 ? prevClose : (fallbackOpen ?? 0);
  if (basis <= 0) return null;
  const session = quote.session ?? "";
  const regPrice = quote.regPrice ?? 0;
  const extended = session !== "regular" && session !== "" && regPrice > 0;
  const price = extended ? regPrice : quote.last;
  if (!price || price <= 0) return null;
  const abs = price - basis;
  let ext: DayChange["ext"] = null;
  if (extended && quote.last > 0 && Math.abs(quote.last - price) > 1e-9) {
    ext = { abs: quote.last - price, pct: ((quote.last - price) / price) * 100, price: quote.last };
  }
  return { abs, pct: (abs / basis) * 100, basis, price, ext, session, basisKind };
}

export const SESSION_LABEL: Record<string, string> = {
  pre: "pre-market", post: "after-hours", closed: "after-hours",
};

/** Day-shaped mini chart: no axes, no labels, tinted by day direction. */
export const Sparkline = memo(function Sparkline({
  closes,
  live,
  basis,
  height = 22,
}: {
  closes: number[];
  live?: number | null;
  basis: number | null; // previous close: tints the line by day direction
  height?: number;
}) {
  const series = live && live > 0 ? [...closes, live] : closes;
  if (series.length < 2 || basis === null) return <span className="spark spark--empty" />;
  const open = basis;
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

/** Day change vs previous close — click anywhere toggles % ↔ $ globally. */
export function DeltaPill({
  quote,
  fallbackOpen,
  size = "sm",
  interactive = true,
}: {
  quote: Quote | undefined;
  fallbackOpen: number | null;
  size?: "sm" | "md";
  interactive?: boolean;
}) {
  const chgDollar = useStore((s) => s.chgDollar);
  const toggleChgMode = useStore((s) => s.toggleChgMode);
  const { coarse } = useViewport();
  const chg = dayChange(quote, fallbackOpen);
  if (!chg) {
    return <span className={`delta-pill delta-pill--${size} dim`}>—</span>;
  }
  const touch = coarse || !interactive;
  const up = chg.abs >= 0;
  const sign = up ? "+" : "−";
  const text = chgDollar
    ? `${sign}$${Math.abs(chg.abs).toFixed(2)}`
    : `${sign}${Math.abs(chg.pct).toFixed(2)}%`;
  const basisText = chg.basisKind === "prevClose"
    ? `vs previous close ${fmtMoney(chg.basis)}`
    : `vs today's open ${fmtMoney(chg.basis)} (feed has no previous close)`;
  const extText = chg.ext
    ? ` · ${SESSION_LABEL[chg.session] ?? "extended"} ${fmtMoney(chg.ext.price)} (${chg.ext.abs >= 0 ? "+" : "−"}${Math.abs(chg.ext.pct).toFixed(2)}%)`
    : "";
  if (touch) {
    // touch: a plain pill (no 20px nested button); the %/$ toggle is in More
    return (
      <span className={`delta-pill delta-pill--${size} ${up ? "up" : "down"}`}
        title={`Today ${basisText}${extText}`}>
        <span className="a">{up ? "▲" : "▼"}</span>{text}
      </span>
    );
  }
  return (
    <button
      className={`delta-pill delta-pill--${size} ${up ? "up" : "down"}`}
      onClick={(e) => { e.stopPropagation(); toggleChgMode(); }}
      title={`Today ${basisText}${extText} — click to switch % / $`}
    >
      <span className="a">{up ? "▲" : "▼"}</span>{text}
    </button>
  );
}

/** Small pre-/after-hours move beside the day pill (trade page header). */
export function ExtendedHoursChip({ quote, fallbackOpen }: {
  quote: Quote | undefined; fallbackOpen: number | null;
}) {
  const chg = dayChange(quote, fallbackOpen);
  if (!chg?.ext) return null;
  const up = chg.ext.abs >= 0;
  return (
    <span className={`ext-chip ${up ? "up" : "down"}`}
      title={`${SESSION_LABEL[chg.session] ?? "extended"} trading: ${fmtMoney(chg.ext.price)} vs the regular-session price ${fmtMoney(chg.price)}`}>
      {SESSION_LABEL[chg.session] ?? "ext"} {fmtMoney(chg.ext.price)}
      {" "}{up ? "+" : "−"}{Math.abs(chg.ext.pct).toFixed(2)}%
    </span>
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
  const el = useRef<HTMLSpanElement>(null);
  if (quote && prev !== undefined) {
    if (quote.last > prev) lastDir.current = "up";
    else if (quote.last < prev) lastDir.current = "down";
  }
  const ticked = !!quote && prev !== undefined && quote.last !== prev;
  // pulse via the Web Animations API — no key-remount per tick (mobile main thread)
  useEffect(() => {
    if (!ticked || !el.current || typeof el.current.animate !== "function") return;
    el.current.animate([{ opacity: 1 }, { opacity: 0.28 }], { duration: 900, easing: "ease-out", fill: "forwards" });
  }, [ticked, quote?.ts]);
  return <span ref={el} className={`tick-arrow ${lastDir.current}`} aria-hidden="true" />;
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
