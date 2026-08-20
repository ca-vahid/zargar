import { memo } from "react";
import { fmtMoney } from "../lib/format";
import { usePrevLast, useQuote, useStore } from "../store";

export const WatchRow = memo(function WatchRow({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const prev = usePrevLast(symbol);
  const active = useStore((s) => s.activeSymbol === symbol);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const setPage = useStore((s) => s.setPage);
  const flash = useStore((s) => s.settings["ui.quote_flash"] ?? true);

  const dir = quote && prev !== undefined
    ? quote.last > prev ? "flash-up" : quote.last < prev ? "flash-down" : ""
    : "";

  return (
    <button
      type="button"
      className={`wl-row ${active ? "active" : ""}`}
      onClick={() => { setActiveSymbol(symbol); setPage("trade"); }}
      aria-label={`Trade ${symbol}`}
    >
      <span className="wl-sym">{symbol}</span>
      <span key={flash ? quote?.ts ?? 0 : 0} className={`wl-price quote-cell ${flash ? dir : ""}`}>
        {quote ? fmtMoney(quote.last) : "…"}
      </span>
      <span className="wl-sub">
        <span>{quote ? `${fmtMoney(quote.bid)} × ${fmtMoney(quote.ask)}` : ""}</span>
        {quote?.halted && <span className="neg">HALTED</span>}
      </span>
    </button>
  );
});
