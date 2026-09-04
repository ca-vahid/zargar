// The Team2 page (docs/techniques/team2/PLAN.md G-2): Plans · Armed · History · Validation.
// Less is more: one-line rows, underline tabs, everything links to its run / armed plan.
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useStore } from "../store";

type Tab = "plans" | "armed" | "history" | "validation";

type Team2Status = {
  enabled: boolean; mode: string; symbols: string[]; planAt: string; preopenAt: string;
  zeroDte: { enabled: boolean; last_entry_et: string; flatten_et: string; max_contracts: number; premium_cap: number } | null;
  armed: any[]; macro: { source: string; events: number; next: { date: string; name: string } | null } | null;
  thresholds: Record<string, unknown>;
};
type Team2Run = { runId: string; symbol: string; planFor: string | null; sheet: string | null; complete: boolean | null;
  dayType: string | null; createdAt: string | null; armed: boolean };
type ReadEvent = { ts: number; time: string; event: string; why: string; [k: string]: unknown };
type ReadResult = { events: ReadEvent[]; trades: any[]; summary: Record<string, any>; bias: any; setups: any[] };
type Sweep = { start: string; end: string; symbols: string[]; rows: any[]; summary: Record<string, any>; thresholds: Record<string, unknown> };

const TABS: { key: Tab; label: string }[] = [
  { key: "plans", label: "Plans" }, { key: "armed", label: "Armed" }, { key: "history", label: "History" },
  { key: "validation", label: "Validation" },
];

function ymd(d: Date): string { return d.toISOString().slice(0, 10); }

