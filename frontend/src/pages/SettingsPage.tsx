import { useEffect, useMemo, useState } from "react";
import { api, getAuthToken, setAuthToken } from "../lib/api";
import { useStore } from "../store";
import type { Watchlist } from "../types";

function usePatch() {
  const toast = useStore((s) => s.toast);
  const setSettings = useStore((s) => s.setSettings);
  return async (key: string, value: unknown) => {
    try {
      const all = await api.patchSettings({ [key]: value });
      setSettings(all);
    } catch (e: any) {
      toast("error", `${key}: ${e.message}`);
    }
  };
}

function NumberRow({ k, label, hint, step = 1 }: { k: string; label: string; hint?: string; step?: number }) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  const [draft, setDraft] = useState<string>("");
  const [editing, setEditing] = useState(false);
  return (
    <div className="setting-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <input
        type="number"
        step={step}
        value={editing ? draft : value ?? ""}
        onFocus={() => { setDraft(String(value ?? "")); setEditing(true); }}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setEditing(false); if (draft !== "" && Number(draft) !== value) patch(k, Number(draft)); }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      />
    </div>
  );
}

function ToggleRow({ k, label, hint }: { k: string; label: string; hint?: string }) {
  const value = useStore((s) => Boolean(s.settings[k]));
  const patch = usePatch();
  return (
    <div className="setting-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <label className="switch">
        <input type="checkbox" checked={value} onChange={(e) => patch(k, e.target.checked)} />
        <span className="track" />
      </label>
    </div>
  );
}

