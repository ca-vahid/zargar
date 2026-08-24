import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { cashText } from "../../lib/brokerage";
import { fmtCcy } from "../../lib/format";
import { useStore } from "../../store";
import { useWorkspace, workspaceOf } from "../../lib/workspace";
import type { ArmOptions, ArmPreflight, ArmRequest, PlanTrigger } from "../../types";
import { BrokerIcon } from "../BrokerIcon";
import { InfoTip } from "../InfoTip";
import { Modal } from "../Modal";

const MODES: { key: "alert" | "proposal" | "auto"; title: string; text: string }[] = [
  { key: "alert", title: "Alert only", text: "When a setup triggers you get a note in the run's chat — nothing is sent to any account. Good for watching first." },
  { key: "proposal", title: "Propose — you approve", text: "A trigger becomes a proposal in Signals with the contract, size and plan filled in. You tap approve; the safety checks run then, and the app manages the exit for you." },
  { key: "auto", title: "Auto-trade", text: "A trigger is bought immediately, then managed for you: stop, scale out at the targets, flat before the close. Every order still passes the safety checks and the kill switch." },
];

// plain-language names for the risk checks the pre-flight returns
const CHECK_LABEL: Record<string, string> = {
  kill_switch: "Kill switch is off", quote_fresh: "Live price is available", not_halted: "Stock isn't halted",
  price_collar: "Order price is sane", short_allowed: "Not going short", options_allowed: "Options are allowed",
  option_premium_cap: "Option cost within the per-trade limit", option_premium_notional: "Option cost within the per-order limit",
  no_naked_short_option: "Not a naked short option", max_position_notional: "Position size within the dollar cap",
  max_position_pct: "Position size within the % cap", max_gross_exposure: "Total exposure within the cap",
  order_rate: "Not too many orders", duplicate_order: "Not a duplicate", daily_loss_limit: "Daily loss limit not hit",
  market_hours: "Market is open", options_supported: "This account can trade options",
  options_enabled: "Options are turned on", premium_cap_estimate: "Estimated option cost within the per-order limit",
  premium_pct_estimate: "Estimated option cost within the % limit", option_symbol: "Valid option contract",
  option_not_expired: "Contract isn't expired", option_max_contracts: "Contracts within the per-order cap",
  option_spread: "Option spread isn't too wide",
};

function fmt(n: number | null | undefined, d = 2) { return n === null || n === undefined ? "—" : Number(n).toFixed(d); }

const GRADE_WORD: Record<string, string> = { A: "strong", B: "decent", C: "weak" };

function firesOnlyIf(t: PlanTrigger): string {
  return t.kind === "bounce"
    ? `fires only if price trades down into ${t.entry.price.toFixed(2)} inside a prime window on adequate volume`
    : `fires only if a bar closes above ${t.entry.price.toFixed(2)} inside a prime window with a volume surge, a decisive candle and follow-through`;
}

