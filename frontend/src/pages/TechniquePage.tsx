import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { ChatPanel } from "../components/technique/ChatPanel";
import { LiveRun } from "../components/technique/LiveRun";
import { OutcomeBadge, ReviewBadge, RunResult, VerdictBadge } from "../components/technique/RunResult";
import { GradeChip, PlanCard } from "../components/technique/PlanCard";
import { ValidationTab } from "../components/technique/ValidationTab";
import { ArmedTab } from "../components/technique/ArmedTab";
import { RailShell, useRail } from "../components/technique/RailShell";
import { Collapse, DisclosureHead, useDisclosure } from "../components/Collapse";
import { Modal } from "../components/Modal";
import { CopyChip } from "../components/CopyChip";
import { EmptyState, Spinner } from "../components/ui";
import { IconX } from "../components/icons";
import { SymbolSearch } from "../components/SymbolSearch";
import { api } from "../lib/api";
import { useWorkspace, workspaceOf } from "../lib/workspace";
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

// The as-of moment. The lookback (5 sessions of 1m, 15 of 30m, 25 of 1h) is always
// applied behind it; a plan is always for the *next* session, so only "now" and "the
// last close" matter day to day — the date box is for checking one specific past close.
const PRESETS: { label: string; get: () => string; title: string }[] = [
  { label: "Now", get: () => "", title: "Live: analyse the current bar (a plan for the next session if the market is closed)" },
  { label: "Last close", get: () => toDateInput(previousBusinessDay()), title: "As of the last session's 16:00 ET close: the plan for the next session" },
];

// --- status header -------------------------------------------------------------------

function StatusBar({ status, onScan, scanBusy }: {
  status: TechniqueStatus | null; onScan: () => void; scanBusy: boolean;
}) {
  if (!status) return <div className="tq-status muted"><Spinner /> loading status…</div>;
  return (
    <div className="tq-status">
      {!status.llmAvailable && <span className="status-pill bad">no API key</span>}
      <span className="status-pill">runs today {status.runsToday}/{status.maxRunsPerDay}</span>
      {(status.armed?.length ?? 0) > 0 && <span className="status-pill ok">{status.armed!.length} armed</span>}
      {status.running.length > 0 && <span className="tq-running-pill"><Spinner /> {status.running.length} running</span>}
      <button className="tq-check-btn" onClick={onScan} disabled={scanBusy}
        title="The main move: analyst-check tonight's graded sheet (or run a live watch-list read), then bulk-arm the confirmed setups — a confirmation shows symbols and cost first">
        {scanBusy ? <><Spinner /> Checking…</> : <>⚡ Check &amp; arm</>}
      </button>
    </div>
  );
}

/** Live progress of a scan: one row per symbol, filling in as runs finish.
 *  In `armable` mode (sheet scan) rows are promoted PLAN runs: each shows its
 *  deterministic grade + the analyst's read, with per-row and bulk Arm. */
