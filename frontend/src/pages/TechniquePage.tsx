import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { ChatPanel } from "../components/technique/ChatPanel";
import { LiveRun } from "../components/technique/LiveRun";
import { OutcomeBadge, ReviewBadge, RunResult, VerdictBadge, WindowBadge } from "../components/technique/RunResult";
import { PlanCard } from "../components/technique/PlanCard";
import { ValidationTab } from "../components/technique/ValidationTab";
import { ArmedTab } from "../components/technique/ArmedTab";
import { Collapse, DisclosureHead, useDisclosure } from "../components/Collapse";
import { Modal } from "../components/Modal";
import { CopyChip } from "../components/CopyChip";
import { EmptyState, Spinner } from "../components/ui";
import { IconX } from "../components/icons";
import { SymbolSearch } from "../components/SymbolSearch";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useStore } from "../store";
import { absoluteUrl } from "../lib/routing";
import type { TechniqueRun, TechniqueSetup, TechniqueStatus } from "../types";

const TFS = ["1m", "5m", "15m", "30m", "1h"];

function readFileAsDataUrl(f: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result));
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}

/** `yyyy-mm-dd` for a Date, in local time. */
function toDateInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Most recent completed trading day before today: Mon->Fri, Sat->Fri, Sun->Fri. */
function previousBusinessDay(from = new Date(), back = 1): Date {
  const d = new Date(from);
  for (let i = 0; i < back; i++) {
    do {
      d.setDate(d.getDate() - 1);
    } while (d.getDay() === 0 || d.getDay() === 6);
  }
  return d;
}

/** A date-only value becomes an as-of instant at that session's close — 16:00 **ET**
 *  (not local time), so the run is in plan mode (R6.4) wherever the user sits. */
function dateToAsOfMs(date: string): number {
  const [y, m, d] = date.split("-").map(Number);
  // 20:00 UTC is 16:00 EDT; in EST (winter) it is 15:00, so nudge by an hour when needed.
  let ms = Date.UTC(y, m - 1, d, 20, 0, 0, 0);
  const etHour = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", hour12: false }).format(new Date(ms)));
  if (etHour === 15) ms += 3600_000;
  return ms;
}

const PRESETS: { label: string; get: () => string }[] = [
  { label: "Today", get: () => "" },
  { label: "Prev session", get: () => toDateInput(previousBusinessDay()) },
  { label: "−2 days", get: () => toDateInput(previousBusinessDay(new Date(), 2)) },
  { label: "−1 week", get: () => toDateInput(previousBusinessDay(new Date(), 5)) },
];

// --- status header -------------------------------------------------------------------

function StatusBar({ status, onScan }: { status: TechniqueStatus | null; onScan: () => void }) {
  const setPage = useStore((s) => s.setPage);
  if (!status) return <div className="tq-status muted"><Spinner /> loading status…</div>;
  return (
    <div className="tq-status">
      <span className={`status-pill ${status.llmAvailable ? "ok" : "bad"}`}>
        {status.llmAvailable ? `${status.model} · ${status.effort}` : "no API key"}
      </span>
      <span className={`status-pill ${status.optionsAvailable ? "ok" : ""}`}>
        options {status.optionsAvailable ? (status.optionsProvider ?? "cboe").toUpperCase() : "off"}
      </span>
      <span className="status-pill">runs today {status.runsToday}/{status.maxRunsPerDay}</span>
      <WindowBadge window={status.sessionWindow} />
      {(status.armed?.length ?? 0) > 0 && <span className="status-pill ok">{status.armed!.length} armed</span>}
      {status.scanEnabled && <span className="status-pill ok">scan on</span>}
      {status.running.length > 0 && <span className="status-pill ok"><Spinner /> {status.running.length} running</span>}
      <button className="link-btn" onClick={onScan}>scan now</button>
      <button className="link-btn" onClick={() => setPage("settings")}>settings</button>
    </div>
  );
}

// --- analyse form ---------------------------------------------------------------------

