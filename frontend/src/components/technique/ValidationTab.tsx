import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { TechniqueSweep, WalkforwardRow } from "../../types";
import { Spinner } from "../ui";
import { Collapse, DisclosureHead, useDisclosure } from "../Collapse";
import { RailShell, useRail } from "./RailShell";
import { SymbolPicker, type SymbolSet } from "./SymbolPicker";
import { SYMBOL_BUNDLES } from "../../lib/symbolBundles";

// --- row-action icons ---------------------------------------------------------------------
const IcoPlan = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /><path d="M8 13h8M8 17h5" /></svg>;
const IcoLlm = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" /></svg>;
const IcoNext = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></svg>;
const IcoOpen = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14L21 3" /></svg>;

// --- dates -------------------------------------------------------------------------------

function toDateInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function fromDateInput(s: string): Date { const [y, m, d] = s.split("-").map(Number); return new Date(y, (m || 1) - 1, d || 1); }
function nextBusinessDay(from: Date = new Date()): Date {
  const d = new Date(from); d.setHours(12, 0, 0, 0);
  do { d.setDate(d.getDate() + 1); } while (d.getDay() === 0 || d.getDay() === 6);
  return d;
}
/** The session a sheet built RIGHT NOW is actually for. Plans build at the last
 * COMPLETED 16:00 ET close — so on a trading day before the close, that is
 * yesterday's close and the sheet covers TODAY, not tomorrow. */
function sheetTarget(): { date: Date; isToday: boolean } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short",
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const etToday = new Date(Number(get("year")), Number(get("month")) - 1, Number(get("day")), 12);
  const isTradingDay = !["Sat", "Sun"].includes(get("weekday"));
  const beforeClose = Number(get("hour")) * 60 + Number(get("minute")) < 16 * 60;
  if (isTradingDay && beforeClose) return { date: etToday, isToday: true };
  return { date: nextBusinessDay(etToday), isToday: false };
}
const STRUCTURE_TF_OPTIONS = ["1d", "1h", "30m", "15m", "5m"];
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
  exhausted: "level failed two breaks — done for the day (R3.2)",
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
    parts.push(`${t.id} ${t.kind === "bounce" ? "bounce" : t.kind === "reject" ? "reject (short)" : t.kind === "breakdown" ? "breakdown (short)" : "break"} fired ${etTime(t.firedTs)}${t.firedWindow ? ` (${String(t.firedWindow).replace(/_/g, " ")})` : ""} → ${OUTCOME_WORDS[sim.outcome] ?? sim.outcome ?? "?"} ${signedR(r)}`);
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

// --- book claims & statistics, in plain language ---------------------------------------------

