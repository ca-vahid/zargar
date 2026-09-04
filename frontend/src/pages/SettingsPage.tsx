import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, getAuthToken, setAuthToken } from "../lib/api";
import { useStore } from "../store";
import { useViewport } from "../lib/viewport";
import { InfoTip } from "../components/InfoTip";
import type { Watchlist } from "../types";
import { Modal } from "../components/Modal";
import { signOut } from "../lib/auth";

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
      <span className="cl">{label}{hint && <InfoTip>{hint}</InfoTip>}</span>
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
      <span className="cl">{label}{hint && <InfoTip>{hint}</InfoTip>}</span>
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
      <span className="cl">{label}{hint && <InfoTip>{hint}</InfoTip>}</span>
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

function ExtraUniverse() {
  const extraRaw = useStore((s) => s.settings["technique.universe.extra"]);
  const bookRaw = useStore((s) => s.settings["technique.walkforward.symbols"]);
  const patch = usePatch();
  const extra: string[] = Array.isArray(extraRaw) ? extraRaw : [];
  const book: string[] = Array.isArray(bookRaw) ? bookRaw : [];
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const parsed = useMemo(() => parseSymbols(draft), [draft]);
  return (
    <div className="auto-choice">
      <span className="cl">Extra symbols</span>
      <div className="universe-line">
        <b>{extra.length ? `${extra.length} of yours` : "none"} · core {book.length}</b>
        <button className="ghost-btn" onClick={() => { setDraft(extra.join(", ")); setOpen(true); }}>Edit…</button>
      </div>
      <span className="hint">
        anything here is planned, sheeted and armable alongside the core universe and the day's most-active names
      </span>
      {open && (
        <Modal title="Extra symbols" onClose={() => setOpen(false)}
          footer={
            <>
              <button className="ghost-btn" onClick={() => { void patch("technique.universe.extra", []); setOpen(false); }}>Clear</button>
              <span style={{ flex: 1 }} />
              <button className="ghost-btn" onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary-btn" onClick={() => { void patch("technique.universe.extra", parsed); setOpen(false); }}>
                Save {parsed.length} symbols
              </button>
            </>
          }>
          <p className="muted" style={{ marginTop: 0 }}>Comma or space separated. US listings only (options chains come from CBOE).</p>
          <textarea rows={6} style={{ width: "100%" }} value={draft} onChange={(e) => setDraft(e.target.value)} />
        </Modal>
      )}
    </div>
  );
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
        <b>{custom ? `${sheet.length} custom symbols` : `core universe · ${book.length} + extras + today's most active`}</b>
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
                Use the core universe ({book.length})
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

/** Who is signed in, and the way out — on every device (the phone reaches it via More → Settings). */
function AccountPanel() {
  const auth = useStore((s) => s.auth);
  const [busy, setBusy] = useState(false);
  if (!auth.required || !auth.user) return null;
  const u = auth.user;
  return (
    <div className="panel mb account-panel">
      <div className="panel-head">Account <span className="sub">signed in with {u.provider === "google" ? "Google" : u.provider}</span></div>
      <div className="panel-body account-row">
        {u.picture ? <img className="account-pic" src={u.picture} alt="" referrerPolicy="no-referrer" />
          : <span className="account-pic account-initial">{(u.name || u.email).slice(0, 1).toUpperCase()}</span>}
        <div className="account-who">
          <b>{u.name || u.email}</b>
          {u.name && <span className="muted small">{u.email}</span>}
          <span className="muted small">Signing out ends the session in this browser only; other devices stay signed in.</span>
        </div>
        <button className="ghost-btn account-signout" disabled={busy}
          onClick={() => { setBusy(true); void signOut().finally(() => setBusy(false)); }}>Sign out</button>
      </div>
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
  const alpacaConnected = (broker as any)?.alpacaConnected;
  // phones: every settings panel folds behind its header (Appearance stays open)
  const { isPhone } = useViewport();
  const gridRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const panels = Array.from(grid.querySelectorAll<HTMLElement>(":scope > .panel"));
    for (const p of panels) {
      const head = p.querySelector<HTMLElement>(":scope > .panel-head");
      const title = head?.textContent?.trim().toLowerCase() ?? "";
      p.classList.toggle("panel--folded", isPhone && !title.startsWith("appearance"));
    }
    if (!isPhone) return;
    const onClick = (e: Event) => {
      const head = (e.target as HTMLElement).closest(".settings-grid > .panel > .panel-head");
      if (!head || (e.target as HTMLElement).closest("button, input, select, a, label")) return;
      head.parentElement?.classList.toggle("panel--folded");
    };
    grid.addEventListener("click", onClick);
    return () => grid.removeEventListener("click", onClick);
  }, [isPhone]);

  return (
    <div className="settings-page">
      <h2 className="page-title">Settings</h2>
      <AccountPanel />
      <MobilePanel />
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
            <ExtraUniverse />
        </div>
      </div>
      <div className="settings-grid" ref={gridRef}>
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
            <Group>Method thresholds — check docs/techniques/enhanced-market/TRADING-RULES.md before tuning</Group>
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
            <span className="sub">how armed plans place and manage orders — shared by EVERY technique (a tip-specific override in Tips below wins); the default mode lives in Evening automation above</span></div>
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
            <Cells>
              <SelCell k="technique.arm.critic_effort" label="Critic speed"
                hint="thinking depth of the fire-time AI double-check — low answers in seconds, which matters when a trigger just fired"
                options={[{ value: "low", label: "fast (low)" }, { value: "medium", label: "medium" }, { value: "high", label: "deep (high)" }]} />
              <NumCell k="technique.arm.critic_kills_per_day" label="Vetoes / trigger / day"
                hint="after this many AI vetoes a trigger stays down for the day" />
              <NumCell k="technique.arm.refire_cooldown_minutes" label="Refire cooldown (min)"
                hint="wait after a veto before the same trigger may fire again — stops one squeeze from burning every veto in minutes" />
            </Cells>
            <ToggleRow k="technique.arm.skip_wide_spread" label="Skip options with a wide spread" hint="avoids contracts that lose money the moment you enter (T5.4) — the entry fallback above can buy shares instead" />
            <ToggleRow k="technique.arm.skip_elevated_iv" label="Skip options with high volatility" hint="avoids IV-crush (T5.3); off by default" />
            <ToggleRow k="technique.arm.use_critic" label="AI double-check before auto-buying" hint="an AI reads the live chart and can veto a weak setup (needs an API key)" />
            <ToggleRow k="risk.halt_allows_exits" label="Kill switch still lets you sell" hint="ON (recommended): the halt stops new buys but stops/flatten can still close a position so you're never trapped" />
            <ToggleRow k="technique.arm.allow_live_auto" label="Allow auto-trade on REAL accounts" hint="off by default; auto on real money also needs LIVE mode and a per-plan tick" />
            <Group>Experiments</Group>
            <ToggleRow k="technique.arm.midday_trading" label="Trade during mid-day (R6.3 experiment)"
              hint="normally 10:30–14:45 ET is watch-only; ON lets armed triggers fire mid-day. Fires carry window=midday so outcomes stay separable — the experiment lives in TRADING-RULES 1.7" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Team2 technique
            <span className="sub">Casey/@Team2Trading's 0DTE index method — its own read, its own 0DTE policy; the shared order/exit machinery above still applies</span></div>
          <div className="panel-body">
            <ToggleRow k="techniques.team2.enabled" label="Enabled" hint="nightly plans + 09:25 completion for SPY · QQQ · IWM" />
            <SelectRow k="techniques.team2.mode" label="Mode"
              hint="alert records what the method would do; proposal and auto are earned after the sweep and the practice soak"
              options={[{ value: "alert", label: "alert only" }, { value: "proposal", label: "propose — I approve each trade" },
                        { value: "auto", label: "auto — practice account only until allowed live" }]} />
            <Group>Read</Group>
            <Cells>
              <NumCell k="techniques.team2.fan_trend_min_atr" label="EMA fan: trend ≥ (ATR)" step={0.05}
                hint="spread of the 13/48/200 EMAs in 2m ATRs below which the stack is chop (no trade)" />
              <NumCell k="techniques.team2.pm_tol_atr" label="Touch tolerance (ATR)" step={0.05}
                hint="how close to the EMA13 / pre-market level a 2m bar must reach to count as a touch" />
              <NumCell k="techniques.team2.pullback_max_touches" label="Pullbacks taken" hint="first N EMA13 touches after confirmation; later ones are watch-only" />
              <NumCell k="techniques.team2.pullback_body_mult" label="Engulfing filter (× avg body)" step={0.25}
                hint="a touching bar with a body above this many average bodies is a lunge, not a drift — skipped" />
              <NumCell k="techniques.team2.max_reentries" label="Re-entries per setup" />
              <NumCell k="techniques.team2.max_losses_per_day" label="Max losses / day" />
            </Cells>
            <ToggleRow k="techniques.team2.range_day_confirmation" label="Range days need the PM level" hint="reject-PDH / bounce-PDL scenarios fire only once price is beyond the pre-market level on the trade's side" />
            <ToggleRow k="techniques.team2.shrink_after_win" label="Shrink after a win" hint="the next trade's size halves once the day is green — one loss can never erase the day" />
            <ToggleRow k="techniques.team2.avoid_event_days" label="Skip macro event days" hint="FOMC/CPI/NFP days from the manual macro list (research.macro_events) take no new entries" />
            <Group>Expression &amp; exits (0DTE)</Group>
            <Cells>
              <NumCell k="techniques.team2.target_premium" label="Target premium ($)" step={0.05}
                hint="the first out-of-the-money strike whose ask is at or under this — the author's ~$0.50 contract" />
              <NumCell k="techniques.team2.premium_floor" label="Premium floor ($)" step={0.05} hint="never buy cheaper than this" />
              <NumCell k="techniques.team2.premium_stop_pct" label="Premium stop (%)" step={5} hint="hard cap under the one-candle stop (author: ~20%)" />
              <NumCell k="techniques.team2.trim_1_pct" label="First trim at (+%)" step={10} />
              <NumCell k="techniques.team2.trim_2_pct" label="Second trim at (+%)" step={10} />
              <NumCell k="techniques.team2.budget_per_trade" label="Budget / trade ($)" step={50}
                hint="premium per full-size entry in practice; the platform's per-order caps still apply" />
            </Cells>
            <ToggleRow k="techniques.team2.target_exit" label="Sell at target" hint="the pre-planned next level closes the rest of the position on touch" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">Tips technique
            <span className="sub">the tip pipeline's own knobs — the shared order/exit machinery above still applies unless a tip-specific override is set</span></div>
          <div className="panel-body">
            <SelectRow k="techniques.tip.mode" label="Default source mode"
              hint="the trust ladder every source starts on — auto self-approves only when the analyst says 'take' (practice-safe; real money also needs the gate below). A per-source override in Tips → Sources beats this"
              options={[{ value: "shadow", label: "shadow — books only, never proposes" },
                        { value: "alert", label: "alert only" },
                        { value: "proposal", label: "propose — I approve each trade" },
                        { value: "auto", label: "auto — analyst 'take' self-approves" }]} />
            <Group>Budgets &amp; expression</Group>
            <Cells>
              <NumCell k="techniques.tip.budget_per_tip" label="Budget / tip ($)" step={50}
                hint="max $ committed to one tip (option debit / share notional) — the arm card warns when this clashes with the risk caps" />
              <NumCell k="techniques.tip.budget_open_max" label="Open budget cap ($)" step={100}
                hint="max $ open across one source's tips at once" />
              <NumCell k="techniques.tip.dte_min" label="Min DTE" hint="option expression window — never 0DTE" />
              <NumCell k="techniques.tip.dte_max" label="Max DTE" />
              <NumCell k="techniques.tip.entry_cutoff_dte" label="Entry cutoff (DTE)"
                hint="stop entering when the tip's contract is this close to expiry — also the fire-time floor on a stated expiry" />
              <NumCell k="techniques.tip.max_chase_pct" label="Never-chase (%)" step={1}
                hint="an armed fire pays at most the stated premium × (1 + this %); above it the entry rests at the cap" />
              <NumCell k="techniques.tip.horizon_sessions" label="Wait horizon (sessions)"
                hint="how long a level-touch tip may stay armed (multi-day plans roll at each close)" />
              <NumCell k="techniques.tip.max_tip_age_hours" label="Max tip age (h)"
                hint="older content is replayed on history, never traded" />
            </Cells>
            <Group>Analyst &amp; learning</Group>
            <ToggleRow k="techniques.tip.analyst_enabled" label="Appraise every tip" hint="the Tips Analyst runs on each tradable tip (LLM)" />
            <ToggleRow k="techniques.tip.review_enabled" label="Review follow-ups" hint="non-tradable updates ('sold 40%', 'I'm out') are reviewed against the desk's open items" />
            <ToggleRow k="techniques.tip.analyst_manage_enabled" label="Analyst may manage" hint="exit-only: rewrite exit campaigns, trim/close positions, disarm waiting plans" />
            <ToggleRow k="techniques.tip.retro_enabled" label="Nightly self-review" hint="position retros + unfilled-tip batches + lane grading, 17:10 ET" />
            <ToggleRow k="techniques.tip.seen_again_reappraise" label="Re-appraise repeats" hint="a re-posted tip with a live waiting plan gets a fresh appraisal" />
            <ToggleRow k="techniques.tip.seen_again_extends" label="Repeats extend the wait" hint="a re-post pushes the waiting plan's horizon window forward" />
            <Group>Safety</Group>
            <Cells>
              <NumCell k="techniques.tip.auto_min_graded" label="Auto: graded tips needed"
                hint="earned auto — closed tip positions a source needs before the default auto self-approves; an explicit per-source auto (Tips → Sources) bypasses" />
              <NumCell k="techniques.tip.auto_min_hit" label="Auto: min hit rate" step={0.05}
                hint="earned auto — minimum winning fraction of those closed positions" />
            </Cells>
            <ToggleRow k="techniques.tip.shadow_auto" label="Shadow books" hint="every open tip auto-arms in its source's shadow book each morning — the track record real money is gated on" />
            <ToggleRow k="techniques.tip.allow_live_auto" label="Auto mode may trade REAL accounts" hint="off by default — a live portfolio needs this AND the source's earned auto mode" />
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
  const auth = useStore((s) => s.auth);
  const setAuth = useStore((s) => s.setAuth);
  const signOut = async () => {
    try { await api.authLogout(); } catch { /* cookie may already be gone */ }
    setAuthToken(""); localStorage.removeItem("zargar_token");
    setAuth({ user: null });
    toast("info", "signed out"); setTimeout(() => location.reload(), 300);
  };
  return (
    <>
      {auth.user && auth.user.provider !== "open" && (
        <div className="setting-row">
          <div className="lbl">Signed in as<small>{auth.user.email} · via {auth.user.provider}</small></div>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            {auth.user.picture && <img src={auth.user.picture} alt="" width={28} height={28} style={{ borderRadius: "50%" }} referrerPolicy="no-referrer" />}
            <button type="button" className="ghost-btn" onClick={signOut}>Sign out</button>
          </span>
        </div>
      )}
    <div className="setting-row">
      <div className="lbl">API token<small>for scripts / CLI (ZARGAR_AUTH_TOKEN); sign-in sessions don't need it</small></div>
      <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setAuthToken(draft); toast("info", "API token saved locally"); }} />
    </div>
    </>
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


/* ── Mobile: the phone's own safety + session controls ─────────────────── */
function MobilePanel() {
  const toast = useStore((s) => s.toast);
  const chgDollar = useStore((s) => s.chgDollar);
  const toggleChgMode = useStore((s) => s.toggleChgMode);
  return (
    <div className="panel mb settings-mobile">
      <div className="panel-head">📱 Mobile
        <span className="sub">what a phone may do — and how it signs in</span></div>
      <div className="panel-body">
        <ToggleRow k="mobile.exit_only" label="Phone is exit-only for LIVE"
          hint="On (default): from a phone you can HALT, flatten, disarm, approve and SELL out of real positions, but not open new ones. Turn off to allow live entries from a phone (the confirm sheet still asks)." />
        <div className="setting-row">
          <div className="lbl">Day change shows<small>the pill next to every price</small></div>
          <div className="seg" role="group" aria-label="Day change unit">
            <button type="button" className={!chgDollar ? "on" : ""} onClick={() => { if (chgDollar) toggleChgMode(); }}>%</button>
            <button type="button" className={chgDollar ? "on" : ""} onClick={() => { if (!chgDollar) toggleChgMode(); }}>$</button>
          </div>
        </div>
        <PushRow />
        <InstallRow />
        <div className="setting-row">
          <div className="lbl">Phone link<small>the address phones open the app at (Tailscale HTTPS) — Telegram alerts get an "Open in Zargar" button</small></div>
          <TextCell k="mobile.public_url" label="" />
        </div>
        <div className="setting-row">
          <div className="lbl">This device<small>forget the sign-in token stored in this browser</small></div>
          <button type="button" className="ghost-btn" onClick={async () => {
            try { await api.authLogout(); } catch { /* ignore */ }
            setAuthToken(""); localStorage.removeItem("zargar_token");
            toast("info", "signed out on this device"); setTimeout(() => location.reload(), 400);
          }}>Sign out</button>
        </div>
      </div>
    </div>
  );
}


function urlB64ToUint8Array(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

/** Web Push opt-in for this browser (needs HTTPS or localhost + a registered service worker). */
function PushRow() {
  const toast = useStore((s) => s.toast);
  const [state, setState] = useState<"unknown" | "unsupported" | "off" | "on" | "busy">("unknown");
  const [count, setCount] = useState(0);
  const [available, setAvailable] = useState(true);
  useEffect(() => {
    (async () => {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) { setState("unsupported"); return; }
      try {
        const v = await api.pushVapid(); setCount(v.subscriptions); setAvailable(v.available);
        const reg = await navigator.serviceWorker.getRegistration();
        const sub = await reg?.pushManager.getSubscription();
        setState(sub ? "on" : "off");
      } catch { setState("off"); }
    })();
  }, []);
  const enable = async () => {
    setState("busy");
    try {
      const v = await api.pushVapid();
      if (!v.available || !v.publicKey) throw new Error("server has no push support (pywebpush)");
      const reg = await navigator.serviceWorker.ready;
      const perm = await Notification.requestPermission();
      if (perm !== "granted") throw new Error("notifications were not allowed");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(v.publicKey) as any });
      const j = sub.toJSON();
      const r = await api.pushSubscribe({ endpoint: j.endpoint!, keys: (j.keys ?? {}) as Record<string, string>, label: navigator.userAgent.slice(0, 60) });
      setCount(r.subscriptions); setState("on"); toast("success", "push notifications on for this device");
    } catch (e: any) { toast("error", e.message); setState("off"); }
  };
  const disable = async () => {
    setState("busy");
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub) { await api.pushUnsubscribe(sub.endpoint).catch(() => undefined); await sub.unsubscribe(); }
      setState("off"); toast("info", "push notifications off for this device");
    } catch (e: any) { toast("error", e.message); setState("on"); }
  };
  return (
    <div className="setting-row">
      <div className="lbl">Push notifications<small>
        fires, exits, failed exits, loss halts, proposals and the kill switch reach this phone even when the app is closed
        {count ? ` · ${count} device(s) subscribed` : ""}{!available ? " · server: pywebpush missing" : ""}
      </small></div>
      {state === "unsupported" ? <span className="muted small">not supported in this browser (needs HTTPS + install)</span>
        : state === "on" ? (
          <span style={{ display: "inline-flex", gap: 8 }}>
            <button type="button" className="ghost-btn" onClick={() => api.pushTest().then((r) => toast("info", `sent to ${r.sent} device(s)`)).catch((e) => toast("error", e.message))}>Test</button>
            <button type="button" className="ghost-btn" onClick={disable}>Turn off</button>
          </span>
        ) : <button type="button" className="primary-btn" disabled={state === "busy" || state === "unknown"} onClick={enable}>Enable on this device</button>}
    </div>
  );
}

/** Install prompt (Android/desktop Chrome fire beforeinstallprompt; iOS is manual). */
function InstallRow() {
  const [prompt, setPrompt] = useState<any>(null);
  const [installed, setInstalled] = useState(() => window.matchMedia("(display-mode: standalone)").matches);
  useEffect(() => {
    const onPrompt = (e: any) => { e.preventDefault(); setPrompt(e); };
    const onInstalled = () => { setInstalled(true); setPrompt(null); };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => { window.removeEventListener("beforeinstallprompt", onPrompt); window.removeEventListener("appinstalled", onInstalled); };
  }, []);
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  return (
    <div className="setting-row">
      <div className="lbl">Install as an app<small>
        {installed ? "running as an installed app" : ios ? "iPhone: Share → \u201cAdd to Home Screen\u201d — it opens on the Now screen" : "home-screen icon, full screen, opens on the Now screen"}
      </small></div>
      {installed ? <span className="status-pill ok">installed</span>
        : prompt ? <button type="button" className="primary-btn" onClick={() => prompt.prompt()}>Install</button>
        : <span className="muted small">{ios ? "use Share → Add to Home Screen" : "use the browser menu → Install app"}</span>}
    </div>
  );
}
