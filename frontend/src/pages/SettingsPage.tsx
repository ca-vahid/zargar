import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getAuthToken, setAuthToken } from "../lib/api";
import { useStore } from "../store";
import type { Watchlist } from "../types";
import { Modal } from "../components/Modal";

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

/* ── full-width rows (toggles, lists, anything that reads like a sentence) ── */

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

/* ── compact cells: label on top, control below, hint as tooltip ──────────
   several per line so a panel of numbers doesn't become a mile-long list */

function Cells({ children }: { children: ReactNode }) {
  return <div className="setting-cells">{children}</div>;
}

function Group({ children }: { children: ReactNode }) {
  return <div className="setting-group">{children}</div>;
}

function NumCell({ k, label, hint, step = 1 }: { k: string; label: string; hint?: string; step?: number }) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  const [draft, setDraft] = useState<string>("");
  const [editing, setEditing] = useState(false);
  return (
    <label className="setting-cell" title={hint}>
      <span className="cl">{label}</span>
      <input
        type="number"
        step={step}
        value={editing ? draft : value ?? ""}
        onFocus={() => { setDraft(String(value ?? "")); setEditing(true); }}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setEditing(false); if (draft !== "" && Number(draft) !== value) patch(k, Number(draft)); }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      />
    </label>
  );
}

