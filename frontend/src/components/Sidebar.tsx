import { type ReactNode } from "react";
import { useStore, type Page } from "../store";
import { useTechniques } from "../lib/techniques";
import {
  IconArmed,
  IconChevron,
  IconDashboard,
  IconJournal,
  IconLedger,
  IconOptions,
  IconPortfolios,
  IconSettings,
  IconTechnique,
  IconTrade,
  IconWatchlist,
} from "./icons";

// NOTE: no top-level "Signals" entry — the Tips page lives under Techniques
// (the registry sub-item), which used to double-list it. Phone TabBar unchanged.
const PAGES: { key: Page; label: string; icon: ReactNode }[] = [
  { key: "dashboard", label: "Dashboard", icon: <IconDashboard /> },
  { key: "trade", label: "Trade", icon: <IconTrade /> },
  { key: "options", label: "Options", icon: <IconOptions /> },
  { key: "technique", label: "Techniques", icon: <IconTechnique /> },
  { key: "armed", label: "Armed", icon: <IconArmed /> },
  { key: "watchlists", label: "Watchlists", icon: <IconWatchlist /> },
  { key: "portfolios", label: "Portfolios", icon: <IconPortfolios /> },
  { key: "ledger", label: "Ledger", icon: <IconLedger /> },
  { key: "journal", label: "Journal", icon: <IconJournal /> },
  { key: "settings", label: "Settings", icon: <IconSettings /> },
];

export function Sidebar({ collapsed: navCollapsed = false, onToggleCollapse }: { collapsed?: boolean; onToggleCollapse?: () => void } = {}) {
  const techniques = useTechniques();
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const pending = useStore((s) => s.proposals.length);
  // the "Techniques" parent stays lit on ANY technique page (EM/Tips/Flow),
  // matching how EM (whose page IS "technique") always lit it
  const techniquePages = new Set<Page>(["technique", ...techniques.map((t) => t.page as Page)]);
  const isActive = (key: Page) => (key === "technique" ? techniquePages.has(page) : page === key);
  const armedCount = useStore((s) => s.techniqueArmed.filter(
    (a) => a.status === "armed" || a.status === "paused").length);

  return (
    <aside className={`sidebar ${navCollapsed ? "collapsed" : ""}`}>
      <button type="button" className="side-collapse" onClick={onToggleCollapse}
        title={navCollapsed ? "Expand the sidebar" : "Collapse the sidebar"}
        aria-label={navCollapsed ? "Expand the sidebar" : "Collapse the sidebar"} aria-expanded={!navCollapsed}>
        <IconChevron size={12} style={{ transform: navCollapsed ? "none" : "rotate(180deg)", transition: "transform 0.2s" }} />
      </button>
      <nav className="nav" aria-label="Primary">
        {PAGES.map((p) => (
          <button
            key={p.key}
            className={isActive(p.key) ? "active" : ""}
            title={navCollapsed ? p.label : undefined}
            aria-current={page === p.key ? "page" : undefined}
            onClick={() => setPage(p.key)}
          >
            {p.icon} <span className="nav-label">{p.label}</span>
            {p.key === "armed" && armedCount > 0 && <span className="badge ok">{armedCount}</span>}
          </button>
        )).flatMap((btn, i) => PAGES[i].key === "technique" ? [btn, ...techniques.map((t) => (
          // techniques are a family: each registered one is a sub-item under "Techniques"
          <button key={`technique-${t.id}`} className={`nav-sub ${page === t.page ? "active" : ""}`}
            title={navCollapsed ? t.label : undefined} onClick={() => setPage(t.page as Page)}>
            <span className="nav-sub-dot" aria-hidden="true" /> <span className="nav-label">{t.label}</span>
            {t.page === "inbox" && pending > 0 && <span className="badge">{pending}</span>}
          </button>
        ))] : [btn])}
      </nav>
    </aside>
  );
}