function SelectRow({ k, label, options, hint }: {
  k: string; label: string; hint?: string; options: { value: string; label: string }[];
}) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  return (
    <div className="setting-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <select value={value ?? ""} onChange={(e) => patch(k, e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export function SettingsPage() {
  const broker = useStore((s) => s.broker);
  const allPortfolios = useStore((s) => s.portfolios);
  const portfolios = useMemo(
    () => allPortfolios.filter((p) => p.kind !== "shadow"), [allPortfolios]);
  const patch = usePatch();
  const defaultPortfolio = useStore((s) => s.settings["trading.default_portfolio"]);

  return (
    <div>
      <h2 className="page-title">Settings</h2>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-head">Trading &amp; routing</div>
          <div className="panel-body">
            <SelectRow k="trading.mode" label="Trading mode"
              hint="practice fills on the simulator; LIVE routes real orders to SnapTrade/IBKR. Per-order dry runs live in the ticket."
              options={[
                { value: "practice", label: "Practice" },
                { value: "live", label: "LIVE" },
              ]} />
            <div className="setting-row">
              <div className="lbl">Default portfolio<small>used by ticket and proposals</small></div>
              <select value={defaultPortfolio ?? ""}
                onChange={(e) => patch("trading.default_portfolio", e.target.value)}>
                {portfolios.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <NumberRow k="trading.default_qty" label="Default order quantity" />
            <div className="setting-row">
              <div className="lbl">Broker connection<small>configured via environment</small></div>
              <span className={`status-pill ${broker?.feedConnected ? "ok" : "bad"}`}>
                {broker?.feed ?? "?"} {broker?.ibkrConnected ? "+ IBKR" : ""}
              </span>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Risk gate</div>
          <div className="panel-body">
            <NumberRow k="risk.max_position_notional" label="Max position ($/symbol)" step={100} />
            <NumberRow k="risk.max_position_pct" label="Max position (% equity)" step={0.5} />
            <NumberRow k="risk.max_gross_exposure_pct" label="Max gross exposure (%)" step={5} />
            <NumberRow k="risk.daily_loss_halt_pct" label="Daily loss halt (%)" step={0.5}
              hint="auto-engages the kill switch" />
            <NumberRow k="risk.price_collar_pct" label="Price collar (%)" step={0.5}
              hint="fat-finger guard vs last price" />
            <NumberRow k="risk.max_orders_per_minute" label="Max orders / minute" />
            <NumberRow k="risk.stale_quote_seconds" label="Stale quote block (s)" />
            <ToggleRow k="risk.allow_short" label="Allow short selling" />
            <ToggleRow k="risk.allow_options" label="Allow options" />
            <NumberRow k="risk.max_option_premium_pct" label="Max option premium (% equity)" step={0.5} />
            <ToggleRow k="risk.require_market_hours" label="Require market hours (live/paper)" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Signals &amp; verification</div>
          <div className="panel-body">
            <NumberRow k="signals.default_sizing_pct" label="Proposal sizing (% equity)" step={0.5} />
            <NumberRow k="signals.default_ttl_minutes" label="Proposal TTL (minutes)" />
            <ToggleRow k="signals.auto_execute_enabled" label="Rules-gated auto-execution"
              hint="graduate a source only after its shadow record earns it" />
            <NumberRow k="signals.max_auto_notional" label="Max auto-execute notional ($)" step={50} />
            <NumberRow k="verification.max_price_deviation_pct" label="Max price deviation (%)" step={0.5}
              hint="reject stale alerts — live price vs claimed entry" />
            <NumberRow k="verification.max_spread_pct" label="Max spread (%)" step={0.1}
              hint="liquidity / pump filter" />
            <NumberRow k="verification.min_price" label="Minimum price ($)" step={0.5}
              hint="penny-stock filter" />
            <ToggleRow k="verification.require_actionable" label="Require explicit actionable call" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Account &amp; integrations</div>
          <div className="panel-body">
            <SelectRow k="account.regime" label="Account regime"
              hint="drives day-trade + tax-loss rules"
              options={[
                { value: "ca", label: "Canada (CRA superficial loss)" },
                { value: "us", label: "United States (IRS wash sale)" },
              ]} />
            <ToggleRow k="account.day_trade_warnings" label="Day-trade warnings" />
            <ToggleRow k="telegram.enabled" label="Telegram approvals"
              hint="needs ZARGAR_TELEGRAM_BOT_TOKEN + CHAT_ID, restart backend" />
            <ApiTokenRow />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Brokerages (SnapTrade)</div>
          <div className="panel-body">
            <div className="setting-row">
              <div className="lbl">SnapTrade<small>Wealthsimple + Webull via aggregator</small></div>
              <span className={`status-pill ${broker?.snaptradeConnected ? "ok" : "dim"}`}>
                {broker?.snaptradeConnected ? "connected" : "off"}
              </span>
            </div>
            <div className="setting-row">
              <div className="lbl">IBKR gateway<small>native connection for live/paper</small></div>
              <span className={`status-pill ${broker?.ibkrConnected ? "ok" : "dim"}`}>
                {broker?.ibkrConnected ? "connected" : "off"}
              </span>
            </div>
            <ToggleRow k="snaptrade.enabled" label="Enable SnapTrade"
              hint="needs ZARGAR_SNAPTRADE_* credentials in .env, restart backend" />
            <NumberRow k="snaptrade.sync_minutes" label="Account sync interval (min)" />
            <NumberRow k="snaptrade.order_poll_seconds" label="Order status poll (s)" step={0.5} />
            <ToggleRow k="snaptrade.allow_brackets" label="Allow bracket orders"
              hint="off by default — broker support varies" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Appearance</div>
          <div className="panel-body">
            <SelectRow k="ui.theme" label="Theme"
              options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
            <AccentRow />
            <SelectRow k="ui.density" label="Density"
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
            <ToggleRow k="ui.quote_flash" label="Flash quotes on change" />
            <ToggleRow k="ui.chart.show_volume" label="Show volume pane" />
            <SelectRow k="ui.chart.type" label="Default chart type"
              options={[{ value: "candlestick", label: "Candlestick" }, { value: "line", label: "Line" }]} />
            <SelectRow k="ui.chart.tf" label="Default timeframe"
              options={["1m", "5m", "15m", "1h"].map((t) => ({ value: t, label: t }))} />
            <DefaultSymbolRow />
          </div>
        </div>

        <WatchlistsPanel />
        <SourcesPanel />
      </div>
    </div>
  );
}

function AccentRow() {
  const value = useStore((s) => s.settings["ui.accent"] ?? "#5b8cff");
  const patch = usePatch();
  return (
    <div className="setting-row">
      <div className="lbl">Accent color</div>
      <input type="color" value={value} style={{ width: 46, height: 28, padding: 2 }}
        onChange={(e) => patch("ui.accent", e.target.value)} />
    </div>
  );
}

function DefaultSymbolRow() {
  const value = useStore((s) => s.settings["ui.default_symbol"] ?? "");
  const patch = usePatch();
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <div className="setting-row">
      <div className="lbl">Default symbol</div>
      <input type="text" value={draft ?? value}
        onChange={(e) => setDraft(e.target.value.toUpperCase())}
        onBlur={() => { if (draft && draft !== value) patch("ui.default_symbol", draft); setDraft(null); }} />
    </div>
  );
}

