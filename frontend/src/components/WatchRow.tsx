import { memo } from "react";
import { fmtMoney } from "../lib/format";
import { useDaySeries } from "../lib/useDaySeries";
import { useQuote, useStore } from "../store";
import { DeltaPill, Sparkline, TickArrow } from "./quotekit";

/** Watchlist row, design "F": day change leads in a pill, day sparkline in the
 * middle, small price with the arrow-pulse tick indicator below. */
export const WatchRow = memo(function WatchRow({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const active = useStore((s) => s.activeSymbol === symbol);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const setPage = useStore((s) => s.setPage);
  const day = useDaySeries(symbol);

  return (
    <button
      type="button"
      className={`wl-row ${active ? "active" : ""}`}
      onClick={() => { setActiveSymbol(symbol); setPage("trade"); }}
      aria-label={`Trade ${symbol}`}
    >
      <span className="wl-sym" title={symbol}>{symbol}</span>
      <span className="wl-spark">
        <Sparkline closes={day.closes} live={quote?.last} open={day.open} />
      </span>
      <DeltaPill price={quote?.last} open={day.open} size="sm" />
      <span className="wl-sub">
        <span>{quote ? `${fmtMoney(quote.bid)} × ${fmtMoney(quote.ask)}` : ""}</span>
        <span className="price-live">
          <TickArrow symbol={symbol} />
          <span>{quote ? fmtMoney(quote.last) : "…"}</span>
          {quote?.halted && <span className="neg"> HALTED</span>}
        </span>
      </span>
    </button>
  );
});