function SelCell({ k, label, options, hint }: {
  k: string; label: string; hint?: string; options: { value: string; label: string }[];
}) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  return (
    <label className="setting-cell" title={hint}>
      <span className="cl">{label}</span>
      <select value={String(value ?? "")} onChange={(e) => patch(k, e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

function TextCell({ k, label, hint, upper }: { k: string; label: string; hint?: string; upper?: boolean }) {
  const value = useStore((s) => s.settings[k] ?? "");
  const patch = usePatch();
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <label className="setting-cell" title={hint}>
      <span className="cl">{label}</span>
      <input type="text" value={draft ?? value}
        onChange={(e) => setDraft(upper ? e.target.value.toUpperCase() : e.target.value)}
        onBlur={() => { if (draft !== null && draft !== value) patch(k, draft); setDraft(null); }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
    </label>
  );
}

function StatusRow({ label, hint, ok, text, dimWhenOff }: {
  label: string; hint?: string; ok: boolean; text: string; dimWhenOff?: boolean;
}) {
  return (
    <div className="setting-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <span className={`status-pill ${ok ? "ok" : dimWhenOff ? "dim" : "bad"}`}>{text}</span>
    </div>
  );
}

/* ── the evening automation hero card ─────────────────────────────────── */

function BigChoice({ k, label, hint, options }: {
  k: string; label: string; hint: string; options: { value: string; label: string }[];
}) {
  const value = useStore((s) => s.settings[k]);
  const patch = usePatch();
  return (
    <div className="auto-choice">
      <span className="cl">{label}</span>
      <select value={String(value ?? "")} onChange={(e) => patch(k, e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <span className="hint">{hint}</span>
    </div>
  );
}

function parseSymbols(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.split(/[\s,;]+/)) {
    const s = raw.trim().toUpperCase();
    if (s) seen.add(s);
  }
  return [...seen];
}

function SheetUniverse() {
  const sheetRaw = useStore((s) => s.settings["technique.sheet.symbols"]);
  const bookRaw = useStore((s) => s.settings["technique.walkforward.symbols"]);
  const setPage = useStore((s) => s.setPage);
  const setTechniqueTab = useStore((s) => s.setTechniqueTab);
  const patch = usePatch();
  const sheet: string[] = Array.isArray(sheetRaw) ? sheetRaw : [];
  const book: string[] = Array.isArray(bookRaw) ? bookRaw : [];
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const parsed = useMemo(() => parseSymbols(draft), [draft]);
  const custom = sheet.length > 0;
  return (
    <div className="auto-choice">
      <span className="cl">Sheet universe</span>
      <div className="universe-line">
        <b>{custom ? `${sheet.length} custom symbols` : `book universe · ${book.length} symbols`}</b>
        <button className="ghost-btn" onClick={() => {
          setDraft((custom ? sheet : book).join(", "));
          setOpen(true);
        }}>Edit…</button>
      </div>
      <span className="hint">
        the symbols the evening sheet grades — sheets themselves live in{" "}
        <a className="link-btn" onClick={() => { setPage("technique"); setTechniqueTab("validation"); }}>
          Technique → Validation
        </a>
      </span>
      {open && (
        <Modal title="Sheet universe" onClose={() => setOpen(false)}
          footer={
            <>
              <button className="ghost-btn" onClick={() => { void patch("technique.sheet.symbols", []); setOpen(false); }}>
                Use book universe ({book.length})
              </button>
              <span style={{ flex: 1 }} />
              <button className="ghost-btn" onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary-btn" disabled={parsed.length === 0}
                onClick={() => { void patch("technique.sheet.symbols", parsed); setOpen(false); }}>
                Save {parsed.length} symbols
              </button>
            </>
          }>
          <p className="muted" style={{ marginTop: 0 }}>
            Symbols separated by commas, spaces or new lines. US listings only (the sheet
            builder needs full-session 1m history). Leave it on the book universe unless you
            have a reason — a bigger list costs nothing to grade, but analyst-checking the
            extra A's does.
          </p>
          <textarea rows={9} style={{ width: "100%", boxSizing: "border-box" }}
            value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder="SPY, QQQ, NVDA…" />
        </Modal>
      )}
    </div>
  );
}

/* ── the page ─────────────────────────────────────────────────────────── */

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
  const alpacaConnected = (broker as any)?.alpacaConnected;

  return (
    <div>
      <h2 className="page-title">Settings</h2>
      <div className="panel mb settings-automation">
        <div className="panel-head">🌙 Evening automation
          <span className="sub">the daily ritual, hands-free: after the close, build tomorrow's graded sheet — and optionally analyst-check the A's</span></div>
        <div className="panel-body">
          <BigChoice k="technique.sheet.auto" label="After each close"
            hint="off = manual (Technique → Validation) · sheet = build the graded sheet automatically (free, deterministic) · + analyst = also run the LLM read on every grade-A setup (~$0.20 each), ready to bulk-arm"
            options={[{ value: "off", label: "do nothing (manual)" },
                      { value: "build", label: "build tomorrow's sheet (free)" },
                      { value: "analyst", label: "build sheet + analyst-check the A's ($)" }]} />
          <BigChoice k="technique.arm.mode" label="Default when arming"
            hint="what a one-click / bulk arm does when a trigger fires — changeable per plan afterwards on the Armed tab"
            options={[{ value: "alert", label: "alert only" },
                      { value: "proposal", label: "propose — I approve each trade" },
                      { value: "auto", label: "auto-trade (practice-safe; live needs extra gates)" }]} />
          <BigChoice k="technique.arm.entry_fallback" label="If the option can't be traded"
            hint="wide spread / high IV / no contract at fire time — SNOW lost +1.89R to a spread skip on 2026-08-25"
            options={[{ value: "off", label: "skip the trade" },
                      { value: "shares", label: "buy the shares instead" }]} />
          <SheetUniverse />
        </div>
      </div>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-head">Trading &amp; risk
            <span className="sub">order defaults + the gate every order must pass</span></div>
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
            <Group>Risk gate — every order passes all of these</Group>
            <Cells>
              <NumCell k="risk.max_position_notional" label="Max position ($)" step={100}
                hint="per symbol, in the account's currency — e.g. 1000 on a CAD account means C$1,000" />
              <NumCell k="risk.max_position_pct" label="Max position (% eq)" step={0.5}
                hint="resulting position vs account equity" />
              <NumCell k="risk.max_gross_exposure_pct" label="Gross exposure (%)" step={5}
                hint="sum of |position values| vs equity" />
              <NumCell k="risk.daily_loss_halt_pct" label="Daily loss halt (%)" step={0.5}
                hint="auto-engages the kill switch" />
              <NumCell k="risk.price_collar_pct" label="Price collar (%)" step={0.5}
                hint="fat-finger guard vs last price" />
              <NumCell k="risk.max_orders_per_minute" label="Orders / minute" />
              <NumCell k="risk.stale_quote_seconds" label="Stale quote (s)"
                hint="orders are rejected when the symbol's quote is older than this" />
              <NumCell k="trading.default_qty" label="Default order qty"
                hint="pre-filled quantity on the manual order ticket" />
            </Cells>
            <ToggleRow k="risk.allow_short" label="Allow short selling" />
            <ToggleRow k="risk.require_market_hours" label="Require market hours (live/paper)"
              hint="option orders always enforce regular hours — they have no extended session" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Technique &amp; LLM
            <span className="sub">EnhancedMarket pipeline + model effort</span></div>
          <div className="panel-body">
            <Group>Model</Group>
            <Cells>
              <SelCell k="llm.effort" label="Thinking depth"
                hint="low = fast/cheap; high = default; xhigh/max = deepest reasoning, slower"
                options={["low", "medium", "high", "xhigh", "max"].map((v) => ({ value: v, label: v }))} />
              <SelCell k="llm.thinking_display" label="Show thinking"
                hint="summarized streams the model's reasoning live; raw chain-of-thought is never returned by the API"
                options={[{ value: "summarized", label: "summarized" }, { value: "omitted", label: "omitted" }]} />
              <NumCell k="llm.max_passes" label="Max calls / run" hint="context, pattern, entry, critic + retries" />
              <NumCell k="technique.max_runs_per_day" label="Daily run cap" hint="cost guard across manual + scans" />
            </Cells>
            <Group>Method thresholds — check docs/TRADING-RULES.md before tuning</Group>
            <Cells>
              <SelCell k="technique.trigger_tf" label="Trigger timeframe"
                hint="where entries/triggers are decided — used by manual runs, session plans, sweeps and armed plans"
                options={[{ value: "1m", label: "1m" }, { value: "5m", label: "5m" }, { value: "15m", label: "15m" }]} />
              <NumCell k="technique.min_risk_reward" label="Min reward:risk" step={0.5} hint="R2 — book: 1:3" />
              <NumCell k="technique.default_risk_pct" label="Analysis risk (%)" step={0.25}
                hint="sizing the pipeline assumes when judging a setup (book: 0.5–1%) — armed plans size with their own knob" />
              <NumCell k="technique.max_risk_pct" label="Max risk (%)" step={0.5} hint="book: 5% ceiling" />
              <NumCell k="technique.max_stop_pct" label="Max stop dist (%)" step={0.5}
                hint="T4.3a/R1 — widest chart-justified stop as % of entry; wider setups are skipped" />
              <NumCell k="technique.level_tolerance_pct" label="Touch tolerance (%)" step={0.05} hint="spec Q1" />
              <NumCell k="technique.min_touches" label="Min level touches" hint="T1.2: 2; strong = 3" />
              <NumCell k="technique.plan.zone_merge_pct" label="Zone merge (%)" step={0.25}
                hint="levels closer than this % are one zone, not a ladder" />
              <NumCell k="technique.volume_spike_mult" label="Volume spike (×)" step={0.1} hint="× baseline" />
              <NumCell k="technique.volume_dryup_mult" label="Volume dry-up (×)" step={0.1} hint="× baseline" />
            </Cells>
            <ToggleRow k="technique.options.enabled" label="Pick option contracts"
              hint="just-OTM strike, weekly/0DTE, greeks + IV warnings (T5) — data provider is set under Options" />
            <ListRow k="technique.scan.symbols" label="Watch-list scan symbols"
              hint='used by Scan now → "Watch list" — a live read not tied to the sheet' />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Auto-trading (Arm)
            <span className="sub">how armed plans place and manage orders — the default mode lives in Evening automation above</span></div>
          <div className="panel-body">
            <ToggleRow k="technique.arm.enabled" label="Allow arming plans" hint="master switch — off means plans can't be armed at all" />
            <Group>Sizing</Group>
            <Cells>
              <SelCell k="technique.arm.instrument" label="Instrument"
                hint="this technique is built for options (buys a call); shares is the alternative"
                options={[{ value: "options", label: "options" }, { value: "shares", label: "shares" }]} />
              <NumCell k="technique.arm.contracts" label="Contracts / trade" hint="book: 1 while learning (R5)" />
              <NumCell k="technique.arm.risk_pct" label="Risk / trade (%)" step={0.25} hint="shares only — book: 0.5–1%" />
              <NumCell k="technique.arm.daily_loss_limit" label="Daily loss limit ($)" step={10}
                hint="a plan flattens and stops for the day after losing this much; 0 = no limit" />
              <NumCell k="technique.arm.max_open_trades" label="Max positions" hint="how many trades one plan may hold at once" />
              <NumCell k="technique.arm.flatten_minutes_before_close" label="Flatten before close" hint="minutes — nothing is held overnight" />
            </Cells>
            <Group>Safety</Group>
            <ToggleRow k="technique.arm.skip_wide_spread" label="Skip options with a wide spread" hint="avoids contracts that lose money the moment you enter (T5.4) — the entry fallback above can buy shares instead" />
            <ToggleRow k="technique.arm.skip_elevated_iv" label="Skip options with high volatility" hint="avoids IV-crush (T5.3); off by default" />
            <ToggleRow k="technique.arm.use_critic" label="AI double-check before auto-buying" hint="an AI reads the live chart and can veto a weak setup (needs an API key)" />
            <ToggleRow k="risk.halt_allows_exits" label="Kill switch still lets you sell" hint="ON (recommended): the halt stops new buys but stops/flatten can still close a position so you're never trapped" />
            <ToggleRow k="technique.arm.allow_live_auto" label="Allow auto-trade on REAL accounts" hint="off by default; auto on real money also needs LIVE mode and a per-plan tick" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Options
            <span className="sub">contracts, risk caps, venue, data provider</span></div>
          <div className="panel-body">
            <ToggleRow k="risk.allow_options" label="Allow option orders" />
            <ToggleRow k="risk.allow_0dte" label="Allow 0DTE contracts"
              hint="the EnhancedMarket method trades weeklies/0DTE — off blocks same-day expiries" />
            <Group>Per-order caps</Group>
            <Cells>
              <NumCell k="risk.max_option_contracts" label="Max contracts" />
              <NumCell k="risk.max_option_premium_notional" label="Max premium ($)" step={50}
                hint="qty × price × 100, buys only; closes are exempt" />
              <NumCell k="risk.max_option_premium_pct" label="Premium (% eq)" step={0.5} />
              <NumCell k="risk.max_option_spread_pct" label="Max spread (%)" step={1}
                hint="market orders on wider spreads are rejected; limits get a warning" />
              <NumCell k="options.fee_per_contract" label="Fee / contract ($)" step={0.01}
                hint="Webull Canada: US$0.99/contract + regulatory fees — used by the ticket estimate" />
              <NumCell k="options.enrich_seconds" label="Quote refresh (s)"
                hint="how often tracked contracts re-read bid/ask from the chain" />
            </Cells>
            <SelectRow k="options.provider" label="Chain data provider"
              hint="CBOE is free with greeks, ~15-min delayed, works in Canada. Tradier needs a US-signup token."
              options={[{ value: "cboe", label: "CBOE delayed (free)" }, { value: "tradier", label: "Tradier (token)" }]} />
            <ListRow k="snaptrade.options_brokers" label="Brokerages that may route option orders"
              hint="verified 2026-08-21: Webull Canada yes, Wealthsimple no (SnapTrade code 1156)" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Data &amp; connections
            <span className="sub">quote feeds, brokerages, external services</span></div>
          <div className="panel-body">
            <StatusRow label="Quote feed" hint="configured via environment"
              ok={Boolean(broker?.feedConnected)} text={broker?.feed ?? "?"} />
            {alpacaConnected !== undefined && alpacaConnected !== null && (
              <StatusRow label="Alpaca stream" hint="full-SIP live quotes for US symbols; Yahoo covers the rest"
                ok={Boolean(alpacaConnected)} text={alpacaConnected ? "streaming" : "down — Yahoo fallback"} />
            )}
            <StatusRow label="SnapTrade" hint="Wealthsimple + Webull via aggregator" dimWhenOff
              ok={Boolean(broker?.snaptradeConnected)} text={broker?.snaptradeConnected ? "connected" : "off"} />
            <StatusRow label="IBKR gateway" hint="native connection for live/paper" dimWhenOff
              ok={Boolean(broker?.ibkrConnected)} text={broker?.ibkrConnected ? "connected" : "off"} />
            <Group>SnapTrade</Group>
            <ToggleRow k="snaptrade.enabled" label="Enable SnapTrade"
              hint="needs ZARGAR_SNAPTRADE_* credentials in .env, restart backend" />
            <Cells>
              <NumCell k="snaptrade.sync_minutes" label="Account sync (min)" />
              <NumCell k="snaptrade.order_poll_seconds" label="Order poll (s)" step={0.5} />
              <NumCell k="quotes.yahoo_poll_seconds" label="Yahoo poll (s)" step={0.5}
                hint="pace of the Yahoo fallback — used for non-US symbols always, and for everything when the Alpaca stream is down" />
            </Cells>
            <ToggleRow k="snaptrade.allow_brackets" label="Allow bracket orders"
              hint="off by default — broker support varies" />
            <ToggleRow k="telegram.enabled" label="Telegram approvals"
              hint="needs ZARGAR_TELEGRAM_BOT_TOKEN + CHAT_ID, restart backend" />
            <ApiTokenRow />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Newsletter signals
            <span className="sub">email alerts → verified proposals (Signals page)</span></div>
          <div className="panel-body">
            <Cells>
              <NumCell k="signals.default_sizing_pct" label="Sizing (% equity)" step={0.5} />
              <NumCell k="signals.default_ttl_minutes" label="Proposal TTL (min)" />
              <NumCell k="verification.max_price_deviation_pct" label="Price deviation (%)" step={0.5}
                hint="reject stale alerts — live price vs claimed entry" />
              <NumCell k="verification.max_spread_pct" label="Max spread (%)" step={0.1}
                hint="liquidity / pump filter" />
              <NumCell k="verification.min_price" label="Min price ($)" step={0.5}
                hint="penny-stock filter" />
            </Cells>
            <ToggleRow k="verification.require_actionable" label="Require explicit actionable call" />
            <Group>Sources — match inbound senders to names</Group>
            <SourcesSection />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Appearance
            <span className="sub">theme, density, chart defaults</span></div>
          <div className="panel-body">
            <Cells>
              <SelCell k="ui.theme" label="Theme"
                options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
              <SelCell k="ui.density" label="Density"
                options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
              <AccentCell />
              <SelCell k="ui.chart.type" label="Chart type"
                options={[
                  { value: "candlestick", label: "Candlestick" },
                  { value: "ohlc", label: "OHLC bars" },
                  { value: "line", label: "Line" },
                ]} />
              <SelCell k="ui.chart.tf" label="Chart timeframe"
                options={["1m", "5m", "15m", "1h"].map((t) => ({ value: t, label: t }))} />
              <TextCell k="ui.default_symbol" label="Default symbol" upper />
            </Cells>
            <ToggleRow k="ui.chart.show_volume" label="Show volume pane" />
          </div>
        </div>

        <WatchlistsPanel />
      </div>
    </div>
  );
}

function AccentCell() {
  const value = useStore((s) => s.settings["ui.accent"] ?? "#5b8cff");
  const patch = usePatch();
  return (
    <label className="setting-cell">
      <span className="cl">Accent color</span>
      <input type="color" value={value} style={{ height: 28, padding: 2 }}
        onChange={(e) => patch("ui.accent", e.target.value)} />
    </label>
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

function SourcesSection() {
  // select the raw value: a `?? []` inside the selector mints a new array every
  // render before the snapshot arrives -> React #185 loop on a /settings deep link
  const registryRaw = useStore((s) => s.settings["sources.registry"]);
  const registry: Source[] = Array.isArray(registryRaw) ? registryRaw : [];
  const patch = usePatch();
  const [name, setName] = useState("");
  const [emails, setEmails] = useState("");

  const save = (next: Source[]) => patch("sources.registry", next);

  return (
    <>
      {registry.length === 0 && (
        <div className="muted" style={{ margin: "6px 0 8px" }}>
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
    </>
  );
}