function AnalyseForm({ onStarted, disabled, running }: {
  onStarted: (run: TechniqueRun) => void;
  disabled: boolean;
  running: boolean;
}) {
  const defaultTf = useStore((s) => s.settings["technique.default_tf"] ?? "1m");
  const activeSymbol = useStore((s) => s.activeSymbol);
  const toast = useStore((s) => s.toast);
  const [symbol, setSymbol] = useState(activeSymbol || "SPY");
  const [tf, setTf] = useState<string>(defaultTf);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [advOpen, toggleAdv] = useDisclosure("tq_adv", false);
  // Collapse the form while a run is in flight and after it lands, so the
  // result owns the screen instead of the settings that produced it.
  const [formOpen, setFormOpen] = useState(true);
  useEffect(() => { if (running) setFormOpen(false); }, [running]);

  useEffect(() => { setTf(defaultTf); }, [defaultTf]);

  const addFile = useCallback(async (f: File | undefined) => {
    if (f && f.type.startsWith("image/")) setImage(await readFileAsDataUrl(f));
  }, []);
  const onPaste = (e: ClipboardEvent) => {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        e.preventDefault(); addFile(item.getAsFile() ?? undefined); return;
      }
    }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); addFile(e.dataTransfer.files[0]); };

  const run = async () => {
    setBusy(true);
    try {
      const body: any = { symbol: symbol.trim().toUpperCase(), tf, note };
      if (date) body.asOf = dateToAsOfMs(date);
      if (image) body.imageDataUrl = image;
      const r = await api.techniqueAnalyze(body);
      onStarted(r);
      toast("info", `Analysing ${r.symbol}…`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  const summary = [
    symbol.toUpperCase() || "—",
    tf,
    date ? `as of ${date}` : "latest",
    image ? "+ image" : null,
    note ? "+ note" : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="panel tq-form" onPaste={onPaste} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      <DisclosureHead open={formOpen} onToggle={() => setFormOpen((v) => !v)}
        extra={!formOpen && (
          <button className="primary-btn tq-rerun" disabled={busy || disabled || running}
            onClick={run}>{running ? "Running…" : "Run again"}</button>
        )}>
        {formOpen ? "Analyse" : <>Analyse <span className="muted">· {summary}</span></>}
      </DisclosureHead>

      <Collapse open={formOpen}>
        <div className="tq-form-body">
          <div className="tq-row">
            <div className="tq-ctl tq-ctl--symbol">
              <span className="tq-ctl-label">Symbol</span>
              <SymbolSearch compact inputId="tq-symbol" value={symbol} placeholder="ticker or company…"
                onValueChange={(v) => setSymbol(v.toUpperCase())}
                onPick={(h) => setSymbol(h.symbol)} />
            </div>
            <div className="tq-ctl tq-ctl--date">
              <span className="tq-ctl-label">Period</span>
              <div className="tq-date-row">
                <div className="tq-presets" role="group" aria-label="Period preset">
                  {PRESETS.map((p) => {
                    const v = p.get();
                    return (
                      <button key={p.label} type="button" className={date === v ? "active" : ""}
                        onClick={() => setDate(v)}
                        title={v ? `Session ending ${v}` : "Latest data"}>{p.label}</button>
                    );
                  })}
                </div>
                <input type="date" value={date} max={toDateInput(new Date())}
                  onChange={(e) => setDate(e.target.value)} aria-label="Session date" />
              </div>
            </div>
            <button className="primary-btn tq-run" disabled={busy || disabled || running || (!symbol.trim() && !image)}
              onClick={run}>{busy || running ? "Running…" : "Run analysis"}</button>
          </div>

          <div className="tq-row tq-row--sub">
            <label className="tq-chipbtn">
              <input type="file" accept="image/*" hidden onChange={(e) => addFile(e.target.files?.[0])} />
              Attach chart image
            </label>
            <button type="button" className={`tq-chipbtn ${note ? "set" : ""}`} onClick={() => setNoteOpen(true)}>
              {note ? "Note ✓" : "Note to analyst"}
            </button>
            <DisclosureHead open={advOpen} onToggle={toggleAdv} level="sub">Advanced</DisclosureHead>
            <span className="tq-cost muted">{date ? "past session → builds a plan for the next session (deterministic, free)" : "paste or drop an image anywhere · ~4 passes · ≈$0.20"}</span>
          </div>

          {image && (
            <div className="tq-thumb">
              <img src={image} alt="attached chart" />
              <span className="muted">attached — analysed alongside the generated charts</span>
              <button onClick={() => setImage(null)} aria-label="remove image"><IconX size={11} /></button>
            </div>
          )}

          <Collapse open={advOpen}>
            <div className="tq-adv">
              <div className="tq-ctl">
                <span className="tq-ctl-label">Primary timeframe</span>
                <select value={tf} onChange={(e) => setTf(e.target.value)}>
                  {TFS.map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <small className="muted">
                Where the entry/trigger decision is made. Structure (levels, patterns) is always read on the
                book's 30m/1h charts as well (p. 114: the author reports 78% vs 58% win rate on those); a finer
                primary timeframe times the entry inside the prime windows (R6). Change defaults in Settings
                (technique.default_tf, technique.structure_tfs).
              </small>
            </div>
          </Collapse>
        </div>
      </Collapse>

      {noteOpen && (
        <Modal title="Note to the analyst" onClose={() => setNoteOpen(false)}
          footer={<>
            <button className="ghost-btn" onClick={() => { setNote(""); setNoteOpen(false); }}>Clear</button>
            <button className="primary-btn" onClick={() => setNoteOpen(false)}>Done</button>
          </>}>
          <p className="muted" style={{ marginTop: 0 }}>
            Sent to the model with the charts — use it to point at something specific
            (“focus on the 10:30 rejection”, “ignore the opening spike”). Optional.
          </p>
          <label className="field">
            <textarea rows={3} value={note} autoFocus onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. focus on the 10:30 rejection" />
          </label>
        </Modal>
      )}
    </div>
  );
}

// --- history -----------------------------------------------------------------------------

type HistoryLens = "all" | "unreviewed" | "wrong" | "losses" | "pending";
const LENSES: { key: HistoryLens; label: string; hint: string }[] = [
  { key: "all", label: "All", hint: "every run" },
  { key: "unreviewed", label: "Unreviewed", hint: "finished runs with no review yet" },
  { key: "wrong", label: "Wrong", hint: "reviewed as anything but correct, or a losing outcome" },
  { key: "losses", label: "Losses", hint: "analysis or rejected-candidate plan lost money" },
  { key: "pending", label: "Pending outcome", hint: "outcome not scored / still partial" },
];

function primaryOutcome(r: TechniqueRun) {
  const outs = r.outcomes ?? [];
  const fired = outs.find((o) => o.planSource.startsWith("trigger:") && o.outcome && !["not_triggered", "observed", "gapped_past", "gapped_through", "gap_void"].includes(o.outcome));
  return fired ?? outs.find((o) => o.planSource === "analysis") ?? outs.find((o) => o.planSource === "candidate")
    ?? outs.find((o) => o.planSource.startsWith("trigger:")) ?? outs.find((o) => o.planSource === "levels") ?? outs[0] ?? null;
}

function HistoryTab({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useStore((s) => s.techniqueRuns);
  const setRuns = useStore((s) => s.setTechniqueRuns);
  const toast = useStore((s) => s.toast);
  const [filter, setFilter] = useState("");
  const [lens, setLens] = useState<HistoryLens>("all");
  const [scoring, setScoring] = useState(false);
  useEffect(() => { api.techniqueRuns(200).then(setRuns).catch(() => undefined); }, [setRuns]);
  const visible = useMemo(() => runs.filter((r) => {
    if (filter && !r.symbol.includes(filter.toUpperCase())) return false;
    if (lens === "all") return true;
    const o = primaryOutcome(r);
    const lost = (r.outcomes ?? []).some((x) => (x.rMultiple ?? 0) < 0);
    if (lens === "unreviewed") return r.status === "done" && !(r.reviewCount ?? 0);
    if (lens === "wrong") return (r.lastReview && r.lastReview.reviewVerdict !== "correct") || lost;
    if (lens === "losses") return lost;
    if (lens === "pending") return r.status === "done" && (!o || o.status === "pending" || o.status === "partial");
    return true;
  }), [runs, filter, lens]);
  const scoreAll = async () => {
    setScoring(true);
    try {
      const res = await api.techniqueScorePending();
      toast("info", `Scored ${res.scored?.length ?? 0} run(s)${res.remaining ? `, ${res.remaining} left` : ""}`);
      api.techniqueRuns(200).then(setRuns).catch(() => undefined);
    } catch (e: any) { toast("error", e.message); } finally { setScoring(false); }
  };
  return (
    <div className="panel">
      <div className="panel-head">Run history <span className="sub">{visible.length} / {runs.length} runs</span>
        <div className="tq-lenses" role="group" aria-label="History lens">
          {LENSES.map((l) => (
            <button key={l.key} type="button" className={lens === l.key ? "active" : ""} title={l.hint}
              onClick={() => setLens(l.key)}>{l.label}</button>
          ))}
        </div>
        <button className="link-btn" disabled={scoring} onClick={scoreAll} title="Score every finished run that has no outcome yet">
          {scoring ? "scoring…" : "score pending"}
        </button>
        <input className="tq-filter" placeholder="filter symbol" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="tq-table tq-history">
          <thead><tr><th>When</th><th>Symbol</th><th>TF</th><th>Verdict</th><th>Conf</th><th>Grounded</th><th>Outcome</th><th>Review</th><th>Trigger</th><th>Run</th><th></th></tr></thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
                <td>{r.createdAt ? fmtDateTime(r.createdAt) : ""}</td>
                <td><b>{r.symbol}</b></td>
                <td>{r.primaryTf}{r.mode === "image_only" ? " (img)" : ""}{r.parentRunId ? " ↺" : ""}</td>
                <td><VerdictBadge run={r} /></td>
                <td>{r.confidence !== null && r.confidence !== undefined ? r.confidence.toFixed(2) : "—"}</td>
                <td>{r.grounded === null || r.grounded === undefined ? "—" : r.grounded ? "yes" : "no"}</td>
                <td><OutcomeBadge outcome={primaryOutcome(r)} /></td>
                <td><ReviewBadge last={r.lastReview ?? null} count={r.reviewCount ?? 0} /></td>
                <td className="muted">{r.trigger}</td>
                <td><CopyChip value={r.id} link={absoluteUrl({ page: "technique", techniqueTab: "analyse", runId: r.id })} /></td>
                <td><button className="link-btn" onClick={(e) => { e.stopPropagation(); if (r.threadId) useStore.getState().openTechniqueChat(r.threadId); }}>chat</button></td>
              </tr>
            ))}
            {visible.length === 0 && <tr><td colSpan={11}><div className="empty">{runs.length ? "No runs match this lens." : "No runs yet."}</div></td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- backtest ---------------------------------------------------------------------------

function BacktestTab() {
  const toast = useStore((s) => s.toast);
  const [symbol, setSymbol] = useState("SPY");
  const [tf, setTf] = useState("5m");
  const [days, setDays] = useState(10);
  const [horizon, setHorizon] = useState(60);
  const [primeOnly, setPrimeOnly] = useState(true);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const run = async () => {
    setBusy(true);
    try { setRes(await api.techniqueBacktest({ symbol: symbol.toUpperCase(), tf, days, horizonBars: horizon, primeWindowsOnly: primeOnly })); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(false); }
  };
  const s = res?.summary;
  return (
    <div>
      <div className="panel mb">
        <div className="panel-head">Backtest <span className="sub">deterministic replay — no model calls, free</span></div>
        <div className="panel-body">
          <div className="tq-row">
            <div className="tq-ctl"><span className="tq-ctl-label">Symbol</span>
              <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">Timeframe</span>
              <select value={tf} onChange={(e) => setTf(e.target.value)}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></div>
            <div className="tq-ctl"><span className="tq-ctl-label">Days back <small className="muted">(1m ≤ 20)</small></span>
              <input type="number" value={days} min={1} max={59} onChange={(e) => setDays(Number(e.target.value))} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">Horizon (bars)</span>
              <input type="number" value={horizon} min={10} max={300} onChange={(e) => setHorizon(Number(e.target.value))} /></div>
            <label className="tq-chipbtn" title="R6: take setups only in 09:30–10:30 / 14:45–16:00 ET (the book's schedule)">
              <input type="checkbox" checked={primeOnly} onChange={(e) => setPrimeOnly(e.target.checked)} /> prime windows only (R6)
            </label>
            <button className="primary-btn tq-run" disabled={busy} onClick={run}>{busy ? "Replaying…" : "Run backtest"}</button>
          </div>
        </div>
      </div>
      {res?.error && <div className="panel mb"><div className="panel-body neg">{res.error}</div></div>}
      {s && (
        <div className="panel mb">
          <div className="panel-head">{s.symbol} {s.tf} · {s.sessions} sessions</div>
          <div className="panel-body">
            <div className="tq-plan">
              <div className="tq-plan-cell"><small>Setups</small><b>{s.setupsEmitted}</b><span>{s.filled} filled · {s.notFilled} not filled</span></div>
              <div className="tq-plan-cell"><small>Win rate</small><b className={s.winRate >= 0.5 ? "pos" : ""}>{(s.winRate * 100).toFixed(0)}%</b><span>of filled</span></div>
              <div className="tq-plan-cell"><small>Avg R</small><b className={s.avgR > 0 ? "pos" : "neg"}>{s.avgR}</b><span>per filled trade</span></div>
              <div className="tq-plan-cell"><small>Total R</small><b className={s.totalR > 0 ? "pos" : "neg"}>{s.totalR}</b><span>min R:R {s.params.minRR}</span></div>
              {Object.entries(s.byType ?? {}).map(([k, v]: any) => (
                <div className="tq-plan-cell" key={k}><small>{k.replace(/_/g, " ")}</small><b>{v.n}</b><span>win {(v.winRate * 100).toFixed(0)}% · avg R {v.avgR}</span></div>
              ))}
              {Object.entries(s.byWindow ?? {}).map(([k, v]: any) => (
                <div className="tq-plan-cell" key={`w-${k}`}><small>window {k.replace(/_/g, " ")}</small><b>{v.n}</b><span>win {(v.winRate * 100).toFixed(0)}% · avg R {v.avgR}</span></div>
              ))}
            </div>
            <table className="tq-table" style={{ marginTop: 10 }}>
              <thead><tr><th>Session</th><th>Type</th><th>Entry</th><th>Stop</th><th>TP1</th><th>Outcome</th><th>R</th><th>Bars</th></tr></thead>
              <tbody>
                {(res.trades ?? []).slice(0, 200).map((t: any, i: number) => (
                  <tr key={i}>
                    <td>{t.session}</td><td>{t.setupType.replace(/_/g, " ")}</td><td>{t.entry.toFixed(2)}</td>
                    <td>{t.stop.toFixed(2)}</td><td>{t.targets[0]?.toFixed(2)}</td>
                    <td className={t.outcome === "stopped" ? "neg" : t.outcome.startsWith("tp") ? "pos" : "muted"}>{t.outcome}</td>
                    <td className={t.rMultiple > 0 ? "pos" : t.rMultiple < 0 ? "neg" : ""}>{t.rMultiple}</td><td>{t.barsHeld}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// --- right rail -----------------------------------------------------------------------

function ArmedPanel() {
  const armed = useStore((s) => s.techniqueArmed);
  const setArmed = useStore((s) => s.setTechniqueArmed);
  const setTab = useStore((s) => s.setTechniqueTab);
  useEffect(() => { api.techniqueArmed().then(setArmed).catch(() => undefined); }, [setArmed]);
  return (
    <div className="panel mb">
      <div className="panel-head">Armed <span className="sub">{armed.length}</span>
        <button className="link-btn" style={{ marginLeft: "auto" }} onClick={() => setTab("armed")}>dashboard</button></div>
      <div className="panel-body tq-setups">
        {armed.length === 0 && <div className="empty">nothing armed</div>}
        {armed.map((a) => (
          <button key={a.runId} className={`tq-setup-row ${a.status === "armed" ? "valid" : ""}`} onClick={() => setTab("armed")}>
            <b>{a.symbol}</b> <span>{a.config.mode}{a.portfolio.kind === "live" ? " · REAL" : ""} · {a.status}</span>
            <span className="muted">{a.summary}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Rail({ rules }: { rules: Record<string, string> }) {
  const setups = useStore((s) => s.techniqueSetups);
  const setSetups = useStore((s) => s.setTechniqueSetups);
  const openRun = useStore((s) => s.openTechniqueRun);
  const [railOpen, toggleRail] = useDisclosure("tq_rail", true);
  const [rulesOpen, toggleRules] = useDisclosure("tq_rules", false);
  const [q, setQ] = useState("");
  useEffect(() => { api.techniqueSetups(50).then(setSetups).catch(() => undefined); }, [setSetups]);
  const ruleList = useMemo(() => Object.entries(rules).filter(([id, t]) =>
    !q || id.toLowerCase().includes(q.toLowerCase()) || t.toLowerCase().includes(q.toLowerCase())), [rules, q]);

  if (!railOpen) {
    return (
      <button className="tq-rail-tab" onClick={toggleRail} title="Show setups and rulebook">
        <span>SETUPS &amp; RULES</span>
      </button>
    );
  }
  return (
    <div className="tq-rail">
      <ArmedPanel />
      <div className="panel mb">
        <DisclosureHead open onToggle={toggleRail}
          extra={<span className="sub">{setups.length} · hide</span>}>Setups</DisclosureHead>
        <div className="panel-body tq-setups">
          {setups.length === 0 && <div className="empty">none yet</div>}
          {setups.slice(0, 12).map((s: TechniqueSetup) => (
            <button key={s.id} className={`tq-setup-row ${s.valid ? "valid" : ""}`} onClick={() => openRun(s.runId)}>
              <b>{s.symbol}</b> <span>{s.setupType.replace(/_/g, " ")}</span>
              <span className="muted">{s.valid ? `entry ${s.entry.toFixed(2)} · R:R ${s.riskReward.toFixed(1)}` : `no trade · ${s.noTradeReasons[0]?.slice(0, 28) ?? ""}`}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="panel">
        <DisclosureHead open={rulesOpen} onToggle={toggleRules}
          extra={<span className="sub">{Object.keys(rules).length}</span>}>Rulebook</DisclosureHead>
        <Collapse open={rulesOpen}>
          <div className="panel-body">
            <input className="chat-search" placeholder="search rules…" value={q}
              onChange={(e) => setQ(e.target.value)} />
            <div className="tq-rules">
              {ruleList.map(([id, t]) => <div key={id} className="tq-rule"><span className="tq-chip">{id}</span><span>{t}</span></div>)}
            </div>
          </div>
        </Collapse>
      </div>
    </div>
  );
}

// --- page -------------------------------------------------------------------------------

export function TechniquePage() {
  const tab = useStore((s) => s.techniqueTab);
  const setTab = useStore((s) => s.setTechniqueTab);
  const runs = useStore((s) => s.techniqueRuns);
  const setRuns = useStore((s) => s.setTechniqueRuns);
  const focusId = useStore((s) => s.techniqueFocusRunId);
  const toast = useStore((s) => s.toast);
  const [status, setStatus] = useState<TechniqueStatus | null>(null);
  const setFocusRun = useStore((s) => s.setTechniqueFocusRun);
  const [full, setFull] = useState<TechniqueRun | null>(null);
  const fetchedFor = useRef<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const armedCount = useStore((s) => s.techniqueArmed.length);
  const bump = useStore((s) => (focusId ? s.techniqueRunBumps[focusId] : undefined) ?? 0);

  const refreshStatus = useCallback(() => { api.techniqueStatus().then(setStatus).catch(() => undefined); }, []);
  useEffect(() => { refreshStatus(); api.techniqueRuns(100).then(setRuns).catch(() => undefined); }, [refreshStatus, setRuns]);
  const active = useMemo(() => runs.find((r) => r.id === focusId) ?? runs[0] ?? null, [runs, focusId]);

  // A deep link may name a run that is not in the recent list — fetch it.
  useEffect(() => {
    if (!focusId || runs.some((r) => r.id === focusId)) return;
    api.techniqueRun(focusId)
      .then((r) => setRuns([r, ...useStore.getState().techniqueRuns.filter((x) => x.id !== r.id)]))
      .catch(() => toast("error", `Run ${focusId.slice(0, 8)} not found`));
  }, [focusId, runs, setRuns, toast]);

  // A client that connects mid-run has no pass history: seed it from the server.
  const chatLive = useStore((s) => s.chatLive);
  const seedChatLive = useStore((s) => s.seedChatLive);
  useEffect(() => {
    if (!active || active.status !== "running" || !active.threadId) return;
    const live = chatLive[active.threadId];
    if (live && live.passes.length > 0) return;
    const tid = active.threadId;
    api.techniqueRun(active.id).then((r: any) => { if (r.live) seedChatLive(tid, r.live); }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, active?.status]);

  // Fetch the full row (facts, passes, outcomes, reviews) once a run finishes,
  // and again whenever an outcome / review lands for it.
  const activeBump = useStore((s) => (active ? s.techniqueRunBumps[active.id] : undefined) ?? 0);
  useEffect(() => {
    if (!active || active.status === "running") return;
    const key = `${active.id}:${active.status}:${activeBump}:${refreshKey}`;
    if (fetchedFor.current === key) return;
    fetchedFor.current = key;
    api.techniqueRun(active.id).then((r) => { setFull(r); refreshStatus(); }).catch((e) => toast("error", e.message));
  }, [active, activeBump, refreshKey, refreshStatus, toast]);
  void bump;

  useEffect(() => { refreshStatus(); }, [runs.length, refreshStatus]);

  const rules = status?.rules ?? {};
  const shown = full && active && full.id === active.id ? { ...active, ...full } : active;
  const running = shown?.status === "running";

  return (
    <div className="tq-page">
      <div className="tq-title-row">
        <h2 className="page-title">Technique <span className="muted">· EnhancedMarket</span></h2>
        <StatusBar status={status} onScan={() => api.techniqueScan().then(() => refreshStatus()).catch((e) => toast("error", e.message))} />
      </div>
      <div className="tabs tq-tabs">
        {(["analyse", "chat", "history", "backtest", "validation", "armed"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "analyse" ? "Analyse" : t === "chat" ? "Chat" : t === "history" ? "History" : t === "backtest" ? "Backtest"
              : t === "validation" ? "Validation" : <>Armed{armedCount > 0 ? <span className="tq-tab-count">{armedCount}</span> : null}</>}
          </button>
        ))}
      </div>
      {tab === "chat" ? (
        <ChatPanel />
      ) : tab === "validation" ? (
        <ValidationTab />
      ) : tab === "armed" ? (
        <ArmedTab />
      ) : (
        <div className="tq-grid">
          <div className="tq-main">
            {tab === "analyse" && (
              <>
                <AnalyseForm disabled={!status?.llmAvailable} running={running}
                  onStarted={(r) => { setFocusRun(r.id); }} />
                {!status?.llmAvailable && status && (
                  <EmptyState title="No API key" hint="Set ZARGAR_ANTHROPIC_API_KEY in backend/.env to run analyses." />
                )}
                {shown && running && <LiveRun run={shown} />}
                {shown && !running && shown.mode === "plan" && <PlanCard run={shown} onRefresh={() => setRefreshKey((k) => k + 1)} />}
                {shown && !running && shown.mode !== "plan" && <RunResult run={shown} rules={rules} onRefresh={() => setRefreshKey((k) => k + 1)} />}
                {!shown && <EmptyState title="No runs yet" hint="Enter a symbol and run the pipeline, or paste a chart screenshot." />}
              </>
            )}
            {tab === "history" && <HistoryTab onOpen={(id) => { setFocusRun(id); setTab("analyse"); }} />}
            {tab === "backtest" && <BacktestTab />}
          </div>
          <Rail rules={rules} />
        </div>
      )}
    </div>
  );
}
