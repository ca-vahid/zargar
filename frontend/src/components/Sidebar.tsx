import { memo } from "react";
import { fmtMoney } from "../lib/format";
import { useQuote, usePrevLast, useStore, type Page } from "../store";

const PAGES: { key: Page; label: string; icon: string }[] = [
  { key: "trade", label: "Trade", icon: "📈" },
  { key: "inbox", label: "Signals", icon: "📥" },
  { key: "portfolios", label: "Portfolios", icon: "💼" },
  { key: "journal", label: "Journal", icon: "🗂" },
  { key: "settings", label: "Settings", icon: "⚙️" },
];

const WatchRow = memo(function WatchRow({ symbol }: { symbol: string }) {
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
    <div
      className={`wl-row ${active ? "active" : ""}`}
      onClick={() => { setActiveSymbol(symbol); setPage("trade"); }}
    >
      <span className="wl-sym">{symbol}</span>
      <span className={`wl-price ${flash ? dir : ""}`}>
        {quote ? fmtMoney(quote.last) : "…"}
      </span>
      <span className="wl-sub">
        <span>{quote ? `${fmtMoney(quote.bid)} × ${fmtMoney(quote.ask)}` : ""}</span>
        {quote?.halted && <span className="neg">HALTED</span>}
      </span>
    </div>
  );
});

export function Sidebar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const watchlists = useStore((s) => s.watchlists);
  const pending = useStore((s) => s.proposals.length);

  return (
    <aside className="sidebar">
      <nav className="nav">
        {PAGES.map((p) => (
          <button
            key={p.key}
            className={page === p.key ? "active" : ""}
            onClick={() => setPage(p.key)}
          >
            <span>{p.icon}</span> {p.label}
            {p.key === "inbox" && pending > 0 && <span className="badge">{pending}</span>}
          </button>
        ))}
      </nav>
      <div className="watchlist">
        {watchlists.map((wl) => (
          <div key={wl.id}>
            <h4>
              {wl.name}
              <button title="Manage in Settings" onClick={() => setPage("settings")}>✎</button>
            </h4>
            {wl.symbols.map((sym) => (
              <WatchRow key={sym} symbol={sym} />
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}
