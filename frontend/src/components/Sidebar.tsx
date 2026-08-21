import { useMemo, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { useStore, type Page } from "../store";
import type { Watchlist } from "../types";
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
  IconX,
} from "./icons";
import { SymbolSearch } from "./SymbolSearch";
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
          <WatchlistSection key={wl.id} wl={wl}
            collapsed={!!collapsed[wl.id]} onToggle={toggle} />
        ))}
      </div>
    </aside>
  );
}

/** One watchlist section with in-place editing: the pencil toggles an edit
 * mode with per-symbol remove and search-to-add, saved straight to the API. */
function WatchlistSection({
  wl,
  collapsed,
  onToggle,
}: {
  wl: Watchlist;
  collapsed: boolean;
  onToggle: (id: string) => void;
}) {
  const watchlists = useStore((s) => s.watchlists);
  const setWatchlists = useStore((s) => s.setWatchlists);
  const toast = useStore((s) => s.toast);
  const [editing, setEditing] = useState(false);

  const save = async (symbols: string[]) => {
    try {
      await api.updateWatchlist(wl.id, wl.name, symbols);
      setWatchlists(watchlists.map((w) => (w.id === wl.id ? { ...w, symbols } : w)));
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const add = (symbol: string) => {
    if (wl.symbols.includes(symbol)) {
      toast("info", `${symbol} is already on ${wl.name}`);
      return;
    }
    void save([...wl.symbols, symbol]);
  };

  return (
    <div>
      <SectionHead id={wl.id} collapsed={collapsed} onToggle={onToggle}
        extra={
          <button className={`icon-btn ${editing ? "active" : ""}`}
            title={editing ? "Done editing" : `Edit ${wl.name}`}
            aria-label={editing ? "Done editing" : `Edit ${wl.name}`}
            aria-pressed={editing}
            onClick={() => setEditing((v) => !v)}>
            <IconEdit size={11} />
          </button>
        }>
        {wl.name}
      </SectionHead>
      {!collapsed && !editing && wl.symbols.map((sym) => (
        <WatchRow key={sym} symbol={sym} />
      ))}
      {!collapsed && editing && (
        <div className="wl-editbox">
          {wl.symbols.map((sym) => (
            <div key={sym} className="wl-edit-row">
              <span className="wl-sym">{sym}</span>
              <button className="icon-btn danger" title={`Remove ${sym}`}
                aria-label={`Remove ${sym} from ${wl.name}`}
                onClick={() => void save(wl.symbols.filter((s) => s !== sym))}>
                <IconX size={11} />
              </button>
            </div>
          ))}
          {wl.symbols.length === 0 && (
            <div className="wl-edit-empty">empty — search below to add</div>
          )}
          <SymbolSearch compact placeholder="Add a stock…"
            onPick={(h) => add(h.symbol)} />
          <button className="link-btn wl-edit-done" onClick={() => setEditing(false)}>
            done
          </button>
        </div>
      )}
    </div>
  );
}
