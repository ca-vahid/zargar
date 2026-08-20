import { useMemo, type ReactNode } from "react";
import { useStore, type Page } from "../store";
import {
  IconDashboard,
  IconEdit,
  IconJournal,
  IconPortfolios,
  IconSettings,
  IconSignals,
  IconTrade,
} from "./icons";
import { WatchRow } from "./WatchRow";

const PAGES: { key: Page; label: string; icon: ReactNode }[] = [
  { key: "dashboard", label: "Dashboard", icon: <IconDashboard /> },
  { key: "trade", label: "Trade", icon: <IconTrade /> },
  { key: "inbox", label: "Signals", icon: <IconSignals /> },
  { key: "portfolios", label: "Portfolios", icon: <IconPortfolios /> },
  { key: "journal", label: "Journal", icon: <IconJournal /> },
  { key: "settings", label: "Settings", icon: <IconSettings /> },
];

export function Sidebar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const watchlists = useStore((s) => s.watchlists);
  const pending = useStore((s) => s.proposals.length);
  const positionsMap = useStore((s) => s.positions);
  const portfolios = useStore((s) => s.portfolios);

  // your real holdings, always on top — the symbols that actually matter
  const holdings = useMemo(() => {
    const real = new Set(portfolios
      .filter((p) => p.kind === "live" || p.kind === "paper").map((p) => p.id));
    const syms = new Set<string>();
    for (const p of Object.values(positionsMap)) {
      if (real.has(p.portfolioId) && Math.abs(p.qty) > 1e-9) syms.add(p.symbol);
    }
    return [...syms].sort();
  }, [positionsMap, portfolios]);

  return (
    <aside className="sidebar">
      <nav className="nav" aria-label="Primary">
        {PAGES.map((p) => (
          <button
            key={p.key}
            className={page === p.key ? "active" : ""}
            aria-current={page === p.key ? "page" : undefined}
            onClick={() => setPage(p.key)}
          >
            {p.icon} {p.label}
            {p.key === "inbox" && pending > 0 && <span className="badge">{pending}</span>}
          </button>
        ))}
      </nav>
      <div className="watchlist">
        {holdings.length > 0 && (
          <div>
            <h4>My holdings <span className="holdings-dot" title="Live positions in your real accounts" /></h4>
            {holdings.map((sym) => (
              <WatchRow key={sym} symbol={sym} />
            ))}
          </div>
        )}
        {watchlists.map((wl) => (
          <div key={wl.id}>
            <h4>
              {wl.name}
              <button title="Manage in Settings" aria-label={`Manage ${wl.name} in Settings`}
                onClick={() => setPage("settings")}>
                <IconEdit size={12} />
              </button>
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
