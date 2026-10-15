// Scout agent (2026-10-14, PLAN section 9): a tool-using research agent proposes up to three swing trades each
// morning; code checks and sizes them; simulated research books trade them beside a random twin and the screen.
// This tab shows the scoreboard, the graduation gate, each day's proposals with their cited evidence, and lessons.
import { useState } from "react";
import { Collapse, DisclosureHead } from "../components/Collapse";
import { SymIcon } from "../components/SymIcon";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useStore } from "../store";
import type { ScoutAgentDiff, ScoutAgentProposal, ScoutAgentRun, ScoutAgentView, ScoutLane } from "../types";

const LANES: { key: string; label: string; note: string }[] = [
  { key: "agent_claude", label: "Agent · Claude", note: "the agent's picks" },
  { key: "agent_gpt", label: "Agent · GPT", note: "same tools, other model" },
  { key: "agent_random", label: "Random twin", note: "a random name per Claude pick, same plan shape" },
  { key: "agent_screen", label: "Screen only", note: "the screen's top names, fixed plan" },
];
const STATUS: Record<string, string> = {
  ok: "proposed", no_trade: "no trade", budget: "budget stop", error: "error", skipped: "skipped", running: "running",
};

function money(v: number | null | undefined) {
  if (v == null) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}$${s}`;
}
function rr(v: number | null | undefined, d = 2) {
  if (v == null) return <span className="muted">—</span>;
  return <span className={v > 0 ? "pos" : v < 0 ? "neg" : ""}>{v > 0 ? "+" : v < 0 ? "−" : ""}{Math.abs(v).toFixed(d)}R</span>;
}
function shortDay(d: string | null | undefined) {
  if (!d) return "—";
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, day)).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}
function diffText(x: ScoutAgentDiff) {
  if (x.diff == null) return <span className="muted">not enough closed trades on both sides</span>;
  return <>{rr(x.diff)} <span className="muted mono-num">95% {x.lo?.toFixed(2)} to {x.hi?.toFixed(2)} · {x.sessions} sessions</span></>;
}

export function AgentTab() {
  const st = useAsync(() => api.scoutAgent(), []);
  if (st.loading && !st.data) return <Spinner label="loading the agent…" />;
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  const v = st.data as ScoutAgentView;
  return (
    <>
      <Today v={v} onReload={st.reload} />
      <Scoreboard v={v} />
      <Gate v={v} />
      <Runs runs={v.runs.filter((r) => r.lane !== "review")} />
      <Positions lanes={v.lanes} />
      <Lessons v={v} />
    </>
  );
}

function Today({ v, onReload }: { v: ScoutAgentView; onReload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const last = v.runs.find((r) => r.lane !== "review");
  const day = last?.day;
  const todays = v.runs.filter((r) => r.day === day && r.lane !== "review");
  const at = v.schedule.find((j) => j.name === "scout_agent")?.at ?? "07:30";
  const run = async () => {
    setBusy(true); setErr(null);
    try { await api.scoutAgentRunNow(); setTimeout(onReload, 4000); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="panel mb">
      <div className="panel-head">Agent <span className="sub">{v.enabled ? `runs at ${at} ET on session days; entries 10:00–11:30 ET` : "off (techniques.scout.agent_enabled)"}</span>
        <span style={{ flex: 1 }} />
        {v.enabled && <button className="chip-btn" disabled={busy} onClick={run}>{busy ? "starting…" : "Run now"}</button>}
      </div>
      <div className="panel-body">
        {err && <div className="neg">{err}</div>}
        {!todays.length ? <span className="muted">No run yet. The first scheduled run is the next session's morning.</span> : (
          <div className="scout-agent-today">
            <span className="muted">{shortDay(day)}</span>
            {todays.map((r) => {
              const picks = r.proposals.filter((p) => p.check.ok).map((p) => p.ticker);
              return (
                <span key={r.id} className="scout-agent-chip">
                  <b>{r.lane === "claude" ? "Claude" : "GPT"}</b> {STATUS[r.status] ?? r.status}
                  {picks.length ? `: ${picks.join(", ")}` : ""}
                  <span className="muted mono-num"> · {r.toolCalls} tools · ${r.costUsd.toFixed(2)}</span>
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Scoreboard({ v }: { v: ScoutAgentView }) {
  const sc = v.scorecard;
  return (
    <div className="panel mb">
      <div className="panel-head">Scoreboard <span className="sub">closed trades, after fees · R = result ÷ planned risk · sample from {shortDay(sc.sampleStart)}</span></div>
      <div className="scout-agent-scroll"><table className="tbl">
        <thead><tr><th>Book</th><th className="num">Closed</th><th className="num">Mean R</th><th className="num">Hit</th>
          <th className="num">vs SPY</th><th className="num">Net</th><th className="num">Open</th></tr></thead>
        <tbody>
          {LANES.map((l) => {
            const s = sc.lanes[l.key];
            if (!s) return null;
            return (
              <tr key={l.key}>
                <td><b>{l.label}</b> <span className="muted">{l.note}</span></td>
                <td className="num mono-num">{s.closed}</td>
                <td className="num mono-num">{rr(s.meanR)}</td>
                <td className="num mono-num">{s.hitRate == null ? "—" : `${Math.round(s.hitRate * 100)}%`}</td>
                <td className="num mono-num">{s.meanExcessVsSpy == null ? "—" : `${s.meanExcessVsSpy >= 0 ? "+" : "−"}${Math.abs(s.meanExcessVsSpy * 100).toFixed(1)}%`}</td>
                <td className={`num mono-num ${s.netPnl > 0 ? "pos" : s.netPnl < 0 ? "neg" : ""}`}>{s.closed ? money(s.netPnl) : "—"}</td>
                <td className="num mono-num muted">{s.open}{s.pending ? ` +${s.pending} pending` : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table></div>
      <div className="panel-body scout-agent-diffs">
        <div>Claude minus random: {diffText(sc.gate.agentVsRandom)}</div>
        <div>Claude minus screen: {diffText(sc.vsScreen)}</div>
        <div>GPT minus random: {diffText(sc.gptVsRandom)}</div>
      </div>
    </div>
  );
}

function Gate({ v }: { v: ScoutAgentView }) {
  const g = v.scorecard.gate;
  return (
    <div className="panel mb">
      <div className="panel-head">Graduation gate <span className="sub">{g.verdict} · passing it only allows the next step to be decided</span></div>
      <div className="panel-body">
        {g.checks.map((c) => (
          <div key={c.name} className="scout-agent-check">
            <span className={c.ok ? "pos" : "muted"} aria-label={c.ok ? "met" : "not met"}>{c.ok ? "✓" : "○"}</span>
            <span>{c.name}</span>
            <span className="muted mono-num">need {c.need} · have {c.have == null ? "—" : c.have}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Runs({ runs }: { runs: ScoutAgentRun[] }) {
  const [open, setOpen] = useState<string | null>(runs[0]?.id ?? null);
  if (!runs.length) return <EmptyState title="No agent runs yet" hint="The agent runs each session morning before the open." art={false} />;
  return (
    <div className="panel mb">
      <div className="panel-head">Runs and proposals <span className="sub">every proposal with the code checks' verdict and the tool results it quoted</span></div>
      {runs.map((r) => (
        <div key={r.id} className="scout-agent-run">
          <DisclosureHead open={open === r.id} onToggle={() => setOpen(open === r.id ? null : r.id)}>
            <span>{shortDay(r.day)}</span> <b>{r.lane === "claude" ? "Claude" : "GPT"}</b>
            <span className="muted"> {STATUS[r.status] ?? r.status} · {r.proposals.filter((p) => p.check.ok).length} of {r.proposals.length} accepted · {r.toolCalls} tool calls · ${r.costUsd.toFixed(2)}</span>
          </DisclosureHead>
          <Collapse open={open === r.id}><RunBody r={r} /></Collapse>
        </div>
      ))}
    </div>
  );
}

function RunBody({ r }: { r: ScoutAgentRun }) {
  const [tx, setTx] = useState<ScoutAgentRun | null>(null);
  const [showTx, setShowTx] = useState(false);
  const loadTx = async () => { setShowTx(!showTx); if (!tx) setTx(await api.scoutAgentRun(r.id)); };
  return (
    <div className="scout-agent-body">
      {r.reason && <div className="muted mb">{r.reason}</div>}
      {r.proposals.map((p, i) => <ProposalCard key={i} p={p} />)}
      {!r.proposals.length && <div className="muted">No proposals.</div>}
      <button className="link-btn" onClick={loadTx}>{showTx ? "hide" : "show"} the tool calls</button>
      {showTx && tx?.transcript && (
        <div className="scout-agent-tx">
          {tx.transcript.map((t) => (
            <details key={t.id}><summary><b>{t.id}</b> {t.tool} {t.args?.ticker ? String(t.args.ticker) : ""}</summary><pre>{t.text}</pre></details>
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p }: { p: ScoutAgentProposal }) {
  const c = p.check;
  const plan = c.plan;
  return (
    <div className={`scout-agent-prop ${c.ok ? "" : "refused"}`}>
      <div className="scout-agent-prop-head">
        <SymIcon sym={p.ticker} size={18} /><b>{p.ticker}</b>
        <span className={c.ok ? "pos" : "neg"}>{c.ok ? "accepted" : "refused"}</span>
        {plan && <span className="muted mono-num">
          {plan.entry.kind === "limit" ? `limit ${plan.entry.limit?.toFixed(2)}` : `now ~${plan.entry.ref.toFixed(2)}`} · stop {plan.stop.toFixed(2)} ({plan.stopAtr.toFixed(1)} ATR)
          · targets {plan.targets.map((t, i) => `${t.toFixed(2)} (${plan.targetsR[i]?.toFixed(1)}R)`).join(", ")} · {plan.horizon} sessions · conviction {plan.conviction}
        </span>}
        {p.twin?.ticker && <span className="muted">· random twin {p.twin.ticker}</span>}
      </div>
      {plan?.thesis && <div>{plan.thesis}</div>}
      {plan?.invalidation && <div className="muted">Wrong if: {plan.invalidation}</div>}
      {!c.ok && <div className="neg">{c.reasons.join("; ")}</div>}
      {c.notes.length > 0 && <div className="muted">{c.notes.join("; ")}</div>}
      {c.evidence.length > 0 && (
        <ul className="scout-agent-ev">
          {c.evidence.map((e, i) => <li key={i}><span className="muted mono-num">{e.resultId}</span> “{e.quote}”{e.point ? <span className="muted"> — {e.point}</span> : null}</li>)}
        </ul>
      )}
      {c.droppedEvidence.length > 0 && <div className="muted">{c.droppedEvidence.length} evidence item(s) dropped: {c.droppedEvidence.map((d) => d.why).join("; ")}</div>}
    </div>
  );
}

function Positions({ lanes }: { lanes: ScoutLane[] }) {
  const openPortfolios = useStore((s) => s.openPortfolios);
  const rows = lanes.flatMap((l) => [...l.openTrades, ...l.closedTrades.slice(-10)].map((t) => ({ l, t })));
  if (!rows.length) return null;
  return (
    <div className="panel mb">
      <div className="panel-head">Trades <span className="sub">open, and the last closed per book</span></div>
      <div className="scout-agent-scroll"><table className="tbl"><tbody>
        {rows.map(({ l, t }) => (
          <tr key={t.id}>
            <td><b>{t.ticker}</b></td>
            <td className="muted">{LANES.find((x) => x.key === l.lane)?.label ?? l.label}</td>
            <td className="muted">{shortDay(t.entryDate)}</td>
            <td className="muted mono-num">{t.qty} @ {t.entryPrice?.toFixed(2)} · stop {t.stopPrice?.toFixed(2)}
              {t.exitPrice != null ? ` → ${t.exitPrice.toFixed(2)} (${t.exitReason ?? ""})` : t.mark != null ? ` · now ${t.mark.toFixed(2)}` : ""}</td>
            <td className="num mono-num">{money(t.netPnl ?? t.openNetPnl ?? null)}</td>
            <td>{l.portfolioId && <button className="link-btn" onClick={() => openPortfolios(l.portfolioId!)}>book</button>}</td>
          </tr>
        ))}
      </tbody></table></div>
    </div>
  );
}

function Lessons({ v }: { v: ScoutAgentView }) {
  return (
    <div className="panel mb">
      <div className="panel-head">Lessons <span className="sub">written by the weekly review from closed cases; supplied from the next week's first session</span></div>
      <div className="panel-body">
        {!v.lessons.length ? <span className="muted">None yet. The first review needs at least four closed picks.</span> :
          v.lessons.map((x) => (
            <div key={x.id} className={`scout-agent-lesson ${x.status}`}>
              <span>{x.text}</span>
              <span className="muted"> · {x.cases.length} cases · {x.status === "active" ? `from ${shortDay(x.effectiveFrom)}` : `retired ${shortDay(x.retiredFrom)}`}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
