import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime, fmtTime } from "../../lib/format";
import { useStore } from "../../store";
import { useWorkspace, workspaceOf } from "../../lib/workspace";
import type { ArmedPlan, ArmedTrade, ArmScorecard } from "../../types";
import { Spinner } from "../ui";
import { InfoTip } from "../InfoTip";
import { ArmedDayPanel } from "./ArmedDayPanel";

function fmt(n: number | null | undefined, d = 2) { return n === null || n === undefined ? "—" : Number(n).toFixed(d); }
function pnlCls(v: number | null | undefined) { return (v ?? 0) > 0 ? "pos" : (v ?? 0) < 0 ? "neg" : ""; }

const STATUS_LABEL: Record<string, string> = {
  waiting: "watching", observed: "touched mid-day", fired: "FIRED", gapped_past: "gapped past", gapped_through: "gapped through stop",
  gap_void: "void (gap)", not_triggered: "no trigger", expired: "expired",
};
const TRADE_LABEL: Record<string, string> = {
  fired: "fired", critic_killed: "killed by critic", alert: "alert only", proposal: "proposal waiting", submitting: "submitting",
  working: "entry working", open: "IN TRADE", closed: "closed", cancelled: "cancelled", failed: "FAILED", skipped: "skipped",
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

function ArmedCard({ a, onChanged }: { a: ArmedPlan; onChanged: () => void }) {
  const toast = useStore((s) => s.toast);
  const openRun = useStore((s) => s.openTechniqueRun);
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
          {a.symbol} <span className="tq-armed-sym-caret">{day ? "▾" : "▸"}</span>
        </button>
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
        {(() => {
          const w = a.sessionWindowNow;
          if (w === "prime_open") return <span className="tq-badge setup" title="R6.1 — one of the book's two trading windows">● LIVE WINDOW — can fire until 10:30 AM ET</span>;
          if (w === "prime_close") return <span className="tq-badge setup" title="R6.2 — one of the book's two trading windows">● LIVE WINDOW — can fire until 4:00 PM ET</span>;
          if (w === "midday") return <span className="tq-badge warnbadge" title="R6.3 — mid-day chop is avoided; touches are logged, nothing fires">⏸ MID-DAY · watching only — fires again 2:45 PM ET</span>;
          if (w === "extended") return <span className="tq-badge nosetup" title="R6.4 — market closed; nothing fires until the next session's windows">MARKET CLOSED — resumes 9:30 AM ET</span>;
          return null;
        })()}
        <span className="sub tq-head-right">
          {a.lastPrice ? <>last <b>{fmt(a.lastPrice)}</b> · </> : null}
          bar {a.barAgeSeconds !== null && a.barAgeSeconds !== undefined ? `${a.barAgeSeconds}s ago` : "—"} · for {a.planFor}
        </span>
      </div>
      <div className="panel-body">
        {a.needsAttention && (
          <div className="tq-attention">
            <b>\u26a0 Needs attention</b>
            <ul>{(a.attentionReasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
            <div className="tq-attention-actions">
              <button className="danger-btn" disabled={busy}
                title="Sell everything this plan still holds, at market, right now (reduce-only)"
                onClick={() => act(() => api.techniqueArmedExit(a.runId), "Sell-now sent")}>Sell now (market)</button>
              <span className="muted small">the watchdog also retries failed exits automatically every 30s</span>
            </div>
          </div>
        )}
        <div className="tq-armed-summary">{a.summary}</div>
        {a.stopReason && <div className="neg small tq-armed-stopline">Stopped: {a.stopReason}</div>}
        {day && <ArmedDayPanel a={a} />}
        {a.scorecard && <Scorecard sc={a.scorecard} />}
        <div className="tq-armed-triggers">
          {a.triggers.map((t) => (
            <div key={t.id} className={`tq-armed-trigger ${t.status}`}>
              <span className="tq-chip">{t.id}</span>
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
          <button className="ghost-btn" disabled={busy} onClick={() => act(() => api.techniqueDisarm(a.runId, false), "Disarmed")}>Disarm</button>
          {openTrades.length > 0 && <button className="ghost-btn neg" disabled={busy}
            onClick={() => { if (confirm(`Sell everything this plan holds in ${a.symbol} at market and disarm?`)) act(() => api.techniqueDisarm(a.runId, true), "Flattened and disarmed"); }}>
            Flatten &amp; disarm</button>}
          <button className="link-btn" onClick={() => openRun(a.runId)}>open plan</button>
          <button className="link-btn" onClick={() => setOpen((v) => !v)}>{open ? "hide log" : "log"}</button>
          <span className="muted small tq-head-right">risk {a.config.riskPct}% · max {a.config.maxQty} sh · critic {a.config.useCritic ? "on" : "off"} · flatten {a.config.flattenMinutesBeforeClose}m before close</span>
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

/** The Armed dashboard: what is armed, in which account and mode, what it is
 *  watching, what fired, what it holds — with pause / resume / disarm / stop all. */
export function ArmedTab() {
  const allArmed = useStore((s) => s.techniqueArmed);
  const setArmed = useStore((s) => s.setTechniqueArmed);
  const halt = useStore((s) => s.halt);
  const settings = useStore((s) => s.settings);
  const toast = useStore((s) => s.toast);
  const [history, setHistory] = useState<any[]>([]);
  const ws = useWorkspace();
  const portfolios = useStore((s) => s.portfolios);
  const pmap = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p])), [portfolios]);
  const armed = useMemo(() => allArmed.filter((a) => workspaceOf(a.portfolio?.kind) === ws), [allArmed, ws]);
  const otherArmed = allArmed.length - armed.length;
  const wsHistory = useMemo(
    () => history.filter((h) => workspaceOf(pmap[h.portfolioId]?.kind) === ws), [history, pmap, ws]);
  const refresh = useCallback(() => {
    api.techniqueArmed().then(setArmed).catch(() => undefined);
    api.techniqueArmedHistory().then(setHistory).catch(() => undefined);
  }, [setArmed]);
  useEffect(() => { refresh(); const id = setInterval(refresh, 30_000); return () => clearInterval(id); }, [refresh]);
  const tradingMode = String(settings["trading.mode"] ?? "practice");
  void settings;
  const openCount = useMemo(() => armed.reduce((n, a) => n + a.openPositions, 0), [armed]);
  const pnl = useMemo(() => armed.reduce((n, a) => n + (a.realizedPnl ?? 0), 0), [armed]);
  const stopAll = async (flatten: boolean) => {
    if (!confirm(flatten ? "Sell every open armed position at market and disarm all plans?" : "Disarm all armed plans? Open positions stay open.")) return;
    try { const r = await api.techniqueStopAll(flatten); toast("info", `Disarmed ${r.disarmed} plan(s)`); refresh(); }
    catch (e: any) { toast("error", e.message); }
  };
  return (
    <div>
      <div className="panel mb tq-armed-top">
        <div className="panel-body tq-armed-topbar">
          <div className="tq-armed-kpi"><small>Armed</small><b>{armed.length}</b></div>
          <div className="tq-armed-kpi"><small>In trade</small><b className={openCount ? "pos" : ""}>{openCount}</b></div>
          <div className="tq-armed-kpi"><small>Realized today</small><b className={pnlCls(pnl)}>{fmt(pnl)}</b></div>
          <div className="tq-armed-kpi"><small>Workspace <InfoTip>Everything on this page belongs to the active workspace. PRACTICE = the simulator, fake money. LIVE = your real accounts (orders route for real). Switch it next to HALT in the top bar.</InfoTip></small><b className={tradingMode === "live" ? "neg" : ""}>{tradingMode.toUpperCase()}</b></div>
          <div className="tq-armed-kpi"><small>Kill switch <InfoTip>The big red HALT stops all new buys instantly. Stops and flatten can still sell so you're never trapped in a position.</InfoTip></small><b className={halt.engaged ? "neg" : "pos"}>{halt.engaged ? "ENGAGED" : "off"}</b></div>
          <div className="tq-armed-topactions">
            {armed.length > 0 && (
              <button className="ghost-btn" onClick={() => stopAll(false)}
                title="Disarm every plan — open positions stay open">Stop all</button>
            )}
            {openCount > 0 && (
              <button className="ghost-btn neg" onClick={() => stopAll(true)}
                title="Sell everything the plans hold at market, then disarm every plan">Flatten &amp; stop all</button>
            )}
          </div>
        </div>
      </div>
      {otherArmed > 0 && (
        <div className="panel mb"><div className="panel-body tq-ws-note">
          <b>{otherArmed}</b> plan{otherArmed === 1 ? " is" : "s are"} armed in the <b>{ws === "live" ? "Practice" : "LIVE"}</b> workspace and stay{otherArmed === 1 ? "s" : ""} active —
          switch the workspace (next to HALT) to see and manage {otherArmed === 1 ? "it" : "them"}.
        </div></div>
      )}
      {armed.length === 0 && (
        <div className="panel mb"><div className="panel-body muted">
          Nothing armed in this workspace. Open a plan (Analyse with a past Period, or History) and press <b>Arm for live triggers</b>, or arm today's plan for a symbol above.
          Armed plans watch live 1-minute bars, fire only inside the prime windows (R6), and — depending on the mode — alert, propose, or execute.
        </div></div>
      )}
      {armed.map((a) => <ArmedCard key={a.runId} a={a} onChanged={refresh} />)}
      {history.length > 0 && (
        <div className="panel">
          <div className="panel-head">History <span className="sub">{history.length} armed plan(s)</span></div>
          <div className="panel-body" style={{ padding: 0 }}>
            <table className="tq-table tq-wf">
              <thead><tr><th>Symbol</th><th>For</th><th>Mode</th><th>Account</th><th>Status</th><th>Fired</th><th>Realized</th><th>Armed at</th></tr></thead>
              <tbody>{wsHistory.map((h) => (
                <tr key={h.runId} className="clickable" onClick={() => useStore.getState().openTechniqueRun(h.runId)}>
                  <td><b>{h.symbol}</b></td><td>{h.planFor}</td><td>{h.mode}</td>
                  <td className="muted">{pmap[h.portfolioId]?.name ?? h.portfolioId.slice(0, 8)}{" "}
                    <span className={`status-pill ${workspaceOf(pmap[h.portfolioId]?.kind) === "live" ? "bad" : "dim"}`}>{workspaceOf(pmap[h.portfolioId]?.kind) === "live" ? "live" : "practice"}</span></td>
                  <td>{h.status}</td><td>{(h.state?.trades ?? []).length}</td>
                  <td className={pnlCls(h.state?.realizedPnl)}>{fmt(h.state?.realizedPnl)}</td>
                  <td className="muted">{h.createdAt ? fmtDateTime(h.createdAt) : ""}</td></tr>))}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
