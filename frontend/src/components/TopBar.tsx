import { useState } from "react";
import { api } from "../lib/api";
import { fmtCcy } from "../lib/format";
import { useStore } from "../store";
import { IconWarn } from "./icons";
import { ConfirmDialog, PromptDialog } from "./Modal";

const MODES = [
  { value: "dry_run", label: "Dry run" },
  { value: "sim", label: "Simulation" },
  { value: "paper", label: "Paper" },
  { value: "live", label: "LIVE" },
];

export function TopBar() {
  const connected = useStore((s) => s.connected);
  const halt = useStore((s) => s.halt);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "sim");
  const portfolios = useStore((s) => s.portfolios);
  const broker = useStore((s) => s.broker);
  const toast = useStore((s) => s.toast);

  const [confirmLive, setConfirmLive] = useState(false);
  const [promptHalt, setPromptHalt] = useState(false);

  const defaultId = useStore((s) => s.settings["trading.default_portfolio"]);
  const active = portfolios.find((p) => p.id === defaultId) ?? portfolios[0];
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

  const toggleHalt = async () => {
    if (halt.engaged) {
      try {
        await api.resume();
      } catch (e: any) {
        toast("error", e.message);
      }
    } else {
      setPromptHalt(true);
    }
  };

  return (
    <header className="topbar">
      <div className="brand">
        Zar<em>gar</em>
      </div>
      <select className="mode-select" value={mode} onChange={(e) => changeMode(e.target.value)}
        aria-label="Trading mode"
        title="Trading mode — the routing gate for all orders">
        {MODES.map((m) => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </select>
      {quoteSource === "yahoo" && (
        <span className="status-pill dim"
          title="Quotes come from Yahoo Finance (~1–2s delayed, indicative). Live IBKR data replaces this when the gateway connects.">
          <IconWarn size={11} /> indicative quotes
        </span>
      )}
      {quoteSource === "sim" && (
        <span className="status-pill dim" title="Simulated quote feed — prices are synthetic.">
          sim quotes
        </span>
      )}
      <div className="spacer" />
      {active && (
        <div className="equity-chip" title={`${active.name} equity`}>
          {active.name}: {fmtCcy(active.equity ?? active.cash, active.baseCurrency ?? "USD")}
        </div>
      )}
      <div role="status" aria-label={connected ? "Connected" : "Disconnected"}
        title={connected ? "Live connection" : "Disconnected"}>
        <div className={`conn-dot ${connected ? "on" : ""}`} />
      </div>
      <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}
        aria-label={halt.engaged ? "Resume trading" : "Halt trading"}>
        {halt.engaged ? "RESUME" : "HALT"}
      </button>

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
    </header>
  );
}
