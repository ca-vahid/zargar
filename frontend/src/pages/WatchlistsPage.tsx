import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import type { Watchlist } from "../types";
import { IconEdit, IconX } from "../components/icons";
import { SymbolSearch } from "../components/SymbolSearch";
import { WatchRow } from "../components/WatchRow";

/** Holdings + watchlists, moved out of the sidebar into their own page.
 *  Same live WatchRow rows (sparkline, day change, click to trade). */
export function WatchlistsPage() {
  const positionsMap = useStore((s) => s.positions);
  const portfolios = useStore((s) => s.portfolios);
  const watchlists = useStore((s) => s.watchlists);

  // your real holdings — the symbols that actually matter
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
    <div>
      <h2 className="page-title">Watchlists</h2>
      <div className="wl-page-grid">
        {holdings.length > 0 && (
          <div className="panel">
            <div className="panel-head">My holdings
              <span className="holdings-dot" title="Live positions in your real accounts" />
              <span className="sub">live positions in your real accounts</span></div>
            <div className="panel-body wl-page-rows">
              {holdings.map((sym) => <WatchRow key={sym} symbol={sym} />)}
            </div>
          </div>
        )}
        {watchlists.map((wl) => <WatchlistPanel key={wl.id} wl={wl} />)}
        <NewWatchlistPanel />
      </div>
    </div>
  );
}

function WatchlistPanel({ wl }: { wl: Watchlist }) {
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
    <div className="panel">
      <div className="panel-head">{wl.name}
        <span className="sub">{wl.symbols.length} symbol(s)</span>
        <button className={`icon-btn tq-head-right ${editing ? "active" : ""}`}
          title={editing ? "Done editing" : `Edit ${wl.name}`}
          aria-label={editing ? "Done editing" : `Edit ${wl.name}`}
          aria-pressed={editing}
          onClick={() => setEditing((v) => !v)}>
          <IconEdit size={12} />
        </button>
      </div>
      <div className="panel-body wl-page-rows">
        {!editing && wl.symbols.map((sym) => <WatchRow key={sym} symbol={sym} />)}
        {!editing && wl.symbols.length === 0 && (
          <div className="muted small">empty — click the pencil to add symbols</div>
        )}
        {editing && (
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
            <SymbolSearch compact placeholder="Add a stock…" onPick={(h) => add(h.symbol)} />
            <button className="link-btn wl-edit-done" onClick={() => setEditing(false)}>done</button>
          </div>
        )}
      </div>
    </div>
  );
}

function NewWatchlistPanel() {
  const setWatchlists = useStore((s) => s.setWatchlists);
  const toast = useStore((s) => s.toast);
  const [name, setName] = useState("");
  return (
    <div className="panel">
      <div className="panel-head">New watchlist</div>
      <div className="panel-body" style={{ display: "flex", gap: 8 }}>
        <input type="text" placeholder="Name…" value={name} style={{ flex: 1 }}
          onChange={(e) => setName(e.target.value)} />
        <button className="ghost-btn" disabled={!name.trim()} onClick={async () => {
          try {
            await api.post("/api/watchlists", { name: name.trim(), symbols: [] });
            setWatchlists(await api.get<Watchlist[]>("/api/watchlists"));
            setName("");
          } catch (e: any) { toast("error", e.message); }
        }}>Create</button>
      </div>
    </div>
  );
}
