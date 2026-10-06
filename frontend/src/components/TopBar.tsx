import { useEffect, useMemo, useRef, useState } from "react";
import { useDisplayCurrency, useToDisplay } from "../lib/displayCurrency";
import { api } from "../lib/api";
import { fmtCcy } from "../lib/format";
import { netWorthByCurrency, useStore } from "../store";
import { ConfirmDialog, PromptDialog } from "./Modal";
import { SymbolSearch, type SymbolHit } from "./SymbolSearch";
import { useLiveTotal } from "../lib/liveEquity";
import { useLiveRouting, useWorkspace, workspaceOf } from "../lib/workspace";
import { useViewport } from "../lib/viewport";
import { Sheet } from "./Sheet";
import { IconSearch } from "./icons";
import { signOut } from "../lib/auth";
import { APP_VERSION } from "../changelog";
import { ChangelogDialog } from "./ChangelogDialog";
import { attentionSummary } from '../lib/armedAttention';

const MODES = [
  { value: "practice", label: "Practice" },
  { value: "live", label: "LIVE" },
];
// The switch is a WORKSPACE VIEW (W6.5, 2026-10-03): it scopes every account-shaped view (money, accounts,
// blotter, armed plans) in this browser only. Real-order routing is its own switch next to HALT (trading.mode on
// the server) - Practice and the live books keep trading whichever view is on screen.