const VERDICT_WORDS: Record<string, { word: string; cls: string }> = {
  pass: { word: "holds in this data", cls: "setup" },
  fail: { word: "does not hold here", cls: "failed" },
  insufficient: { word: "not enough fires yet", cls: "nosetup" },
};
function r2(v: any) { return v === null || v === undefined ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}R`; }

/** Turn a claim row from `walkforward.aggregate()` into a question + one evidence sentence. */
function describeClaim(c: any): { question: string; evidence: string } {
  const d = c.detail ?? {};
  switch (c.claim) {
    case "Prior-day HOD/LOD are the strongest levels":
      return { question: "Are yesterday's high and low the most reliable levels?", evidence: `held when tested: prior-day ${pct(d.priorDay)} vs every other level ${pct(d.other)}` };
    case "More touches = stronger level":
      return { question: "Does a level touched 3+ times hold better than one touched twice?", evidence: `held when tested: 3+ touches ${pct(d["3+"])} vs 2 touches ${pct(d["2"])}` };
    case "Prime windows beat mid-day":
      return { question: "Do fires inside the prime windows (09:30–10:30 · 14:45–16:00) beat mid-day fires?", evidence: `avg ${r2(d.primeAvgR)} over ${d.primeFired ?? 0} prime fires vs ${r2(d.middayAvgR)} over ${d.middayFired ?? 0} mid-day fires (mid-day fires come from the replay without the R6 gate — for real, the gate blocks them)` };
    case "Gap rules help (ours)":
      return { question: "Do our gap rules (Q11–Q13: void a plan when the open gaps too far) improve results?", evidence: `avg ${r2(d.with)} with the rules vs ${r2(d.without)} without them` };
    case "R:R >= 3 gate is not dominated by a stricter one":
      return { question: "Is reward-to-risk ≥ 3 the right bar, or should we demand ≥ 4?", evidence: `R:R 3–4: avg ${r2(d["rr3-4"]?.avgR)} over ${d["rr3-4"]?.fired ?? 0} fires · R:R ≥ 4: avg ${r2(d["rr>=4"]?.avgR)} over ${d["rr>=4"]?.fired ?? 0} fires` };
    case "Confirmed breakouts are worth taking": { const k = d.breakout ?? {}; return { question: "Do breakout entries (buy through resistance) make money?", evidence: `${k.fired ?? 0} fired of ${k.planned ?? 0} planned · win rate ${pct(k.winRate)} · avg ${r2(k.avgR)}` }; }
    case "Bounce at the level works": { const k = d.bounce ?? {}; return { question: "Do bounce entries (buy the dip at support) make money?", evidence: `${k.fired ?? 0} fired of ${k.planned ?? 0} planned · win rate ${pct(k.winRate)} · avg ${r2(k.avgR)}` }; }
    default: return { question: c.claim, evidence: JSON.stringify(d) };
  }
}

function Bar({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">—</span>;
  const p = Math.max(0, Math.min(100, Math.round(v * 100)));
  return <span className="tq-bar" title={`${p}%`}><span style={{ width: `${p}%` }} /><b>{p}%</b></span>;
}

const LEVEL_LABELS: Record<string, string> = {
  priorDay: "Prior-day high / low", other: "Every other level",
  "T1.3a": "Prior-day high / low", "T1.3b": "Prior-session extreme", "T1.3c": "Swing pivots (touched 2+ times)", "T1.3d": "Round numbers",
  "1": "1 touch", "2": "2 touches", "3+": "3+ touches",
  "1h": "Read on 1h", "30m": "Read on 30m", "1m": "Read on 1m (trigger tf)", "?": "unknown",
};
function LevelQuality({ title, data, hint }: { title: string; data: Record<string, any>; hint?: string }) {
  const rows = Object.entries(data ?? {}).filter(([, v]: any) => v && v.n);
  if (!rows.length) return null;
  return (
    <div className="tq-section">
      <div className="tq-label">{title}{hint && <span className="muted tq-hint"> · {hint}</span>}</div>
      <div className="tq-table-wrap"><table className="tq-table tq-wf tq-stat">
        <thead><tr><th></th><th>levels planned</th><th>tested</th><th>held</th><th>broke</th><th>flipped</th><th>held when tested</th></tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{LEVEL_LABELS[k] ?? k}</b></td><td>{v.n}</td><td>{v.n - (v.untested ?? 0)}</td><td className="pos">{v.respected}</td><td className="neg">{v.broken}</td><td>{v.flipped}</td><td className="tq-barcell"><Bar v={v.testedRespectRate} /></td></tr>))}</tbody>
      </table></div>
    </div>
  );
}

const TRIGGER_LABELS: Record<string, string> = {
  bounce: "Bounce — buy the dip at support", breakout: "Breakout — buy through resistance",
  reject: "Rejection — short at resistance (put)", breakdown: "Breakdown — short through support (put)",
  prime_open: "Prime open 09:30–10:30", prime_close: "Prime close 14:45–16:00", midday: "Mid-day", "?": "unknown window",
  base: "As designed — prime-window gate + gap rules on", noWindowGate: "Without the prime-window gate (R6)", noGapRules: "Without the gap rules (Q11–Q13)",
  middayBlocked: "Mid-day fires the R6 gate blocked — what they would have done",
  "rr3-4": "Reward-to-risk between 3 and 4", "rr>=4": "Reward-to-risk 4 or better",
};
function TriggerQuality({ title, data, hint, why = false }: { title: string; data: Record<string, any>; hint?: string; why?: boolean }) {
  const rows = Object.entries(data ?? {}).filter(([, v]: any) => v && (v.fired || v.planned));
  if (!rows.length) return null;
  const whyText = (v: any) => [v.notTriggered ? `${v.notTriggered} never touched` : "", v.gapVoid ? `${v.gapVoid} voided by the opening gap` : "",
    v.gappedPast ? `${v.gappedPast} gapped past the level` : "", v.gappedThrough ? `${v.gappedThrough} stop gapped through` : "",
    v.observedMidday ? `${v.observedMidday} touched mid-day only` : ""].filter(Boolean).join(" · ") || "—";
  return (
    <div className="tq-section">
      <div className="tq-label">{title}{hint && <span className="muted tq-hint"> · {hint}</span>}</div>
      <div className="tq-table-wrap"><table className="tq-table tq-wf tq-stat">
        <thead><tr><th></th>{why && <th>planned</th>}<th>fired</th><th>won</th><th>win rate</th><th>avg R</th><th>ΣR</th>{why && <th>why the rest never fired</th>}</tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{TRIGGER_LABELS[k] ?? k}</b></td>{why && <td>{v.planned ?? "—"}</td>}
            <td>{v.fired}{why && v.planned ? <span className="muted"> ({pct(v.triggerRate)})</span> : null}</td><td>{v.wins}</td><td className="tq-barcell"><Bar v={v.winRate} /></td>
            <td className={(v.avgR ?? 0) > 0 ? "pos" : (v.avgR ?? 0) < 0 ? "neg" : ""}><b>{r2(v.avgR)}</b></td><td>{r2(v.sumR)}</td>
            {why && <td className="muted tq-why">{whyText(v)}</td>}</tr>))}</tbody>
      </table></div>
    </div>
  );
}

// --- plan sheet: the next session's setups, ranked ---------------------------------------------

interface SheetRow { row: WalkforwardRow; best: any | null; valid: any[]; levels: number; trend: string; why: string; gap: string }
function readSheetRow(r: WalkforwardRow): SheetRow {
  const plan = r.plan ?? {};
  const trig: any[] = plan.triggers ?? [];
  const valid = trig.filter((t) => t.valid).sort((a, b) =>
    ((b.assessment?.score ?? 0) - (a.assessment?.score ?? 0)) || (b.confidence - a.confidence) || (b.riskReward - a.riskReward));
  const best = valid[0] ?? null;
  const tr = plan.context?.trend ?? {};
  const ARROW: Record<string, string> = { uptrend: "↑", downtrend: "↓", sideways: "→", up: "↑", down: "↓" };
  const trend = Object.entries(tr).filter(([k]) => k !== (plan.triggerTf ?? "1m"))
    .map(([k, v]: any) => { const w = String(typeof v === "string" ? v : v?.direction ?? v?.trend ?? "?"); return `${k}${ARROW[w] ?? " " + w}`; }).join("  ");
  const cand = trig.slice().sort((a, b) => (b.confidence - a.confidence))[0];
  const why = best ? (best.confluences ?? []).join(", ") : cand ? (cand.noTradeReasons ?? []).join("; ") || "rejected" : "no level close enough to trade";
  const gap = best ? (best.voidIf ?? []).join("; ") : "";
  return { row: r, best, valid, levels: (plan.levels ?? []).length, trend, why, gap };
}

function SymAvatar({ sym }: { sym: string }) {
  const [err, setErr] = useState(false);
  const hue = Array.from(sym).reduce((a, c) => a + c.charCodeAt(0) * 7, 0) % 360;
  if (err) return <span className="tq-avatar tq-avatar-mono" style={{ background: `hsl(${hue} 45% 40%)` }} aria-hidden="true">{sym.slice(0, 2)}</span>;
  return <img className="tq-avatar" alt="" loading="lazy" src={`https://assets.parqet.com/logos/symbol/${sym}?format=png&size=32`} onError={() => setErr(true)} />;
}