export function Team2Page() {
  const toast = useStore((s) => s.toast);
  const pageTab = useStore((s) => s.pageTab);
  const setPageTab = useStore((s) => s.setPageTab);
  const openArmedPlan = useStore((s) => s.openArmedPlan);
  const tab: Tab = (TABS.some((t) => t.key === pageTab) ? pageTab : "plans") as Tab;
  const [status, setStatus] = useState<Team2Status | null>(null);
  const [runs, setRuns] = useState<Team2Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [read, setRead] = useState<{ source: string; result: ReadResult } | null>(null);
  const [sweep, setSweep] = useState<Sweep | null>(null);
  const [sweepForm, setSweepForm] = useState(() => {
    const end = new Date();
    const start = new Date(end.getTime() - 21 * 86400_000);
    return { start: ymd(start), end: ymd(end), overrides: "" };
  });

  const refresh = useCallback(async () => {
    try {
      const [st, rs] = await Promise.all([api.get<Team2Status>("/api/team2/status"), api.get<Team2Run[]>("/api/team2/runs?limit=60")]);
      setStatus(st);
      setRuns(rs);
    } catch { /* engine warming up */ }
    setLoading(false);
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 30_000); return () => clearInterval(t); }, [refresh]);

  useEffect(() => {
    if (!selected) { setRead(null); return; }
    let dead = false;
    api.get<{ source: string; result: ReadResult }>(`/api/team2/runs/${selected}/read`)
      .then((r) => { if (!dead) setRead(r); })
      .catch((e) => toast("error", `read failed: ${String(e)}`));
    return () => { dead = true; };
  }, [selected, toast]);

  const planNow = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>("/api/team2/plan-now", { arm: true });
      toast(r.failed?.length ? "error" : "info", `Team2: ${r.runs?.length ?? 0} plan(s) for ${r.planFor}, ${r.armed?.length ?? 0} armed` + (r.failed?.length ? ` — ${r.failed.join("; ")}` : ""));
      await refresh();
    } catch (e) { toast("error", `plan failed: ${String(e)}`); }
    setBusy(false);
  };

  const runSweep = async () => {
    setBusy(true);
    try {
      let overrides: Record<string, unknown> | null = null;
      if (sweepForm.overrides.trim()) {
        overrides = {};
        for (const part of sweepForm.overrides.split(/[,\s]+/).filter(Boolean)) {
          const [k, v] = part.split("=");
          if (!k || v === undefined) continue;
          overrides[k] = v === "true" ? true : v === "false" ? false : Number.isNaN(Number(v)) ? v : Number(v);
        }
      }
      const r = await api.post<Sweep>("/api/team2/sweep", { start: sweepForm.start, end: sweepForm.end, overrides });
      setSweep(r);
    } catch (e) { toast("error", `sweep failed: ${String(e)}`); }
    setBusy(false);
  };

  const armedRows = useMemo(() => (status?.armed ?? []).filter((a: any) => a.technique === "team2" || true), [status]);
  const todaysPlans = useMemo(() => {
    const latest = runs.length ? runs[0].planFor : null;
    return runs.filter((r) => r.planFor === latest);
  }, [runs]);

  if (loading) return <div className="page"><Spinner label="loading Team2…" /></div>;

  return (
    <div className="page flow-page">
      <div className="flow-head">
        <div>
          <div className="page-title">Team2</div>
          <div className="muted flow-head-sub">
            {status ? <>
              {status.symbols?.join(" · ")} · {status.mode} mode · plans {status.planAt} ET, pre-open {status.preopenAt}
              {status.zeroDte?.enabled ? ` · 0DTE: entries until ${status.zeroDte.last_entry_et}, flat by ${status.zeroDte.flatten_et}` : " · 0DTE policy off"}
              {status.macro?.next ? ` · next macro: ${status.macro.next.name} ${status.macro.next.date}` : ""}
            </> : "status unavailable"}
          </div>
        </div>
        <div className="tabs" role="tablist" style={{ marginLeft: 10 }}>
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""} onClick={() => setPageTab(t.key)}>{t.label}</button>
          ))}
        </div>
        <button className="ghost-btn" disabled={busy} onClick={planNow}>{busy ? "Working…" : "Plan now"}</button>
      </div>

      {tab === "plans" && <HowItWorks status={status} />}
      {tab === "plans" && (
        todaysPlans.length === 0 ? <EmptyState title="No plans yet" hint="Plan now builds tonight's skeleton for each symbol (prior-day zones, targets) and arms it in the configured mode; 09:25 completes it with the pre-market range." /> :
        <table className="table">
          <thead><tr><th>Symbol</th><th>For</th><th>Day</th><th>Sheet</th><th></th></tr></thead>
          <tbody>
            {todaysPlans.map((r) => (
              <tr key={r.runId} className={selected === r.runId ? "selected" : ""} onClick={() => setSelected(r.runId)}>
                <td className="mono-num">{r.symbol}</td>
                <td className="mono-num">{r.planFor}</td>
                <td className="muted">{r.dayType ?? (r.complete ? "—" : "pre-open pending")}</td>
                <td className="muted" style={{ whiteSpace: "normal" }}>{r.sheet}</td>
                <td>{r.armed ? <button className="ghost-btn" onClick={(e) => { e.stopPropagation(); openArmedPlan(r.runId); }}>armed →</button> : <span className="muted">not armed</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "armed" && (
        armedRows.length === 0 ? <EmptyState title="Nothing armed" hint="Armed Team2 plans appear here and on the Armed page." /> :
        <table className="table">
          <thead><tr><th>Symbol</th><th>For</th><th>Status</th><th>Mode</th><th>Trades</th><th></th></tr></thead>
          <tbody>
            {armedRows.map((a: any) => (
              <tr key={a.runId}>
                <td className="mono-num">{a.symbol}</td><td className="mono-num">{a.planFor}</td>
                <td>{a.status}{a.needsAttention ? " · needs attention" : ""}</td><td>{a.config?.mode ?? a.mode}</td>
                <td className="mono-num">{(a.trades ?? []).length}</td>
                <td><button className="ghost-btn" onClick={() => openArmedPlan(a.runId)}>open →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "history" && (
        <div className="flow-split">
          <div>
            {runs.length === 0 ? <EmptyState title="No runs" /> :
            <table className="table">
              <thead><tr><th>For</th><th>Symbol</th><th>Day</th><th>Built</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.runId} className={selected === r.runId ? "selected" : ""} onClick={() => setSelected(r.runId)}>
                    <td className="mono-num">{r.planFor}</td><td className="mono-num">{r.symbol}</td>
                    <td className="muted">{r.dayType ?? "—"}</td><td className="muted mono-num">{r.createdAt?.slice(0, 16).replace("T", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
          </div>
          <div>
            {!selected ? <div className="state-note">Pick a run to see what the method saw.</div> :
             !read ? <Spinner label="reading…" /> :
             <ReadView read={read} />}
          </div>
        </div>
      )}

      {tab === "validation" && (
        <div>
          <div className="flow-head" style={{ gap: 8, flexWrap: "wrap" }}>
            <label className="muted">from <input value={sweepForm.start} onChange={(e) => setSweepForm({ ...sweepForm, start: e.target.value })} style={{ width: 110 }} /></label>
            <label className="muted">to <input value={sweepForm.end} onChange={(e) => setSweepForm({ ...sweepForm, end: e.target.value })} style={{ width: 110 }} /></label>
            <label className="muted">variant <input placeholder="pullback_max_touches=3 target_premium=0.5" value={sweepForm.overrides} onChange={(e) => setSweepForm({ ...sweepForm, overrides: e.target.value })} style={{ width: 300 }} /></label>
            <button className="ghost-btn" disabled={busy} onClick={runSweep}>{busy ? "Sweeping…" : "Run sweep"}</button>
          </div>
          {!sweep ? <div className="state-note">A sweep walks every banked day with the same read the live runner uses (premium path: Black–Scholes on the VIX proxy, fees and slippage included). Variants change one number at a time.</div> :
          <SweepView sweep={sweep} />}
        </div>
      )}
    </div>
  );
}

function ReadView({ read }: { read: { source: string; result: ReadResult } }) {
  const r = read.result;
  const s = r.summary ?? {};
  return (
    <div>
      <div className="muted" style={{ marginBottom: 6 }}>
        {read.source === "live" ? "live read" : "replay"} · {s.trades ?? 0} trade(s), {s.wins ?? 0} won · sum {s.pnlPctSum ?? 0}% · bias {r.bias?.label ?? "none"} · σ {s.sigma}
      </div>
      {(r.trades ?? []).length > 0 && (
        <table className="table" style={{ marginBottom: 8 }}>
          <thead><tr><th>Setup</th><th>Side</th><th>Entry</th><th>Strike</th><th>Prem</th><th>Result</th><th>Exit</th></tr></thead>
          <tbody>
            {r.trades.map((t: any, i: number) => (
              <tr key={i}>
                <td>{t.setup}</td><td>{t.direction}</td><td className="mono-num">{t.entrySpot}</td><td className="mono-num">{t.strike}</td>
                <td className="mono-num">{t.entryPremium}</td><td className="mono-num">{t.pnlPct > 0 ? "+" : ""}{t.pnlPct}%</td>
                <td className="muted" style={{ whiteSpace: "normal" }}>{t.exitReason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <table className="table">
        <thead><tr><th>Time</th><th>Event</th><th>Why</th></tr></thead>
        <tbody>
          {(r.events ?? []).map((e, i) => (
            <tr key={i}><td className="mono-num">{e.time}</td><td>{e.event}</td><td className="muted" style={{ whiteSpace: "normal" }}>{e.why}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SweepView({ sweep }: { sweep: Sweep }) {
  const s = sweep.summary;
  const groups: [string, Record<string, any>][] = [["by setup", s.byScenario], ["by entry", s.byKind], ["by bucket", s.byBucket], ["early (<10:00)", s.early]];
  return (
    <div>
      <div className="muted" style={{ margin: "8px 0" }}>
        {s.days} day(s) with bars, {s.noData} without · {s.trades} trades · win rate {s.winRate ?? "—"} · sum {s.pnlPctSum}% · avg win {s.avgWinPct ?? "—"}% · avg loss {s.avgLossPct ?? "—"}%
        {Object.keys(s.overrides ?? {}).length ? ` · variant ${Object.entries(s.overrides).map(([k, v]) => `${k}=${v}`).join(", ")}` : ""}
      </div>
      <div className="flow-split">
        <div>
          {groups.filter(([, g]) => g && Object.keys(g).length).map(([title, g]) => (
            <table key={title} className="table" style={{ marginBottom: 8 }}>
              <thead><tr><th>{title}</th><th>trades</th><th>wins</th><th>sum %</th></tr></thead>
              <tbody>
                {Object.entries(g).map(([k, v]: [string, any]) => (
                  <tr key={k}><td>{k}</td><td className="mono-num">{v.trades}</td><td className="mono-num">{v.wins}</td><td className="mono-num">{v.pnlPctSum}</td></tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
        <div>
          <table className="table">
            <thead><tr><th>Date</th><th>Sym</th><th>Day</th><th>Scenario</th><th>Trades</th><th>Sum %</th></tr></thead>
            <tbody>
              {sweep.rows.map((r: any, i: number) => (
                <tr key={i}>
                  <td className="mono-num">{r.date}</td><td className="mono-num">{r.symbol}</td>
                  <td className="muted">{r.status === "ok" ? r.dayType : r.status}</td><td className="muted">{r.scenario ?? "—"}</td>
                  <td className="mono-num">{r.summary?.trades ?? 0}</td><td className="mono-num">{r.summary?.pnlPctSum ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}


function HowItWorks({ status }: { status: Team2Status | null }) {
  const [open, setOpen] = useState(false);
  const mode = status?.mode ?? "alert";
  return (
    <div className="panel" style={{ marginBottom: 10 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => setOpen(!open)}>
        How Team2 works {open ? "▾" : "▸"}
        <span className="sub">deterministic — no model, no LLM; every decision is a rule with a number, and every step is logged with its reason</span>
      </div>
      {open && (
        <div className="panel-body muted" style={{ lineHeight: 1.5 }}>
          <p><b>Every evening (17:00 ET)</b> one plan per symbol is built from the day's 15-minute bars: the previous-day
            high and low as small zones (wick to the next candle's body), the next resistance above and support below, and the
            four scenarios that set the day's bias — break PDH → calls, reject PDH → puts, bounce PDL → calls, break PDL → puts.
            The plan is armed in <b>{mode}</b> mode and shows on the Armed page like any other plan.</p>
          <p><b>At 09:25</b> the plan is completed with the pre-market high and low (04:00–09:25), the day type (gap up / gap
            down / inside / normal) and the sizing bucket: full size beyond yesterday's zones, small between a zone and the
            pre-market level, no trade inside the pre-market range.</p>
          <p><b>During the session</b> the read runs after every 2-minute close: the 13/48/200 EMA stack (extended hours on) must
            agree with the bias and must not be braided; a level counts as broken only when a <b>15-minute candle body closes</b>
            beyond it; then the first or second <b>2-minute pullback into the 13 EMA</b> (or the retest of the level) that closes
            back on the trade's side is the fire. A lunging, engulfing candle is not a pullback and is skipped. Before 09:45 and
            after 15:30 nothing fires.</p>
          <p><b>The contract</b> is the same-day (0DTE) call or put whose ask is closest under the target premium (≈ $0.60,
            never below $0.20) — the author's "$0.50 contract". Team2 has its own 0DTE policy in the risk gate: last entry
            {status?.zeroDte ? ` ${status.zeroDte.last_entry_et}` : ""}, everything flat by{status?.zeroDte ? ` ${status.zeroDte.flatten_et}` : " 15:45"},
            hard caps on contracts and premium per order.</p>
          <p><b>Exits</b>: one 2-minute close back through the EMA (or the level) is the stop; a −25% premium loss is the hard
            cap; a third is sold at +50% and another third at +100%; the rest rides the 13 EMA and sells at the pre-planned
            target. Two losses end the day; after a win the next trade is half size.</p>
          <p><b>What each mode means.</b> <b>alert</b>: the read runs and records what it would have done (fires, trims, exits
            appear in the plan's log as "would …"), nothing is sent. <b>proposal</b>: a fire becomes an approval for you. <b>auto</b>:
            the order is placed through the risk gate on the practice account; live needs the explicit acknowledgement.
            The ladder is earned: alert until the walk-forward sweep on ≥ 20 banked sessions and the calibration say the read
            pays after fees, then proposal on practice, then auto.</p>
          <p><b>Where to look.</b> Plans: tonight's sheet per symbol. Armed: the live plans (also on the Armed page). History: pick a
            run to see every decision with its reason — this is the review loop. Validation: run the sweep over the banked days,
            with variants ("pullback_max_touches=3") to test one rule at a time. Settings → Team2 technique holds every number.</p>
        </div>
      )}
    </div>
  );
}
