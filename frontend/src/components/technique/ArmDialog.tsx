import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { useStore } from "../../store";
import type { ArmOptions, ArmRequest } from "../../types";
import { Modal } from "../Modal";

const MODE_HELP: Record<string, string> = {
  alert: "Watch only. A fired trigger becomes a setup row + a note; nothing is sent anywhere.",
  proposal: "A fired trigger becomes a practice proposal in Signals that you approve (RiskGate on approval).",
  auto: "A fired trigger is bought now (limit at the trigger price + slippage), then managed: 30/40/15 trims at the targets, stop, flatten before the close. Every order passes RiskGate.",
};

/** Account + execution-mode picker shown before a plan is armed. */
export function ArmDialog({ symbol, planFor, onClose, onArm }: {
  symbol: string; planFor: string; onClose: () => void; onArm: (req: ArmRequest) => Promise<void>;
}) {
  const toast = useStore((s) => s.toast);
  const [opts, setOpts] = useState<ArmOptions | null>(null);
  const [portfolioId, setPortfolioId] = useState("");
  const [mode, setMode] = useState<"alert" | "proposal" | "auto">("proposal");
  const [riskPct, setRiskPct] = useState(0.5);
  const [maxQty, setMaxQty] = useState(100);
  const [qty, setQty] = useState<string>("");
  const [useCritic, setUseCritic] = useState(true);
  const [allowLive, setAllowLive] = useState(false);
  const [flatten, setFlatten] = useState(5);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.techniqueArmOptions().then((o) => {
      setOpts(o);
      setPortfolioId(o.defaults.portfolioId || o.portfolios.find((p) => p.kind === "sim")?.id || o.portfolios[0]?.id || "");
      setMode(o.defaults.mode as any);
      setRiskPct(o.defaults.riskPct); setMaxQty(o.defaults.maxQty); setUseCritic(o.defaults.useCritic);
      setFlatten(o.defaults.flattenMinutesBeforeClose);
    }).catch((e) => toast("error", e.message));
  }, [toast]);
  const portfolio = useMemo(() => opts?.portfolios.find((p) => p.id === portfolioId), [opts, portfolioId]);
  const isLive = portfolio ? (portfolio.kind === "live" || portfolio.kind === "paper") : false;
  const liveBlocked = mode === "auto" && isLive && (!opts?.allowLiveAuto || opts?.tradingMode !== "live");
  const submit = async () => {
    setBusy(true);
    try {
      await onArm({ portfolioId, mode, riskPct, maxQty, qty: qty ? Number(qty) : undefined, useCritic, allowLive,
        flattenMinutesBeforeClose: flatten });
      onClose();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Arm ${symbol} plan for ${planFor}`} onClose={onClose}
      footer={<>
        <button className="ghost-btn" onClick={onClose}>Cancel</button>
        <button className="primary-btn" disabled={busy || !opts || !portfolioId || liveBlocked || (mode === "auto" && isLive && !allowLive)} onClick={submit}>
          {busy ? "Arming…" : mode === "auto" ? (isLive ? "Arm — REAL MONEY" : "Arm — auto (practice)") : "Arm"}
        </button>
      </>}>
      {!opts && <div className="muted">loading accounts…</div>}
      {opts && (
        <div className="tq-arm-form">
          <label className="field"><span className="tq-ctl-label">Account this plan trades in</span>
            <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
              {opts.portfolios.map((p) => (
                <option key={p.id} value={p.id}>{p.name} · {p.kind.toUpperCase()}{p.venue ? ` · ${p.venue}` : ""}{p.baseCurrency ? ` · ${p.baseCurrency}` : ""}</option>
              ))}
            </select>
          </label>
          <div className="tq-arm-modes" role="radiogroup">
            {(["alert", "proposal", "auto"] as const).map((m) => (
              <label key={m} className={`tq-arm-mode ${mode === m ? "active" : ""}`}>
                <input type="radio" name="arm-mode" checked={mode === m} onChange={() => setMode(m)} />
                <b>{m === "alert" ? "Alert" : m === "proposal" ? "Proposal" : "Auto-execute"}</b>
                <span className="muted">{MODE_HELP[m]}</span>
              </label>
            ))}
          </div>
          {mode !== "alert" && (
            <div className="tq-row">
              <label className="tq-ctl"><span className="tq-ctl-label">Risk % of equity (R1)</span>
                <input type="number" step="0.1" min={0.1} max={5} value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))} /></label>
              <label className="tq-ctl"><span className="tq-ctl-label">Max shares</span>
                <input type="number" min={1} value={maxQty} onChange={(e) => setMaxQty(Number(e.target.value))} /></label>
              <label className="tq-ctl"><span className="tq-ctl-label">Fixed shares (optional)</span>
                <input type="number" min={1} value={qty} placeholder="size by risk" onChange={(e) => setQty(e.target.value)} /></label>
              {mode === "auto" && <label className="tq-ctl"><span className="tq-ctl-label">Flatten (min before close)</span>
                <input type="number" min={1} max={60} value={flatten} onChange={(e) => setFlatten(Number(e.target.value))} /></label>}
            </div>
          )}
          <label className="tq-chipbtn"><input type="checkbox" checked={useCritic} disabled={!opts.llmAvailable} onChange={(e) => setUseCritic(e.target.checked)} />
            run the vision critic on a live fire{!opts.llmAvailable ? " (no API key — off)" : ""}</label>
          {mode === "auto" && isLive && (
            <div className="tq-arm-live">
              <b>Real money.</b> Auto-execution on a {portfolio?.kind} account
              {!opts.allowLiveAuto && <> is <b>disabled</b> (setting <code>technique.arm.allow_live_auto</code>)</>}
              {opts.allowLiveAuto && opts.tradingMode !== "live" && <> is blocked while <code>trading.mode</code> is practice</>}
              {!liveBlocked && <>: every order still passes RiskGate and the kill switch.</>}
              {!liveBlocked && <label className="tq-chipbtn" style={{ marginTop: 6 }}>
                <input type="checkbox" checked={allowLive} onChange={(e) => setAllowLive(e.target.checked)} /> I understand this will place real orders
              </label>}
            </div>
          )}
          {opts.halt?.engaged && <div className="neg">Kill switch is engaged — nothing will fire until it is released.</div>}
          <small className="muted">Fires only inside 09:30–10:30 / 14:45–16:00 ET (R6); mid-day touches are logged, not taken. Nothing is held overnight.</small>
        </div>
      )}
    </Modal>
  );
}