function ApiTokenRow() {
  const [draft, setDraft] = useState(getAuthToken());
  const toast = useStore((s) => s.toast);
  return (
    <div className="setting-row">
      <div className="lbl">API token<small>stored in this browser; needed when ZARGAR_AUTH_TOKEN is set</small></div>
      <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setAuthToken(draft); toast("info", "API token saved locally"); }} />
    </div>
  );
}

function WatchlistsPanel() {
  const watchlists = useStore((s) => s.watchlists);
  const setWatchlists = useStore((s) => s.setWatchlists);
  const toast = useStore((s) => s.toast);
  const [newName, setNewName] = useState("");

  const refresh = async () => setWatchlists(await api.get<Watchlist[]>("/api/watchlists"));

  const save = async (wl: Watchlist, symbols: string[]) => {
    try {
      await api.put(`/api/watchlists/${wl.id}`, { name: wl.name, symbols });
      await refresh();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">Watchlists</div>
      <div className="panel-body">
        {watchlists.map((wl) => (
          <WatchlistEditor key={wl.id} wl={wl} onSave={save}
            onDelete={async () => { await api.del(`/api/watchlists/${wl.id}`); await refresh(); }} />
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <input type="text" placeholder="New watchlist name" value={newName}
            onChange={(e) => setNewName(e.target.value)} />
          <button className="ghost-btn" disabled={!newName.trim()} onClick={async () => {
            await api.post("/api/watchlists", { name: newName.trim(), symbols: [] });
            setNewName("");
            await refresh();
          }}>Add</button>
        </div>
      </div>
    </div>
  );
}

function WatchlistEditor({ wl, onSave, onDelete }: {
  wl: Watchlist;
  onSave: (wl: Watchlist, symbols: string[]) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(wl.symbols.join(", "));
  useEffect(() => setDraft(wl.symbols.join(", ")), [wl.symbols.join(",")]);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <b>{wl.name}</b>
        <button className="link-btn danger" onClick={onDelete}>remove</button>
      </div>
      <input type="text" value={draft} onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const symbols = draft.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
          if (symbols.join(",") !== wl.symbols.join(",")) onSave(wl, symbols);
        }}
        placeholder="AAPL, MSFT, SHOP.TO" />
    </div>
  );
}

interface Source { name: string; emails: string[]; trust: string; notes: string }

function SourcesPanel() {
  const registry: Source[] = useStore((s) => s.settings["sources.registry"] ?? []);
  const patch = usePatch();
  const [name, setName] = useState("");
  const [emails, setEmails] = useState("");

  const save = (next: Source[]) => patch("sources.registry", next);

  return (
    <div className="panel">
      <div className="panel-head">
        Signal sources <span className="sub">match inbound email senders to named sources</span>
      </div>
      <div className="panel-body">
        {registry.length === 0 && (
          <div className="muted" style={{ marginBottom: 8 }}>
            No sources registered — inbound emails will be tracked by sender address.
          </div>
        )}
        {registry.map((src, i) => (
          <div key={i} className="setting-row">
            <div className="lbl">
              {src.name}
              <small>{(src.emails ?? []).join(", ") || "no addresses"}</small>
            </div>
            <button className="link-btn danger"
              onClick={() => save(registry.filter((_, j) => j !== i))}>
              remove
            </button>
          </div>
        ))}
        <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
          <input type="text" placeholder="Source name (e.g. Motley Letter)" value={name}
            onChange={(e) => setName(e.target.value)} />
          <input type="text" placeholder="Sender addresses, comma separated" value={emails}
            onChange={(e) => setEmails(e.target.value)} />
          <button className="ghost-btn" disabled={!name.trim()} onClick={() => {
            save([...registry, {
              name: name.trim(),
              emails: emails.split(",").map((s) => s.trim()).filter(Boolean),
              trust: "manual", notes: "",
            }]);
            setName(""); setEmails("");
          }}>Add source</button>
        </div>
      </div>
    </div>
  );
}
