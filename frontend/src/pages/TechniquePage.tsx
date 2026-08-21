import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { ChatPanel } from "../components/technique/ChatPanel";
import { LiveRun } from "../components/technique/LiveRun";
import { RuleChips, RunResult, VerdictBadge } from "../components/technique/RunResult";
import { EmptyState, Spinner } from "../components/ui";
import { IconX } from "../components/icons";
import { SymbolSearch } from "../components/SymbolSearch";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useStore } from "../store";
import type { TechniqueRun, TechniqueSetup, TechniqueStatus } from "../types";

const TFS = ["1m", "5m", "15m"];

/** Local `datetime-local` string for a Date. */
function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Most recent completed trading day before `from`: Mon->Fri, Sat->Fri, Sun->Fri.
 *  Set to 16:00 local so the whole session is inside the window. */
function previousBusinessDay(from = new Date(), back = 1): Date {
  const d = new Date(from);
  d.setHours(16, 0, 0, 0);
  for (let i = 0; i < back; i++) {
    do {
      d.setDate(d.getDate() - 1);
    } while (d.getDay() === 0 || d.getDay() === 6);
  }
  return d;
}

function readFileAsDataUrl(f: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result));
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}

// --- status header -------------------------------------------------------------------

function StatusBar({ status, onScan }: { status: TechniqueStatus | null; onScan: () => void }) {
  const setPage = useStore((s) => s.setPage);
  if (!status) return <div className="tq-status muted"><Spinner /> loading status…</div>;
  return (
    <div className="tq-status">
      <span className={`status-pill ${status.llmAvailable ? "ok" : "bad"}`}>
        {status.llmAvailable ? `${status.model} · ${status.effort}` : "no API key"}
      </span>
      <span className="status-pill">thinking: {status.thinkingDisplay}</span>
      <span className={`status-pill ${status.optionsAvailable ? "ok" : ""}`}>
        options {status.optionsAvailable
          ? `${(status.optionsProvider ?? "cboe").toUpperCase()}${status.optionsProvider === "cboe" ? " (free, delayed)" : ""}`
          : "off"}
      </span>
      <span className="status-pill">runs today {status.runsToday}/{status.maxRunsPerDay}</span>
      <span className={`status-pill ${status.scanEnabled ? "ok" : ""}`}>
        scan {status.scanEnabled ? `on · ${status.scanSymbols.join(" ")}` : "off"}
      </span>
      {status.running.length > 0 && <span className="status-pill ok"><Spinner /> {status.running.length} running</span>}
      <button className="link-btn" onClick={onScan}>scan watch symbols now</button>
      <button className="link-btn" onClick={() => setPage("settings")}>settings</button>
    </div>
  );
}

// --- analyse form ---------------------------------------------------------------------

