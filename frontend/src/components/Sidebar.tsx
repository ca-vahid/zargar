import type { ReactNode } from "react";
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
