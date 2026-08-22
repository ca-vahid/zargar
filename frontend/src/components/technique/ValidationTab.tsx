import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { TechniqueSweep, WalkforwardRow } from "../../types";
import { Spinner } from "../ui";
import { Collapse, DisclosureHead, useDisclosure } from "../Collapse";
import { RailShell, useRail } from "./RailShell";
import { SymbolPicker, type SymbolSet } from "./SymbolPicker";

// --- dates -------------------------------------------------------------------------------

function toDateInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function fromDateInput(s: string): Date { const [y, m, d] = s.split("-").map(Number); return new Date(y, (m || 1) - 1, d || 1); }
function businessDaysBack(from: Date, n: number): Date {
  const d = new Date(from);
  let left = n;
  while (left > 0) { d.setDate(d.getDate() - 1); if (d.getDay() !== 0 && d.getDay() !== 6) left--; }
  return d;
}
/** The last session that has finished: yesterday's weekday (today's bars are still being written). */
function lastCompletedSession(): string { return toDateInput(businessDaysBack(new Date(), 1)); }
function etTime(ts: number | null | undefined): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
}
function pct(v: number | null | undefined) { return v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`; }
function num(v: number | null | undefined, d = 2) { return v === null || v === undefined ? "—" : Number(v).toFixed(d); }
function signedR(v: number | null | undefined) { if (v === null || v === undefined) return "—"; return `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}R`; }

const SESSION_COUNTS = [1, 5, 10, 20];
const OUTCOME_WORDS: Record<string, string> = {
  tp1: "hit TP1", tp2: "hit TP2", tp3: "hit TP3", stopped: "stopped out", not_filled: "not filled",
  expired: "ran out of session", flat: "flat at the close", open: "still open",
};
const STATUS_WORDS: Record<string, string> = {
  not_triggered: "never touched", gapped_past: "gapped past at the open (T4.1)", gapped_through: "stop gapped through (T4.3a)",
  gap_void: "plan void — open gapped too far (Q13)", expired: "touched outside the prime windows only (R6)",
  not_tradeable: "rejected in the plan", observed_midday: "touched mid-day only (R6)", voided: "voided",
};

// --- per-row reading ---------------------------------------------------------------------

interface Finding {
  row: WalkforwardRow; fired: number; wins: number; sumR: number; planned: number;
  verdict: "win" | "loss" | "mixed" | "none" | "nodata"; text: string; levels: string; gap: string;
}
function readRow(r: WalkforwardRow): Finding {
  const res = r.result ?? {};
  const s = r.summary ?? {};
  const trig: any[] = res.triggers ?? [];
  if (s.note || !res.bars) return { row: r, fired: 0, wins: 0, sumR: 0, planned: 0, verdict: "nodata", text: s.note ?? "no bars for the scored session", levels: "—", gap: "—" };
  const valid = trig.filter((t) => t.valid);
  const fired = valid.filter((t) => t.status === "fired");
  const parts: string[] = [];
  for (const t of fired) {
    const sim = t.sim ?? {};
    const r = sim.rMultiple ?? 0;
    parts.push(`${t.id} ${t.kind === "bounce" ? "bounce" : "break"} fired ${etTime(t.firedTs)}${t.firedWindow ? ` (${String(t.firedWindow).replace(/_/g, " ")})` : ""} → ${OUTCOME_WORDS[sim.outcome] ?? sim.outcome ?? "?"} ${signedR(r)}`);
  }
  if (!fired.length) {
    if (!valid.length) parts.push(trig.length ? "no tradeable trigger in the plan (all rejected)" : "no triggers planned");
    else {
      const why = valid.map((t) => `${t.id} ${STATUS_WORDS[t.status] ?? String(t.status).replace(/_/g, " ")}${t.observedMidday ? ` (${t.observedMidday} mid-day touch${t.observedMidday > 1 ? "es" : ""})` : ""}`);
      parts.push(`nothing fired — ${why.join("; ")}`);
    }
  }
  const sumR = Number(s.sumR ?? 0);
  const wins = Number(s.wins ?? 0);
  const verdict: Finding["verdict"] = fired.length === 0 ? "none" : wins === fired.length ? "win" : wins === 0 ? "loss" : "mixed";
  const levels = `${s.levelsRespected ?? 0} held · ${s.levelsBroken ?? 0} broke · ${s.levelsUntested ?? 0} untested`;
  const gap = s.gapPct === undefined || s.gapPct === null ? "—" : `${Number(s.gapPct) > 0 ? "+" : ""}${Number(s.gapPct).toFixed(2)}%`;
  return { row: r, fired: fired.length, wins, sumR, planned: valid.length, verdict, text: parts.join("; "), levels, gap };
}

// --- statistics tables (book claims) ------------------------------------------------------

function LevelTable({ title, data }: { title: string; data: Record<string, any> }) {
  const rows = Object.entries(data ?? {});
  if (!rows.length) return null;
  return (
    <div className="tq-section">
      <div className="tq-label">{title}</div>
      <div className="tq-table-wrap"><table className="tq-table tq-wf">
        <thead><tr><th></th><th>n</th><th>respected</th><th>broken</th><th>flipped</th><th>untested</th><th>respect (tested)</th></tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{k}</b></td><td>{v.n}</td><td className="pos">{v.respected}</td><td className="neg">{v.broken}</td><td>{v.flipped}</td><td className="muted">{v.untested}</td>
            <td><b>{pct(v.testedRespectRate)}</b></td></tr>))}</tbody>
      </table></div>
    </div>
  );
}

function TriggerTable({ title, data, planned = true }: { title: string; data: Record<string, any>; planned?: boolean }) {
  const rows = Object.entries(data ?? {});
  if (!rows.length) return null;
  return (
    <div className="tq-section">
      <div className="tq-label">{title}</div>
      <div className="tq-table-wrap"><table className="tq-table tq-wf">
        <thead><tr><th></th>{planned && <th>planned</th>}<th>fired</th><th>wins</th><th>win rate</th><th>avg R</th><th>ΣR</th>
          {planned && <><th>gapped past</th><th>gapped through</th><th>gap void</th><th>mid-day observed</th><th>not triggered</th></>}</tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{k}</b></td>{planned && <td>{v.planned ?? "—"}</td>}<td>{v.fired}</td><td>{v.wins}</td><td>{pct(v.winRate)}</td>
            <td className={(v.avgR ?? 0) > 0 ? "pos" : (v.avgR ?? 0) < 0 ? "neg" : ""}><b>{num(v.avgR)}</b></td><td>{num(v.sumR)}</td>
            {planned && <><td>{v.gappedPast ?? "—"}</td><td>{v.gappedThrough ?? "—"}</td><td>{v.gapVoid ?? "—"}</td><td>{v.observedMidday ?? "—"}</td><td>{v.notTriggered ?? "—"}</td></>}</tr>))}</tbody>
      </table></div>
    </div>
  );
}

// --- the tab -------------------------------------------------------------------------------

type Lens = "all" | "fired" | "wins" | "losses" | "none";
const LENSES: { key: Lens; label: string; hint: string }[] = [
  { key: "all", label: "All", hint: "every symbol / session" },
  { key: "fired", label: "Fired", hint: "a trigger actually fired" },
  { key: "wins", label: "Winners", hint: "fired and finished positive" },
  { key: "losses", label: "Losers", hint: "fired and finished negative" },
  { key: "none", label: "Nothing fired", hint: "the plan never triggered (and why)" },
];

export function ValidationTab({ llmAvailable = true }: { llmAvailable?: boolean }) {
  const toast = useStore((s) => s.toast);
  const settings = useStore((s) => s.settings);
  const openRun = useStore((s) => s.openTechniqueRun);
  const bump = useStore((s) => s.techniqueSweepBump);
  const positions = useStore((s) => s.positions);
  const watchlists = useStore((s) => s.watchlists);
  const bookUniverse: string[] = (settings["technique.walkforward.symbols"] as string[]) ?? ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN"];

  const [symbols, setSymbols] = useState<string[]>(() => {
    try { const v = JSON.parse(localStorage.getItem("zargar_tq_sweep_symbols") || "null"); if (Array.isArray(v) && v.length) return v; } catch { /* ignore */ }
    return bookUniverse;
  });
  useEffect(() => { localStorage.setItem("zargar_tq_sweep_symbols", JSON.stringify(symbols)); }, [symbols]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [preset, setPreset] = useState<"last" | "date">("last");
  const [date, setDate] = useState(lastCompletedSession());
  const [count, setCount] = useState(1);
  const [advOpen, toggleAdv] = useDisclosure("tq_wf_adv", false);
  const [structure, setStructure] = useState(((settings["technique.structure_tfs"] as string[]) ?? ["1h", "30m"]).join(","));
  const [trigger, setTrigger] = useState(String(settings["technique.trigger_tf"] ?? "1m"));
  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sweeps, setSweeps] = useState<TechniqueSweep[]>([]);
  const [sel, setSel] = useState<TechniqueSweep | null>(null);
  const [lens, setLens] = useState<Lens>("all");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [statsOpen, toggleStats] = useDisclosure("tq_wf_stats", false);
  const [llmBusy, setLlmBusy] = useState(false);
  const rail = useRail("tq_rail_validation");

  const scored = preset === "last" ? lastCompletedSession() : date;
  const end = toDateInput(businessDaysBack(fromDateInput(scored), 1));           // plan built at this close
  const start = toDateInput(businessDaysBack(fromDateInput(end), count - 1));
  const firstScored = toDateInput(businessDaysBack(fromDateInput(scored), count - 1));

  const refresh = useCallback(() => { api.techniqueSweeps().then(setSweeps).catch(() => undefined); }, []);
  useEffect(() => { refresh(); }, [refresh, bump]);
  const refetchSel = useCallback((id: string) => {
    // only apply if the user is still looking at that sweep (a bump that fires while a new
    // sweep is being selected must not drag the panel back to the old one)
    api.techniqueSweep(id).then((r) => setSel((cur) => (cur && cur.id === r.id ? r : cur))).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!sel) return;
    refetchSel(sel.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bump, sel?.id]);
  useEffect(() => { if (!sel && sweeps.length) api.techniqueSweep(sweeps[0].id).then(setSel).catch(() => undefined); }, [sweeps, sel]);
  // a running sweep: poll its detail every few seconds until it finishes
  useEffect(() => {
    if (!sel || sel.status !== "running") return;
    const t = setInterval(() => refetchSel(sel.id), 4000);
    return () => clearInterval(t);
  }, [sel?.id, sel?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const sets = useMemo<SymbolSet[]>(() => {
    const held = Array.from(new Set(Object.values(positions).filter((p) => p.secType === "STK" && p.qty !== 0).map((p) => p.symbol))).sort();
    const recent = Array.from(new Set(sweeps.flatMap((s) => s.symbols))).filter((s) => !bookUniverse.includes(s)).slice(0, 30);
    return [
      { key: "book", label: "The book's universe", hint: "liquid, optionable names the method is written for (technique.walkforward.symbols)", symbols: bookUniverse },
      { key: "held", label: "My holdings", hint: "stocks you hold in any account", symbols: held },
      ...watchlists.map((w) => ({ key: `wl-${w.id}`, label: `Watchlist · ${w.name}`, hint: `${w.symbols.length} symbols`, symbols: w.symbols })),
      { key: "recent", label: "Recently swept", hint: "symbols from earlier sweeps", symbols: recent },
    ];
  }, [positions, watchlists, sweeps, bookUniverse]);

  const run = async () => {
    if (!symbols.length) { toast("error", "Pick at least one symbol"); return; }
    setBusy(true);
    try {
      const d = await api.techniqueStartSweep({
        symbols, start, end, label: `${symbols.length} symbol${symbols.length === 1 ? "" : "s"} · ${count === 1 ? scored : `${firstScored}..${scored}`}`,
        structureTfs: structure.split(",").map((s) => s.trim()).filter(Boolean), triggerTf: trigger, includeInvalid,
      });
      toast("info", `Validation started: ${d.symbols.length} symbol(s), ${count} session${count === 1 ? "" : "s"} ending ${scored}`);
      setSel(d); setChecked({}); refresh();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const promote = async (r: WalkforwardRow, withVision: boolean) => {
    if (!sel) return;
    try {
      const run = await api.techniquePromote(sel.id, { symbol: r.symbol, session: r.session, withVision, wait: !withVision });
      toast("success", withVision ? `LLM read started for ${r.symbol} (${r.planFor}) → run ${run.id.slice(0, 8)}` : `Plan for ${r.symbol} ${r.planFor} → run ${run.id.slice(0, 8)}`);
      if (!withVision) openRun(run.id); else refetchSel(sel.id);
    } catch (e: any) { toast("error", e.message); }
  };
  const llmSelected = async () => {
    if (!sel) return;
    const rows = (sel.rows ?? []).filter((r) => checked[r.id] && !r.promotedRunId);
    if (!rows.length) { toast("error", "Select findings first (tick the rows)"); return; }
    setLlmBusy(true);
    let ok = 0;
    for (const r of rows) {
      try { await api.techniquePromote(sel.id, { symbol: r.symbol, session: r.session, withVision: true, wait: false }); ok++; }
      catch (e: any) { toast("error", `${r.symbol} ${r.session}: ${e.message}`); }
    }
    toast("success", `${ok} LLM read${ok === 1 ? "" : "s"} started — they appear in History as they finish`);
    setChecked({}); setLlmBusy(false);
    refetchSel(sel.id);
  };

  const sm = sel?.summary ?? {};
  const findings = useMemo(() => (sel?.rows ?? []).map(readRow).sort((a, b) => {
    const rank = (f: Finding) => (f.verdict === "win" ? 0 : f.verdict === "mixed" ? 1 : f.verdict === "loss" ? 2 : f.verdict === "none" ? 3 : 4);
    return rank(a) - rank(b) || b.sumR - a.sumR || a.row.symbol.localeCompare(b.row.symbol) || (b.row.planFor ?? "").localeCompare(a.row.planFor ?? "");
  }), [sel]);
  const visible = useMemo(() => findings.filter((f) => (
    lens === "fired" ? f.fired > 0 : lens === "wins" ? f.verdict === "win" : lens === "losses" ? f.verdict === "loss" || f.verdict === "mixed" && f.sumR < 0 : lens === "none" ? f.fired === 0 : true)), [findings, lens]);
  const nChecked = Object.values(checked).filter(Boolean).length;
  const counts = useMemo(() => ({
    rows: findings.length, plansFired: findings.filter((f) => f.fired > 0).length,
    fires: findings.reduce((a, f) => a + f.fired, 0), wins: findings.reduce((a, f) => a + f.wins, 0),
    losses: findings.reduce((a, f) => a + (f.fired - f.wins), 0), sumR: findings.reduce((a, f) => a + f.sumR, 0),
  }), [findings]);
  const llmOk = llmAvailable;

  return (
    <div className={rail.gridClass}>
      <div className="tq-main">
        {/* ---- set-up ---- */}
        <div className="panel tq-form">
          <div className="panel-head">Walk-forward validation
            <span className="sub">build the plan at a close, replay it on the next session's real bars — deterministic, free, no LLM (≥100 fires before trusting a number, p. 72)</span>
          </div>
          <div className="panel-body tq-wf-form">
            <div className="tq-wf-block">
              <div className="tq-ctl-label">Symbols <span className="muted">· {symbols.length}</span></div>
              <div className="tq-wf-symbols">
                {symbols.slice(0, 24).map((s) => <span key={s} className="tq-sym-chip on static">{s}</span>)}
                {symbols.length > 24 && <span className="muted">+{symbols.length - 24} more</span>}
                <button type="button" className="secondary-btn tq-wf-pick" onClick={() => setPickerOpen(true)}>Choose symbols…</button>
              </div>
            </div>
            <div className="tq-wf-block tq-wf-when">
              <div>
                <div className="tq-ctl-label">Session to check</div>
                <div className="tq-date-row">
                  <div className="tq-presets" role="group" aria-label="Session preset">
                    <button type="button" className={preset === "last" ? "active" : ""} onClick={() => setPreset("last")} title="The last completed session">Last session</button>
                    <input type="date" value={preset === "date" ? date : scored} max={lastCompletedSession()}
                      onChange={(e) => { setDate(e.target.value); setPreset("date"); }} title="A specific completed session" />
                  </div>
                </div>
              </div>
              <div>
                <div className="tq-ctl-label">Sessions <span className="muted">· how far back</span></div>
                <div className="tq-presets" role="group" aria-label="Sessions back">
                  {SESSION_COUNTS.map((n) => <button key={n} type="button" className={count === n ? "active" : ""} onClick={() => setCount(n)}>{n}</button>)}
                </div>
              </div>
              <button className="primary-btn tq-run tq-wf-run" disabled={busy || !symbols.length} onClick={run}>{busy ? "Starting…" : `Validate ${symbols.length} symbol${symbols.length === 1 ? "" : "s"}`}</button>
            </div>
            <div className="tq-wf-explain muted">
              {count === 1
                ? <>Builds each symbol's plan at the <b>{end}</b> close — exactly what "Last close" on the Analyse tab would have shown that evening — and replays it on <b>{scored}</b>'s 1-minute bars: did a trigger fire inside the prime windows, and where did it end?</>
                : <>Does that for each of the last <b>{count}</b> sessions ending <b>{scored}</b> (plans built {start}..{end}, scored {firstScored}..{scored}) — one row per symbol per session, so you get a sample, not an anecdote.</>}
              {" "}Triggers on {trigger}, structure on {structure}; Yahoo keeps ~20 sessions of 1m bars.
            </div>
            <DisclosureHead open={advOpen} onToggle={toggleAdv} level="sub">Advanced</DisclosureHead>
            <Collapse open={advOpen}>
              <div className="tq-row tq-adv-row">
                <div className="tq-ctl"><span className="tq-ctl-label">Structure TFs</span><input value={structure} onChange={(e) => setStructure(e.target.value)} style={{ width: 90 }} /></div>
                <div className="tq-ctl"><span className="tq-ctl-label">Trigger TF</span>
                  <select value={trigger} onChange={(e) => setTrigger(e.target.value)}>{["1m", "5m", "15m"].map((t) => <option key={t}>{t}</option>)}</select></div>
                <label className="tq-chipbtn" title="Also replay triggers the plan rejected (R2 etc.) to see what they would have done"><input type="checkbox" checked={includeInvalid} onChange={(e) => setIncludeInvalid(e.target.checked)} /> include rejected triggers</label>
              </div>
            </Collapse>
          </div>
        </div>

        {/* ---- results ---- */}
        {sel && (
          <div className="panel">
            <div className="panel-head">
              {sel.status === "running" && <Spinner />} {sel.label || sel.id.slice(0, 8)}
              <span className="sub">{sel.symbols.length} symbol{sel.symbols.length === 1 ? "" : "s"} · plans {sel.start}..{sel.end} · {sel.status}
                {sel.progress?.total ? ` · ${sel.progress.done ?? 0}/${sel.progress.total} symbols` : ""}</span>
              {sel.status === "running" && sel.progress?.total ? (
                <div className="tq-wf-progress" aria-label="progress"><div style={{ width: `${Math.round(((sel.progress.done ?? 0) / sel.progress.total) * 100)}%` }} /></div>
              ) : null}
            </div>
            <div className="panel-body">
              {findings.length === 0 && <div className="muted">{sel.status === "running" ? "Fetching bars and building plans…" : sel.error ?? "No sessions came back — the date may be a holiday, or the symbols have no 1m history that far back."}</div>}
              {findings.length > 0 && (
                <>
                  <div className="tq-plan">
                    <div className="tq-plan-cell"><small>Checked</small><b>{counts.rows}</b><span>symbol · session pairs</span></div>
                    <div className="tq-plan-cell"><small>Fires</small><b>{counts.fires}</b><span>{counts.rows ? `in ${counts.plansFired} of ${counts.rows} plans (${Math.round((counts.plansFired / counts.rows) * 100)}%)` : ""}</span></div>
                    <div className="tq-plan-cell"><small>Won / lost</small><b><span className="pos">{counts.wins}</span> / <span className="neg">{counts.losses}</span></b><span>{counts.fires ? `win rate ${Math.round((counts.wins / counts.fires) * 100)}% of fires` : "no fires"}</span></div>
                    <div className="tq-plan-cell"><small>Total R</small><b className={counts.sumR > 0 ? "pos" : counts.sumR < 0 ? "neg" : ""}>{signedR(counts.sumR)}</b><span>{counts.fires ? `avg ${signedR(counts.sumR / counts.fires)} per fire` : ""}</span></div>
                    <div className="tq-plan-cell"><small>Prior-day levels</small><b>{pct(sm.levels?.priorDayVsOther?.priorDay?.testedRespectRate)}</b><span>held when tested · other {pct(sm.levels?.priorDayVsOther?.other?.testedRespectRate)}</span></div>
                    <div className="tq-plan-cell"><small>Sample</small><b>{counts.fires}</b><span>of the ≥{sm.sample?.target ?? 100} fires the book asks for (p. 72)</span></div>
                  </div>

                  <div className="tq-wf-findings-head">
                    <div className="tq-label">Findings <span className="muted">· one row per symbol per session, best first</span></div>
                    <div className="tq-lenses" role="group" aria-label="Findings lens">
                      {LENSES.map((l) => <button key={l.key} type="button" className={lens === l.key ? "active" : ""} title={l.hint} onClick={() => setLens(l.key)}>{l.label}</button>)}
                    </div>
                    <span style={{ flex: 1 }} />
                    <button className="secondary-btn" disabled={!nChecked || llmBusy || !llmOk} onClick={llmSelected}
                      title="Run the full 4-pass analyst read (vision + critic) on the selected plans, ≈$0.20 each; results land in History">
                      {llmBusy ? "Starting…" : `LLM read on ${nChecked || "selected"} ${nChecked === 1 ? "finding" : "findings"}`}
                    </button>
                  </div>
                  <div className="tq-table-wrap">
                    <table className="tq-table tq-wf tq-findings">
                      <thead><tr>
                        <th><input type="checkbox" aria-label="select all visible" checked={visible.length > 0 && visible.every((f) => checked[f.row.id])}
                          onChange={(e) => { const on = e.target.checked; setChecked((c) => { const n = { ...c }; visible.forEach((f) => { n[f.row.id] = on; }); return n; }); }} /></th>
                        <th>Symbol</th><th>Plan → scored</th><th>Result</th><th>What happened</th><th>R</th><th>Levels</th><th>Gap</th><th></th>
                      </tr></thead>
                      <tbody>
                        {visible.map((f) => (
                          <tr key={f.row.id} className={`tq-finding ${f.verdict}`}>
                            <td><input type="checkbox" checked={!!checked[f.row.id]} onChange={(e) => setChecked((c) => ({ ...c, [f.row.id]: e.target.checked }))} aria-label={`select ${f.row.symbol} ${f.row.planFor}`} /></td>
                            <td><b>{f.row.symbol}</b></td>
                            <td className="muted nowrap">{f.row.session} → <b>{f.row.planFor}</b></td>
                            <td><span className={`tq-badge ${f.verdict === "win" ? "setup" : f.verdict === "loss" ? "failed" : f.verdict === "mixed" ? "wait" : "nosetup"}`}>
                              {f.verdict === "win" ? "WIN" : f.verdict === "loss" ? "LOSS" : f.verdict === "mixed" ? "MIXED" : f.verdict === "none" ? `NO FIRE · ${f.planned} planned` : "NO DATA"}</span></td>
                            <td className="tq-finding-text">{f.text}</td>
                            <td className={`nowrap ${f.sumR > 0 ? "pos" : f.sumR < 0 ? "neg" : "muted"}`}><b>{f.fired ? signedR(f.sumR) : "—"}</b></td>
                            <td className="muted nowrap">{f.levels}</td>
                            <td className="muted nowrap">{f.gap}</td>
                            <td className="nowrap">
                              {f.row.promotedRunId
                                ? <button className="link-btn" onClick={() => openRun(f.row.promotedRunId!)}>open run</button>
                                : <><button className="link-btn" onClick={() => promote(f.row, false)} title="Open this plan as a reviewable run (deterministic, free)">plan</button>
                                  {" · "}<button className="link-btn" disabled={!llmOk} onClick={() => promote(f.row, true)} title="Full analyst read on this plan (≈$0.20)">LLM read</button></>}
                            </td>
                          </tr>
                        ))}
                        {visible.length === 0 && <tr><td colSpan={9}><div className="empty">No findings match this lens.</div></td></tr>}
                      </tbody>
                    </table>
                  </div>

                  <DisclosureHead open={statsOpen} onToggle={toggleStats}
                    extra={<span className="sub">{(sm.claims ?? []).length} claims · level & trigger quality</span>}>Book claims &amp; statistics</DisclosureHead>
                  <Collapse open={statsOpen}>
                    <div className="tq-section">
                      <div className="tq-label">Claims — book vs data (§6.4)</div>
                      <div className="tq-table-wrap"><table className="tq-table tq-wf tq-claims">
                        <thead><tr><th>Claim</th><th>Rule</th><th>Metric</th><th>Verdict</th><th>Detail</th></tr></thead>
                        <tbody>{(sm.claims ?? []).map((c: any, i: number) => (
                          <tr key={i}><td>{c.claim}</td><td><span className="tq-chip">{c.rule}</span></td><td className="muted">{c.metric}</td>
                            <td><span className={`tq-badge ${c.verdict === "pass" ? "setup" : c.verdict === "fail" ? "failed" : "nosetup"}`}>{c.verdict}</span></td>
                            <td className="muted small">{JSON.stringify(c.detail)}</td></tr>))}</tbody>
                      </table></div>
                    </div>
                    <LevelTable title="Level quality — prior-day extremes vs other (T1.3a)" data={sm.levels?.priorDayVsOther} />
                    <LevelTable title="Level quality — by source" data={sm.levels?.bySource} />
                    <LevelTable title="Level quality — by touches (T1.2)" data={sm.levels?.byTouches} />
                    <LevelTable title="Level quality — by structure timeframe (p. 114)" data={sm.levels?.byTimeframe} />
                    <TriggerTable title="Trigger quality — by kind" data={sm.triggers?.byKind} />
                    <TriggerTable title="Trigger quality — by window fired (R6)" data={sm.triggers?.byWindow} planned={false} />
                    <TriggerTable title="Counterfactuals — with vs without our gates" data={sm.triggers?.counterfactual} planned={false} />
                    {sm.triggers?.middayFiresWithoutGate && <div className="muted small">Mid-day fires without the R6 gate: {JSON.stringify(sm.triggers.middayFiresWithoutGate)}</div>}
                    <TriggerTable title="By R:R gate (R2)" data={sm.triggers?.byRrGate} planned={false} />
                    {sm.errors?.length > 0 && <div className="neg">errors: {JSON.stringify(sm.errors)}</div>}
                  </Collapse>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <RailShell open={rail.open} onToggle={rail.toggle} label="Sweeps">
        <div className="panel">
          <div className="panel-head">Past validations <span className="sub">{sweeps.length}</span></div>
          <div className="panel-body tq-setups">
            {sweeps.length === 0 && <div className="empty">none yet</div>}
            {sweeps.map((s) => (
              <button key={s.id} className={`tq-setup-row ${sel?.id === s.id ? "valid" : ""}`} onClick={() => api.techniqueSweep(s.id).then(setSel)}>
                <b>{s.label || `${s.start}..${s.end}`}</b> <span className="muted">{s.status}{s.summary?.sample?.fired !== undefined ? ` · ${s.summary.sample.fired} fired` : ""}</span>
                <span className="muted">{s.symbols.slice(0, 6).join(", ")}{s.symbols.length > 6 ? ` +${s.symbols.length - 6}` : ""} · {s.createdAt ? fmtDateTime(s.createdAt) : ""}</span>
              </button>
            ))}
          </div>
        </div>
      </RailShell>

      {pickerOpen && <SymbolPicker initial={symbols} sets={sets} onClose={() => setPickerOpen(false)}
        onApply={(s) => { setSymbols(s); setPickerOpen(false); }} />}
    </div>
  );
}