function Conf({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">—</span>;
  const p = Math.round(v * 100);
  return <span className={`tq-conf ${p >= 80 ? "hi" : p >= 60 ? "mid" : "lo"}`}>{p}%</span>;
}

function Grade({ t }: { t: any }) {
  const a = t?.assessment;
  if (!a?.grade) return <Conf v={t?.confidence} />;
  const tip = [`Validity ${a.grade} — ${a.score}/100`, ...(a.strengths ?? []).map((s: string) => `✓ ${s}`),
    ...(a.cautions ?? []).map((s: string) => `⚠ ${s}`)].join("\n");
  return <span className={`tq-grade g${a.grade}`} title={tip}>{a.grade}</span>;
}
const WHY_SHORT: [RegExp, string][] = [
  [/prior-day extreme \(T1\.3a\)/, "PD"], [/(\d+) touches \(T1\.2\)/, "$1×"],
  [/higher timeframe not against it \(T3\.3g\)/, "HTF✓"], [/higher timeframe uptrend \(T3\.3g\)/, "HTF↑"],
  [/confluence across timeframes/, "CF"], [/volume drying up.*$/, "VOL↓"],
  [/rejection candle.*$/, "REJ"], [/round number.*$/, "RND"],
];
function whyChips(why: string): string[] {
  return why.split(/,\s*/).map((part) => {
    for (const [re, out] of WHY_SHORT) { if (re.test(part)) return part.replace(re, out); }
    return part;
  }).filter(Boolean).slice(0, 5);
}

function SetupsSheet({ sel, pending, onOpen, onScore, scorable }: {
  sel: TechniqueSweep; pending: Record<string, string>; onOpen: (r: WalkforwardRow) => void; onScore: () => void; scorable: boolean;
}) {
  const openRun = useStore((s) => s.openTechniqueRun);
  const rows = useMemo(() => (sel.rows ?? []).map(readSheetRow), [sel.rows]);
  const withSetup = rows.filter((x) => x.best).sort((a, b) =>
    ((b.best.assessment?.score ?? 0) - (a.best.assessment?.score ?? 0)) || (b.best.confidence - a.best.confidence)
    || (b.best.riskReward - a.best.riskReward) || a.row.symbol.localeCompare(b.row.symbol));
  const without = rows.filter((x) => !x.best);
  const bounces = withSetup.filter((x) => x.best.kind === "bounce").length;
  const avgRR = withSetup.length ? withSetup.reduce((a, x) => a + (x.best.riskReward || 0), 0) / withSetup.length : null;
  const planFor = sel.params?.planFor ?? sel.summary?.planFor;
  return (
    <>
      <div className="tq-wf-callout">
        <b>Setups for {planFor}</b> — each symbol's plan built at the {sel.start} close, exactly what you would arm. Ranked by validity grade (A strong · B decent · C weak — hover a grade for the breakdown), then reward-to-risk. Nothing here is a fill: every row fires only if its conditions are met inside a prime window.
        {" "}A setup is an <i>if-then</i>: it only becomes a trade if price reaches the entry inside a prime window. {scorable
          ? <> The session has closed — <button className="link-btn" onClick={onScore}>score this sheet now</button> to see what each setup did.</>
          : <> After {planFor} closes, this sheet scores itself into a validation.</>}
      </div>
      <div className="tq-plan">
        <div className="tq-plan-cell"><small>Symbols</small><b>{rows.length}</b><span>planned at the {sel.start} close</span></div>
        <div className="tq-plan-cell"><small>With a setup</small><b>{withSetup.length}</b><span>{rows.length ? `${Math.round((withSetup.length / rows.length) * 100)}% of symbols` : ""}</span></div>
        <div className="tq-plan-cell"><small>Bounces / breakouts</small><b>{bounces} / {withSetup.length - bounces}</b><span>best trigger per symbol</span></div>
        <div className="tq-plan-cell"><small>Avg reward-to-risk</small><b>{avgRR === null ? "—" : avgRR.toFixed(1)}</b><span>the book's floor is 3 (R2)</span></div>
        <div className="tq-plan-cell"><small>Status</small><b>{sel.status === "running" ? `${sel.progress?.done ?? 0}/${sel.progress?.total ?? "?"}` : "ready"}</b><span>{sel.status === "running" ? "building plans…" : "deterministic · no LLM"}</span></div>
      </div>
      <div className="tq-wf-findings-head"><span className="tq-label">Setups · best first</span>
        <span className="muted small"><b>PD</b> prior-day level · <b>N×</b> touches · <b>HTF✓/↑</b> higher timeframe agrees · <b>CF</b> confluence · hover a row for the void rules · ⚡ arms</span></div>
      <div className="tq-table-wrap sticky-head">
        <table className="tq-table tq-wf tq-findings tq-sheet">
          <thead><tr><th>Symbol</th><th>Setup</th><th title="Additional valid triggers in the same plan">Alt</th><th>Entry</th><th>Stop</th><th>Targets</th><th title="Reward-to-risk — the book's floor is 3 (R2)">R:R</th><th title="Validity grade A (strong) / B (decent) / C (weak) — deterministic: level strength, real targets, chart stop, minus cautions. Hover for the breakdown.">Grade</th><th>Why</th><th title="Structure trend on the higher timeframes (↑ up · → sideways · ↓ down)">Trend</th><th aria-label="arm"></th></tr></thead>
          <tbody>
            {withSetup.map(({ row, best, valid, trend, why }) => (
              <tr key={row.id} className="tq-finding win" title={`${row.symbol}: ${best.kind} at ${num(best.levelPrice)} · void if: ${(best.voidIf ?? []).join("; ") || "—"}`}>
                <td className="nowrap"><span className="tq-symcell"><SymAvatar sym={row.symbol} /><b>{row.symbol}</b>
                  {row.promotedRunId && <button className="tq-act tq-arm-inline" onClick={() => openRun(row.promotedRunId!)} title="This setup already has a run — open it (and arm there)"><IcoOpen /><span>open</span></button>}</span></td>
                <td className="nowrap"><span className={`tq-badge ${best.kind === "bounce" ? "setup" : best.direction === "short" ? "neg" : "plan"}`}>{best.kind === "bounce" ? "BOUNCE" : best.kind === "breakout" ? "BREAKOUT" : best.kind === "reject" ? "REJECT ↓" : best.kind === "breakdown" ? "BREAKDOWN ↓" : "WEDGE"}</span></td>
                <td>{valid.length > 1
                  ? <span className="tq-alt" title={valid.slice(1).map((t: any) => `${t.id} ${t.kind} at ${num(t.entry?.price)} (R:R ${num(t.riskReward, 1)})`).join("; ")}>+{valid.length - 1}</span>
                  : <span className="muted">—</span>}</td>
                <td className="nowrap">{num(best.entry?.price)} <span className="muted small">{best.entry?.basis === "on_break" ? "on break" : "at level"}</span></td>
                <td className="nowrap neg">{num(best.stop?.price)}</td>
                <td className="nowrap small">{(best.targets ?? []).slice(0, 3).map((t: any, i: number) => <span key={i}>{i > 0 && <span className="tq-sep"> / </span>}<span className="pos">{num(t.price)}</span></span>)}</td>
                <td><b>{num(best.riskReward, 1)}</b></td>
                <td><Grade t={best} /></td>
                <td><div className="tq-why-chips" title={why}>{whyChips(why || "").map((w, i) => <span key={i}>{w}</span>)}</div></td>
                <td className="muted nowrap small">{trend || "—"}</td>
                <td className="nowrap tq-arm-cell">{pending[row.id]
                  ? <span className="muted small"><Spinner /></span>
                  : row.promotedRunId
                    ? <button className="tq-act tq-act-icon" onClick={() => openRun(row.promotedRunId!)} aria-label={`Open ${row.symbol} run`}
                        title={`${row.symbol} already has its run — open it`}><IcoOpen /></button>
                    : <button className="tq-act next tq-act-icon" onClick={() => onOpen(row)} aria-label={`Arm ${row.symbol}`}
                        title={`Arm ${row.symbol} — opens its plan for ${planFor} as a run with the Arm button (chart, trace, everything)`}><IcoNext /></button>}</td>
              </tr>
            ))}
            {withSetup.length === 0 && <tr><td colSpan={11}><div className="empty">{sel.status === "running" ? "Building plans…" : "No symbol has a tradeable setup for this session."}</div></td></tr>}
          </tbody>
        </table>
      </div>
      {without.length > 0 && (
        <details className="tq-sheet-none">
          <summary className="muted">No setup for {without.length} symbol{without.length === 1 ? "" : "s"} — why</summary>
          <div className="tq-table-wrap"><table className="tq-table tq-wf">
            <tbody>{without.map(({ row, why }) => { const first = (why || "no triggers").split(";")[0]; const more = (why || "").split(";").length - 1;
              return <tr key={row.id}><td className="nowrap"><b>{row.symbol}</b></td>
                <td className="muted tq-finding-text" title={why}>{first}{more > 0 && <span className="small"> · +{more} more reason{more > 1 ? "s" : ""}</span>}</td>
                <td className="nowrap"><button className="tq-act" onClick={() => onOpen(row)} title="Open the plan anyway (levels, chart, trace)"><IcoPlan /><span>open</span></button></td></tr>; })}</tbody>
          </table></div>
        </details>
      )}
    </>
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

const LEGACY_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN"];

export function ValidationTab({ llmAvailable = true, sweepVersion = null }: { llmAvailable?: boolean; sweepVersion?: string | null }) {
  const toast = useStore((s) => s.toast);
  const settings = useStore((s) => s.settings);
  const openRun = useStore((s) => s.openTechniqueRun);
  const bump = useStore((s) => s.techniqueSweepBump);
  const positions = useStore((s) => s.positions);
  const watchlists = useStore((s) => s.watchlists);
  const bookUniverse: string[] = (settings["technique.walkforward.symbols"] as string[]) ?? LEGACY_UNIVERSE;
  const extraUniverse: string[] = Array.isArray(settings["technique.universe.extra"]) ? (settings["technique.universe.extra"] as string[]) : [];
  const [autoUniverse, setAutoUniverse] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    api.techniqueUniverse().then((u) => {
      if (!alive) return;
      setAutoUniverse((u.symbols ?? []).filter((s) => u.provenance?.[s] === "auto"));
    }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  // null = "the book's universe" (follows the setting, which loads after mount); a
  // picked list is remembered until the user changes it again
  const [picked, setPicked] = useState<string[] | null>(() => {
    try {
      const v = JSON.parse(localStorage.getItem("zargar_tq_sweep_symbols_v2") || "null");
      // a stored copy of the pre-2026-08-22 nine-name default is not a choice — follow the setting
      if (Array.isArray(v) && v.length && v.join(",") !== LEGACY_UNIVERSE.join(",")) return v;
    } catch { /* ignore */ }
    return null;
  });
  const symbols = picked ?? bookUniverse;
  const setSymbols = (s: string[]) => {
    const isBook = s.length === bookUniverse.length && s.every((x, i) => x === bookUniverse[i]);
    setPicked(isBook ? null : s);
    if (isBook) localStorage.removeItem("zargar_tq_sweep_symbols_v2"); else localStorage.setItem("zargar_tq_sweep_symbols_v2", JSON.stringify(s));
  };
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
  const [pending, setPending] = useState<Record<string, "plan" | "llm" | "next">>({});
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"check" | "prepare">(() => (localStorage.getItem("zargar_tq_wf_mode") as any) || "check");
  useEffect(() => { localStorage.setItem("zargar_tq_wf_mode", mode); }, [mode]);
  const { date: sheetFor, isToday: sheetIsToday } = sheetTarget();
  const sheetForLabel = sheetFor.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
    + (sheetIsToday ? " (today)" : "");
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null);
  const rename = async (id: string, value: string) => {
    const v = value.trim();
    setRenaming(null);
    if (!v) return;
    try {
      const d = await api.techniqueRenameSweep(id, v);
      setSweeps((list) => list.map((x) => (x.id === id ? { ...x, label: d.label } : x)));
      setSel((cur) => (cur && cur.id === id ? { ...cur, label: d.label } : cur));
    } catch (e: any) { toast("error", e.message); }
  };
  const structureList = structure.split(",").map((x) => x.trim()).filter(Boolean);
  const toggleStructure = (tf: string) => {
    const on = structureList.includes(tf);
    if (on && structureList.length === 1) { toast("error", "Keep at least one structure timeframe"); return; }
    const next = STRUCTURE_TF_OPTIONS.filter((x) => (x === tf ? !on : structureList.includes(x)));
    setStructure(next.join(","));
  };
  const [histOpen, toggleHist] = useDisclosure("tq_wf_hist", false);
  const [formOpen, setFormOpen] = useState<boolean | null>(null);   // null = auto: open until a validation is shown
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
  const pollN = useRef(0);
  useEffect(() => {
    if (!sel || sel.status !== "running") return;
    const t = setInterval(() => {
      pollN.current += 1;
      if (pollN.current % 8 === 0) { refetchSel(sel.id); return; }   // full rows every ~32s
      // light poll: progress only — a 250-row sweep re-serialized every 4s was
      // megabytes of JSON per tick for both the engine and the browser
      api.techniqueSweep(sel.id, false).then((d) => {
        setSel((cur) => (cur && cur.id === d.id ? { ...d, rows: d.status !== "running" ? cur.rows : cur.rows } : cur));
        if (d.status !== "running") refetchSel(d.id);                 // finished: fetch everything once
      }).catch(() => undefined);
    }, 4000);
    return () => clearInterval(t);
  }, [sel?.id, sel?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const sets = useMemo<SymbolSet[]>(() => {
    const held = Array.from(new Set(Object.values(positions).filter((p) => p.secType === "STK" && p.qty !== 0).map((p) => p.symbol))).sort();
    const recent = Array.from(new Set(sweeps.flatMap((s) => s.symbols))).filter((s) => !bookUniverse.includes(s)).slice(0, 30);
    return [
      { key: "book", label: "Core universe", hint: `${bookUniverse.length} big, famous, heavily-traded names — most options-liquid first (technique.walkforward.symbols)`, symbols: bookUniverse },
      { key: "extra", label: "My extras", hint: "symbols you added yourself (Settings → Auto-trading → Extra symbols)", symbols: extraUniverse },
      { key: "auto", label: "Today's most active", hint: "added automatically from today's most-active US stocks (price floor applies)", symbols: autoUniverse },
      { key: "held", label: "My holdings", hint: "stocks you hold in any account", symbols: held },
      ...watchlists.map((w) => ({ key: `wl-${w.id}`, label: `Watchlist · ${w.name}`, hint: `${w.symbols.length} symbols`, symbols: w.symbols })),
      { key: "recent", label: "Recently swept", hint: "symbols from earlier sweeps", symbols: recent },
      ...SYMBOL_BUNDLES.map((b) => ({ ...b, collapsed: true, group: "Bundles — add a whole theme at once" })),
    ];
  }, [positions, watchlists, sweeps, bookUniverse, extraUniverse, autoUniverse]);

  // What the selection is made of, in words: whole sets first, then loose symbols
  const coverage = useMemo(() => {
    const selSet = new Set(symbols);
    const candidates = [{ label: "Core universe", symbols: bookUniverse }, { label: "My extras", symbols: extraUniverse }, { label: "Today's most active", symbols: autoUniverse }, ...SYMBOL_BUNDLES.map((b) => ({ label: b.label, symbols: b.symbols }))]
      .sort((x, y) => y.symbols.length - x.symbols.length);
    const covered = new Set<string>();
    const names: { label: string; n: number; members: string[] }[] = [];
    for (const c of candidates) {
      if (c.symbols.length < 3 || !c.symbols.every((x) => selSet.has(x))) continue;
      const fresh = c.symbols.filter((x) => !covered.has(x));
      if (fresh.length < Math.max(3, Math.ceil(c.symbols.length * 0.3))) continue;
      names.push({ label: c.label, n: c.symbols.length, members: c.symbols });
      c.symbols.forEach((x) => covered.add(x));
    }
    return { names, rest: symbols.filter((x) => !covered.has(x)) };
  }, [symbols, bookUniverse]);
  const anyRunning = sweeps.some((x) => x.status === "running") || sel?.status === "running";
  const runningSweep = sweeps.find((x) => x.status === "running") ?? (sel?.status === "running" ? sel : null);

  const run = async () => {
    if (!symbols.length) { toast("error", "Pick at least one symbol"); return; }
    setBusy(true);
    try {
      const d = await api.techniqueStartSweep({
        symbols, start, end, label: name.trim() || `${symbols.length} symbol${symbols.length === 1 ? "" : "s"} · ${count === 1 ? scored : `${firstScored}..${scored}`}`,
        structureTfs: structure.split(",").map((s) => s.trim()).filter(Boolean), triggerTf: trigger, includeInvalid,
      });
      toast("info", `Validation started: ${d.symbols.length} symbol(s), ${count} session${count === 1 ? "" : "s"} ending ${scored}`);
      setSel(d); setChecked({}); setName(""); refresh();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const runSheet = async () => {
    if (!symbols.length) { toast("error", "Pick at least one symbol"); return; }
    setBusy(true);
    try {
      const d = await api.techniqueStartSheet({ symbols, label: name.trim() || `Setups for ${toDateInput(sheetFor)} · ${symbols.length} symbols` });
      toast("info", `Building ${d.symbols.length} plans for ${d.params?.planFor ?? "the next session"}…`);
      setSel(d); setChecked({}); setName(""); refresh();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const scoreSheet = async () => {
    if (!sel) return;
    try { const d = await api.techniqueScoreSheet(sel.id); setSel(d); refresh(); toast("success", d.summary?.pending ? "Session not complete yet — try after the close" : "Sheet scored"); }
    catch (e: any) { toast("error", e.message); }
  };
  const openSheetRow = async (r: WalkforwardRow) => {
    if (pending[r.id] || !sel) return;
    if (r.promotedRunId) { openRun(r.promotedRunId); return; }
    setPending((p) => ({ ...p, [r.id]: "next" }));
    try {
      // promote (not plan): the run is recorded ON the sheet row, so the \u26a1 turns
      // into "open" permanently and a second press can never mint a duplicate.
      // wait:false — the run page streams its own progress; no frozen button.
      const run = await api.techniquePromote(sel.id, { symbol: r.symbol, session: r.session, withVision: false, wait: false });
      setSel((cur) => cur && cur.id === sel.id
        ? { ...cur, rows: (cur.rows ?? []).map((x) => (x.id === r.id ? { ...x, promotedRunId: run.id } : x)) }
        : cur);
      toast("success", `${r.symbol}: building the plan — opening it now (arm from there)`);
      openRun(run.id);
    } catch (e: any) { toast("error", e.message); }
    finally { setPending((p) => { const n = { ...p }; delete n[r.id]; return n; }); }
  };
  const promote = async (r: WalkforwardRow, withVision: boolean) => {
    if (!sel || pending[r.id]) return;
    setPending((p) => ({ ...p, [r.id]: withVision ? "llm" : "plan" }));
    toast("info", withVision ? `Starting the LLM read for ${r.symbol} ${r.planFor}…` : `Building the ${r.symbol} plan for ${r.planFor} (a few seconds)…`);
    try {
      const run = await api.techniquePromote(sel.id, { symbol: r.symbol, session: r.session, withVision, wait: false });
      // mark the row at once so a second click can't mint a duplicate run
      setSel((cur) => cur && cur.id === sel.id
        ? { ...cur, rows: (cur.rows ?? []).map((x) => (x.id === r.id ? { ...x, promotedRunId: run.id } : x)) }
        : cur);
      if (withVision) { toast("success", `LLM read started for ${r.symbol} ${r.planFor} → run ${run.id.slice(0, 8)} (appears in History when done)`); refetchSel(sel.id); }
      else { toast("success", `Plan ${r.symbol} ${r.planFor} → run ${run.id.slice(0, 8)} — opening on Analyse`); openRun(run.id); }
    } catch (e: any) { toast("error", e.message); }
    finally { setPending((p) => { const n = { ...p }; delete n[r.id]; return n; }); }
  };
  // Build THIS symbol's plan for the NEXT session (at the last close) — the one that can be armed
  const planNext = async (r: WalkforwardRow) => {
    if (pending[r.id]) return;
    setPending((p) => ({ ...p, [r.id]: "next" }));
    toast("info", `Building ${r.symbol}'s plan for the next session at the last close…`);
    try {
      const run = await api.techniquePlan({ symbol: r.symbol, withVision: false, wait: true });
      toast("success", `${r.symbol} plan for ${run.result?.plan?.planFor ?? "the next session"} → run ${run.id.slice(0, 8)} — arm it there`);
      openRun(run.id);
    } catch (e: any) { toast("error", e.message); }
    finally { setPending((p) => { const n = { ...p }; delete n[r.id]; return n; }); }
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
  const isSheet = !!sel && sel.params?.kind === "next" && (sel.rows ?? []).some((r) => r.result?.pending) || (!!sel && sel.params?.kind === "next" && sel.status === "running");
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
          <div className="panel-head tq-form-head" role="button" tabIndex={0} onClick={() => setFormOpen((v) => !(v ?? !sel))}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setFormOpen((v) => !(v ?? !sel)); }}>
            <span className="tq-picker-caret">{(formOpen ?? !sel) ? "▾" : "▸"}</span> Walk-forward validation
            <span className="sub">build the plan at a close, replay it on the next session's real bars — deterministic, free, no LLM (≥100 fires before trusting a number, p. 72)</span>
          </div>
          {(formOpen ?? !sel) && <div className="panel-body tq-wf-form">
            <div className="tq-wf-block">
              <div className="tq-mode" role="tablist" aria-label="What to do">
              <button type="button" role="tab" aria-selected={mode === "check"} className={mode === "check" ? "active" : ""} onClick={() => setMode("check")}>Check the past</button>
              <button type="button" role="tab" aria-selected={mode === "prepare"} className={mode === "prepare" ? "active" : ""} onClick={() => setMode("prepare")}>Prepare the next session · {sheetForLabel}</button>
            </div>
            {mode === "check" ? (
              <div className="tq-wf-callout">
                <b>Looks backward.</b> Every row here is a plan built at a past close and replayed on the session that followed — evidence for or against the method, never a trade.
                To see what to trade on <b>{sheetForLabel}</b>, switch to <b>Prepare the next session</b> above (or press <span className="tq-act static next"><IcoNext /><span>next</span></span> on a single finding).
              </div>
            ) : (
              <div className="tq-wf-callout">
                <b>Looks forward.</b> Builds each symbol's plan for <b>{sheetForLabel}</b> at the last close — the same plan "Last close" on Analyse shows — and ranks the setups: which level, entry, stop, targets, reward-to-risk, and why.
                Deterministic, free, no LLM, no runs spent. Each setup opens with the <b>Arm</b> button; after the session closes the sheet scores itself, so it becomes a validation.
                {sheetIsToday && (
                  <div className="tq-wf-today-note">
                    ⚠ The market hasn't closed yet, so plans can only be built from <b>yesterday's</b> close —
                    a sheet built now is for <b>today's remaining session</b>, and its plans expire at 4:00 PM ET.
                    To prepare <b>tomorrow</b>, come back after today's close.
                  </div>
                )}
              </div>
            )}
            <div className="tq-ctl-label">Symbols <span className="muted">· {symbols.length}</span></div>
              <div className="tq-wf-symbols">
                {coverage.names.map((c) => <span key={c.label} className="tq-cov-chip" title={c.members.join(", ")}>{c.label} <span>· {c.n}</span></span>)}
                {coverage.rest.slice(0, 14).map((x) => <span key={x} className="tq-sym-chip on static">{x}</span>)}
                {coverage.rest.length > 14 && <span className="muted" title={coverage.rest.slice(14).join(", ")}>+{coverage.rest.length - 14} more</span>}
                <button type="button" className="secondary-btn tq-wf-pick" onClick={() => setPickerOpen(true)}>Choose symbols…</button>
              </div>
            </div>
            {mode === "check" ? (<>
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
              <div className="tq-wf-go">
                <div>
                  <div className="tq-ctl-label">Name <span className="muted">· optional</span></div>
                  <input className="tq-wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`${symbols.length} symbols · ${count === 1 ? scored : `${firstScored}..${scored}`}`}
                    title="Shown in Past validations — you can rename it later too" onKeyDown={(e) => { if (e.key === "Enter" && !busy && !anyRunning && symbols.length) run(); }} />
                </div>
                <button className="primary-btn tq-run tq-wf-run" disabled={busy || anyRunning || !symbols.length} onClick={run}
                  title={anyRunning ? "A validation is running — wait for it to finish" : undefined}>
                  {busy ? "Starting…" : anyRunning ? <><span className="spinner" /> Validating… {runningSweep?.progress?.done ?? 0}/{runningSweep?.progress?.total ?? runningSweep?.symbols.length ?? "?"}</> : `Validate ${symbols.length} symbol${symbols.length === 1 ? "" : "s"}`}
                </button>
              </div>
            </div>
            <div className="tq-wf-explain muted">
              {count === 1
                ? <>Builds each symbol's plan at the <b>{end}</b> close — exactly what "Last close" on the Analyse tab would have shown that evening — and replays it on <b>{scored}</b>'s 1-minute bars: did a trigger fire inside the prime windows, and where did it end?</>
                : <>Does that for each of the last <b>{count}</b> sessions ending <b>{scored}</b> (plans built {start}..{end}, scored {firstScored}..{scored}) — one row per symbol per session, so you get a sample, not an anecdote.</>}
              {" "}Triggers on {trigger}, structure on {structure}; Yahoo keeps ~20 sessions of 1m bars.
            </div>
            </>) : (
              <div className="tq-wf-block tq-wf-when">
                <div className="tq-wf-go tq-wf-go-left">
                  <div>
                    <div className="tq-ctl-label">Name <span className="muted">· optional</span></div>
                    <input className="tq-wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`Setups for ${toDateInput(sheetFor)} · ${symbols.length} symbols`}
                      onKeyDown={(e) => { if (e.key === "Enter" && !busy && !anyRunning && symbols.length) runSheet(); }} />
                  </div>
                  <button className="primary-btn tq-run tq-wf-run" disabled={busy || anyRunning || !symbols.length} onClick={runSheet}
                    title={anyRunning ? "A validation is running — wait for it to finish" : `Build ${symbols.length} plans at the last close for ${sheetForLabel}`}>
                    {busy ? "Starting…" : anyRunning ? <><span className="spinner" /> Building… {runningSweep?.progress?.done ?? 0}/{runningSweep?.progress?.total ?? runningSweep?.symbols.length ?? "?"}</> : `Build setups for ${sheetForLabel} · ${symbols.length} symbol${symbols.length === 1 ? "" : "s"}`}
                  </button>
                </div>
                <div className="tq-wf-explain muted" style={{ flexBasis: "100%" }}>
                  Plans are built at the <b>{lastCompletedSession()}</b> close with structure on {structure} and triggers on {trigger} — the sheet lists every symbol that has a tradeable trigger (R:R ≥ 3, a real level, inside a prime window), best first. Nothing is armed until you open a row and press Arm.
                </div>
              </div>
            )}
            <DisclosureHead open={advOpen} onToggle={toggleAdv} level="sub">Advanced</DisclosureHead>
            <Collapse open={advOpen}>
              <div className="tq-adv-line">
                <div className="tq-adv-item" title="Where levels and trend are read — the book reads structure on 30m / 1h (p. 114). Pick one or more.">
                  <span className="tq-ctl-label">Structure</span>
                  <div className="tq-presets" role="group" aria-label="Structure timeframes">
                    {STRUCTURE_TF_OPTIONS.map((tf) => <button key={tf} type="button" className={structureList.includes(tf) ? "active" : ""} onClick={() => toggleStructure(tf)}>{tf}</button>)}
                  </div>
                </div>
                <div className="tq-adv-item" title="Where the entry fires and the replay runs, bar by bar">
                  <span className="tq-ctl-label">Trigger</span>
                  <div className="tq-presets" role="group" aria-label="Trigger timeframe">
                    {["1m", "5m", "15m"].map((tf) => <button key={tf} type="button" className={trigger === tf ? "active" : ""} onClick={() => setTrigger(tf)}>{tf}</button>)}
                  </div>
                </div>
                <div className="tq-adv-item" title="Also score the triggers the plan rejected (R:R < 3 etc.) — shows what the gate cost or saved">
                  <span className="tq-ctl-label">Rejected triggers</span>
                  <label className={`tq-chipbtn ${includeInvalid ? "set" : ""}`}><input type="checkbox" checked={includeInvalid} onChange={(e) => setIncludeInvalid(e.target.checked)} /> replay them too</label>
                </div>
              </div>
              <div className="tq-adv-hint">Structure = where levels and trend are read (book: 30m / 1h, p. 114) · Trigger = where the entry fires and the replay runs · rejected triggers = also score what the plan turned down (R:R &lt; 3 etc.).</div>
            </Collapse>
          </div>}
        </div>

        {/* ---- results ---- */}
        {sel && (
          <div className="panel">
            <div className="panel-head">
              {sel.status === "running" && <Spinner />}
              {renaming?.id === sel.id
                ? <input className="tq-rename" autoFocus value={renaming.value} onChange={(e) => setRenaming({ id: sel.id, value: e.target.value })}
                    onBlur={() => rename(sel.id, renaming.value)} onKeyDown={(e) => { if (e.key === "Enter") rename(sel.id, renaming.value); if (e.key === "Escape") setRenaming(null); }} />
                : <>{sel.label || sel.id.slice(0, 8)} <button className="tq-pencil" title="Rename this validation" onClick={() => setRenaming({ id: sel.id, value: sel.label || "" })}>✎</button></>}
              <span className="sub">{sel.symbols.length} symbol{sel.symbols.length === 1 ? "" : "s"} · plans {sel.start}..{sel.end} · {sel.status}
                {sel.progress?.total ? ` · ${sel.progress.done ?? 0}/${sel.progress.total} symbols` : ""}
                {sel.status === "running" && sel.progress?.workers ? ` · ${sel.progress.workers}` : ""}</span>
              {sel.status === "running" && sel.progress?.total ? (
                <div className="tq-wf-progress" aria-label="progress"><div style={{ width: `${Math.round(((sel.progress.done ?? 0) / sel.progress.total) * 100)}%` }} /></div>
              ) : null}
            </div>
            <div className="panel-body">
              {isSheet && sel && <SetupsSheet sel={sel} pending={pending} onOpen={openSheetRow} onScore={scoreSheet} scorable={String(sel.params?.planFor ?? "") <= lastCompletedSession()} />}
              {!isSheet && findings.length === 0 && <div className="muted">{sel.status === "running" ? "Fetching bars and scoring plans — symbols run in parallel, each appears as it finishes…" : sel.error ?? "No sessions came back — the date may be a holiday, or the symbols have no 1m history that far back."}</div>}
              {!isSheet && findings.length > 0 && (
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
                  <div className="tq-acts-legend muted small">
                    Results: <span className="tq-badge setup">WIN</span> every fired trigger won · <span className="tq-badge wait">MIXED</span> some won, some lost (R is the net) · <span className="tq-badge failed">LOSS</span> every fired trigger stopped out · <span className="tq-badge nosetup">NO FIRE · N planned</span> N tradeable triggers, none fired — all of these are <b>past</b> sessions, evidence only.
                  </div>
                  <div className="tq-acts-legend muted small">
                    Row actions: <span className="tq-act static"><IcoPlan /><span>open</span></span> open this past plan as a run (free, for review) ·
                    <span className="tq-act static"><IcoLlm /><span>LLM</span></span> analyst read of it (≈$0.20) ·
                    <span className="tq-act static next"><IcoNext /><span>next</span></span> plan the symbol's <b>next</b> session — the one you can arm.
                  </div>
                  <div className="tq-table-wrap sticky-head">
                    <table className="tq-table tq-wf tq-findings">
                      <thead><tr>
                        <th><input type="checkbox" aria-label="select all visible" checked={visible.length > 0 && visible.every((f) => checked[f.row.id])}
                          onChange={(e) => { const on = e.target.checked; setChecked((c) => { const n = { ...c }; visible.forEach((f) => { n[f.row.id] = on; }); return n; }); }} /></th>
                        <th>Symbol</th><th title="The plan was built at the close of the first date and replayed on the second date's real 1-minute bars">Built at close of → replayed on</th><th>Result</th><th>What happened</th><th>R</th><th>Levels</th><th>Gap</th><th></th>
                      </tr></thead>
                      <tbody>
                        {visible.map((f) => (
                          <tr key={f.row.id} className={`tq-finding ${f.verdict}`}>
                            <td><input type="checkbox" checked={!!checked[f.row.id]} onChange={(e) => setChecked((c) => ({ ...c, [f.row.id]: e.target.checked }))} aria-label={`select ${f.row.symbol} ${f.row.planFor}`} /></td>
                            <td><b>{f.row.symbol}</b></td>
                            <td className="muted nowrap">{f.row.session} → <b>{f.row.planFor}</b></td>
                            <td><span className={`tq-badge ${f.verdict === "win" ? "setup" : f.verdict === "loss" ? "failed" : f.verdict === "mixed" ? "wait" : "nosetup"}`}
                              title={f.verdict === "win" ? "Every trigger that fired that day ended in profit" : f.verdict === "loss" ? "Every trigger that fired that day ended at the stop" : f.verdict === "mixed" ? "Some fired triggers won, some lost — the R column is the net" : f.verdict === "none" ? `The plan had ${f.planned} tradeable trigger${f.planned === 1 ? "" : "s"} but price never fired one inside a prime window (reason in the row)` : "No bars for that session"}>
                              {f.verdict === "win" ? "WIN" : f.verdict === "loss" ? "LOSS" : f.verdict === "mixed" ? "MIXED" : f.verdict === "none" ? `NO FIRE · ${f.planned} planned` : "NO DATA"}</span></td>
                            <td className="tq-finding-text">{f.text}</td>
                            <td className={`nowrap ${f.sumR > 0 ? "pos" : f.sumR < 0 ? "neg" : "muted"}`}><b>{f.fired ? signedR(f.sumR) : "—"}</b></td>
                            <td className="muted nowrap">{f.levels}</td>
                            <td className="muted nowrap">{f.gap}</td>
                            <td className="nowrap">
                              {pending[f.row.id]
                                ? <span className="muted nowrap"><Spinner /> {pending[f.row.id] === "plan" ? "opening…" : pending[f.row.id] === "llm" ? "LLM read starting…" : "planning next session…"}</span>
                                : <span className="tq-acts">
                                    {f.row.promotedRunId
                                      ? <button className="tq-act" onClick={() => openRun(f.row.promotedRunId!)} title={`Open the run for this plan (${f.row.promotedRunId.slice(0, 8)}) — chart, trace, replay, discuss`}><IcoOpen /><span>open</span></button>
                                      : <>
                                        <button className="tq-act" onClick={() => promote(f.row, false)} title={`Open as a run — this exact ${f.row.symbol} plan for ${f.row.planFor} on the Analyse tab, with chart, trace, replay and chat. Deterministic, free, a few seconds. It is a PAST plan: for review, not arming.`}><IcoPlan /><span>open</span></button>
                                        <button className="tq-act" disabled={!llmOk} onClick={() => promote(f.row, true)} title={`LLM read — the model's 4-pass analyst read of this ${f.row.symbol} plan (≈$0.20, ~1 min). Lands in History.`}><IcoLlm /><span>LLM</span></button>
                                      </>}
                                    <button className="tq-act next" onClick={() => planNext(f.row)} title={`Plan the NEXT session for ${f.row.symbol} at the last close — the plan you can ARM for live triggers. Deterministic, free.`}><IcoNext /><span>next</span></button>
                                  </span>}
                            </td>
                          </tr>
                        ))}
                        {visible.length === 0 && <tr><td colSpan={9}><div className="empty">No findings match this lens.</div></td></tr>}
                      </tbody>
                    </table>
                  </div>

                  <DisclosureHead open={statsOpen} onToggle={toggleStats}
                    extra={<span className="sub">{(sm.claims ?? []).length} claims checked against {counts.fires} fire{counts.fires === 1 ? "" : "s"} · level & trigger quality</span>}>Does the book hold up?</DisclosureHead>
                  <Collapse open={statsOpen}>
                    <div className="tq-stats-intro muted">Everything below is computed from this validation only — {counts.rows} symbol-session{counts.rows === 1 ? "" : "s"}, {counts.fires} fire{counts.fires === 1 ? "" : "s"}. The book asks for ≥100 fires before trusting a number (p. 72), so until then read these as early signals, not verdicts.</div>
                    <div className="tq-section">
                      <div className="tq-label">The book's claims, checked against the data <span className="muted tq-hint">· §6.4</span></div>
                      <div className="tq-claims-list">
                        {(sm.claims ?? []).map((c: any, i: number) => {
                          const d = describeClaim(c); const vw = VERDICT_WORDS[c.verdict] ?? VERDICT_WORDS.insufficient;
                          return (
                            <div key={i} className={`tq-claim ${c.verdict}`}>
                              <div className="tq-claim-verdict"><span className={`tq-badge ${vw.cls}`}>{vw.word}</span></div>
                              <div className="tq-claim-body">
                                <div className="tq-claim-q">{d.question} <span className="tq-chip" title={c.claim}>{c.rule}</span></div>
                                <div className="muted small">{d.evidence}</div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    <LevelQuality title="Do planned levels hold?" hint="tested = price came within tolerance · held = reversed ≥3× tolerance before any close through · broke = closed through · flipped = broke, then acted as the opposite level" data={sm.levels?.priorDayVsOther} />
                    <LevelQuality title="…by where the level came from" data={sm.levels?.bySource} />
                    <LevelQuality title="…by how many times it had been touched (T1.2)" data={sm.levels?.byTouches} />
                    <LevelQuality title="…by the timeframe it was read on (p. 114)" data={sm.levels?.byTimeframe} />
                    <TriggerQuality title="Do the triggers pay?" hint="fired = price reached the entry inside a prime window · R = result in units of the planned risk" data={sm.triggers?.byKind} why />
                    <TriggerQuality title="…by the window they fired in (R6)" data={sm.triggers?.byWindow} />
                    <TriggerQuality title="Our own rules — the same plans replayed with one rule switched off" hint="if a rule earns its keep, the row without it should look worse"
                      data={{ ...(sm.triggers?.counterfactual ?? {}), ...(sm.triggers?.middayFiresWithoutGate?.fired ? { middayBlocked: sm.triggers.middayFiresWithoutGate } : {}) }} />
                    <TriggerQuality title="…by the reward-to-risk the plan demanded (R2)" data={sm.triggers?.byRrGate} />
                    {sm.errors?.length > 0 && <div className="muted small">Could not validate: {sm.errors.map((e: any) => `${e.symbol} (${e.error})`).join(", ")}</div>}
                  </Collapse>
                </>
              )}
            </div>
          </div>
        )}
        {/* ---- history of validations ---- */}
        {sweeps.length > 0 && (
          <div className="panel">
            <DisclosureHead open={histOpen} onToggle={toggleHist}>Past validations <span className="sub">{sweeps.length} · every run is kept — click one to reopen it</span></DisclosureHead>
            <Collapse open={histOpen}>
              <div className="panel-body table-wrap">
                <table className="data-table tq-hist">
                  <thead><tr><th>Ran</th><th>Validation</th><th>Symbols</th><th>Plans</th><th>Status</th><th>Checked</th><th>Fires</th><th>Win rate</th><th>ΣR</th><th>Engine</th><th></th></tr></thead>
                  <tbody>
                    {sweeps.map((s) => {
                      const base = s.summary?.triggers?.counterfactual?.base ?? {};
                      const fired = s.summary?.sample?.fired ?? base.fired;
                      const sr = Number(base.sumR ?? 0);
                      return (
                        <tr key={s.id} className={`clickable ${sel?.id === s.id ? "selected" : ""}`} onClick={() => api.techniqueSweep(s.id).then(setSel).catch(() => undefined)}>
                          <td className="muted nowrap">{s.createdAt ? fmtDateTime(s.createdAt) : ""}</td>
                          <td onClick={(e) => e.stopPropagation()}>{renaming?.id === s.id
                            ? <input className="tq-rename" autoFocus value={renaming.value} onChange={(e) => setRenaming({ id: s.id, value: e.target.value })}
                                onBlur={() => rename(s.id, renaming.value)} onKeyDown={(e) => { if (e.key === "Enter") rename(s.id, renaming.value); if (e.key === "Escape") setRenaming(null); }} />
                            : <><b className="clickable" onClick={() => api.techniqueSweep(s.id).then(setSel).catch(() => undefined)}>{s.label || `${s.start}..${s.end}`}</b> <button className="tq-pencil" title="Rename" onClick={() => setRenaming({ id: s.id, value: s.label || "" })}>✎</button></>}</td>
                          <td className="muted">{s.symbols.length} · {s.symbols.slice(0, 5).join(", ")}{s.symbols.length > 5 ? ` +${s.symbols.length - 5}` : ""}</td>
                          <td className="muted nowrap">{s.params?.kind === "next" ? <span title="A plan sheet: plans built at the close of the first date for the second date's session">{s.start} → <b>{s.params.planFor}</b> {s.summary?.pending && <span className="tq-badge plan" style={{ marginLeft: 4 }}>setups · {s.summary?.setups ?? "?"}</span>}</span> : s.start === s.end ? s.start : `${s.start} → ${s.end}`}</td>
                          <td>{s.status === "running" ? <span className="nowrap"><Spinner /> {s.progress?.done ?? 0}/{s.progress?.total ?? s.symbols.length}</span> : s.status === "failed" ? <span className="neg">failed</span> : <span className="pos">done</span>}</td>
                          <td>{s.summary?.sessions ?? "—"}</td>
                          <td>{fired ?? "—"}</td>
                          <td>{base.winRate !== undefined && base.winRate !== null ? `${Math.round(base.winRate * 100)}%` : "—"}</td>
                          <td className={sr > 0 ? "pos" : sr < 0 ? "neg" : "muted"}>{fired ? signedR(sr) : "—"}</td>
                          <td className="nowrap">{(() => { const v = s.params?.sweepVersion as string | undefined; const stale = !!(v && sweepVersion && v !== sweepVersion) || (!v && !!sweepVersion);
                            return stale
                              ? <span className="tq-stale" title={`Built with an earlier version of the plan builder${v ? ` (${v})` : ""} — levels/triggers may differ from today's engine (${sweepVersion}). Re-run to compare like with like.`}>⚠ older engine</span>
                              : <span className="muted small" title={`Plan-builder fingerprint ${v ?? "?"} — same as the engine running now`}>{v ? v.slice(0, 6) : "—"}</span>; })()}</td>
                          <td className="nowrap">{sel?.id === s.id ? <span className="muted small">showing</span> : <button className="link-btn" onClick={(e) => { e.stopPropagation(); api.techniqueSweep(s.id).then(setSel).catch(() => undefined); }}>open</button>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Collapse>
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
