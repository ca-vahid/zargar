import { type ReactNode } from "react";
import { useStore, type Page } from "../store";
import type React from "react";
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

// the desk's order for the technique family (user 2026-09-04): Tips, Team2, EM, Flow — and the short
// sidebar name for each; anything the registry adds later lands after these in registry order
const TECHNIQUE_ORDER: Record<string, number> = { inbox: 0, team2: 1, technique: 2, flow: 3 };
const TECHNIQUE_SHORT: Record<string, string> = { enhanced_market: "EM" };

/** A click ripple from where the pointer landed — pure CSS animation, removed when it ends. */
function ripple(e: React.MouseEvent<HTMLButtonElement>) {
  const el = e.currentTarget;
  const r = el.getBoundingClientRect();
  const span = document.createElement("span");
  const size = Math.max(r.width, r.height) * 1.6;
  span.className = "nav-ripple";
  span.style.width = span.style.height = `${size}px`;
  span.style.left = `${e.clientX - r.left - size / 2}px`;
  span.style.top = `${e.clientY - r.top - size / 2}px`;
  el.appendChild(span);
  span.addEventListener("animationend", () => span.remove(), { once: true });
}

export function Sidebar({ collapsed: navCollapsed = false, onToggleCollapse }: { collapsed?: boolean; onToggleCollapse?: () => void } = {}) {
  const registry = useTechniques();
  const techniques = [...registry].sort((a, b) => (TECHNIQUE_ORDER[a.page] ?? 99) - (TECHNIQUE_ORDER[b.page] ?? 99));
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
            onClick={(e) => { ripple(e); setPage(p.key); }}
          >
            {p.icon} <span className="nav-label">{p.label}</span>
            {p.key === "armed" && armedCount > 0 && <span className="badge ok">{armedCount}</span>}
          </button>
        )).flatMap((btn, i) => PAGES[i].key === "technique" ? [btn, ...techniques.map((t) => (
          // techniques are a family: each registered one is a sub-item under "Techniques"
          <button key={`technique-${t.id}`} className={`nav-sub ${page === t.page ? "active" : ""}`}
            title={navCollapsed ? t.label : undefined} onClick={(e) => { ripple(e); setPage(t.page as Page); }}>
            <span className="nav-sub-dot" aria-hidden="true" /> <span className="nav-label">{TECHNIQUE_SHORT[t.id] ?? t.label}</span>
            {t.page === "inbox" && pending > 0 && <span className="badge">{pending}</span>}
          </button>
        ))] : [btn])}
      </nav>
    </aside>
  );
}
