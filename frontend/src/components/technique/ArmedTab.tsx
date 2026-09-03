import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime, fmtTime } from "../../lib/format";
import { useStore } from "../../store";
import { useWorkspace, workspaceOf } from "../../lib/workspace";
import type { ArmedPlan, ArmedTrade, ArmScorecard } from "../../types";
import { Spinner } from "../ui";
import { InfoTip } from "../InfoTip";
import { ArmedDayPanel } from "./ArmedDayPanel";
import { SymIcon } from "../SymIcon";

export function fmt(n: number | null | undefined, d = 2) { return n === null || n === undefined ? "—" : Number(n).toFixed(d); }
export function pnlCls(v: number | null | undefined) { return (v ?? 0) > 0 ? "pos" : (v ?? 0) < 0 ? "neg" : ""; }

const STATUS_LABEL: Record<string, string> = {
  waiting: "watching", observed: "touched mid-day", fired: "FIRED", gapped_past: "gapped past", gapped_through: "gapped through stop",
  gap_void: "void (gap)", not_triggered: "no trigger", expired: "expired",
  exhausted: "done — 2 false breaks (R3.2)", invalidated: "level broken",
};
const TRADE_LABEL: Record<string, string> = {
  fired: "fired", critic_killed: "killed by critic", alert: "alert only", proposal: "proposal waiting", submitting: "submitting",
  working: "entry working", open: "IN TRADE", closed: "closed", cancelled: "cancelled", failed: "FAILED", skipped: "skipped",
  critic_unavailable: "critic down — not sent",
};

function TradeRow({ t }: { t: ArmedTrade }) {
  const nextTp = t.targets[t.trimsDone];
  return (
    <div className={`tq-armed-trade ${t.status}`}>
      <div className="tq-armed-trade-head">
        <span className="tq-chip">{t.triggerId}</span>
        <b>{TRADE_LABEL[t.status] ?? t.status}</b>
        <span className="muted">{t.kind.replace(/_/g, " ")} · fired {fmtTime(t.firedTs)} ({t.window?.replace(/_/g, " ")})</span>
        {t.status === "open" && <span className={`tq-badge ${pnlCls(t.unrealizedPnl)}`}>open {fmt(t.unrealizedPnl)} unreal.</span>}
        {t.status === "closed" && <span className={`tq-badge ${(t.realizedPnl ?? 0) >= 0 ? "setup" : "failed"}`}>{(t.realizedPnl ?? 0) >= 0 ? "+" : ""}{fmt(t.realizedPnl)} ({t.realizedR ?? "—"}R)</span>}
      </div>
      {t.contract && (
        <div className="tq-armed-contract">
          <b>{t.contract.display ?? t.contract.symbol}</b> · {t.contract.is0dte ? "0DTE" : `exp ${t.contract.expiry}`} · strike {fmt(t.contract.strike)} · bid/ask {fmt(t.contract.bid)}/{fmt(t.contract.ask)}
          {t.contract.delta !== undefined && t.contract.delta !== null ? ` · Δ ${t.contract.delta}` : ""}{t.contract.iv ? ` · IV ${t.contract.iv}` : ""}
          {t.contract.substituted ? <span className="neg" title="The bought contract differs from the one the tip/analyst named"> · SUBSTITUTED: {t.contract.substituted}</span> : null}
          {t.contract.warnings?.length ? <span className="neg"> · {t.contract.warnings.join("; ")}</span> : null}
        </div>
      )}
      <div className="tq-plan tq-armed-nums">
        <div className="tq-plan-cell"><small>{t.instrument === "options" ? "Premium" : "Entry"}</small><b>{fmt(t.avgFill ?? (t.instrument === "options" ? t.limitPrice : t.entry))}</b>
          <span>{t.instrument === "options" ? `underlying trigger ${fmt(t.entry)}${t.premiumPaid ? ` · paid ${fmt(t.premiumPaid)}` : ""}` : t.avgFill ? "filled" : `plan ${fmt(t.entry)}${t.limitPrice ? ` · limit ${fmt(t.limitPrice)}` : ""}`}</span></div>
        <div className="tq-plan-cell"><small>Size</small><b>{t.filledQty || t.qty || "—"}</b><span>{t.instrument === "options" ? (t.remaining ? `${t.remaining} contract(s) left` : "contract(s)") : t.remaining ? `${t.remaining} left` : t.qty ? "shares" : ""}</span></div>
        <div className="tq-plan-cell"><small>Stop</small><b className="neg">{fmt(t.stop)}</b><span>sell all if hit</span></div>
        <div className="tq-plan-cell"><small>Next target</small><b className="pos">{nextTp !== undefined ? fmt(nextTp) : "runner"}</b><span>{t.trimsDone}/{t.targets.length} trims done</span></div>
        <div className="tq-plan-cell"><small>Realized</small><b className={pnlCls(t.realizedPnl)}>{fmt(t.realizedPnl)}</b><span>{t.exits.length} exit(s)</span></div>
      </div>
      {t.reason && <div className="muted small">{t.reason}</div>}
      {t.proposalId && <div className="muted small">proposal {t.proposalId.slice(0, 8)} — approve it in Signals</div>}
      {t.exits.length > 0 && (
        <div className="muted small">exits: {t.exits.map((e, i) => `${e.kind} ${e.filledQty || e.qty}${e.price ? ` @ ${fmt(e.price)}` : ""}${e.status && !["FILLED"].includes(e.status) ? ` (${e.status})` : ""}`).join(" · ")}</div>
      )}
      {t.errors.length > 0 && <div className="neg small">{t.errors.slice(-2).join(" · ")}{t.retries ? ` · retries ${t.retries}` : ""}</div>}
      {t.critic && <div className="muted small">critic: {t.critic.kill ? "KILLED" : "survived"} — {t.critic.summary}</div>}
    </div>
  );
}

