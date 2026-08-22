import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { cashText } from "../../lib/brokerage";
import { fmtCcy } from "../../lib/format";
import { useStore } from "../../store";
import type { ArmOptions, ArmRequest } from "../../types";
import { BrokerIcon } from "../BrokerIcon";
import { Modal } from "../Modal";

const MODES: { key: "alert" | "proposal" | "auto"; title: string; text: string }[] = [
  { key: "alert", title: "Alert only", text: "When a trigger fires you get a setup row and a note in the run's chat. Nothing is sent to any account." },
  { key: "proposal", title: "Proposal — you approve", text: "A fired trigger becomes a proposal in Signals with the contract, size and plan filled in. You click approve; RiskGate runs on approval." },
  { key: "auto", title: "Auto-execute", text: "A fired trigger is bought immediately, then managed for you: stop first, scale out at the targets (30/40/15 or all-at-TP2 for a single contract), flat before the close. Every order passes RiskGate and the kill switch." },
];

function fmt(n: number | null | undefined, d = 2) { return n === null || n === undefined ? "—" : Number(n).toFixed(d); }

/** Account + instrument + execution-mode picker shown before a plan is armed. */
export function ArmDialog({ symbol, planFor, bestTrigger, onClose, onArm }: {
  symbol: string; planFor: string; bestTrigger?: { entry: number; stop: number; riskReward: number; id: string } | null;
  onClose: () => void; onArm: (req: ArmRequest) => Promise<void>;
}) {
  const toast = useStore((s) => s.toast);
  const brokerages = useStore((s) => s.brokerages);
  const [opts, setOpts] = useState<ArmOptions | null>(null);
  const [portfolioId, setPortfolioId] = useState("");
  const [mode, setMode] = useState<"alert" | "proposal" | "auto">("proposal");
  const [instrument, setInstrument] = useState<"options" | "shares">("options");
  const [contracts, setContracts] = useState<string>("1");
  const [maxContracts, setMaxContracts] = useState(5);
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
      setInstrument(((o.defaults.instrument as any) || "options"));
      setContracts(String(o.defaults.contracts ?? 1));
      setMaxContracts(o.defaults.maxContracts ?? 5);
      setRiskPct(o.defaults.riskPct); setMaxQty(o.defaults.maxQty); setUseCritic(o.defaults.useCritic);
      setFlatten(o.defaults.flattenMinutesBeforeClose);
    }).catch((e) => toast("error", e.message));
  }, [toast]);
  // broker logo / native cash for SnapTrade accounts
  const brokerFor = useMemo(() => {
    const m = new Map<string, { account: any; provider: any }>();
    for (const prov of brokerages?.providers ?? []) for (const a of prov.accounts) m.set(a.portfolioId, { account: a, provider: prov });
    return m;
  }, [brokerages]);
  const portfolio = useMemo(() => opts?.portfolios.find((p) => p.id === portfolioId), [opts, portfolioId]);
  const isLive = portfolio ? (portfolio.kind === "live" || portfolio.kind === "paper") : false;
  const liveBlocked = mode === "auto" && isLive && (!opts?.allowLiveAuto || opts?.tradingMode !== "live");
  const optionsBlocked = instrument === "options" && mode === "auto" && portfolio ? !portfolio.optionsOk : false;
  const cashOf = (p: ArmOptions["portfolios"][number]) => {
    const b = brokerFor.get(p.id);
    return b ? cashText(b.account) : fmtCcy(p.cash ?? 0, p.baseCurrency ?? "USD");
  };
  // sizing hint from the plan's best trigger
  const equity = portfolio ? (brokerFor.get(portfolio.id)?.account?.equity ?? portfolio.cash ?? 0) : 0;
  const perShare = bestTrigger ? Math.max(bestTrigger.entry - bestTrigger.stop, 0.01) : null;
  const sharesHint = perShare && equity ? Math.min(Math.floor(equity * riskPct / 100 / perShare), maxQty) : null;
  const submit = async () => {
    setBusy(true);
    try {
      await onArm({ portfolioId, mode, instrument, contracts: contracts ? Number(contracts) : undefined, maxContracts,
        riskPct, maxQty, qty: qty ? Number(qty) : undefined, useCritic, allowLive, flattenMinutesBeforeClose: flatten });
      onClose();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const armDisabled = busy || !opts || !portfolioId || liveBlocked || optionsBlocked || (mode === "auto" && isLive && !allowLive);
  return (
    <Modal wide title={<>Arm <b>{symbol}</b> plan for {planFor} <span className="muted">— EM Options technique</span></>} onClose={onClose}
      footer={<>
        <button className="ghost-btn" onClick={onClose}>Cancel</button>
        <button className="primary-btn" disabled={armDisabled} onClick={submit}>
          {busy ? "Arming…" : mode === "auto" ? (isLive ? "Arm — REAL MONEY" : "Arm — auto (practice)") : mode === "proposal" ? "Arm — propose on fire" : "Arm — alert only"}
        </button>
      </>}>
      {!opts && <div className="muted">loading accounts…</div>}
      {opts && (
        <div className="tq-arm-form">
          {/* 1. account */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">1 · Account this plan trades in</div>
            <div className="tq-arm-accounts">
              {opts.portfolios.map((p) => {
                const b = brokerFor.get(p.id);
                const live = p.kind === "live" || p.kind === "paper";
                return (
                  <label key={p.id} className={`tq-arm-account ${portfolioId === p.id ? "active" : ""} ${live ? "live" : ""}`}>
                    <input type="radio" name="arm-account" checked={portfolioId === p.id} onChange={() => setPortfolioId(p.id)} />
                    {b?.provider ? <BrokerIcon name={b.provider.broker} logoUrl={b.provider.logoUrl} size={22} />
                      : <span className="tq-arm-venue">{p.venue === "ibkr" ? "IB" : "SIM"}</span>}
                    <span className="tq-arm-acct-main">
                      <span className="tq-arm-acct-name">{p.name}</span>
                      <span className="muted small">{live ? "REAL" : "PRACTICE"} · {p.venue}{p.optionsOk ? " · options ✓" : ` · no options (${p.optionsNote})`}</span>
                    </span>
                    <span className="tq-arm-acct-cash"><b>{cashOf(p)}</b><span className="muted small">available</span></span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* 2. instrument */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">2 · What to buy when a trigger fires</div>
            <div className="tq-arm-rows">
              <label className={`tq-arm-row ${instrument === "options" ? "active" : ""}`}>
                <input type="radio" name="arm-instr" checked={instrument === "options"} onChange={() => setInstrument("options")} />
                <span><b>Options — the book's way (T5)</b>
                  <span className="muted">Buys the <b>call just out of the money</b>, expiring <b>this Friday</b> (0DTE when it's Friday), at the ask, from the live chain ({opts.optionsProvider.toUpperCase()}). Exits still follow the <i>underlying</i> price: stop, targets, flat by the close.</span></span>
              </label>
              <label className={`tq-arm-row ${instrument === "shares" ? "active" : ""}`}>
                <input type="radio" name="arm-instr" checked={instrument === "shares"} onChange={() => setInstrument("shares")} />
                <span><b>Shares</b><span className="muted">Buys the stock itself at the trigger price (+ slippage). Same stop / targets / flatten.</span></span>
              </label>
            </div>
            {instrument === "options" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Contracts per trade</span>
                  <input type="number" min={1} max={maxContracts} value={contracts} onChange={(e) => setContracts(e.target.value)} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Max contracts</span>
                  <input type="number" min={1} value={maxContracts} onChange={(e) => setMaxContracts(Number(e.target.value))} /></label>
                <small className="muted tq-arm-hint">
                  The book says <b>one contract per trade</b> for the first 3–6 months (R5) — keep 1 while the method is being validated.
                  With fewer than 3 contracts the 30/40/15 ladder can't split, so the position exits at TP2 (setting <code>single_contract_exit</code>).
                  Leave contracts empty to size by risk % of equity instead.
                </small>
              </div>
            )}
            {instrument === "shares" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Risk per trade (% of equity)</span>
                  <input type="number" step="0.1" min={0.1} max={opts.defaults.maxRiskPct} value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Max shares</span>
                  <input type="number" min={1} value={maxQty} onChange={(e) => setMaxQty(Number(e.target.value))} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Fixed shares (optional)</span>
                  <input type="number" min={1} value={qty} placeholder="size by risk" onChange={(e) => setQty(e.target.value)} /></label>
                <small className="muted tq-arm-hint">
                  R1: the book risks <b>0.5–1 %</b> of the account per trade (5 % is the hard cap). Size = equity × risk % ÷ (entry − stop).
                  {bestTrigger && sharesHint !== null && <> For trigger {bestTrigger.id} (entry {fmt(bestTrigger.entry)}, stop {fmt(bestTrigger.stop)}, risk {fmt(perShare)} /share) that is ≈ <b>{sharesHint}</b> shares on {fmtCcy(equity, portfolio?.baseCurrency ?? "USD")}.</>}
                </small>
              </div>
            )}
          </div>

          {/* 3. mode */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">3 · What happens when a trigger fires</div>
            <div className="tq-arm-rows">
              {MODES.map((m) => (
                <label key={m.key} className={`tq-arm-row ${mode === m.key ? "active" : ""} ${m.key === "auto" && isLive ? "live" : ""}`}>
                  <input type="radio" name="arm-mode" checked={mode === m.key} onChange={() => setMode(m.key)} />
                  <span><b>{m.title}</b><span className="muted">{m.text}</span></span>
                </label>
              ))}
            </div>
            {mode === "auto" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Flatten (min before close)</span>
                  <input type="number" min={1} max={60} value={flatten} onChange={(e) => setFlatten(Number(e.target.value))} /></label>
                <label className="tq-chipbtn"><input type="checkbox" checked={useCritic} disabled={!opts.llmAvailable} onChange={(e) => setUseCritic(e.target.checked)} />
                  run the vision critic before entering{!opts.llmAvailable ? " (no API key — off)" : ""}</label>
              </div>
            )}
            {optionsBlocked && <div className="neg">This account can't trade options here ({portfolio?.optionsNote}). Pick another account or switch to shares.</div>}
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
          </div>
          <small className="muted">Fires only inside 09:30–10:30 / 14:45–16:00 ET (R6); mid-day touches are logged, not taken. Nothing is held overnight.</small>
        </div>
      )}
    </Modal>
  );
}
