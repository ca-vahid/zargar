import { memo } from "react";
import { fmtMoney } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useDaySeries } from "../lib/useDaySeries";
import { useQuote, useStore } from "../store";
import { dayChange, DeltaPill, Sparkline, TickArrow } from "./quotekit";

/** Watchlist row, design "F": day change leads in a pill, day sparkline in the
 * middle, small price with the arrow-pulse tick indicator below. */
export const WatchRow = memo(function WatchRow({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const active = useStore((s) => s.activeSymbol === symbol);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const setPage = useStore((s) => s.setPage);
  const openOptions = useStore((s) => s.openOptions);
  const day = useDaySeries(symbol);
  const chg = dayChange(quote, day.open);
  const occ = parseOcc(symbol);

  return (
    <button
      type="button"
      className={`wl-row ${active ? "active" : ""}`}
      onClick={() => {
        if (occ) openOptions({ contract: occ.symbol });
        else { setActiveSymbol(symbol); setPage("trade"); }
      }}
      aria-label={`Trade ${occ?.display ?? symbol}`}
    >
      <span className="wl-sym" title={occ ? `${occ.display} (${symbol})` : symbol}>{occ?.short ?? symbol}</span>
      <span className="wl-spark">
        <Sparkline closes={day.closes} live={chg?.price ?? quote?.last}
          basis={chg?.basis ?? day.open} />
      </span>
      <DeltaPill quote={quote} fallbackOpen={day.open} size="sm" />
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
