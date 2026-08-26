import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtCcy } from "../lib/format";
import { netWorthByCurrency, useStore } from "../store";
import { ConfirmDialog, PromptDialog } from "./Modal";
import { SymbolSearch, type SymbolHit } from "./SymbolSearch";
import { workspaceOf } from "../lib/workspace";
import { useViewport } from "../lib/viewport";
import { Sheet } from "./Sheet";
import { IconSearch } from "./icons";

const MODES = [
  { value: "practice", label: "Practice" },
  { value: "live", label: "LIVE" },
];
// The switch is a WORKSPACE: it scopes every account-shaped view (money, accounts,
// blotter, armed plans) AND gates order routing (practice rejects real-account orders).

export function TopBar() {
  const connected = useStore((s) => s.connected);
  const halt = useStore((s) => s.halt);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const portfolios = useStore((s) => s.portfolios);
  const broker = useStore((s) => s.broker);
  const toast = useStore((s) => s.toast);

  const brokerages = useStore((s) => s.brokerages);
  const setPage = useStore((s) => s.setPage);
  const openTrade = useStore((s) => s.openTrade);
  const watchlists = useStore((s) => s.watchlists);
  const setWatchlists = useStore((s) => s.setWatchlists);
  const searchRef = useRef<HTMLInputElement>(null);
  const [confirmLive, setConfirmLive] = useState(false);
  const [promptHalt, setPromptHalt] = useState(false);
  const [confirmResume, setConfirmResume] = useState(false);
  const { isPhone } = useViewport();
  const [searchOpen, setSearchOpen] = useState(false);

  // real money is the headline; practice is its own clearly-labeled chip
  const realTotals = useMemo(
    () => netWorthByCurrency(portfolios, brokerages).filter((t) => t.brokerage > 0),
    [portfolios, brokerages]);
  const practice = useMemo(
    () => portfolios.filter((p) => p.kind === "sim"), [portfolios]);
  const practiceTotal = practice.reduce((sum, p) => sum + (p.equity ?? p.cash), 0);
  // armed plans living in the OTHER workspace must never be invisible
  const armedPlans = useStore((s) => s.techniqueArmed);
  const otherArmed = useMemo(
    () => armedPlans.filter((a) => workspaceOf(a.portfolio?.kind) !== (mode === "live" ? "live" : "practice")).length,
    [armedPlans, mode]);
  const attention = useMemo(() => armedPlans.filter((a) => a.needsAttention), [armedPlans]);
  const quoteSource = broker?.quoteSource;

  const applyMode = async (value: string) => {
    try {
      await api.patchSettings({ "trading.mode": value });
      toast("info", `Trading mode: ${value}`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const changeMode = (value: string) => {
    if (value === "live") setConfirmLive(true);
    else void applyMode(value);
  };

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
          title="Switch to LIVE mode?"
          danger
          confirmLabel="Go live"
          body={
            <p style={{ margin: 0 }}>
              Real orders will route to your brokerage accounts (SnapTrade / IBKR).
              Every order still passes the risk gate, and real-money submits ask
              for confirmation.
            </p>
          }
          onConfirm={() => { setConfirmLive(false); void applyMode("live"); }}
          onCancel={() => setConfirmLive(false)}
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
        <div className="brand">
          <img className="brand-logo" src="/art/logo-mark.png" alt="" aria-hidden="true" />
          Zargar
        </div>
        <button type="button" className={`topbar-phone-ws ${mode === "live" ? "live" : ""}`}
          aria-label={`Workspace: ${mode === "live" ? "LIVE — real accounts" : "Practice — simulator"}`}
          onClick={() => setPage("settings")}>
          <span className="mode-dot" />{mode === "live" ? "LIVE" : "PRACTICE"}
        </button>
        <div className="spacer" />
        {attention.length > 0 && (
          <button type="button" className="topbar-attn" onClick={() => setPage("armed")}
            aria-label={`${attention.length} armed plans need attention`}>
            ⚠ {attention.length}
          </button>
        )}
        <button type="button" className="icon-btn topbar-search-btn" aria-label="Search stocks"
          onClick={() => setSearchOpen(true)}>
          <IconSearch size={20} />
        </button>
        <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}
          aria-label={halt.engaged ? "Resume trading" : "Halt trading"}>
          {halt.engaged ? "RESUME" : "HALT"}
        </button>
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
      <div className="brand">
        <img className="brand-logo" src="/art/logo-mark.png" alt="" aria-hidden="true" />
        Zargar
      </div>
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
      {mode === "live" && realTotals.length > 0 && (
        <button className="equity-chip equity-chip--real" onClick={() => setPage("dashboard")}
          title="Real brokerage net worth (per currency) — click for the Dashboard">
          {realTotals.map((t) => fmtCcy(t.brokerage, t.currency)).join(" · ")}
        </button>
      )}
      {mode !== "live" && practice.length > 0 && (
        <button className="equity-chip" onClick={() => setPage("portfolios")}
          title="Practice equity (simulated fills) — click for Portfolios">
          {fmtCcy(practiceTotal, practice[0]?.baseCurrency ?? "USD")}
        </button>
      )}
      {attention.length > 0 && (
        <button className="status-pill attention"
          title={`${attention.length} armed plan(s) need attention (failed exit / unmanaged position) — click for the Armed page. This shows regardless of workspace.`}
          onClick={() => setPage("armed")}>
          \u26a0 {attention.length} needs attention
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
      <div className={`mode-indicator mode-indicator--${mode}`}
        title={mode === "live"
          ? "LIVE workspace — you see real accounts only, and real orders route to your brokerages. Switch to Practice to see the simulator."
          : "Practice workspace — you see the simulator only, and orders to real accounts are blocked. Switch to LIVE for real accounts."}>
        <select className="mode-select" value={mode} onChange={(e) => changeMode(e.target.value)}
          aria-label="Workspace">
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>
      <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}
        aria-label={halt.engaged ? "Resume trading" : "Halt trading"}>
        {halt.engaged ? "RESUME" : "HALT"}
      </button>
      {dialogs}
    </header>
  );
}