/** Account + instrument + execution-mode picker shown before a plan is armed. */
export function ArmDialog({ symbol, planFor, bestTrigger, triggers, onClose, onArm }: {
  symbol: string; planFor: string; bestTrigger?: { entry: number; stop: number; riskReward: number; id: string } | null;
  triggers?: PlanTrigger[];
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
  const [maxOpen, setMaxOpen] = useState(1);
  const [lossLimit, setLossLimit] = useState<string>("");
  const [skipWide, setSkipWide] = useState(true);
  const [skipIv, setSkipIv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<ArmPreflight | null>(null);
  const [pfBusy, setPfBusy] = useState(false);
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
      setMaxOpen(o.defaults.maxOpenTrades ?? 1);
      setLossLimit(o.defaults.dailyLossLimit ? String(o.defaults.dailyLossLimit) : "");
      setSkipWide(o.defaults.skipWideSpread ?? true);
      setSkipIv(o.defaults.skipElevatedIv ?? false);
    }).catch((e) => toast("error", e.message));
  }, [toast]);
  const ws = useWorkspace();
  const wsPortfolios = useMemo(() => (opts?.portfolios ?? []).filter((p) => workspaceOf(p.kind) === ws), [opts, ws]);
  const isPendingAcct = useCallback((p: any) => p.venue === "ibkr" && (p.kind === "live" || p.kind === "paper"), [] as any);
  useEffect(() => {
    if (!wsPortfolios.length) return;
    if (!wsPortfolios.some((p) => p.id === portfolioId && !isPendingAcct(p))) {
      const first = wsPortfolios.find((p) => !isPendingAcct(p)) ?? wsPortfolios[0];
      setPortfolioId(first.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsPortfolios]);
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
  const equity = portfolio ? (brokerFor.get(portfolio.id)?.account?.equity ?? portfolio.cash ?? 0) : 0;
  const perShare = bestTrigger ? Math.max(bestTrigger.entry - bestTrigger.stop, 0.01) : null;
  const sharesHint = perShare && equity ? Math.min(Math.floor(equity * riskPct / 100 / perShare), maxQty) : null;

  const req = useCallback((): ArmRequest => ({
    portfolioId, mode, instrument, contracts: contracts ? Number(contracts) : undefined, maxContracts,
    riskPct, maxQty, qty: qty ? Number(qty) : undefined, useCritic, allowLive, flattenMinutesBeforeClose: flatten,
    maxOpenTrades: maxOpen, dailyLossLimit: lossLimit ? Number(lossLimit) : 0, skipWideSpread: skipWide, skipElevatedIv: skipIv,
  }), [portfolioId, mode, instrument, contracts, maxContracts, riskPct, maxQty, qty, useCritic, allowLive, flatten, maxOpen, lossLimit, skipWide, skipIv]);

  // pre-flight: dry-run the entry so we can say — before arming — if it would pass
  const runId = useStore((s) => s.techniqueFocusRunId);
  const pfTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!opts || !portfolioId || !runId || mode === "alert") { setPreflight(null); return; }
    window.clearTimeout(pfTimer.current);
    pfTimer.current = window.setTimeout(() => {
      setPfBusy(true);
      api.techniqueArmPreflight(runId, req()).then(setPreflight).catch(() => setPreflight(null)).finally(() => setPfBusy(false));
    }, 350);
    return () => window.clearTimeout(pfTimer.current);
  }, [opts, portfolioId, mode, instrument, contracts, riskPct, maxQty, qty, runId, req]);

  const submit = async () => {
    setBusy(true);
    try { await onArm(req()); onClose(); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const armDisabled = busy || !opts || !portfolioId || liveBlocked || optionsBlocked || (mode === "auto" && isLive && !allowLive);
  const failing = (preflight?.checks ?? []).filter((c) => !c.passed);
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
          {/* what is actually being armed — the conditional triggers and their validity */}
          {triggers && triggers.length > 0 && (
            <div className="tq-arm-block tq-arm-what">
              <div className="tq-arm-h">What you're arming
                <InfoTip>Arming places <b>no order</b>. The app watches these conditions on live 1-minute bars; a trigger that never meets them simply never fires. The grade is the plan's own deterministic read of how good each trigger is — expand the trigger on the run page for the full breakdown.</InfoTip>
              </div>
              <ul className="tq-arm-triggers">
                {triggers.map((t) => (
                  <li key={t.id}>
                    <span className="tq-chip">{t.id}</span>
                    {t.assessment?.grade && <span className={`tq-grade g${t.assessment.grade}`} title={`${t.assessment.score}/100`}>{t.assessment.grade}</span>}
                    <b>{t.kind === "bounce" ? "Support bounce" : t.kind === "breakout" ? "Breakout" : "Wedge break"}</b>
                    {t.assessment?.grade && <span className="muted"> ({GRADE_WORD[t.assessment.grade]})</span>}
                    <span className="muted"> — {firesOnlyIf(t)}; then long {fmt(t.entry.price)}, stop {fmt(t.stop.price)}.</span>
                    {(t.assessment?.cautions ?? []).length > 0 && (
                      <div className="small warn">⚠ {t.assessment!.cautions.join(" · ")}</div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* real/practice banner */}
          <div className={`tq-arm-banner ${isLive ? "live" : "practice"}`}>
            {isLive
              ? <><b>REAL MONEY.</b> This account places real orders on {portfolio?.venue}. Practice first if you're unsure — switch the account below.</>
              : <><b>Practice account.</b> Orders are simulated — nothing real is bought or sold. Safe to experiment.</>}
          </div>

          {/* 1. account */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">1 · Which account trades this plan
              <InfoTip>Only the active workspace's accounts are offered — Practice shows the simulator, LIVE shows your real accounts (switch next to HALT). IBKR's paper account will appear under LIVE, greyed until the gateway connects.</InfoTip>
            </div>
            <div className="tq-arm-accounts">
              {wsPortfolios.map((p) => {
                const b = brokerFor.get(p.id);
                const live = p.kind === "live" || p.kind === "paper";
                const pending = isPendingAcct(p);
                return (
                  <label key={p.id} className={`tq-arm-account ${portfolioId === p.id ? "active" : ""} ${live ? "live" : ""} ${pending ? "disabled" : ""}`}
                    title={pending ? "IBKR is not connected yet — this account (incl. IBKR paper) activates with the gateway" : undefined}>
                    <input type="radio" name="arm-account" disabled={pending} checked={portfolioId === p.id} onChange={() => setPortfolioId(p.id)} />
                    {b?.provider ? <BrokerIcon name={b.provider.broker} logoUrl={b.provider.logoUrl} size={22} />
                      : <span className="tq-arm-venue">{p.venue === "ibkr" ? "IB" : "SIM"}</span>}
                    <span className="tq-arm-acct-main">
                      <span className="tq-arm-acct-name">{p.name}</span>
                      <span className="muted small">{live ? (p.kind === "paper" ? "PAPER — IBKR-hosted practice, lives in LIVE" : "REAL") : "PRACTICE"} · {p.venue}{p.optionsOk ? " · options ✓" : ` · no options (${p.optionsNote})`}</span>
                    </span>
                    <span className="tq-arm-acct-cash"><b>{cashOf(p)}</b><span className="muted small">available</span></span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* 2. instrument */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">2 · What to buy when a trigger fires
              <InfoTip>This technique is written for options — it buys a call so a small move in the stock makes a bigger move in the option. You can switch to plain shares if you prefer.</InfoTip>
            </div>
            <div className="tq-arm-rows">
              <label className={`tq-arm-row ${instrument === "options" ? "active" : ""}`}>
                <input type="radio" name="arm-instr" checked={instrument === "options"} onChange={() => setInstrument("options")} />
                <span><b>Options — the book's way (T5)</b>
                  <span className="muted">Buys the <b>call just above the current price</b>, expiring <b>this Friday</b> (or same-day on Fridays), at the ask, from the live chain ({opts.optionsProvider.toUpperCase()}). The stop and targets still watch the <i>stock</i>; when they hit, the option is sold.</span></span>
              </label>
              <label className={`tq-arm-row ${instrument === "shares" ? "active" : ""}`}>
                <input type="radio" name="arm-instr" checked={instrument === "shares"} onChange={() => setInstrument("shares")} />
                <span><b>Shares</b><span className="muted">Buys the stock itself at the trigger price. Same stop / targets / flatten.</span></span>
              </label>
            </div>
            {instrument === "options" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Contracts per trade <InfoTip>The book says trade just <b>one contract</b> for the first few months while you learn (rule R5). One contract = 100 shares of exposure.</InfoTip></span>
                  <input type="number" min={1} max={maxContracts} value={contracts} onChange={(e) => setContracts(e.target.value)} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Max contracts</span>
                  <input type="number" min={1} value={maxContracts} onChange={(e) => setMaxContracts(Number(e.target.value))} /></label>
                <small className="muted tq-arm-hint">
                  Keep <b>1</b> while the method is being validated (R5). With fewer than 3 contracts the position exits all-at-once at your chosen target (below). Leave contracts blank to size by risk % instead.
                </small>
                <div className="tq-arm-toggles">
                  <label className="tq-chipbtn"><input type="checkbox" checked={skipWide} onChange={(e) => setSkipWide(e.target.checked)} /> skip if the option's spread is wide (T5.4)
                    <InfoTip>A wide gap between the buy and sell price means you lose money the moment you enter. Skipping protects you from bad contracts.</InfoTip></label>
                  <label className="tq-chipbtn"><input type="checkbox" checked={skipIv} onChange={(e) => setSkipIv(e.target.checked)} /> skip if implied volatility is high (T5.3)
                    <InfoTip>High implied volatility means the option is expensive and can lose value fast even if you're right ("IV crush"). Off by default.</InfoTip></label>
                </div>
              </div>
            )}
            {instrument === "shares" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Risk per trade (% of account) <InfoTip>How much of the account you're willing to lose if the stop is hit. The book risks <b>0.5–1%</b>. Shares bought = this ÷ (entry − stop).</InfoTip></span>
                  <input type="number" step="0.1" min={0.1} max={opts.defaults.maxRiskPct} value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Max shares</span>
                  <input type="number" min={1} value={maxQty} onChange={(e) => setMaxQty(Number(e.target.value))} /></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Fixed shares (optional)</span>
                  <input type="number" min={1} value={qty} placeholder="size by risk" onChange={(e) => setQty(e.target.value)} /></label>
                <small className="muted tq-arm-hint">
                  {bestTrigger && sharesHint !== null && <>For trigger {bestTrigger.id} (entry {fmt(bestTrigger.entry)}, stop {fmt(bestTrigger.stop)}) that's ≈ <b>{sharesHint}</b> shares on {fmtCcy(equity, portfolio?.baseCurrency ?? "USD")}.</>}
                </small>
              </div>
            )}
          </div>

          {/* 3. mode */}
          <div className="tq-arm-block">
            <div className="tq-arm-h">3 · What happens when a trigger fires
              <InfoTip>Start with <b>Alert</b> to watch, move to <b>Propose</b> to approve each trade yourself, and only use <b>Auto</b> once you trust it.</InfoTip>
            </div>
            <div className="tq-arm-rows">
              {MODES.map((m) => (
                <label key={m.key} className={`tq-arm-row ${mode === m.key ? "active" : ""} ${m.key === "auto" && isLive ? "live" : ""}`}>
                  <input type="radio" name="arm-mode" checked={mode === m.key} onChange={() => setMode(m.key)} />
                  <span><b>{m.title}</b><span className="muted">{m.text}</span></span>
                </label>
              ))}
            </div>
            {mode !== "alert" && (
              <div className="tq-row tq-arm-size">
                <label className="tq-ctl"><span className="tq-ctl-label">Stop the day after losing <InfoTip>A safety brake: once this plan has lost this many dollars today, it sells everything and stops trading for the day. Leave blank for no limit.</InfoTip></span>
                  <div className="tq-arm-money"><span>{portfolio?.baseCurrency === "CAD" ? "C$" : "$"}</span>
                    <input type="number" min={0} step={10} value={lossLimit} placeholder="no limit" onChange={(e) => setLossLimit(e.target.value)} /></div></label>
                <label className="tq-ctl"><span className="tq-ctl-label">Max positions at once <InfoTip>How many trades this plan may hold at the same time. The book's spirit is one at a time.</InfoTip></span>
                  <input type="number" min={1} max={5} value={maxOpen} onChange={(e) => setMaxOpen(Number(e.target.value))} /></label>
                {mode === "auto" && <label className="tq-ctl"><span className="tq-ctl-label">Flatten (min before close) <InfoTip>Nothing is held overnight — everything is sold this many minutes before the 4pm close.</InfoTip></span>
                  <input type="number" min={1} max={60} value={flatten} onChange={(e) => setFlatten(Number(e.target.value))} /></label>}
                {mode === "auto" && <label className="tq-chipbtn"><input type="checkbox" checked={useCritic} disabled={!opts.llmAvailable} onChange={(e) => setUseCritic(e.target.checked)} />
                  double-check with AI before buying{!opts.llmAvailable ? " (no API key)" : ""}
                  <InfoTip>Before each auto-buy, an AI reads the live chart and can veto a weak setup. Needs an API key.</InfoTip></label>}
              </div>
            )}
            {optionsBlocked && <div className="neg">This account can't trade options here ({portfolio?.optionsNote}). Pick another account or switch to shares.</div>}
            {mode === "auto" && isLive && (
              <div className="tq-arm-live">
                <b>Real money.</b> Auto-trading on a {portfolio?.kind} account
                {!opts.allowLiveAuto && <> is <b>turned off</b> in Settings (Auto-trading → allow live auto)</>}
                {opts.allowLiveAuto && opts.tradingMode !== "live" && <> is blocked while the app is in <b>practice</b> mode</>}
                {!liveBlocked && <>: every order still passes the safety checks and the kill switch.</>}
                {!liveBlocked && <label className="tq-chipbtn" style={{ marginTop: 6 }}>
                  <input type="checkbox" checked={allowLive} onChange={(e) => setAllowLive(e.target.checked)} /> I understand this will place real orders
                </label>}
              </div>
            )}
            {opts.halt?.engaged && <div className="neg">Kill switch is engaged — nothing will fire until it's released{opts.haltAllowsExits ? " (open positions can still be closed)" : ""}.</div>}
          </div>

          {/* pre-flight: would the first order actually go through? */}
          {mode !== "alert" && (
            <div className={`tq-arm-preflight ${preflight ? (preflight.ok ? "ok" : "bad") : ""}`}>
              <div className="tq-arm-pf-head">
                <b>Pre-flight check {pfBusy ? "…" : ""}</b>
                <InfoTip>A dry run of the first order against this account's safety limits — no order is placed. It tells you now, not at 9:31am, whether a trade would go through.</InfoTip>
              </div>
              {preflight?.blocked && <div className="neg small">{preflight.blocked}</div>}
              {preflight?.note && !preflight.blocked && <div className="muted small">{preflight.note}</div>}
              {preflight && !preflight.blocked && (
                preflight.ok
                  ? <div className="pos small">✓ Ready — the first order would pass{preflight.size?.shares ? ` (≈${preflight.size.shares} shares, $${fmt(preflight.size.notional, 0)})` : preflight.size?.contracts ? ` (${preflight.size.contracts} contract${preflight.size.contracts === 1 ? "" : "s"}, ≈$${fmt(preflight.size.estNotional, 0)})` : ""}</div>
                  : <div className="neg small">✗ Would be blocked: {failing.map((c) => c.detail || CHECK_LABEL[c.name] || c.name).join("; ")}. Fix in Settings → Auto-trading, or change the account/size.</div>
              )}
            </div>
          )}
          <small className="muted">Fires only 09:30–10:30 / 14:45–16:00 ET (the book's prime windows); mid-day touches are logged, not taken. Stops and flatten can always sell, even if the kill switch is on.</small>
        </div>
      )}
    </Modal>
  );
}