export function TopBar() {
  const connected = useStore((s) => s.connected);
  const halt = useStore((s) => s.halt);
  const mode = useWorkspace();                       // the VIEW
  const routing = useLiveRouting();                  // real orders route to live/paper accounts
  const setView = useStore((s) => s.setViewWorkspace);
  const [confirmRoutingOff, setConfirmRoutingOff] = useState(false);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const portfolios = useStore((s) => s.portfolios);
  const broker = useStore((s) => s.broker);
  const toast = useStore((s) => s.toast);

  const brokerages = useStore((s) => s.brokerages);
  const setPage = useStore((s) => s.setPage);
  const setMoreOpen = useStore((s) => s.setMoreOpen);
  const openTrade = useStore((s) => s.openTrade);
  const watchlists = useStore((s) => s.watchlists);
  const setWatchlists = useStore((s) => s.setWatchlists);
  const searchRef = useRef<HTMLInputElement>(null);
  const [confirmLive, setConfirmLive] = useState(false);
  const [promptHalt, setPromptHalt] = useState(false);
  const [confirmResume, setConfirmResume] = useState(false);
  const { isPhone } = useViewport();
  const authUser = useStore((s) => s.auth.user);
  const authRequired = useStore((s) => s.auth.required);
  const [accountOpen, setAccountOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [changelog, setChangelog] = useState(false);

  // real money is the headline; practice is its own clearly-labeled chip
  const realTotals = useMemo(
    () => netWorthByCurrency(portfolios, brokerages).filter((t) => t.brokerage > 0),
    [portfolios, brokerages]);
  // ONE number in the display currency (2026-10-05): the SnapTrade accounts plus every REAL (kind live) app book -
  // a funded IBKR live book counts; IBKR paper never does
  const [dispCcy] = useDisplayCurrency();
  const toDisp = useToDisplay();
  const realOne = useMemo(() => {
    const parts: [number, string][] = [];
    const brokeragePids = new Set((brokerages?.providers ?? []).flatMap((pr) => pr.accounts.map((a) => a.portfolioId)));
    for (const pr of brokerages?.providers ?? []) for (const a of pr.accounts) parts.push([a.equity, a.currency]);
    for (const p of portfolios) {
      if (p.kind !== "live" || p.archived || brokeragePids.has(p.id)) continue;
      parts.push([p.equity ?? p.cash, p.baseCurrency ?? "USD"]);
    }
    let sum = 0;
    for (const [v, c] of parts) {
      const d = toDisp(v, c);
      if (d == null) return null;
      sum += d;
    }
    return sum > 0 ? sum : null;
  }, [portfolios, brokerages, toDisp]);
  const practice = useMemo(
    () => portfolios.filter((p) => p.kind === "sim" && !p.archived), [portfolios]);
  // marked to the live tape, not to the 30 s server push: the chip used to
  // sit still between pushes while quotes arrived behind it (2026-09-14)
  const practiceIds = useMemo(() => practice.map((p) => p.id), [practice]);
  const practiceTotal = useLiveTotal(practiceIds);
  // armed plans living in the OTHER workspace must never be invisible
  const armedPlans = useStore((s) => s.techniqueArmed);
  const otherArmed = useMemo(
    () => armedPlans.filter((a) => workspaceOf(a.portfolio?.kind) !== (mode === "live" ? "live" : "practice")).length,
    [armedPlans, mode]);
  const attention = useMemo(() => armedPlans.filter((a) => a.needsAttention), [armedPlans]);
  const attentionNeedsAction = attention.some(a=>!attentionSummary(a).notice);
  const quoteSource = broker?.quoteSource;

  const applyMode = async (value: string) => {
    try {
      await api.patchSettings({ "trading.mode": value });
      toast("info", value === "live" ? "Real-order routing ON" : "Real-order routing OFF");
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const changeMode = (value: string) => setView(value === "live" ? "live" : "practice");

  const doHalt = async (reason: string) => {
    setPromptHalt(false);
    try {
      await api.halt(reason || "manual halt");
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const doResume = async () => {
    setConfirmResume(false);
    try {
      await api.resume();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const toggleHalt = () => {
    if (halt.engaged) setConfirmResume(true);
    else setPromptHalt(true);
  };

  // "/" focuses the stock lookup from anywhere (unless already typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const lookupPick = (hit: SymbolHit) => {
    void api.watchSymbol(hit.symbol).catch(() => undefined); // start quotes flowing now
    openTrade(hit.symbol);
  };

  const lookupAdd = async (hit: SymbolHit) => {
    const wl = watchlists[0];
    if (!wl) { toast("error", "no watchlist yet — create one in Settings"); return; }
    if (wl.symbols.includes(hit.symbol)) {
      toast("info", `${hit.symbol} is already on ${wl.name}`);
      return;
    }
    try {
      const symbols = [...wl.symbols, hit.symbol];
      await api.updateWatchlist(wl.id, wl.name, symbols);
      setWatchlists(watchlists.map((w) => (w.id === wl.id ? { ...w, symbols } : w)));
      toast("info", `${hit.symbol} added to ${wl.name}`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const dialogs = (
    <>
      {confirmLive && (
        <ConfirmDialog
          title="Turn on real-order routing?"
          danger
          confirmLabel="Route real orders"
          body={
            <p style={{ margin: 0 }}>
              Orders for live and paper accounts (SnapTrade / IBKR) will route to the broker. Every order still
              passes the risk gate. This does not change which workspace you see.
            </p>
          }
          onConfirm={() => { setConfirmLive(false); void applyMode("live"); }}
          onCancel={() => setConfirmLive(false)}
        />
      )}
      {confirmRoutingOff && (
        <ConfirmDialog
          title="Turn off real-order routing?"
          confirmLabel="Stop real orders"
          body={
            <p style={{ margin: 0 }}>
              New orders for live and paper accounts are refused. Exits that only close a position still route.
              Practice keeps trading.
            </p>
          }
          onConfirm={() => { setConfirmRoutingOff(false); void applyMode("practice"); }}
          onCancel={() => setConfirmRoutingOff(false)}
        />
      )}
      {confirmResume && (
        <ConfirmDialog
          title="Release the kill switch?"
          confirmLabel="Resume trading"
          body={
            <div>
              <p style={{ marginTop: 0 }}>
                Halted because: <b>{halt.reason || "manual halt"}</b>
              </p>
              <p style={{ marginBottom: 0 }}>
                Resuming lets orders route again (per the trading mode and risk
                gate). If this was an auto-halt, make sure you understand what
                tripped it first.
              </p>
            </div>
          }
          onConfirm={() => void doResume()}
          onCancel={() => setConfirmResume(false)}
        />
      )}
      {promptHalt && (
        <PromptDialog
          title="Engage kill switch"
          label="Halt reason"
          defaultValue="manual halt"
          submitLabel="HALT"
          onSubmit={(v) => void doHalt(v)}
          onCancel={() => setPromptHalt(false)}
        />
      )}
    </>
  );

  if (isPhone) {
    // phone: brand · workspace · attention · HALT · search — HALT can never be pushed off-screen
    return (
      <header className="topbar topbar--phone">
        <button type="button" className="brand" onClick={() => setPage("dashboard")} aria-label="Home — Dashboard">
          <img className="brand-logo" src="/art/logo-mark.png" alt="" aria-hidden="true" />
          Zargar
        </button>
        <button type="button" className="ver-chip" onClick={() => setChangelog(true)}
          aria-label={`Version ${APP_VERSION} — what's new`}>v{APP_VERSION}</button>
        <button type="button" className={`topbar-phone-ws ${mode === "live" ? "live" : ""}`}
          aria-label={`Workspace: ${mode === "live" ? "LIVE — real accounts" : "Practice — simulator"} — switch in the More sheet`}
          onClick={() => setMoreOpen(true)}>
          <span className="mode-dot" />{mode === "live" ? "LIVE" : "PRACTICE"}
        </button>
        <div className="spacer" />
        {attention.length > 0 && (
          <button type="button" className="topbar-attn attention-chip" onClick={() => useStore.setState({page:"armed",pageTab:"attention",armedFocusRunId:null})}
            aria-label={`Review ${attention.length} flagged plans`}>
            {attentionNeedsAction ? '⚠' : 'ⓘ'} {attention.length}
          </button>
        )}
        <button type="button" className="icon-btn topbar-search-btn" aria-label="Search stocks"
          onClick={() => setSearchOpen(true)}>
          <IconSearch size={20} />
        </button>
        <button type="button" className={`routing-chip ${routing ? "on" : ""}`}
        onClick={() => (routing ? setConfirmRoutingOff(true) : setConfirmLive(true))}
        title={routing ? "Real orders route to live/paper accounts — click to turn off"
                       : "Real orders to live/paper accounts are blocked — click to turn on"}
        aria-label={routing ? "Real-order routing on" : "Real-order routing off"}>
        <span className="mode-dot" />{routing ? "Real orders on" : "Real orders off"}
      </button>
      <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}
          aria-label={halt.engaged ? "Resume trading" : "Halt trading"}>
          {halt.engaged ? "RESUME" : "HALT"}
        </button>
        {changelog && <ChangelogDialog onClose={() => setChangelog(false)} />}
        {searchOpen && (
          <Sheet title="Search stocks" onClose={() => setSearchOpen(false)} full>
            <SymbolSearch compact autoFocus placeholder="Ticker or company name"
              onPick={(h) => { setSearchOpen(false); lookupPick(h); }}
              onAdd={(h) => { setSearchOpen(false); void lookupAdd(h); }} />
          </Sheet>
        )}
        {dialogs}
      </header>
    );
  }

  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={() => setPage("dashboard")} aria-label="Home — Dashboard">
        <img className="brand-logo" src="/art/logo-mark.png" alt="" aria-hidden="true" />
        Zargar
      </button>
      <button type="button" className="ver-chip" onClick={() => setChangelog(true)}
        title="What's new — release history" aria-label={`Version ${APP_VERSION} — what's new`}>v{APP_VERSION}</button>
      {changelog && <ChangelogDialog onClose={() => setChangelog(false)} />}
      {quoteSource === "alpaca" && (broker as any)?.alpacaConnected === false && (
        <span className="status-pill warn"
          title="The Alpaca data stream is down — quotes and bars are running on the slower Yahoo fallback. Check backend/.env keys or status.alpaca.markets.">
          ⚠ data: fallback
        </span>
      )}
      {quoteSource === "sim" && (
        <span className="status-pill dim" title="Simulated quote feed — prices are synthetic.">
          sim quotes
        </span>
      )}
      <SymbolSearch
        placeholder="Search stocks…  ( / )"
        onPick={lookupPick}
        onAdd={(h) => void lookupAdd(h)}
        inputRef={searchRef}
      />
      <div className="spacer" />
      {mode === "live" && (realTotals.length > 0 || realOne != null) && (
        <button className="equity-chip equity-chip--real" onClick={() => setPage("dashboard")}
          title="Real money across every real account, in your display currency (IBKR paper excluded) — click for the Dashboard">
          <span className="equity-chip-lbl">Real money</span>
          <span className="equity-chip-num">
            {realOne != null ? fmtCcy(realOne, dispCcy)
              : realTotals.map((t) => fmtCcy(t.brokerage, t.currency)).join("  ·  ")}
          </span>
        </button>
      )}
      {mode !== "live" && practice.length > 0 && (
        <button className="equity-chip" onClick={() => setPage("dashboard")}
          title="Practice equity (simulated fills) — click for the Dashboard">
          <span className="equity-chip-lbl">Practice</span>
          <span className="equity-chip-num">
            {fmtCcy(practiceTotal, practice[0]?.baseCurrency ?? "USD")}
          </span>
        </button>
      )}
      {attention.length > 0 && (
        <button className={`attention-chip ${attentionNeedsAction ? 'action' : 'notice'}`}
          title={`${attention.map(a=>a.symbol).join(', ')} — review flagged plans across Practice and Live`}
          onClick={() => useStore.setState({page:'armed',pageTab:'attention',armedFocusRunId:null})}>
          <span aria-hidden="true">{attentionNeedsAction ? '⚠' : 'ⓘ'}</span><span>{attention.length} {attentionNeedsAction ? `${attention.length === 1 ? 'plan' : 'plans'} to review` : `${attention.length === 1 ? 'plan notice' : 'plan notices'}`}</span>
        </button>
      )}
      {otherArmed > 0 && (
        <button className="status-pill warn ws-other-chip"
          title={`${otherArmed} plan(s) are armed in the ${mode === "live" ? "Practice" : "LIVE"} workspace — click to open the Armed page (switch workspace to manage them)`}
          onClick={() => setPage("armed")}>
          {otherArmed} armed in {mode === "live" ? "practice" : "LIVE"}
        </button>
      )}
      <div role="status" aria-label={connected ? "Connected" : "Disconnected"}
        title={connected ? "Live connection" : "Disconnected"}>
        <div className={`conn-dot ${connected ? "on" : ""}`} />
      </div>
      <button className="icon-btn theme-btn" aria-label="Toggle light/dark mode"
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        onClick={() => {
          const next = theme === "dark" ? "light" : "dark";
          useStore.getState().setSettings({ ...useStore.getState().settings, "ui.theme": next });
          api.patchSettings({ "ui.theme": next }).catch((e) => toast("error", e.message));
        }}>
        {theme === "dark" ? "☀" : "🌙"}
      </button>
      {authRequired && authUser && (
        <div className="account-wrap">
          <button className="icon-btn account-btn" aria-label="Account" aria-expanded={accountOpen}
            title={`${authUser.name || authUser.email} — account`} onClick={() => setAccountOpen((v) => !v)}>
            {authUser.picture
              ? <img src={authUser.picture} alt="" referrerPolicy="no-referrer" />
              : <span>{(authUser.name || authUser.email).slice(0, 1).toUpperCase()}</span>}
          </button>
          {accountOpen && (
            <>
              <div className="account-backdrop" onClick={() => setAccountOpen(false)} />
              <div className="account-pop" role="menu">
                <b>{authUser.name || authUser.email}</b>
                {authUser.name && <span className="muted small">{authUser.email}</span>}
                <button className="ghost-btn" role="menuitem" onClick={() => { setAccountOpen(false); void signOut(); }}>Sign out</button>
              </div>
            </>
          )}
        </div>
      )}
      <div className={`mode-indicator mode-indicator--${mode}`}
        title={mode === "live"
          ? "LIVE view — you see real accounts. Switching the view never stops or starts trading."
          : "Practice view — you see the simulator. Switching the view never stops or starts trading."}>
        <select className="mode-select" value={mode} onChange={(e) => changeMode(e.target.value)}
          aria-label="Workspace">
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>
      <button type="button" className={`routing-chip ${routing ? "on" : ""}`}
        onClick={() => (routing ? setConfirmRoutingOff(true) : setConfirmLive(true))}
        title={routing ? "Real orders route to live/paper accounts — click to turn off"
                       : "Real orders to live/paper accounts are blocked — click to turn on"}
        aria-label={routing ? "Real-order routing on" : "Real-order routing off"}>
        <span className="mode-dot" />{routing ? "Real orders on" : "Real orders off"}
      </button>
      <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}
        aria-label={halt.engaged ? "Resume trading" : "Halt trading"}>
        {halt.engaged ? "RESUME" : "HALT"}
      </button>
      {dialogs}
    </header>
  );
}
