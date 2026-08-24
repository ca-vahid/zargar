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
      <select value={String(value ?? "")} onChange={(e) => patch(k, e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function ListRow({ k, label, hint }: { k: string; label: string; hint?: string }) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  const [draft, setDraft] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const current = Array.isArray(value) ? value.join(", ") : "";
  return (
    <div className="setting-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <input type="text" value={editing ? draft : current}
        onFocus={() => { setDraft(current); setEditing(true); }}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const list = draft.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean);
          if (list.join(",") !== (Array.isArray(value) ? value.join(",") : "")) patch(k, list);
        }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
    </div>
  );
}

export function SettingsPage() {
  const broker = useStore((s) => s.broker);
  const allPortfolios = useStore((s) => s.portfolios);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  // the account list follows the trading mode (set in the top banner):
  // practice -> simulator accounts, LIVE -> real/paper accounts
  const portfolios = useMemo(
    () => allPortfolios.filter((p) =>
      mode === "live" ? p.kind === "live" || p.kind === "paper" : p.kind === "sim"),
    [allPortfolios, mode]);
  const patch = usePatch();
  const defaultPortfolio = useStore((s) => s.settings["trading.default_portfolio"]);
  const offModePortfolio = useMemo(
    () => allPortfolios.find((p) => p.id === defaultPortfolio && !portfolios.some((q) => q.id === p.id)),
    [allPortfolios, portfolios, defaultPortfolio]);

  return (
    <div>
      <h2 className="page-title">Settings</h2>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-head">Order defaults
            <span className="sub">default account and quantity — the trading mode itself lives in the top banner</span></div>
          <div className="panel-body">
            <div className="setting-row">
              <div className="lbl">Default portfolio
                <small>used by ticket and proposals — list follows the {mode === "live" ? "LIVE" : "practice"} mode</small></div>
              <select value={defaultPortfolio ?? ""}
                onChange={(e) => patch("trading.default_portfolio", e.target.value)}>
                {offModePortfolio && (
                  <option value={offModePortfolio.id}>{offModePortfolio.name} (other mode)</option>
                )}
                {portfolios.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <NumberRow k="trading.default_qty" label="Default order quantity" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Risk gate
            <span className="sub">every order must pass all of these</span></div>
          <div className="panel-body">
            <NumberRow k="risk.max_position_notional" label="Max position ($/symbol)" step={100}
              hint="in the account's currency — e.g. 1000 on a CAD account means C$1,000" />
            <NumberRow k="risk.max_position_pct" label="Max position (% equity)" step={0.5}
              hint="resulting position vs account equity" />
            <NumberRow k="risk.max_gross_exposure_pct" label="Max gross exposure (%)" step={5}
              hint="sum of |position values| vs equity" />
            <NumberRow k="risk.daily_loss_halt_pct" label="Daily loss halt (%)" step={0.5}
              hint="auto-engages the kill switch" />
            <NumberRow k="risk.price_collar_pct" label="Price collar (%)" step={0.5}
              hint="fat-finger guard vs last price" />
            <NumberRow k="risk.max_orders_per_minute" label="Max orders / minute" />
            <NumberRow k="risk.stale_quote_seconds" label="Stale quote block (s)"
              hint="orders are rejected when the symbol's quote is older than this" />
            <ToggleRow k="risk.allow_short" label="Allow short selling" />
            <ToggleRow k="risk.require_market_hours" label="Require market hours (live/paper)"
              hint="option orders always enforce regular hours — they have no extended session" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Options
            <span className="sub">contracts, risk caps, venue, data provider</span></div>
          <div className="panel-body">
            <ToggleRow k="risk.allow_options" label="Allow option orders" />
            <ToggleRow k="risk.allow_0dte" label="Allow 0DTE contracts"
              hint="the EnhancedMarket method trades weeklies/0DTE — off blocks same-day expiries" />
            <NumberRow k="risk.max_option_contracts" label="Max contracts per order" />
            <NumberRow k="risk.max_option_premium_notional" label="Max premium per order ($)" step={50}
              hint="qty × price × 100, buys only; closes are exempt" />
            <NumberRow k="risk.max_option_premium_pct" label="Max premium (% equity)" step={0.5} />
            <NumberRow k="risk.max_option_spread_pct" label="Max bid/ask spread (%)" step={1}
              hint="market orders on wider spreads are rejected; limits get a warning" />
            <NumberRow k="options.fee_per_contract" label="Fee per contract (USD)" step={0.01}
              hint="Webull Canada: US$0.99/contract + regulatory fees — used by the ticket estimate" />
            <SelectRow k="options.provider" label="Chain data provider"
              hint="CBOE is free with greeks, ~15-min delayed, no account (works in Canada). Tradier needs a US-signup token."
              options={[{ value: "cboe", label: "CBOE delayed (free)" }, { value: "tradier", label: "Tradier (token)" }]} />
            <NumberRow k="options.enrich_seconds" label="Contract quote refresh (s)"
              hint="how often tracked contracts re-read bid/ask from the chain" />
            <ListRow k="snaptrade.options_brokers" label="Brokerages allowed to route option orders"
              hint="verified 2026-08-21: Webull Canada yes, Wealthsimple no (SnapTrade code 1156)" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Signals &amp; verification
            <span className="sub">how newsletter alerts become proposals</span></div>
          <div className="panel-body">
            <NumberRow k="signals.default_sizing_pct" label="Proposal sizing (% equity)" step={0.5} />
            <NumberRow k="signals.default_ttl_minutes" label="Proposal TTL (minutes)" />
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
          <div className="panel-head">Integrations &amp; connections
            <span className="sub">brokerages, quote feed, external services</span></div>
          <div className="panel-body">
            <div className="setting-row">
              <div className="lbl">Quote feed<small>configured via environment</small></div>
              <span className={`status-pill ${broker?.feedConnected ? "ok" : "bad"}`}>
                {broker?.feed ?? "?"}
              </span>
            </div>
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
            <ToggleRow k="telegram.enabled" label="Telegram approvals"
              hint="needs ZARGAR_TELEGRAM_BOT_TOKEN + CHAT_ID, restart backend" />
            <ApiTokenRow />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Technique &amp; LLM
            <span className="sub">EnhancedMarket pipeline, model effort, scans</span></div>
          <div className="panel-body">
            <SelectRow k="llm.effort" label="Thinking depth (effort)"
              hint="low = fast/cheap; high = default; xhigh/max = deepest reasoning, slower"
              options={[
                { value: "low", label: "low" }, { value: "medium", label: "medium" },
                { value: "high", label: "high" }, { value: "xhigh", label: "xhigh" }, { value: "max", label: "max" },
              ]} />
            <SelectRow k="llm.thinking_display" label="Show thinking"
              hint="summarized streams the model's reasoning live; raw chain-of-thought is never returned by the API"
              options={[{ value: "summarized", label: "summarized (visible)" }, { value: "omitted", label: "omitted (silent)" }]} />
            <NumberRow k="llm.max_passes" label="Max model calls per run" hint="context, pattern, entry, critic + retries" />
            <NumberRow k="technique.max_runs_per_day" label="Daily run cap" hint="cost guard across manual + scans" />
            <SelectRow k="technique.trigger_tf" label="Trigger timeframe"
              hint="where entries/triggers are decided — used by manual runs, session plans, sweeps and armed plans"
              options={[{ value: "1m", label: "1m" }, { value: "5m", label: "5m" }, { value: "15m", label: "15m" }]} />
            <NumberRow k="technique.min_risk_reward" label="Min reward:risk (R2)" step={0.5} hint="book: 1:3" />
            <NumberRow k="technique.default_risk_pct" label="Analysis risk sizing (%)" step={0.25}
              hint="sizing the pipeline assumes when judging a setup (book: 0.5-1%) — armed plans size with their own knob below" />
            <NumberRow k="technique.max_risk_pct" label="Max risk per trade (%)" step={0.5} hint="book: 5% ceiling" />
            <NumberRow k="technique.max_stop_pct" label="Max stop distance (%)" step={0.5}
              hint="T4.3a/R1 — widest chart-justified stop as % of entry; wider setups are skipped" />
            <NumberRow k="technique.level_tolerance_pct" label="Level touch tolerance (%)" step={0.05} hint="spec Q1" />
            <NumberRow k="technique.min_touches" label="Min touches for a level" hint="T1.2: 2; strong = 3" />
            <NumberRow k="technique.plan.zone_merge_pct" label="Level zone merge (%)" step={0.25}
              hint="levels closer than this % are treated as one zone, not a ladder" />
            <NumberRow k="technique.volume_spike_mult" label="Volume spike (x baseline)" step={0.1} />
            <NumberRow k="technique.volume_dryup_mult" label="Volume dry-up (x baseline)" step={0.1} />
            <ToggleRow k="technique.options.enabled" label="Pick option contracts" hint="just-OTM strike, weekly/0DTE, greeks + IV warnings (T5) — data provider is set under Options" />
            <ToggleRow k="technique.emit_proposals" label="Valid setups become practice proposals" hint="approval still goes through the RiskGate" />
            <ToggleRow k="technique.scan.enabled" label="Scheduled scans" />
            <NumberRow k="technique.scan.interval_minutes" label="Scan interval (min)" />
            <ToggleRow k="technique.scan.rth_only" label="Scan only during US market hours" />
            <ListRow k="technique.scan.symbols" label="Scan symbols" hint="comma separated" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Appearance
            <span className="sub">theme, density, chart defaults</span></div>
          <div className="panel-body">
            <SelectRow k="ui.theme" label="Theme"
              options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
            <AccentRow />
            <SelectRow k="ui.density" label="Density"
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
            <SelectRow k="quotes.yahoo_poll_seconds" label="Tick speed"
              hint="how often the quote feed refreshes (applies live)"
              options={[
                { value: "10", label: "1 · calm" },
                { value: "6", label: "2 · easy" },
                { value: "3", label: "3 · market" },
                { value: "2", label: "4 · busy" },
                { value: "1", label: "5 · frantic" },
              ]} />
            <ToggleRow k="ui.chart.show_volume" label="Show volume pane" />
            <SelectRow k="ui.chart.type" label="Default chart type"
              options={[
                { value: "candlestick", label: "Candlestick" },
                { value: "ohlc", label: "OHLC bars" },
                { value: "line", label: "Line" },
              ]} />
            <SelectRow k="ui.chart.tf" label="Default timeframe"
              options={["1m", "5m", "15m", "1h"].map((t) => ({ value: t, label: t }))} />
            <DefaultSymbolRow />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Auto-trading (Arm)
            <span className="sub">how armed plans place and manage orders — safe defaults, change with care</span></div>
          <div className="panel-body">
            <ToggleRow k="technique.arm.enabled" label="Allow arming plans" hint="master switch — off means plans can't be armed at all" />
            <SelectRow k="technique.arm.mode" label="Default mode"
              hint="alert = watch only · propose = you approve each trade · auto = trades for you"
              options={[{ value: "alert", label: "Alert only" }, { value: "proposal", label: "Propose" }, { value: "auto", label: "Auto-trade" }]} />
            <SelectRow k="technique.arm.instrument" label="Default instrument"
              hint="this technique is built for options (buys a call); shares is the alternative"
              options={[{ value: "options", label: "Options" }, { value: "shares", label: "Shares" }]} />
            <NumberRow k="technique.arm.contracts" label="Contracts per trade" hint="book: 1 while learning (R5)" />
            <NumberRow k="technique.arm.risk_pct" label="Risk per trade (%)" step={0.25} hint="shares only — book: 0.5–1%" />
            <NumberRow k="technique.arm.daily_loss_limit" label="Daily loss limit ($)" step={10} hint="a plan flattens and stops for the day after losing this much; 0 = no limit" />
            <NumberRow k="technique.arm.max_open_trades" label="Max positions per plan" hint="how many trades one plan may hold at once" />
            <NumberRow k="technique.arm.flatten_minutes_before_close" label="Flatten before close (min)" hint="nothing is held overnight" />
            <ToggleRow k="technique.arm.skip_wide_spread" label="Skip options with a wide spread" hint="avoids contracts that lose money the moment you enter (T5.4)" />
            <ToggleRow k="technique.arm.skip_elevated_iv" label="Skip options with high volatility" hint="avoids IV-crush (T5.3); off by default" />
            <ToggleRow k="technique.arm.use_critic" label="AI double-check before auto-buying" hint="an AI reads the live chart and can veto a weak setup (needs an API key)" />
            <ToggleRow k="risk.halt_allows_exits" label="Kill switch still lets you sell" hint="ON (recommended): the halt stops new buys but stops/flatten can still close a position so you're never trapped" />
            <ToggleRow k="technique.arm.allow_live_auto" label="Allow auto-trade on REAL accounts" hint="off by default; auto on real money also needs LIVE mode and a per-plan tick" />
            <ListRow k="technique.arm.auto_symbols" label="Auto-arm at the open" hint="symbols to build + arm a plan for every morning; comma separated" />
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
  // select the raw value: a `?? []` inside the selector mints a new array every
  // render before the snapshot arrives -> React #185 loop on a /settings deep link
  const registryRaw = useStore((s) => s.settings["sources.registry"]);
  const registry: Source[] = Array.isArray(registryRaw) ? registryRaw : [];
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
