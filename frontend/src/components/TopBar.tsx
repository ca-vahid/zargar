import { api } from "../lib/api";
import { fmtUsd } from "../lib/format";
import { useStore } from "../store";

const MODES = [
  { value: "dry_run", label: "Dry run" },
  { value: "sim", label: "Simulation" },
  { value: "paper", label: "Paper (IBKR)" },
  { value: "live", label: "LIVE (IBKR)" },
];

export function TopBar() {
  const connected = useStore((s) => s.connected);
  const halt = useStore((s) => s.halt);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "sim");
  const portfolios = useStore((s) => s.portfolios);
  const toast = useStore((s) => s.toast);

  const defaultId = useStore((s) => s.settings["trading.default_portfolio"]);
  const active = portfolios.find((p) => p.id === defaultId) ?? portfolios[0];

  const changeMode = async (value: string) => {
    if (value === "live" && !window.confirm("Switch to LIVE mode? Real orders will route to IBKR."))
      return;
    try {
      await api.patchSettings({ "trading.mode": value });
      toast("info", `Trading mode: ${value}`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const toggleHalt = async () => {
    try {
      if (halt.engaged) await api.resume();
      else {
        const reason = window.prompt("Halt reason:", "manual halt");
        if (reason === null) return;
        await api.halt(reason || "manual halt");
      }
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return (
    <header className="topbar">
      <div className="brand">
        Zar<em>gar</em>
      </div>
      <select className="mode-select" value={mode} onChange={(e) => changeMode(e.target.value)}
        title="Trading mode — the routing gate for all orders">
        {MODES.map((m) => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </select>
      <div className="spacer" />
      {active && (
        <div className="equity-chip" title={`${active.name} equity`}>
          {active.name}: {fmtUsd(active.equity ?? active.cash)}
        </div>
      )}
      <div className="conn-dot-wrap" title={connected ? "Live connection" : "Disconnected"}>
        <div className={`conn-dot ${connected ? "on" : ""}`} />
      </div>
      <button className={`halt-btn ${halt.engaged ? "halted" : ""}`} onClick={toggleHalt}>
        {halt.engaged ? "RESUME" : "HALT"}
      </button>
    </header>
  );
}