function ScanPanel({ ids, armable, onDone, onClose, onOpen, onArmedAll }: {
  ids: string[]; armable?: boolean; onDone: () => void; onClose: () => void;
  onOpen: (id: string) => void; onArmedAll?: (n: number) => void;
}) {
  const toast = useStore((s) => s.toast);
  const armed = useStore((s) => s.techniqueArmed);
  const portfolios = useStore((s) => s.portfolios);
  const maxConcurrent = useStore((s) => Number(s.settings["technique.max_concurrent_runs"] ?? 8));
  const ws = useWorkspace();
  // arms always land in the ACTIVE workspace: practice -> the simulator,
  // live -> the default/first live account (the server guards the same way)
  const armPortfolio = useMemo(() => portfolios.find((p) =>
    workspaceOf(p.kind) === ws && (ws !== "live" ? p.kind === "sim" : true)), [portfolios, ws]);
  const [rows, setRows] = useState<Record<string, TechniqueRun>>({});
  const [full, setFull] = useState<Record<string, TechniqueRun>>({});
  const [active, setActive] = useState<Record<string, { symbol?: string; stage?: string }>>({});
  const [armBusy, setArmBusy] = useState<Record<string, boolean>>({});
  const [bulkArm, setBulkArm] = useState<{ done: number; total: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const finished = useRef(false);
  const doneOrder = useRef<string[]>([]);

  useEffect(() => {
    finished.current = false;   // ids can GROW mid-scan (batch adoption below)
    let stop = false;
    const poll = async () => {
      if (finished.current) return;
      try {
        // the list window MUST cover the whole batch — a 72-run batch once sat
        // stuck at "60 done" because this poll only looked at the last 60 runs
        const all = await api.techniqueRuns(Math.max(100, ids.length + 30));
        if (stop) return;
        const map: Record<string, TechniqueRun> = {};
        for (const r of all) if (ids.includes(r.id)) map[r.id] = r;
        // stragglers that still fell outside the window: fetch them directly
        for (const id of ids.filter((x) => !map[x]).slice(0, 12)) {
          try { map[id] = await api.techniqueRun(id); } catch { /* transient */ }
        }
        if (stop) return;
        setRows(map);
        for (const id of ids) {
          const r = map[id];
          if (r && r.status !== "running") {
            if (!doneOrder.current.includes(id)) doneOrder.current.push(id);
            if (!full[id] && r.status !== "failed")
              api.techniqueRun(id).then((fr) => setFull((m) => ({ ...m, [fr.id]: fr }))).catch(() => undefined);
          }
        }
        api.techniqueStatus().then((st) => { if (!stop) setActive((st as any).activeRuns ?? {}); }).catch(() => undefined);
        setNow(Date.now());
        if (ids.length && ids.every((id) => map[id] && map[id].status !== "running")) {
          finished.current = true;
          onDone();
        }
      } catch { /* transient */ }
    };
    void poll();
    const t = setInterval(() => void poll(), 3000);
    return () => { stop = true; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(","), Object.keys(full).length]);

  const bestTrigger = (fr?: TechniqueRun) => {
    const trig = (fr?.result?.plan?.triggers ?? []).filter((t: any) => t.valid);
    if (!trig.length) return null;
    return trig.slice().sort((a: any, b: any) => (b.assessment?.score ?? 0) - (a.assessment?.score ?? 0))[0];
  };
  const analystOk = (fr?: TechniqueRun) => fr?.result?.analysis?.verdict === "setup";
  const isArmed = (id: string) => armed.some((a) => a.runId === id);
  // quiet=true is the bulk path: no per-plan toasts (21 chips once buried the
  // screen) — the caller shows ONE summary instead
  const armOne = async (id: string, sym: string, quiet = false): Promise<string | null> => {
    setArmBusy((m) => ({ ...m, [id]: true }));
    try {
      const a = await api.techniqueArm(id, (armPortfolio ? { portfolioId: armPortfolio.id } : undefined) as any);
      if (!quiet) toast("success", `${sym} armed — ${a.config.mode} on ${a.portfolio?.name ?? "default account"}`);
      return null;
    }
    catch (e: any) {
      if (!quiet) toast("error", e.message);
      return `${sym}: ${e.message}`;
    }
    finally { setArmBusy((m) => ({ ...m, [id]: false })); }
  };

  // ---- live progress: done / working (real semaphore slots) / queued ------
  const doneIds = doneOrder.current.filter((id) => rows[id]);
  const failedIds = doneIds.filter((id) => rows[id]?.status === "failed");
  const allDone = finished.current || (ids.length > 0 && ids.every((id) => rows[id] && rows[id].status !== "running"));
  const workingIds = ids.filter((id) => active[id] && (!rows[id] || rows[id].status === "running"));
  const queuedIds = ids.filter((id) => !active[id] && (!rows[id] || rows[id].status === "running"));
  const pct = ids.length ? Math.round((doneIds.length / ids.length) * 100) : 0;
  const startMs = useMemo(() => {
    const ts = ids.map((id) => rows[id]?.createdAt).filter(Boolean)
      .map((t) => new Date(t as string).getTime());
    return ts.length ? Math.min(...ts) : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Object.keys(rows).length]);
  let eta = "";
  if (!allDone && startMs && doneIds.length >= 3) {
    const remainMs = ((now - startMs) / doneIds.length) * (ids.length - doneIds.length);
    const m = Math.max(1, Math.round(remainMs / 60000));
    eta = m >= 90 ? `~${(m / 60).toFixed(1)} h left` : `~${m} min left`;
  }
  const STAGE: Record<string, string> = {
    preparing: "rendering charts", context: "pass 1/4 · context", pattern: "pass 2/4 · pattern",
    entry: "pass 3/4 · entry plan", critic: "pass 4/4 · critic",
  };

  const passed = ids.filter((id) => analystOk(full[id]) && bestTrigger(full[id]) && !isArmed(id));
  const setups = armable ? ids.filter((id) => analystOk(full[id]))
    : doneIds.filter((id) => rows[id]?.verdict === "setup");
  const armAll = async () => {
    const total = passed.length;
    const fails: string[] = [];
    setBulkArm({ done: 0, total });
    try {
      for (const [i, id] of passed.entries()) {
        const err = await armOne(id, full[id]?.symbol ?? id.slice(0, 6), true);
        if (err) fails.push(err);
        setBulkArm({ done: i + 1, total });
      }
    } finally { setBulkArm(null); }
    const ok = total - fails.length;
    if (fails.length) toast(ok ? "info" : "error",
      `${ok}/${total} armed · ${fails.length} failed — first: ${fails[0]}`);
    else toast("success", `All ${ok} armed — they're on the Armed dashboard`);
    if (ok) onArmedAll?.(ok);
  };

  // completion order while running (rows appear as they finish, no jumping);
  // the quality sort (analyst first, then score) applies once everything is in
  const tableIds = allDone
    ? ids.slice().sort((a, b) => (Number(analystOk(full[b])) - Number(analystOk(full[a])))
        || ((bestTrigger(full[b])?.assessment?.score ?? -1) - (bestTrigger(full[a])?.assessment?.score ?? -1)))
    : doneIds;

  const progress = (
    <div className="tq-scan-progress">
      <div className="tq-progress-bar" role="progressbar" aria-valuenow={pct}>
        <div className="fill" style={{ width: `${pct}%` }} />
      </div>
      <b className="nowrap">{doneIds.length}/{ids.length} · {pct}%</b>
      {!allDone && (
        <span className="muted nowrap">
          {workingIds.length} working · {queuedIds.length} queued{eta ? ` · ${eta}` : ""}
        </span>
      )}
      {failedIds.length > 0 && <span className="neg nowrap">{failedIds.length} failed</span>}
    </div>
  );

  const chipGroups = !allDone && (workingIds.length > 0 || queuedIds.length > 0) && (
    <div className="tq-scan-groups">
      {workingIds.length > 0 && (
        <div className="tq-scan-group">
          <div className="tq-scan-group-title">Working now</div>
          <div className="tq-scan-chips">
            {workingIds.map((id) => (
              <span key={id} className="tq-scan-chip working">
                <Spinner /> <b>{rows[id]?.symbol ?? active[id]?.symbol ?? id.slice(0, 6)}</b>
                <span className="muted">{STAGE[active[id]?.stage ?? ""] ?? active[id]?.stage ?? ""}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {queuedIds.length > 0 && (
        <div className="tq-scan-group">
          <div className="tq-scan-group-title">Queued — {maxConcurrent} run at a time</div>
          <div className="tq-scan-chips">
            {queuedIds.map((id) => (
              <span key={id} className="tq-scan-chip">{rows[id]?.symbol ?? id.slice(0, 6)}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="panel mb tq-scan-panel">
      <div className="panel-head">
        {allDone
          ? <b>{armable ? `Analyst check finished — ${setups.length}/${ids.length} confirmed` : `Scan finished — ${setups.length ? `${setups.length} setup(s) found` : "no setups"} across ${ids.length} symbol(s)`}</b>
          : <b><Spinner /> {armable ? "Analyst-checking" : "Scanning"}</b>}
        <span className="sub">{armable ? "grade = the plan's own read · analyst = the 4-pass model read of the same charts" : "each row is a full analysis run; they also live in History (trigger \"scan\")"}</span>
        {armable && allDone && (passed.length > 0 || bulkArm) && (
          <button className="primary-btn tq-scan-armall" disabled={!!bulkArm}
            onClick={() => void armAll()}>
            {bulkArm ? `⚡ Arming ${bulkArm.done}/${bulkArm.total}…` : `⚡ Arm ${passed.length} confirmed`}
          </button>
        )}
        <button className="icon-btn tq-head-right" onClick={onClose} aria-label="Dismiss scan results"><IconX /></button>
      </div>
      {progress}
      {armable ? (
        <div className="panel-body" style={{ padding: 0 }}>
          {tableIds.length > 0 && (
            <div className="tq-table-wrap">
              <table className="tq-table tq-scan-table">
                <thead><tr><th>Symbol</th><th title="Deterministic validity grade of the best trigger">Grade</th>
                  <th title="The 4-pass model read of the same plan — advice, not a gate">Analyst</th>
                  <th>Setup</th><th>Entry</th><th>Stop</th><th>Targets</th>
                  <th title="Reward-to-risk of the graded trigger">R:R</th><th aria-label="actions" /></tr></thead>
                <tbody>
                  {tableIds.map((id) => {
                    const r = rows[id];
                    const fr = full[id];
                    const best = bestTrigger(fr);
                    const failed = r?.status === "failed";
                    const fp = (n: any) => (typeof n === "number" ? n.toFixed(2) : "—");
                    return (
                      <tr key={id} className="clickable" onClick={() => r && onOpen(r.id)} title={r ? "Open this run" : ""}>
                        <td className="nowrap"><b>{r?.symbol ?? id.slice(0, 8)}</b></td>
                        <td>{best ? <GradeChip a={best.assessment} valid /> : failed ? null : <span className="muted small">none</span>}</td>
                        <td className="nowrap">{failed
                          ? <span className="neg" title={r?.error ?? ""}>✗ failed — open to retry</span>
                          : fr?.result?.analysis
                            ? <span className={analystOk(fr) ? "pos" : "muted"}
                                title={analystOk(fr)
                                  ? "The analyst read the plan and endorses this trigger"
                                  : `Would stand aside. First reason: ${fr.result.analysis.noTradeReasons?.[0] ?? "(none)"} — open the run for the full read. Advice, not a gate.`}>
                                {analystOk(fr) ? `✓ ${(fr.result.analysis.confidence ?? 0).toFixed(2)}` : "✗ stand aside"}
                              </span>
                            : <span className="muted small"><Spinner /></span>}</td>
                        <td>{best ? <span className={`tq-badge ${best.kind === "bounce" ? "setup" : "plan"}`}>{best.kind === "bounce" ? "BOUNCE" : best.kind === "breakout" ? "BREAKOUT" : "WEDGE"}</span> : null}</td>
                        <td className="nowrap">{best ? <>{fp(best.entry?.price)} <span className="muted small">{best.entry?.basis === "on_break" ? "on break" : "at level"}</span></> : "—"}</td>
                        <td className="nowrap neg">{best ? fp(best.stop?.price) : "—"}</td>
                        <td className="nowrap small">{best ? (best.targets ?? []).slice(0, 3).map((t: any, i: number) =>
                          <span key={i}>{i > 0 && <span className="tq-sep"> / </span>}<span className="pos">{fp(t.price)}</span></span>) : "—"}</td>
                        <td>{best ? <b>{typeof best.riskReward === "number" ? best.riskReward.toFixed(1) : "—"}</b> : "—"}</td>
                        <td className="nowrap tq-arm-cell" onClick={(e) => e.stopPropagation()}>
                          {best && (isArmed(id)
                            ? <span className="tq-badge setup">ARMED</span>
                            : <button className="tq-act next" disabled={!!armBusy[id]}
                                onClick={() => void armOne(id, r!.symbol)}
                                title="Arm this plan with your default account/mode (nothing fires until its conditions are met)">
                                {armBusy[id] ? "…" : "⚡ arm"}
                              </button>)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {chipGroups}
        </div>
      ) : (
        <div className="panel-body tq-scan-rows">
          {doneIds.map((id) => {
            const r = rows[id];
            return (
              <span key={id} className="tq-scan-row" role="button" tabIndex={0} onClick={() => r && onOpen(r.id)}
                onKeyDown={(e) => { if (e.key === "Enter" && r) onOpen(r.id); }} title={r ? "Open this run" : ""}>
                <b>{r?.symbol ?? id.slice(0, 8)}</b>
                <VerdictBadge run={r} />
                {r.verdict !== "setup" && <span className="muted small">nothing tradeable at this moment</span>}
              </span>
            );
          })}
          {chipGroups}
        </div>
      )}
    </div>
  );
}


// --- analyse form ---------------------------------------------------------------------

function AnalyseForm({ onStarted, disabled, running }: {
  onStarted: (run: TechniqueRun) => void;
  disabled: boolean;
  running: boolean;
}) {
  const defaultTf = useStore((s) => s.settings["technique.trigger_tf"] ?? "1m");
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
    date ? `as of ${date} close` : "now",
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
        {formOpen
          ? <>EM Options Technique <span className="muted">· EnhancedMarket method · just-OTM weeklies / 0DTE</span></>
          : <>EM Options Technique <span className="muted">· {summary}</span></>}
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
              <span className="tq-ctl-label">As of</span>
              <div className="tq-date-row">
                <div className="tq-presets" role="group" aria-label="As-of preset">
                  {PRESETS.map((p) => {
                    const v = p.get();
                    return (
                      <button key={p.label} type="button" className={date === v ? "active" : ""}
                        onClick={() => setDate(v)} title={p.title}>{p.label}</button>
                    );
                  })}
                </div>
                <input type="date" value={date} max={toDateInput(new Date())}
                  onChange={(e) => setDate(e.target.value)} aria-label="A specific session close"
                  title="Or a specific past close (16:00 ET) — to check what the plan for the following day would have been" />
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
            <span className="tq-cost muted">{date ? `as of the ${date} close → the plan for the next session (deterministic, free); always looks back 5/15/25 sessions from there` : "paste or drop an image anywhere · ~4 passes · ≈$0.20"}</span>
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
                (technique.trigger_tf, technique.structure_tfs).
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
      <div className="panel-body tq-table-wrap" style={{ padding: 0 }}>
        <table className="tq-table tq-history">
          <thead><tr><th>When</th><th>Symbol</th><th>TF</th><th>Verdict</th><th className="tq-col-opt">Conf</th><th className="tq-col-opt">Grounded</th><th>Outcome</th><th>Review</th><th className="tq-col-opt">Trigger</th><th>Run</th><th></th></tr></thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
                <td className="nowrap muted">{r.createdAt ? fmtDateTime(r.createdAt) : ""}</td>
                <td><b>{r.symbol}</b></td>
                <td className="nowrap">{r.primaryTf}{r.mode === "image_only" ? " (img)" : ""}{r.parentRunId ? " ↺" : ""}</td>
                <td><VerdictBadge run={r} /></td>
                <td className="tq-col-opt">{r.confidence !== null && r.confidence !== undefined ? r.confidence.toFixed(2) : "—"}</td>
                <td className="tq-col-opt">{r.grounded === null || r.grounded === undefined ? "—" : r.grounded ? "yes" : "no"}</td>
                <td><OutcomeBadge outcome={primaryOutcome(r)} /></td>
                <td><ReviewBadge last={r.lastReview ?? null} count={r.reviewCount ?? 0} /></td>
                <td className="muted tq-col-opt">{r.trigger}</td>
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

/** One-line switcher between the runs behind the armed plans — the fastest way
    to review tomorrow's fleet plan by plan without leaving the Analyse view. */
function ArmedRunStrip({ currentId }: { currentId?: string | null }) {
  const armed = useStore((s) => s.techniqueArmed);
  const openRun = useStore((s) => s.openTechniqueRun);
  if (armed.length < 2) return null;
  const idx = armed.findIndex((a) => a.runId === currentId);
  const go = (d: number) => {
    const n = armed[((idx < 0 ? 0 : idx) + d + armed.length) % armed.length];
    if (n) openRun(n.runId);
  };
  return (
    <div className="tq-armed-strip" role="navigation" aria-label="Armed plan runs">
      <span className="tq-armed-strip-label">Armed plans</span>
      <button className="icon-btn" onClick={() => go(-1)} aria-label="Previous armed plan" title="Previous armed plan">‹</button>
      <div className="chips">
        {armed.map((a) => (
          <button key={a.runId} className={`tq-scan-chip ${a.runId === currentId ? "working" : ""}`}
            onClick={() => openRun(a.runId)} title={`Open ${a.symbol}'s plan run${a.grade ? ` (grade ${a.grade})` : ""}`}>
            {a.symbol}{a.grade ? <span className="muted"> {a.grade}</span> : null}</button>
        ))}
      </div>
      <button className="icon-btn" onClick={() => go(1)} aria-label="Next armed plan" title="Next armed plan">›</button>
    </div>
  );
}

// --- right rail -----------------------------------------------------------------------

function ArmedPanel() {
  const armed = useStore((s) => s.techniqueArmed);
  const setArmed = useStore((s) => s.setTechniqueArmed);
  const setTab = useStore((s) => s.setTechniqueTab);
  const openRun = useStore((s) => s.openTechniqueRun);
  const currentRunId = useStore((s) => s.techniqueFocusRunId);
  useEffect(() => { api.techniqueArmed().then(setArmed).catch(() => undefined); }, [setArmed]);
  return (
    <div className="panel mb">
      <div className="panel-head">Armed <span className="sub">{armed.length}</span>
        <button className="link-btn" style={{ marginLeft: "auto" }} onClick={() => setTab("armed")}
          title="Live management view: fills, exits, P&L">dashboard</button></div>
      <div className="panel-body tq-setups">
        {armed.length === 0 && <div className="empty">nothing armed</div>}
        {armed.map((a) => (
          <button key={a.runId}
            className={`tq-setup-row ${a.status === "armed" ? "valid" : ""} ${a.runId === currentRunId ? "active" : ""}`}
            onClick={() => openRun(a.runId)}
            title="Open this plan's analysis run — the plan, chart and the model's 4-pass read">
            <b>{a.symbol}</b> <span>{a.grade ? `${a.grade} · ` : ""}{a.config.mode}{a.portfolio.kind === "live" ? " · REAL" : ""} · {a.status}</span>
            <span className="muted">{a.summary}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const ET_HM = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true });
const ET_MD = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
const ET_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

/** "1:57 PM ET", with "Aug 23, " in front when the run is not from today. */
function etStamp(iso: string | null | undefined, todayEt: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const day = ET_DAY.format(d);
  return `${day !== todayEt ? ET_MD.format(d) + ", " : ""}${ET_HM.format(d)} ET`;
}

function Rail({ rules, open, onToggle }: { rules: Record<string, string>; open: boolean; onToggle: () => void }) {
  const setups = useStore((s) => s.techniqueSetups);
  const setSetups = useStore((s) => s.setTechniqueSetups);
  const runs = useStore((s) => s.techniqueRuns);
  const openRun = useStore((s) => s.openTechniqueRun);
  const [rulesOpen, toggleRules] = useDisclosure("tq_rules", false);
  const [q, setQ] = useState("");
  useEffect(() => { api.techniqueSetups(50).then(setSetups).catch(() => undefined); }, [setSetups, runs.length]);
  const ruleList = useMemo(() => Object.entries(rules).filter(([id, t]) =>
    !q || id.toLowerCase().includes(q.toLowerCase()) || t.toLowerCase().includes(q.toLowerCase())), [rules, q]);
  const todayEt = ET_DAY.format(new Date());
  const todaysRuns = useMemo(() => runs
    .filter((r) => r.createdAt && ET_DAY.format(new Date(r.createdAt)) === todayEt)
    .slice(0, 15), [runs, todayEt]);
  const validSetups = useMemo(() => setups.filter((s: TechniqueSetup) => s.valid).slice(0, 8), [setups]);

  return (
    <RailShell open={open} onToggle={onToggle} label="Runs & rules">
      <ArmedPanel />
      {validSetups.length > 0 && (
        <div className="panel mb">
          <div className="panel-head">Valid setups <span className="sub">{validSetups.length}</span></div>
          <div className="panel-body tq-setups">
            {validSetups.map((s: TechniqueSetup) => (
              <button key={s.id} className="tq-setup-row valid" onClick={() => openRun(s.runId)}
                title="A run whose setup cleared every gate — click to open it">
                <b>{s.symbol}</b> <span>{s.setupType.replace(/_/g, " ")}</span>
                <span className="muted">entry {s.entry.toFixed(2)} · stop {s.stop.toFixed(2)} · R:R {s.riskReward.toFixed(1)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="panel mb">
        <div className="panel-head">Today's runs <span className="sub">{todaysRuns.length}</span></div>
        <div className="panel-body tq-setups">
          {todaysRuns.length === 0 && <div className="empty">none yet today — Run analysis, scan now, or promote from a sheet</div>}
          {todaysRuns.map((r) => (
            <button key={r.id} className={`tq-setup-row ${r.verdict === "setup" ? "valid" : ""}`} onClick={() => openRun(r.id)}
              title={`Open run ${r.id.slice(0, 8)}`}>
              <span className="muted tq-run-t">{etStamp(r.createdAt, todayEt)}</span>
              <b>{r.symbol}</b>
              {r.status === "running" ? <span className="muted"><Spinner /></span> : <VerdictBadge run={r} />}
              <span className="muted small">{r.trigger && r.trigger !== "manual" ? r.trigger : ""}</span>
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
    </RailShell>
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
  const rail = useRail("tq_rail");

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

  // While anything is running, poll status + the run list so the running pill,
  // History rows and the rail spinners come down on their own.
  const runningCount = status?.running?.length ?? 0;
  useEffect(() => {
    if (!runningCount) return;
    const tick = () => {
      refreshStatus();
      api.techniqueRuns(100).then(setRuns).catch(() => undefined);
    };
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, [runningCount > 0, refreshStatus, setRuns]);

  const rules = status?.rules ?? {};
  const shown = full && active && full.id === active.id ? { ...active, ...full } : active;
  const running = shown?.status === "running";

  const [scanConfirm, setScanConfirm] = useState(false);
  // survives F5: an in-flight or finished scan keeps its panel until dismissed
  const [scan, setScan] = useState<{ ids: string[]; done: boolean; armable?: boolean } | null>(() => {
    try {
      const s = JSON.parse(localStorage.getItem("zargar_tq_scan") || "null");
      if (s && Array.isArray(s.ids) && s.ids.length && Date.now() - (s.ts ?? 0) < 86_400_000)
        return { ids: s.ids, done: !!s.done, armable: !!s.armable };
    } catch { /* corrupt state — start clean */ }
    return null;
  });
  useEffect(() => {
    if (scan) localStorage.setItem("zargar_tq_scan", JSON.stringify({ ...scan, ts: Date.now() }));
    else localStorage.removeItem("zargar_tq_scan");
  }, [scan]);
  // No saved panel (e.g. it was lost before persistence existed)? Reconstruct it
  // from today's latest analyst-check batch: promote-triggered runs cluster
  // within minutes of each other, so the newest one defines the batch.
  useEffect(() => {
    if (scan || !runs.length) return;
    const todayEt = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
    const promos = runs.filter((r) => r.trigger === "promote" && r.createdAt
      && new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(r.createdAt)) === todayEt);
    if (promos.length < 2) return;
    const newest = Math.max(...promos.map((r) => new Date(r.createdAt!).getTime()));
    const batch = promos.filter((r) => newest - new Date(r.createdAt!).getTime() < 10 * 60_000);
    if (batch.length < 2) return;
    const ids = batch.map((r) => r.id).sort();
    if (localStorage.getItem("zargar_tq_scan_dismissed") === ids.join(",")) return;
    setScan({ ids, done: batch.every((r) => r.status !== "running"), armable: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan, runs.length]);
  // A batch can still be GROWING (checks launched one by one, e.g. via the API):
  // adopt newly appearing promote runs that cluster with the open panel, so the
  // count is the whole batch — not just the runs that existed at page load.
  useEffect(() => {
    if (!scan?.armable || !runs.length) return;
    const have = new Set(scan.ids);
    const times = runs.filter((r) => have.has(r.id) && r.createdAt)
      .map((r) => new Date(r.createdAt!).getTime());
    if (!times.length) return;
    const hi = Math.max(...times);
    const extra = runs.filter((r) => r.trigger === "promote" && !have.has(r.id) && r.createdAt
      && Math.abs(new Date(r.createdAt!).getTime() - hi) < 10 * 60_000).map((r) => r.id);
    if (extra.length) setScan((s) => (s ? { ...s, ids: [...s.ids, ...extra], done: false } : s));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, scan?.ids.join(",")]);
  const scanSymbols = status?.scanSymbols ?? [];
  // tonight's sheet, if one exists for the upcoming session: scan can analyst-check its graded rows
  const [sheetScan, setSheetScan] = useState<{ sweepId: string; planFor: string;
    freshness: "next" | "today" | "stale";
    rows: { symbol: string; session: string; grade: string }[] } | null | undefined>(undefined);
  const [scanSource, setScanSource] = useState<"sheet" | "watch">("sheet");
  const [scanGrades, setScanGrades] = useState<Set<string>>(new Set(["A"]));
  useEffect(() => {
    if (!scanConfirm) return;
    let stop = false;
    setSheetScan(undefined);
    (async () => {
      try {
        const sweeps = await api.techniqueSweeps();
        // newest prepared sheet, whatever its date — the dialog explains if it is stale
        const sheet = sweeps.find((s) => s.params?.kind === "next" && s.status === "done");
        if (!sheet) { if (!stop) { setSheetScan(null); setScanSource("watch"); } return; }
        const fullSheet = await api.techniqueSweep(sheet.id, true);
        const rows = (fullSheet.rows ?? []).map((r) => {
          const trig = (r.plan?.triggers ?? []).filter((t: any) => t.valid);
          if (!trig.length) return null;
          const best = trig.slice().sort((a: any, b: any) => (b.assessment?.score ?? 0) - (a.assessment?.score ?? 0))[0];
          return { symbol: r.symbol, session: r.session, grade: String(best.assessment?.grade ?? "C") };
        }).filter(Boolean) as { symbol: string; session: string; grade: string }[];
        if (!stop) {
          const planFor = String(sheet.params?.planFor ?? sheet.summary?.planFor ?? "");
          const et = new Intl.DateTimeFormat("en-CA", {
            timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", hour12: false,
          }).formatToParts(new Date());
          const get = (t: string) => et.find((p) => p.type === t)?.value ?? "";
          const todayEt = `${get("year")}-${get("month")}-${get("day")}`;
          const pastClose = Number(get("hour")) * 60 + Number(get("minute")) >= 16 * 60;
          const freshness: "next" | "today" | "stale" =
            planFor > todayEt ? "next" : planFor === todayEt && !pastClose ? "today" : "stale";
          setSheetScan(rows.length ? { sweepId: sheet.id, planFor, rows, freshness } : null);
          setScanSource(rows.length && freshness !== "stale" ? "sheet" : "watch");
        }
      } catch { if (!stop) { setSheetScan(null); setScanSource("watch"); } }
    })();
    return () => { stop = true; };
  }, [scanConfirm]);
  const gradeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const r of sheetScan?.rows ?? []) m[r.grade] = (m[r.grade] ?? 0) + 1;
    return m;
  }, [sheetScan]);
  const sheetPicked = (sheetScan?.rows ?? []).filter((r) => scanGrades.has(r.grade));
  const startScan = async () => {
    setScanConfirm(false);
    try {
      if (scanSource === "sheet" && sheetScan && sheetPicked.length) {
        const settled = await Promise.allSettled(sheetPicked.map((r) =>
          api.techniquePromote(sheetScan.sweepId, { symbol: r.symbol, session: r.session, withVision: true, wait: false })));
        const ids = settled.filter((s): s is PromiseFulfilledResult<TechniqueRun> => s.status === "fulfilled").map((s) => s.value.id);
        const failed = settled.length - ids.length;
        if (failed) toast("info", `${failed} symbol(s) could not start (daily cap / errors)`);
        if (ids.length) setScan({ ids, done: false, armable: true });
      } else {
        const r = await api.techniqueScan();
        if (r.skipped?.length) toast("info", `skipped ${r.skipped.map((s: any) => `${s.symbol} (${s.reason})`).join("; ")}`.slice(0, 160));
        if (r.started?.length) setScan({ ids: r.started, done: false });
      }
      refreshStatus();
      api.techniqueRuns(100).then(setRuns).catch(() => undefined);
    } catch (e: any) { toast("error", e.message); }
  };

  return (
    <div className="tq-page">
      <div className="tq-head">
        <div className="tabs tq-tabs" role="tablist" aria-label="EM Options Technique">
          {(["analyse", "validation", "chat", "history", "backtest", "armed"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {t === "analyse" ? "EM Options · Analyse" : t === "validation" ? "Validation" : t === "chat" ? "Chat" : t === "history" ? "History"
                : t === "backtest" ? "Backtest" : <>Armed{armedCount > 0 ? <span className="tq-tab-count">{armedCount}</span> : null}</>}
            </button>
          ))}
        </div>
        <StatusBar status={status} scanBusy={!!scan && !scan.done} onScan={() => setScanConfirm(true)} />
      </div>
      {scanConfirm && (
        <Modal title={<>⚡ Check &amp; arm <span className="muted">— the analyst read costs money; choose what it reads</span></>}
          onClose={() => setScanConfirm(false)}
          footer={<>
            <button className="ghost-btn" onClick={() => setScanConfirm(false)}>Cancel</button>
            <button className="primary-btn" disabled={scanSource === "sheet" ? (!sheetScan || !sheetPicked.length) : !scanSymbols.length}
              onClick={() => void startScan()}>
              {scanSource === "sheet"
                ? `Analyst-check ${sheetPicked.length} setup(s) · ≈$${(sheetPicked.length * 0.2).toFixed(2)}`
                : `Scan ${scanSymbols.length} symbol(s) · ≈$${(scanSymbols.length * 0.2).toFixed(2)}`}
            </button>
          </>}>
          <div className="tq-scan-dialog">
            {sheetScan === undefined && <div className="muted"><Spinner /> checking for tonight's sheet…</div>}
            {sheetScan && sheetScan.freshness !== "stale" && (
              <label className={`tq-arm-row ${scanSource === "sheet" ? "active" : ""}`}>
                <input type="radio" name="scan-src" checked={scanSource === "sheet"} onChange={() => setScanSource("sheet")} />
                <span>
                  <b>Prepared sheet — analyst-check the graded setups for {sheetScan.planFor}
                    {sheetScan.freshness === "today" ? " (TODAY)" : ""}</b>
                  {sheetScan.freshness === "today" && (
                    <span className="warn small">
                      ⚠ This sheet is for TODAY: arming from it covers only the rest of today's session —
                      triggers fire in the remaining prime window(s) and every plan expires flat at the
                      16:00 ET close. For tomorrow, build a fresh sheet in Validation after today's close.
                    </span>
                  )}
                  <span className="muted">
                    Runs the 4-pass analyst read on each symbol's own plan run — the same run you arm, so grade,
                    analyst verdict and the Arm button end up in one place. Pick which grades:
                  </span>
                  <span className="tq-scan-grades">
                    {["A", "B", "C"].map((g) => (
                      <label key={g} className={`tq-chipbtn ${scanGrades.has(g) ? "active" : ""}`} onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={scanGrades.has(g)}
                          onChange={(e) => setScanGrades((s) => { const n = new Set(s); e.target.checked ? n.add(g) : n.delete(g); return n; })} />
                        <span className={`tq-grade g${g}`}>{g}</span> {gradeCounts[g] ?? 0}
                      </label>
                    ))}
                  </span>
                </span>
              </label>
            )}
            {sheetScan && sheetScan.freshness === "stale" && (
              <div className="tq-scan-stale">
                <b>Prepared sheet for {sheetScan.planFor} — expired</b>
                <span className="muted">
                  That session is over, so its plans can't be analyst-checked or armed any more. Build a fresh
                  sheet for the next session (free, deterministic), then come back here.
                </span>
                <button className="ghost-btn" onClick={() => { setScanConfirm(false); setTab("validation"); }}>
                  Prepare the next session in Validation →
                </button>
              </div>
            )}
            {sheetScan === null && (
              <div className="muted small">
                No prepared sheet found — build one first in Validation → "Prepare the next session"
                (free, deterministic) to analyst-check graded setups instead of a flat watch list.
              </div>
            )}
            <label className={`tq-arm-row ${scanSource === "watch" ? "active" : ""}`}>
              <input type="radio" name="scan-src" checked={scanSource === "watch"} onChange={() => setScanSource("watch")} />
              <span>
                <b>Watch list — a live read of {scanSymbols.join(", ") || "—"}</b>
                <span className="muted">
                  "Is anything tradeable right now?" Full analysis per symbol, not tied to the sheet. Results
                  land below and in History (trigger "scan"). List editable in Settings → technique.scan.symbols.
                </span>
              </span>
            </label>
            <div className="muted small">
              ≈$0.20 and 30–60 s per symbol, run in parallel; counts against the daily cap
              ({status ? `${status.runsToday}/${status.maxRunsPerDay} used` : "…"}).
            </div>
          </div>
        </Modal>
      )}
      {scan && (
        <ScanPanel ids={scan.ids} armable={scan.armable}
          onDone={() => { setScan((s) => (s ? { ...s, done: true } : s)); refreshStatus(); }}
          onClose={() => { localStorage.setItem("zargar_tq_scan_dismissed", scan.ids.slice().sort().join(",")); setScan(null); }}
          onOpen={(id) => { setFocusRun(id); setTab("analyse"); }}
          onArmedAll={() => setTab("armed")} />
      )}
      {tab === "chat" ? (
        <ChatPanel />
      ) : tab === "validation" ? (
        <ValidationTab llmAvailable={status?.llmAvailable ?? true} sweepVersion={status?.sweepVersion ?? null} />
      ) : tab === "armed" ? (
        <ArmedTab />
      ) : (
        <div className={rail.gridClass}>
          <div className="tq-main">
            {tab === "analyse" && (
              <>
                <AnalyseForm disabled={!status?.llmAvailable} running={running}
                  onStarted={(r) => { setFocusRun(r.id); }} />
                {!status?.llmAvailable && status && (
                  <EmptyState title="No API key" hint="Set ZARGAR_ANTHROPIC_API_KEY in backend/.env to run analyses." />
                )}
                <ArmedRunStrip currentId={shown?.id} />
                {shown && running && <LiveRun run={shown} />}
                {shown && !running && shown.mode === "plan" && <PlanCard run={shown} rules={rules} onRefresh={() => setRefreshKey((k) => k + 1)} />}
                {shown && !running && shown.mode !== "plan" && <RunResult run={shown} rules={rules} onRefresh={() => setRefreshKey((k) => k + 1)} />}
                {!shown && <EmptyState title="No runs yet" hint="Enter a symbol and run the pipeline, or paste a chart screenshot." />}
              </>
            )}
            {tab === "history" && <HistoryTab onOpen={(id) => { setFocusRun(id); setTab("analyse"); }} />}
            {tab === "backtest" && <BacktestTab />}
          </div>
          <Rail rules={rules} open={rail.open} onToggle={rail.toggle} />
        </div>
      )}
    </div>
  );
}