function AnalyseForm({ onStarted, disabled }: { onStarted: (run: TechniqueRun) => void; disabled: boolean }) {
  const defaultTf = useStore((s) => s.settings["technique.default_tf"] ?? "1m");
  const activeSymbol = useStore((s) => s.activeSymbol);
  const toast = useStore((s) => s.toast);
  const [symbol, setSymbol] = useState(activeSymbol || "SPY");
  const [tf, setTf] = useState<string>(defaultTf);
  const [asOf, setAsOf] = useState<string>("");
  const [note, setNote] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setTf(defaultTf); }, [defaultTf]);

  const addFile = useCallback(async (f: File | undefined) => {
    if (f && f.type.startsWith("image/")) setImage(await readFileAsDataUrl(f));
  }, []);
  const onPaste = (e: ClipboardEvent) => {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) { e.preventDefault(); addFile(item.getAsFile() ?? undefined); return; }
    }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); addFile(e.dataTransfer.files[0]); };

  const run = async () => {
    setBusy(true);
    try {
      const body: any = { symbol: symbol.trim().toUpperCase(), tf, note };
      if (asOf) body.asOf = new Date(asOf).getTime();
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

  return (
    <div className="panel tq-form" onPaste={onPaste} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      <div className="panel-head">Analyse <span className="sub">symbol + period, or paste a chart screenshot</span></div>
      <div className="panel-body tq-form-body">
        <div className="field"><span>Symbol</span>
          <div className="tq-symbol-row">
            <input className="tq-symbol-input" value={symbol} spellCheck={false}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="SPY" />
            <SymbolSearch compact placeholder="search by name or ticker…"
              onPick={(h) => setSymbol(h.symbol)} />
          </div>
        </div>
        <label className="field"><span>Primary timeframe</span>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
        <div className="field"><span>As of <small className="muted">(blank = now; 1m history ≈ 20 days)</small></span>
          <div className="tq-asof-row">
            <input type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
            <div className="tq-presets">
              <button type="button" className={!asOf ? "active" : ""} onClick={() => setAsOf("")}>Now</button>
              <button type="button" onClick={() => setAsOf(toLocalInput(previousBusinessDay()))}
                title="Most recent completed trading day (skips weekends)">Prev session</button>
              <button type="button" onClick={() => setAsOf(toLocalInput(previousBusinessDay(new Date(), 2)))}>−2 days</button>
              <button type="button" onClick={() => setAsOf(toLocalInput(previousBusinessDay(new Date(), 5)))}>−1 week</button>
            </div>
          </div>
        </div>
        <label className="field tq-note"><span>Note to the analyst <small className="muted">(optional)</small></span>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. focus on the 10:30 rejection" /></label>
        <div className="field tq-drop">
          <span>Chart image <small className="muted">(paste / drop; with a symbol it is an extra view, alone it is image-only)</small></span>
          {image ? (
            <span className="chat-attach-item big"><img src={image} alt="chart" /><button onClick={() => setImage(null)} aria-label="remove"><IconX size={10} /></button></span>
          ) : (
            <label className="tq-dropzone">drop or paste an image here, or <u>browse</u>
              <input type="file" accept="image/*" style={{ display: "none" }} onChange={(e) => addFile(e.target.files?.[0])} /></label>
          )}
        </div>
        <div className="tq-form-actions">
          <button className="primary-btn" disabled={busy || disabled || (!symbol.trim() && !image)} onClick={run}>
            {busy ? "Starting…" : "Run analysis"}
          </button>
          <span className="muted">~4 model passes · ≈$0.20 · 1–3 min</span>
        </div>
      </div>
    </div>
  );
}

// --- history -----------------------------------------------------------------------------

function HistoryTab({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useStore((s) => s.techniqueRuns);
  const setRuns = useStore((s) => s.setTechniqueRuns);
  const [filter, setFilter] = useState("");
  useEffect(() => { api.techniqueRuns(200).then(setRuns).catch(() => undefined); }, [setRuns]);
  const visible = useMemo(() => runs.filter((r) => !filter || r.symbol.includes(filter.toUpperCase())), [runs, filter]);
  return (
    <div className="panel">
      <div className="panel-head">Run history <span className="sub">{runs.length} runs</span>
        <input className="tq-filter" placeholder="filter symbol" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="tq-table tq-history">
          <thead><tr><th>When</th><th>Symbol</th><th>TF</th><th>Verdict</th><th>Conf</th><th>Grounded</th><th>Trigger</th><th>Tokens</th><th></th></tr></thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
                <td>{r.createdAt ? fmtDateTime(r.createdAt) : ""}</td>
                <td><b>{r.symbol}</b></td>
                <td>{r.primaryTf}{r.mode === "image_only" ? " (img)" : ""}</td>
                <td><VerdictBadge run={r} /></td>
                <td>{r.confidence !== null && r.confidence !== undefined ? r.confidence.toFixed(2) : "—"}</td>
                <td>{r.grounded === null || r.grounded === undefined ? "—" : r.grounded ? "yes" : "no"}</td>
                <td className="muted">{r.trigger}</td>
                <td className="muted">{(r.usage as any)?.output ?? ""}</td>
                <td><button className="link-btn" onClick={(e) => { e.stopPropagation(); if (r.threadId) useStore.getState().openTechniqueChat(r.threadId); }}>chat</button></td>
              </tr>
            ))}
            {visible.length === 0 && <tr><td colSpan={9}><div className="empty">No runs yet.</div></td></tr>}
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
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const run = async () => {
    setBusy(true);
    try { setRes(await api.techniqueBacktest({ symbol: symbol.toUpperCase(), tf, days, horizonBars: horizon })); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(false); }
  };
  const s = res?.summary;
  return (
    <div>
      <div className="panel mb">
        <div className="panel-head">Backtest <span className="sub">deterministic replay — no model calls, free</span></div>
        <div className="panel-body tq-form-body">
          <label className="field"><span>Symbol</span><input value={symbol} onChange={(e) => setSymbol(e.target.value)} /></label>
          <label className="field"><span>Timeframe</span>
            <select value={tf} onChange={(e) => setTf(e.target.value)}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label className="field"><span>Days back <small className="muted">(1m ≤ 20, 5m ≤ 59)</small></span>
            <input type="number" value={days} min={1} max={59} onChange={(e) => setDays(Number(e.target.value))} /></label>
          <label className="field"><span>Horizon (bars)</span>
            <input type="number" value={horizon} min={10} max={300} onChange={(e) => setHorizon(Number(e.target.value))} /></label>
          <div className="tq-form-actions"><button className="primary-btn" disabled={busy} onClick={run}>{busy ? "Replaying…" : "Run backtest"}</button></div>
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

function Rail({ rules }: { rules: Record<string, string> }) {
  const setups = useStore((s) => s.techniqueSetups);
  const setSetups = useStore((s) => s.setTechniqueSetups);
  const openRun = useStore((s) => s.openTechniqueRun);
  const [q, setQ] = useState("");
  useEffect(() => { api.techniqueSetups(50).then(setSetups).catch(() => undefined); }, [setSetups]);
  const ruleList = useMemo(() => Object.entries(rules).filter(([id, t]) =>
    !q || id.toLowerCase().includes(q.toLowerCase()) || t.toLowerCase().includes(q.toLowerCase())), [rules, q]);
  return (
    <div className="tq-rail">
      <div className="panel mb">
        <div className="panel-head">Setups <span className="sub">latest emitted</span></div>
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
        <div className="panel-head">Rulebook <input className="tq-filter" placeholder="search" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="panel-body tq-rules">
          {ruleList.map(([id, t]) => <div key={id} className="tq-rule"><span className="tq-chip">{id}</span><span>{t}</span></div>)}
        </div>
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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [full, setFull] = useState<TechniqueRun | null>(null);
  const fetchedFor = useRef<string | null>(null);

  const refreshStatus = useCallback(() => { api.techniqueStatus().then(setStatus).catch(() => undefined); }, []);
  useEffect(() => { refreshStatus(); api.techniqueRuns(100).then(setRuns).catch(() => undefined); }, [refreshStatus, setRuns]);
  useEffect(() => { if (focusId) { setActiveId(focusId); setTab("analyse"); } }, [focusId, setTab]);

  // the run we show: explicit focus, else the most recent
  const active = useMemo(() => runs.find((r) => r.id === activeId) ?? runs[0] ?? null, [runs, activeId]);

  // a client that connects mid-run has no pass history: seed it from the server
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

  // fetch the full row (facts, passes) once a run finishes
  useEffect(() => {
    if (!active || active.status === "running") { return; }
    const key = `${active.id}:${active.status}`;
    if (fetchedFor.current === key) return;
    fetchedFor.current = key;
    api.techniqueRun(active.id).then((r) => { setFull(r); refreshStatus(); }).catch((e) => toast("error", e.message));
  }, [active, refreshStatus, toast]);

  useEffect(() => { refreshStatus(); }, [runs.length, refreshStatus]);

  const rules = status?.rules ?? {};
  const shown = full && active && full.id === active.id ? { ...active, ...full } : active;

  return (
    <div className="tq-page">
      <div className="tq-title-row">
        <h2 className="page-title">Technique <span className="muted">· EnhancedMarket (Day Trading 101)</span></h2>
        <StatusBar status={status} onScan={() => api.techniqueScan().then(() => refreshStatus()).catch((e) => toast("error", e.message))} />
      </div>
      <div className="tabs tq-tabs">
        {(["analyse", "chat", "history", "backtest"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "analyse" ? "Analyse" : t === "chat" ? "Chat" : t === "history" ? "History" : "Backtest"}
          </button>
        ))}
      </div>
      {tab === "chat" ? (
        <ChatPanel />
      ) : (
        <div className="tq-grid">
          <div className="tq-main">
            {tab === "analyse" && (
              <>
                <AnalyseForm disabled={!status?.llmAvailable} onStarted={(r) => { setActiveId(r.id); }} />
                {!status?.llmAvailable && status && (
                  <EmptyState title="No API key" hint="Set ZARGAR_ANTHROPIC_API_KEY in backend/.env to run analyses." />
                )}
                {shown && shown.status === "running" && <LiveRun run={shown} />}
                {shown && shown.status !== "running" && <RunResult run={shown} rules={rules} />}
                {!shown && <EmptyState title="No runs yet" hint="Enter a symbol and run the pipeline, or paste a chart screenshot." />}
              </>
            )}
            {tab === "history" && <HistoryTab onOpen={(id) => { setActiveId(id); setTab("analyse"); }} />}
            {tab === "backtest" && <BacktestTab />}
          </div>
          <Rail rules={rules} />
        </div>
      )}
    </div>
  );
}
