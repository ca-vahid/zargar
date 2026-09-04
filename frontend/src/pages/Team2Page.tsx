// The Team2 page (docs/techniques/team2/PLAN.md G-2): Plans · Armed · History · Validation.
// Less is more: one-line rows, underline tabs, everything links to its run / armed plan.
import { useCallback, useEffect, useMemo, useState } from "react";
import { CopyChip } from "../components/CopyChip";
import { SymIcon } from "../components/SymIcon";
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
  dayType: string | null; createdAt: string | null; armed: boolean;
  status?: string | null; stopReason?: string | null };
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
      toast(r.failed?.length ? "error" : "info", `Team2: ${r.runs?.length ?? 0} plan(s) for ${r.planFor}, ${r.armed?.length ?? 0} armed`
        + (r.skipped?.length ? ` — skipped ${r.skipped.join("; ")}` : "") + (r.failed?.length ? ` — ${r.failed.join("; ")}` : ""));
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

  const armedRows = useMemo(() => (status?.armed ?? []).filter((a: any) => !a.technique || a.technique === "team2"), [status]);
  const todaysPlans = useMemo(() => {
    const latest = runs.length ? runs[0].planFor : null;
    return runs.filter((r) => r.planFor === latest);
  }, [runs]);

  if (loading) return <div className="tips-page"><Spinner label="loading Team2…" /></div>;

  const latestFor = runs.length ? runs[0].planFor : null;
  const pill = (st?: string | null) => st === "armed" ? "ok" : st === "paused" ? "wait" : st === "disarmed" ? "bad" : "dim";
  const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
  const statusLine = status
    ? `${status.symbols?.join(" · ")} · ${status.mode} mode · plans ${status.planAt} ET, pre-open ${status.preopenAt}`
      + (status.zeroDte?.enabled ? ` · 0DTE: entries until ${status.zeroDte.last_entry_et}, flat by ${status.zeroDte.flatten_et}` : " · 0DTE policy off")
      + (status.macro?.next ? ` · next macro: ${status.macro.next.name} ${status.macro.next.date}` : "")
    : "status unavailable";
  // one row per symbol for the coming session — the armed plan wins, else the newest; earlier (replaced,
  // disarmed) plans fold away instead of repeating the same sheet three times
  const sameDay = runs.filter((r) => r.planFor === latestFor);
  const bySym = new Map<string, Team2Run>();
  for (const r of sameDay) {
    const cur = bySym.get(r.symbol);
    if (!cur || (r.armed && !cur.armed)) bySym.set(r.symbol, r);
  }
  const primary = Array.from(bySym.values());
  const earlier = sameDay.filter((r) => !primary.includes(r));
  const planRow = (r: Team2Run) => (
    <tr key={r.runId} className={selected === r.runId ? "selected" : ""} onClick={() => setSelected(r.runId)}>
      <td><SymIcon sym={r.symbol} size={18} /> <b>{r.symbol}</b></td>
      <td className="num">{r.planFor}</td>
      <td className="muted">{r.dayType ? r.dayType.replace("_", " ") : (r.complete ? "—" : "pre-open pending")}</td>
      <td className="muted" style={{ whiteSpace: "normal", minWidth: 420 }}>{r.sheet}</td>
      <td>
        <span className={`status-pill ${pill(r.status)}`} title={r.stopReason ?? undefined}>{r.status ?? "not armed"}</span>
        {r.stopReason ? <span className="muted small"> {r.stopReason}</span> : null}
        {r.armed && <> <button className="link-btn" onClick={(e) => { e.stopPropagation(); openArmedPlan(r.runId); }}>open →</button></>}
      </td>
      <td className="muted">{when(r.createdAt)}</td>
      <td><CopyChip value={r.runId} title={`run ${r.runId} — click to copy`} /></td>
    </tr>
  );

  return (
    <div className="tips-page">
      <div className="tips-head">
        <div className="tabs" role="tablist" style={{ flex: 1 }}>
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""} onClick={() => setPageTab(t.key)}>
              {t.label}{t.key === "armed" && armedRows.length ? <span className="tab-count">{armedRows.length}</span> : null}
            </button>
          ))}
          {/* an action, not desk work — parked on the far right like Tips' Sources */}
          <button role="tab" className="tab-config" disabled={busy} onClick={planNow}
            title="Build (or rebuild) tonight's plan for each symbol now and arm it in the configured mode">
            ▶<span className="tab-config-label"> {busy ? "Working…" : "Plan now"}</span>
          </button>
        </div>
      </div>

      {tab === "plans" && (
        <>
          <div className="panel mb">
            <div className="panel-head">Plans <span className="sub">{statusLine}</span></div>
            <div className="scroll-x">
              {primary.length === 0 ? (
                <div className="empty">No plans yet — Plan now builds tonight's skeleton for each symbol (prior-day zones, targets) and arms it in the configured mode; 09:25 completes it with the pre-market range.</div>
              ) : (
                <table className="tbl">
                  <thead><tr><th>Symbol</th><th className="num">For</th><th>Day</th><th>Sheet</th><th>Status</th><th>When</th><th>Id</th></tr></thead>
                  <tbody>{primary.map(planRow)}</tbody>
                </table>
              )}
            </div>
            {earlier.length > 0 && (
              <details className="muted small" style={{ padding: "6px 10px" }}>
                <summary>{earlier.length} earlier plan{earlier.length === 1 ? "" : "s"} for {latestFor} — replaced or disarmed</summary>
                <div className="scroll-x"><table className="tbl"><tbody>{earlier.map(planRow)}</tbody></table></div>
              </details>
            )}
          </div>
          <HowItWorks status={status} />
          {status?.thresholds && (
            <div className="panel mb">
              <details className="muted small" style={{ padding: "6px 10px" }}>
                <summary>Every number the read runs on tonight (read-only — change them in Settings → Team2 technique)</summary>
                <div className="mono-num" style={{ columns: 3, columnGap: 24, marginTop: 6 }}>
                  {Object.entries(status.thresholds as Record<string, any>).filter(([k]) => !["windows", "round_number_steps"].includes(k)).map(([k, v]) => (
                    <div key={k} style={{ breakInside: "avoid" }}>{k} = {typeof v === "number" ? +v.toFixed(4) : String(v)}</div>
                  ))}
                </div>
              </details>
            </div>
          )}
        </>
      )}

      {tab === "armed" && (
        <div className="panel mb">
          <div className="panel-head">Armed <span className="sub">the live plans — the same rows sit on the Armed page with every other technique</span></div>
          <div className="scroll-x">
            {armedRows.length === 0 ? <div className="empty">Nothing armed — tonight's plans arm at {status?.planAt ?? "17:00"} ET, or use Plan now.</div> : (
              <table className="tbl">
                <thead><tr><th>Symbol</th><th className="num">For</th><th>Status</th><th>Mode</th><th>Account</th><th>The read right now</th><th className="num">Filled</th><th className="num">P&amp;L</th><th>Id</th></tr></thead>
                <tbody>
                  {armedRows.map((a: any) => (
                    <tr key={a.runId} onClick={() => openArmedPlan(a.runId)} style={{ cursor: "pointer" }} title="open on the Armed page">
                      <td><SymIcon sym={a.symbol} size={18} /> <b>{a.symbol}</b></td>
                      <td className="num">{a.planFor}</td>
                      <td>
                        <span className={`status-pill ${pill(a.status)}`} title={a.stopReason ?? undefined}>{a.status}</span>
                        {a.needsAttention ? <span className="status-pill bad"> needs attention</span> : null}
                        {a.stale ? <span className="status-pill wait"> stale</span> : null}
                        {a.stopReason ? <span className="muted small"> {a.stopReason}</span> : null}
                      </td>
                      <td>
                        <span className={`status-pill ${a.config?.mode === "auto" ? "ok" : a.config?.mode === "proposal" ? "wait" : "dim"}`}>{a.config?.mode ?? a.mode}</span>
                        {a.config?.premiumBudget ? <span className="muted small"> ${Number(a.config.premiumBudget).toLocaleString()}/trade</span> : null}
                        {a.config?.dailyLossLimit ? <span className="muted small"> · halt ${Number(a.config.dailyLossLimit).toFixed(0)}</span> : null}
                      </td>
                      <td>{a.portfolio?.name ?? "—"}{a.portfolio?.kind === "live" ? <span className="status-pill bad"> LIVE</span> : null}</td>
                      <td className="muted" style={{ whiteSpace: "normal", minWidth: 360 }}>
                        {a.summary ?? "—"}{a.team2?.live?.length ? ` · contract ${a.team2.live[0].livePct > 0 ? "+" : ""}${a.team2.live[0].livePct}% live` : ""}
                        {typeof a.barAgeSeconds === "number" ? <span className="small"> · bar {Math.round(a.barAgeSeconds)}s old</span> : null}
                      </td>
                      <td className="num">{(a.trades ?? []).filter((t: any) => (t.filledQty ?? 0) > 0).length}<span className="muted">/{(a.trades ?? []).length}</span></td>
                      <td className={`num ${(a.realizedPnl ?? 0) > 0 ? "pos" : (a.realizedPnl ?? 0) < 0 ? "neg" : ""}`}>{typeof a.realizedPnl === "number" ? `${a.realizedPnl > 0 ? "+" : ""}${a.realizedPnl.toFixed(0)}` : "—"}</td>
                      <td onClick={(e) => e.stopPropagation()}><CopyChip value={a.runId} title={`run ${a.runId} — click to copy`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {tab === "history" && (
        <div className="flow-split">
          <div className="panel mb">
            <div className="panel-head">Runs <span className="sub">every plan the desk built, newest first — pick one to see what the method saw</span></div>
            <div className="scroll-x">
              {runs.length === 0 ? <EmptyState title="No runs" /> : (
                <table className="tbl">
                  <thead><tr><th className="num">For</th><th>Symbol</th><th>Day</th><th>Status</th><th>Built</th></tr></thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.runId} className={selected === r.runId ? "selected" : ""} onClick={() => setSelected(r.runId)} style={{ cursor: "pointer" }}>
                        <td className="num">{r.planFor}</td><td><SymIcon sym={r.symbol} size={16} /> {r.symbol}</td>
                        <td className="muted">{r.dayType ? r.dayType.replace("_", " ") : "—"}</td>
                        <td><span className={`status-pill ${pill(r.status)}`} title={r.stopReason ?? undefined}>{r.status ?? "not armed"}</span></td>
                        <td className="muted">{when(r.createdAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
          <div className="panel mb">
            <div className="panel-head">The read <span className="sub">{selected ? (read?.source === "live" ? "live — what the runner acted on" : "replay over the banked bars") : "nothing selected"}</span></div>
            <div className="panel-body">
              {!selected ? <div className="state-note">Pick a run to see what the method saw.</div> :
               !read ? <Spinner label="reading…" /> :
               <ReadView read={read} />}
            </div>
          </div>
        </div>
      )}

      {tab === "validation" && (
        <>
          <div className="panel mb">
            <div className="panel-head">Walk-forward sweep <span className="sub">every banked day replayed with the same read the live runner uses — deterministic, no LLM; a variant changes one number</span></div>
            <div className="panel-body" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <label className="muted">from <input value={sweepForm.start} onChange={(e) => setSweepForm({ ...sweepForm, start: e.target.value })} style={{ width: 110 }} /></label>
              <label className="muted">to <input value={sweepForm.end} onChange={(e) => setSweepForm({ ...sweepForm, end: e.target.value })} style={{ width: 110 }} /></label>
              <label className="muted">variant <input placeholder="pullback_max_touches=3 target_premium=0.5" value={sweepForm.overrides} onChange={(e) => setSweepForm({ ...sweepForm, overrides: e.target.value })} style={{ width: 300 }} /></label>
              <button className="primary-btn" disabled={busy} onClick={runSweep}>{busy ? "Sweeping…" : "Run sweep"}</button>
            </div>
          </div>
          {!sweep ? (
            <div className="state-note">Premium path: Black–Scholes on the VIX proxy, fees and slippage included. Judge a rule from ≥ 20 banked sessions, not from one day.</div>
          ) : (
            <div className="panel mb"><div className="panel-head">Result <span className="sub">{sweep.start} → {sweep.end} · {sweep.symbols.join(" · ")}</span></div><div className="panel-body"><SweepView sweep={sweep} /></div></div>
          )}
        </>
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
        <table className="tbl" style={{ marginBottom: 8 }}>
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
      <table className="tbl">
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
          <table className="tbl">
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
