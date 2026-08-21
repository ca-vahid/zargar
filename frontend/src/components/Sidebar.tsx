import { useMemo, useState, type ReactNode } from "react";
import { useStore, type Page } from "../store";
import {
  IconChevron,
  IconDashboard,
  IconEdit,
  IconJournal,
  IconPortfolios,
  IconSettings,
  IconSignals,
  IconTechnique,
  IconTrade,
} from "./icons";
import { WatchRow } from "./WatchRow";

const PAGES: { key: Page; label: string; icon: ReactNode }[] = [
  { key: "dashboard", label: "Dashboard", icon: <IconDashboard /> },
  { key: "trade", label: "Trade", icon: <IconTrade /> },
  { key: "inbox", label: "Signals", icon: <IconSignals /> },
  { key: "technique", label: "Technique", icon: <IconTechnique /> },
  { key: "portfolios", label: "Portfolios", icon: <IconPortfolios /> },
  { key: "journal", label: "Journal", icon: <IconJournal /> },
  { key: "settings", label: "Settings", icon: <IconSettings /> },
];

function loadCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem("zargar_wl_collapsed") ?? "{}");
  } catch {
    return {};
  }
}

function SectionHead({
  id,
  children,
  extra,
  collapsed,
  onToggle,
}: {
  id: string;
  children: ReactNode;
  extra?: ReactNode;
  collapsed: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="wl-head">
      <button className="wl-head-btn" onClick={() => onToggle(id)}
        aria-expanded={!collapsed}>
        <IconChevron size={11}
          style={{ transform: collapsed ? "none" : "rotate(90deg)", transition: "transform 0.15s" }} />
        {children}
      </button>
      {extra}
    </div>
  );
}

export function Sidebar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const watchlists = useStore((s) => s.watchlists);
  const pending = useStore((s) => s.proposals.length);
  const positionsMap = useStore((s) => s.positions);
  const portfolios = useStore((s) => s.portfolios);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(loadCollapsed);

  const toggle = (id: string) =>
    setCollapsed((c) => {
      const next = { ...c, [id]: !c[id] };
      localStorage.setItem("zargar_wl_collapsed", JSON.stringify(next));
      return next;
    });

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
            <SectionHead id="holdings" collapsed={!!collapsed["holdings"]} onToggle={toggle}
              extra={<span className="holdings-dot" title="Live positions in your real accounts" />}>
              My holdings
            </SectionHead>
            {!collapsed["holdings"] && holdings.map((sym) => (
              <WatchRow key={sym} symbol={sym} />
            ))}
          </div>
        )}
        {watchlists.map((wl) => (
          <div key={wl.id}>
            <SectionHead id={wl.id} collapsed={!!collapsed[wl.id]} onToggle={toggle}
              extra={
                <button className="icon-btn" title="Manage in Settings"
                  aria-label={`Manage ${wl.name} in Settings`}
                  onClick={() => setPage("settings")}>
                  <IconEdit size={11} />
                </button>
              }>
              {wl.name}
            </SectionHead>
            {!collapsed[wl.id] && wl.symbols.map((sym) => (
              <WatchRow key={sym} symbol={sym} />
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}