function Scorecard({ sc }: { sc: ArmScorecard }) {
  return (
    <div className="tq-armed-scorecard">
      <div className="tq-label">How it went vs the plan
        <InfoTip>After the close we replay the same session deterministically and compare: did the live plan fire when it should have, and how did the fills and exits line up? This is the record you review it by.</InfoTip>
      </div>
      <div className="tq-plan">
        <div className="tq-plan-cell"><small>Fired</small><b>{sc.actualFires} / {sc.theoreticalFires}</b><span>live vs the replay</span></div>
        <div className="tq-plan-cell"><small>Matched</small><b className={sc.matched === sc.theoreticalFires ? "pos" : ""}>{sc.matched}</b><span>same decision</span></div>
        <div className="tq-plan-cell"><small>Realized</small><b className={pnlCls(sc.realizedPnl)}>{fmt(sc.realizedPnl)}</b><span>this plan</span></div>
        <div className="tq-plan-cell"><small>Replay ΣR</small><b>{fmt(sc.theoreticalSumR)}</b><span>if traded on the stock</span></div>
      </div>
      {sc.rows.some((r) => r.notes.length) && (
        <ul className="tq-armed-sc-notes">
          {sc.rows.filter((r) => r.notes.length).map((r) => (
            <li key={r.trigger}><b>{r.trigger}</b> {r.kind}: {r.notes.join("; ")}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ArmedCard({ a, onChanged }: { a: ArmedPlan; onChanged: () => void }) {
  const toast = useStore((s) => s.toast);
  const openRun = useStore((s) => s.openTechniqueRun);
  const middayExp = useStore((s) => Boolean(s.settings["technique.arm.midday_trading"]));
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState(a.status === "armed" || a.status === "paused");
  const [audit, setAudit] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const live = a.portfolio.kind === "live" || a.portfolio.kind === "paper";
  const act = async (fn: () => Promise<any>, msg: string) => {
    setBusy(true);
    try { await fn(); toast("info", msg); onChanged(); } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  useEffect(() => { if (open) api.techniqueArmedAudit(a.runId).then(setAudit).catch(() => setAudit([])); }, [open, a.runId, a.events.length]);
  const openTrades = a.trades.filter((t) => t.status === "open" || t.status === "working");
  return (
    <div className={`panel mb tq-armed-card ${a.status} ${a.stale ? "stale" : ""}`}>
      <div className="panel-head tq-armed-head">
        <button type="button" className="tq-armed-sym tq-armed-sym-btn" onClick={() => setDay((v) => !v)}
          title={day ? "Hide the day view" : "Show today's chart + timeline: what happened, what was refused and why, what we're waiting for"}>
          <SymIcon sym={a.symbol} size={20} /> {a.symbol} <span className="tq-armed-sym-caret">{day ? "▾" : "▸"}</span>
        </button>
        {a.grade && <span className={`tq-grade g${a.grade}`}
          title="Deterministic plan grade — outcomes are scored against it for calibration (TRADING-RULES 1.2)">{a.grade}</span>}
        <span className={`tq-badge ${a.config.mode === "auto" ? (live ? "failed" : "setup") : "nosetup"}`} title="execution mode">
          {a.config.mode === "auto" ? (live ? "AUTO · REAL MONEY" : "AUTO") : a.config.mode.toUpperCase()}
        </span>
        <span className="tq-badge nosetup" title="instrument">{a.config.instrument === "options" ? `OPTIONS · ${a.config.contracts ?? "risk-sized"} ct` : "SHARES"}</span>
        {(() => {
          // the workspace already says practice/live — name the account only when it adds information
          const nm = a.portfolio.name ?? a.portfolio.id;
          if (live) return <span className="tq-badge failed" title="account">{nm} · {a.portfolio.kind === "paper" ? "PAPER" : "LIVE"}</span>;
          return nm.toUpperCase() === "PRACTICE" ? null : <span className="tq-badge nosetup" title="account">{nm}</span>;
        })()}
        {a.status !== "armed" && (
          <span className={`tq-badge ${a.status === "paused" ? "failed" : "nosetup"}`}>{a.status.toUpperCase()}</span>
        )}
        {a.stale && <span className="tq-badge failed">STALE DATA</span>}
        {a.stopReason && <span className="tq-badge failed" title={a.stopReason}>STOPPED</span>}
        {(a.horizonSessions ?? 1) > 1 && (
          <span className="tq-badge nosetup"
            title={`Multi-day plan: stays armed and rolls at each close until it fills or its last session (${a.expiresSession ?? a.planFor}) passes`}>
            DAY {a.sessionDay ?? 1} of {a.horizonSessions} · until {a.expiresSession ?? a.planFor}
          </span>
        )}
        {(() => {
          // window copy from the PLAN'S OWN rules (ARM-GAPS F1): the backend
          // stamps per-trigger windowOpenNow from the technique's windows — a
          // tip can fire mid-day; EM's prime-clock copy applies to EM only
          const w = a.sessionWindowNow;
          if (w === "extended") return <span className="tq-badge nosetup" title="market closed; nothing fires until the next session">MARKET CLOSED — RESUMES 9:30 AM ET</span>;
          const canFire = (a.triggers ?? []).some((t: any) => t.windowOpenNow && ["waiting", "observed"].includes(t.status));
          if (w === "midday" && !canFire) return middayExp
            ? <span className="tq-badge setup" title="R6.3 experiment is ON (Settings → Auto-trading → Experiments): mid-day fires are allowed and tagged for analysis">● MID-DAY · EXPERIMENT — fires allowed</span>
            : <span className="tq-badge warnbadge" title="this plan's windows avoid mid-day chop; touches are logged, nothing fires">⏸ MID-DAY · watching only — fires again 2:45 PM ET</span>;
          if (canFire) return <span className="tq-badge setup" title="one of this plan's own trading windows is open">● WINDOW OPEN — can fire</span>;
          return null;
        })()}
        {(a.technique && a.technique !== "enhanced_market") && (
          <span className="tq-badge nosetup" title="the technique that armed this plan">{a.technique.toUpperCase()}</span>
        )}
        <span className="sub tq-head-right">
          {a.lastPrice ? <>last <b>{fmt(a.lastPrice)}</b> · </> : null}
          bar {a.barAgeSeconds !== null && a.barAgeSeconds !== undefined ? `${a.barAgeSeconds}s ago` : "—"} · for {a.planFor}
        </span>
      </div>
      <div className="panel-body">
        {a.riskWarning && (
          <div className="tq-attention" title="arm-time preflight: the tip budget vs the platform risk caps">
            <b>{"⚠"} Budget vs risk caps</b>
            <div className="small">{a.riskWarning}</div>
          </div>
        )}
        {a.needsAttention && (
          <div className="tq-attention">
            <b>{"\u26a0"} Needs attention</b>
            <ul>{(a.attentionReasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
            {a.trades.some((t) => t.remaining > 0) ? (
              <div className="tq-attention-actions">
                <button className="danger-btn" disabled={busy}
                  title="Sell everything this plan still holds, at market, right now (reduce-only)"
                  onClick={() => act(() => api.techniqueArmedExit(a.runId), "Sell-now sent")}>Sell now (market)</button>
                <span className="muted small">the watchdog also retries failed exits automatically every 30s</span>
              </div>
            ) : (
              <span className="muted small">nothing is held \u2014 the entry was refused before any money moved;
                this is a heads-up that a planned trade was missed, not something to act on</span>
            )}
          </div>
        )}
        <div className="tq-armed-summary">{a.summary}</div>
        {a.stopReason && <div className="neg small tq-armed-stopline">Stopped: {a.stopReason}</div>}
        {day && <ArmedDayPanel a={a} />}
        {a.scorecard && <Scorecard sc={a.scorecard} />}
        <div className="tq-armed-triggers">
          {a.triggers.map((t) => (
            <div key={t.id} className={`tq-armed-trigger ${t.status}`}>
              <span className="tq-chip">{t.label ?? t.id}</span>
              <b>{t.kind.replace(/_/g, " ")}</b>
              <span>@ <b>{fmt(t.entry)}</b></span>
              <span className="muted">{t.distancePct !== undefined ? `${t.distancePct > 0 ? "+" : ""}${t.distancePct.toFixed(2)}% away` : ""}</span>
              <span className={`tq-badge ${t.status === "fired" ? "setup" : t.status === "waiting" ? "nosetup" : "failed"}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
              <span className="muted small">stop {fmt(t.stop)} · R:R {fmt(t.riskReward)}{t.observedMidday ? ` · ${t.observedMidday} mid-day touch(es)` : ""}</span>
            </div>
          ))}
          {a.triggers.length === 0 && <div className="muted">no valid triggers in this plan</div>}
        </div>
        {a.trades.length > 0 && <div className="tq-armed-trades">{a.trades.map((t) => (
          <div key={t.triggerId} className="tq-armed-traderow">
            <TradeRow t={t} />
            {(t.remaining ?? 0) > 0 && (
              <button className="link-btn danger" disabled={busy}
                title={`Sell the ${t.remaining} this trade still holds, at market, right now`}
                onClick={() => act(() => api.techniqueArmedExit(a.runId, t.triggerId), `${t.triggerId}: sell-now sent`)}>
                sell now
              </button>
            )}
          </div>
        ))}</div>}
        <div className="tq-armed-actions">
          {a.status === "armed" && <button className="ghost-btn" disabled={busy} onClick={() => act(() => api.techniquePause(a.runId), "Paused")}>Pause</button>}
          {a.status === "paused" && <button className="primary-btn" disabled={busy} onClick={() => act(() => api.techniqueResume(a.runId), "Resumed")}>Resume</button>}
          <button className="ghost-btn" disabled={busy}
            onClick={() => { if (confirm(`Disarm the ${a.symbol} plan? It stops watching its triggers for ${a.planFor}${openTrades.length ? " — open positions stay open (use Flatten & disarm to also sell them)" : ""}. Re-arm it any time from the run page.`)) act(() => api.techniqueDisarm(a.runId, false), "Disarmed"); }}>
            Disarm</button>
          {openTrades.length > 0 && <button className="ghost-btn neg" disabled={busy}
            onClick={() => { if (confirm(`Sell everything this plan holds in ${a.symbol} at market and disarm?`)) act(() => api.techniqueDisarm(a.runId, true), "Flattened and disarmed"); }}>
            Flatten &amp; disarm</button>}
          <label className="tq-armed-modesel" title="Change what happens when a trigger fires: alert = note only · proposal = you approve each trade · auto = trade and manage it automatically (auto derives a daily loss halt if none is set)">
            <span className="muted small">on fire:</span>
            <select value={a.config.mode} disabled={busy}
              onChange={(e) => { const m = e.target.value; void act(() => api.techniqueSetMode(a.runId, { mode: m }), `${a.symbol}: mode → ${m}`); }}>
              {["alert", "proposal", "auto"].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          {a.config.instrument === "options" && (
            <label className="tq-chipbtn" title="If the option entry is blocked (wide spread, elevated IV, no contract), buy the underlying shares instead of skipping — the level trade still gets expressed. SNOW lost +1.89R to a spread skip on 2026-08-25.">
              <input type="checkbox" disabled={busy} checked={a.config.entryFallback === "shares"}
                onChange={(e) => { const v = e.target.checked ? "shares" : "off"; void act(() => api.techniqueSetMode(a.runId, { entryFallback: v }), `${a.symbol}: fallback → ${v}`); }} />
              shares fallback
            </label>
          )}
          <button className="link-btn" onClick={() => openRun(a.runId)}>open plan</button>
          <button className="link-btn" onClick={() => setOpen((v) => !v)}>{open ? "hide log" : "log"}</button>
          <span className="muted small tq-head-right">risk {a.config.riskPct}% · max {a.config.maxQty} sh · critic {(a as any).reviewerAvailable === false ? "n/a (no reviewer)" : a.config.useCritic ? "on" : "off"} · flatten {a.config.flattenMinutesBeforeClose}m before close</span>
        </div>
        {open && (
          <div className="tq-armed-log">
            <div className="tq-label">Live log</div>
            <ul>{a.events.slice().reverse().slice(0, 25).map((e, i) => <li key={i}><span className="muted">{fmtTime(e.ts)}</span> <b>{e.event}</b> {e.text}</li>)}</ul>
            <div className="tq-label">Audit trail (journal)</div>
            {audit === null && <Spinner />}
            {audit && <ul>{audit.slice().reverse().slice(0, 40).map((e) => (
              <li key={e.id}><span className="muted">{e.ts ? fmtDateTime(e.ts) : ""}</span> <b>{e.type}</b>
                <span className="muted small"> {JSON.stringify(Object.fromEntries(Object.entries(e.payload ?? {}).filter(([k]) => !["trace", "config", "targets", "exits", "statuses"].includes(k)))).slice(0, 220)}</span></li>
            ))}</ul>}
          </div>
        )}
      </div>
    </div>
  );
}

export const WINDOW_SHORT: Record<string, [string, string]> = {
  prime_open: ["● open", "setup"], prime_close: ["● close", "setup"],
  midday: ["⏸ mid-day", "warnbadge"], extended: ["closed", "nosetup"],
};

export function nearestPct(a: ArmedPlan): number {
  const ds = (a.triggers ?? []).map((t) => Math.abs(t.distancePct ?? 99));
  return ds.length ? Math.min(...ds) : 99;
}
export function fleetRank(a: ArmedPlan): number {
  if (a.needsAttention) return 0;
  if (a.openPositions > 0 || (a.trades ?? []).some((t) => ["open", "working", "submitting"].includes(t.status))) return 1;
  if ((a.trades ?? []).length) return 2;
  return 3;
}
