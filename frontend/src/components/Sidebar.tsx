import { type ReactNode } from "react";
import { useStore, type Page } from "../store";
import {
  IconArmed,
  IconChevron,
  IconDashboard,
  IconJournal,
  IconOptions,
  IconPortfolios,
  IconSettings,
  IconSignals,
  IconTechnique,
  IconTrade,
  IconWatchlist,
} from "./icons";

const PAGES: { key: Page; label: string; icon: ReactNode }[] = [
  { key: "dashboard", label: "Dashboard", icon: <IconDashboard /> },
  { key: "trade", label: "Trade", icon: <IconTrade /> },
  { key: "options", label: "Options", icon: <IconOptions /> },
  { key: "inbox", label: "Signals", icon: <IconSignals /> },
  { key: "technique", label: "Techniques", icon: <IconTechnique /> },
  { key: "armed", label: "Armed", icon: <IconArmed /> },
  { key: "watchlists", label: "Watchlists", icon: <IconWatchlist /> },
  { key: "portfolios", label: "Portfolios", icon: <IconPortfolios /> },
  { key: "journal", label: "Journal", icon: <IconJournal /> },
  { key: "settings", label: "Settings", icon: <IconSettings /> },
];

export function Sidebar({ collapsed: navCollapsed = false, onToggleCollapse }: { collapsed?: boolean; onToggleCollapse?: () => void } = {}) {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const pending = useStore((s) => s.proposals.length);
  const armedCount = useStore((s) => s.techniqueArmed.filter(
    (a) => a.status === "armed" || a.status === "paused").length);

  return (
    <aside className={`sidebar ${navCollapsed ? "collapsed" : ""}`}>
      <button type="button" className="side-collapse" onClick={onToggleCollapse}
        title={navCollapsed ? "Expand the sidebar" : "Collapse the sidebar"} aria-expanded={!navCollapsed}>
        <IconChevron size={12} style={{ transform: navCollapsed ? "none" : "rotate(180deg)", transition: "transform 0.2s" }} />
      </button>
      <nav className="nav" aria-label="Primary">
        {PAGES.map((p) => (
          <button
            key={p.key}
            className={page === p.key ? "active" : ""}
            title={navCollapsed ? p.label : undefined}
            aria-current={page === p.key ? "page" : undefined}
            onClick={() => setPage(p.key)}
          >
            {p.icon} <span className="nav-label">{p.label}</span>
            {p.key === "inbox" && pending > 0 && <span className="badge">{pending}</span>}
            {p.key === "armed" && armedCount > 0 && <span className="badge ok">{armedCount}</span>}
          </button>
        )).flatMap((btn, i) => PAGES[i].key === "technique" ? [btn, (
          // techniques are a family: each one is a sub-item under "Techniques"
          <button key="technique-em" className={`nav-sub ${page === "technique" ? "active" : ""}`}
            title={navCollapsed ? "EM Options" : undefined} onClick={() => setPage("technique")}>
            <span className="nav-sub-dot" aria-hidden="true" /> <span className="nav-label">EM Options</span>
          </button>
        )] : [btn])}
      </nav>
    </aside>
  );
}
