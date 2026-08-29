import { useEffect, useRef, useState } from "react";
import { CopyChip } from "../components/CopyChip";
import { IconCheck, IconClock, IconHalf, IconX } from "../components/icons";
import { ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney, timeUntil } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { onAnalystStep } from "../lib/ws";
import { useStore } from "../store";
import type { AnalystRun, AnalystStep, Proposal, RawContentItem, Signal, SourceScorecard } from "../types";
import { useViewport } from "../lib/viewport";
import { Sheet } from "../components/Sheet";

/* The Tips page (redesigned 2026-08-28): the composer is the product — paste
   text or a screenshot, the app extracts the trade AND the source, verifies it
   against the live market and shows what both shadow books did with it.
   Tabs: New tip · Tips · Sources · Inbox; pending proposals ride above the
   tabs as an attention strip (they expire in minutes). */

type Tab = "compose" | "tips" | "sources" | "analyst" | "inbox";
const TABS: Tab[] = ["tips", "compose", "analyst", "inbox", "sources"];

export function InboxPage() {
  const pageTab = useStore((s) => s.pageTab);
  const setPageTab = useStore((s) => s.setPageTab);
  const tab: Tab = (TABS as string[]).includes(pageTab) ? (pageTab as Tab) : "tips";
  const setTab = (t: Tab) => setPageTab(t);
  const proposals = useStore((s) => s.proposals);
  const signals = useStore((s) => s.signals);
  return (
    <div className="tips-page">
      <div className="tips-head">
        <h2 className="page-title">Tips</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "tips"} className={tab === "tips" ? "active" : ""}
            onClick={() => setTab("tips")}>Tips{signals.length ? ` · ${signals.length}` : ""}</button>
          <button role="tab" aria-selected={tab === "compose"} className={tab === "compose" ? "active" : ""}
            onClick={() => setTab("compose")}>New tip</button>
          <button role="tab" aria-selected={tab === "analyst"} className={tab === "analyst" ? "active" : ""}
            onClick={() => setTab("analyst")}>Analyst</button>
          <button role="tab" aria-selected={tab === "inbox"} className={tab === "inbox" ? "active" : ""}
            onClick={() => setTab("inbox")}>Inbox</button>
          {/* configuration, not desk work — the gear is the only differentiator */}
          <button role="tab" aria-selected={tab === "sources"}
            className={`tab-config ${tab === "sources" ? "active" : ""}`}
            onClick={() => setTab("sources")}
            title="Configure where tips come from (Discord sources, scorecards)">
            ⚙<span className="tab-config-label"> Sources</span>
          </button>
        </div>
        <span className="muted tips-head-sub">every source runs two shadow books: buy at tip time vs wait for the level</span>
      </div>

      {proposals.length > 0 && (
        <div className="panel mb">
          <div className="panel-head">
            Awaiting your decision
            <span className="sub">{proposals.length} proposal{proposals.length === 1 ? "" : "s"} — they expire</span>
          </div>
          <div className="panel-body">
            {proposals.map((p) => <ProposalCard key={p.id} p={p} />)}
          </div>
        </div>
      )}

      {tab === "compose" && <ComposeTab goTips={() => setTab("tips")} />}
      {tab === "tips" && <TipsTab />}
      {tab === "sources" && <SourcesTab />}
      {tab === "analyst" && <AnalystTab />}
      {tab === "inbox" && <InboxTab />}
    </div>
  );
}

// Less is more (user, 2026-08-29): only the statuses that can still ACT keep a
// color; dead/informational rows read as quiet gray text, not alarm pills.
function statusPill(status: string): string {
  if (status === "verified" || status === "proposed") return "ok";
  return "dim";
}

const STATUS_LABEL: Record<string, string> = {
  verification_failed: "failed", verified: "verified", proposed: "proposed",
  parked: "parked", shadow: "shadow", expired: "expired", replayed: "replayed",
};
const statusLabel = (s: string) => STATUS_LABEL[s] ?? s.replace(/_/g, " ");

function contractLabel(s: Signal): string | null {
  if (s.instrument === "call" || s.instrument === "put") {
    const k = s.strike ? `${s.strike}${s.instrument === "call" ? "C" : "P"}` : s.instrument;
    const exp = s.expiry ? ` ${s.expiry.slice(5)}` : s.dteHintDays ? ` ~${s.dteHintDays}d` : "";
    return `${k}${exp}`;
  }
  if (s.instrument === "shares") return "shares";
  return null;
}

function vehicleChip(s: Signal) {
  const expr = (s as any).extraction?.shadowExpression;
  if (!expr) return null;
  if (expr.vehicle === "option") {
    return <span className="muted" title={`Immediate book bought ${expr.contracts ?? "?"}× ${expr.display ?? expr.contract}`}>
      {expr.display ?? "option"}{expr.contracts ? ` ×${expr.contracts}` : ""}</span>;
  }
  if (expr.fallback) {
    return <span className="muted" title={`Wanted the option but: ${expr.fallback}`}>shares (fallback)</span>;
  }
  return null;
}

function ArmButton({ s }: { s: Signal }) {
  const toast = useStore((st) => st.toast);
  const [busy, setBusy] = useState(false);
  if (s.status !== "verified" && s.status !== "parked" && s.status !== "shadow") return null;
  const arm = async () => {
    setBusy(true);
    try {
      const snap = await api.armTipSignal(s.id, { mode: "alert" });
      toast("success", `Armed ${s.ticker} for ${snap.planFor} (alert mode) — see the Armed page`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="link-btn" disabled={busy} onClick={arm}
      title="Arm this tip as a level-touch plan (alert mode — watches the level, no orders). Switch modes on the Armed page.">
      {busy ? "arming…" : "arm"}
    </button>
  );
}

/** "analysis" link on a tip row → the tip's analyst run in the Analyst tab. */
function AnalystLink({ s }: { s: Signal }) {
  const openAnalystRun = useStore((st) => st.openAnalystRun);
  const runId = (s as any).extraction?.analyst?.runId;
  if (!runId) return null;
  return (
    <button className="link-btn" onClick={() => openAnalystRun(runId)}
      title="open this tip's analyst run — the full play-by-play">
      analysis
    </button>
  );
}

/* ---------------------------------------------------------------- compose */

function ComposeTab({ goTips }: { goTips: () => void }) {
  const toast = useStore((s) => s.toast);
  const [text, setText] = useState("");
  const [source, setSource] = useState("");          // empty = auto-detect
  const [image, setImage] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const namesState = useAsync(() => api.sourceNames(), []);
  const names = namesState.data ?? [];

  const readFile = (f: File) => {
    const reader = new FileReader();
    reader.onload = () => setImage(String(reader.result));
    reader.readAsDataURL(f);
  };

  const onPaste = (e: React.ClipboardEvent) => {
    for (const item of Array.from(e.clipboardData?.items ?? [])) {
      if (item.type.startsWith("image/")) {
        const f = item.getAsFile();
        if (f) { readFile(f); e.preventDefault(); return; }
      }
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer?.files?.[0];
    if (f && f.type.startsWith("image/")) readFile(f);
  };

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const out = await api.ingestManual(text, source.trim() || "auto", "manual paste", image ?? undefined);
      setResult(out);
      const n = out.signals?.length ?? 0;
      if (out.note) toast("info", out.note);
      else if (n === 0) toast("info", "No actionable tip found in that content");
      else {
        toast("success", `Extracted ${n} tip${n === 1 ? "" : "s"} from ${out.source ?? "content"}`);
        setText("");
        setImage(null);
      }
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tips-compose">
      <div className="panel">
        <div className="panel-head">
          New tip
          <span className="sub">paste the message or a screenshot of your own chat client — nothing is scraped</span>
        </div>
        <div className="panel-body">
          <div className={`tips-drop ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}>
            <textarea ref={boxRef} rows={7} value={text} onChange={(e) => setText(e.target.value)}
              onPaste={onPaste}
              placeholder={'"NVDA 180c 9/19" · "buying AAPL, entry $230, stop $220, target $260" · or just Ctrl+V a screenshot'} />
            {image && (
              <div className="tips-shot">
                <img src={image} alt="tip screenshot" />
                <button className="link-btn danger" onClick={() => setImage(null)}>remove</button>
              </div>
            )}
            <div className="tips-drop-hint">Ctrl+V pastes a screenshot straight from the clipboard · drag &amp; drop works too</div>
          </div>

          <div className="tips-compose-row">
            <label className="field" style={{ flex: 1, marginBottom: 0 }}>
              <span>Source — who said it (their track record depends on this)</span>
              <input list="tip-source-names" value={source} placeholder="Auto-detect from the content"
                onChange={(e) => setSource(e.target.value)} />
              <datalist id="tip-source-names">
                {names.map((n) => <option key={n} value={n} />)}
              </datalist>
            </label>
            <label className="link-btn" style={{ cursor: "pointer", paddingBottom: 9 }}>
              attach image…
              <input type="file" accept="image/*" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ""; }} />
            </label>
            <button className="primary-btn" disabled={busy || (!text.trim() && !image)} onClick={run}>
              {busy ? "Reading…" : "Extract & verify"}
            </button>
          </div>
          {!source.trim() && (
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              Left on auto: the channel name, poster's handle or newsletter masthead visible in the
              content becomes the source, matched against the {names.length || "known"} source{names.length === 1 ? "" : "s"} you already track.
            </div>
          )}
        </div>
      </div>

      {result && <ExtractionOutcome out={result} goTips={goTips} />}
    </div>
  );
}

function ExtractionOutcome({ out, goTips }: { out: any; goTips: () => void }) {
  if (out.note) {
    return (
      <div className="panel mb">
        <div className="panel-body muted">
          {out.note}
          {out.contentId && <> <CopyChip value={out.contentId}
            title={`extraction ${out.contentId} — click to copy; quote this id to review the run`} /></>}
        </div>
      </div>
    );
  }
  const sigs: any[] = out.signals ?? [];
  return (
    <div className="panel mb">
      <div className="panel-head">
        What the app read
        {out.contentId && <CopyChip value={out.contentId}
          title={`extraction ${out.contentId} — click to copy; quote this id to review how this content was read`} />}
        {out.source && (
          <span className="sub">
            source: <b>{out.source}</b>{out.sourceDetected ? " (detected from the content)" : ""}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button className="link-btn" onClick={goTips}>all tips →</button>
      </div>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {sigs.length === 0 && (
          <div className="muted">No actionable tip in that content — recaps, marketing and commentary
            are ignored on purpose.</div>
        )}
        {sigs.map((item, i) => <TipResultCard key={i} item={item} />)}
      </div>
    </div>
  );
}

function TipResultCard({ item }: { item: any }) {
  const s: Signal = item.signal;
  const failed = (s.verification?.checks ?? []).filter((c) => !c.passed);
  const contract = contractLabel(s);
  if (item.duplicateOf) {
    return (
      <div className="tip-card">
        <div className="tip-card-head">
          <span className="tip-sym">{s.ticker}</span>
          <span className="status-pill dim">seen ×{s.seenCount}</span>
          <CopyChip value={s.id} title={`tip ${s.id} — click to copy`} />
          <span className="muted">same tip already tracked — repeat mentions are counted, not re-traded</span>
        </div>
      </div>
    );
  }
  return (
    <div className="tip-card">
      <div className="tip-card-head">
        <span className="tip-sym">{s.ticker}</span>
        <span className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</span>
        {contract && <span className="status-pill dim">{contract}</span>}
        <span className={`status-pill ${statusPill(s.status)}`}>{s.status.replace("_", " ")}</span>
        {vehicleChip(s)}
        <FlowChip sym={s.ticker} />
        <CopyChip value={s.id}
          title={`tip ${s.id} — click to copy; quote this id to review the extract & verify of this tip`} />
        <span style={{ flex: 1 }} />
        <ArmButton s={s} />
      </div>
      <div className="tip-prices">
        <span><b>entry</b> {s.entryPrice ? fmtMoney(s.entryPrice) : "—"}</span>
        <span><b>stop</b> {s.stopPrice ? fmtMoney(s.stopPrice) : "—"}</span>
        <span><b>target</b> {s.targetPrice ? fmtMoney(s.targetPrice) : "—"}</span>
        {s.horizonSessions ? <span><b>horizon</b> {s.horizonSessions} sessions</span> : null}
        {s.catalyst ? <span><b>catalyst</b> {s.catalyst}</span> : null}
      </div>
      {s.thesisSummary && <div className="muted" style={{ fontSize: 12 }}>{s.thesisSummary}</div>}
      {s.status === "parked" && (
        <div className="muted" style={{ fontSize: 12 }}>
          Parked: price has moved away from the stated entry — the app watches for it to come back
          (arm it, or the morning sweep arms it in shadow automatically).
        </div>
      )}
      {s.status === "shadow" && (
        <div className="muted" style={{ fontSize: 12 }}>
          Shadow only: a directional lean, not an explicit call — both shadow books trade it and
          the source's scorecard learns from it, but it never becomes a proposal.
        </div>
      )}
      {s.status === "replayed" && <ReplayBlock s={s} />}
      <AnalystBlock s={s} />
      {s.verification?.flowContext && <div className="muted" style={{ fontSize: 12 }}>{s.verification.flowContext}</div>}
      {s.verification?.calendarContext && <div className="muted" style={{ fontSize: 12 }}>⚠ {s.verification.calendarContext}</div>}
      {failed.length > 0 && (
        <ul className="check-list">
          {failed.map((c) => (
            <li key={c.name} className="check-item fail">
              <b>{c.name.replace(/_/g, " ")}</b>{c.detail ? ` — ${c.detail}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A stale tip's history replay: what both books WOULD have done had it
    arrived on time (extraction.replay, built by techniques/tip/replay.py). */
function ReplayBlock({ s }: { s: Signal }) {
  const x = (s as any).extraction ?? {};
  const r = x.replay;
  const age = x.ageHours != null ? `${Math.round(x.ageHours / 24)} day(s) old` : "stale";
  if (!r?.ok) {
    return (
      <div className="muted" style={{ fontSize: 12 }}>
        This content is {age} — too old to trade{r?.note ? `, and the replay could not run (${r.note})` : ""}.
      </div>
    );
  }
  const a = r.armed ?? {};
  const im = r.immediate ?? {};
  return (
    <div style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
      <span className="muted">This content is {age} — replayed on history instead of traded
        (tip-time price {fmtMoney(r.referencePrice)}, now {fmtMoney(r.lastPrice)}):</span>
      <span>
        <b>Waiting for the level</b> ({a.entry ? fmtMoney(a.entry) : "—"}):{" "}
        {a.filled
          ? <span className={(a.rMultiple ?? 0) >= 0 ? "pos" : "neg"}>
              filled → {String(a.outcome)} at {a.rMultiple > 0 ? "+" : ""}{a.rMultiple}R
              {a.mfeR ? ` (best ${a.mfeR}R)` : ""}</span>
          : <span className="muted">never filled</span>}
      </span>
      <span>
        <b>Buying at tip time</b>:{" "}
        <span className={(im.pnlPct ?? 0) >= 0 ? "pos" : "neg"}>
          {im.pnlPct > 0 ? "+" : ""}{im.pnlPct}% ({im.reason})</span>
        {im.toTodayPct != null && <span className="muted"> · held to today {im.toTodayPct > 0 ? "+" : ""}{im.toTodayPct}%</span>}
      </span>
    </div>
  );
}

/** The tips analyst's advisory opinion (extraction.analyst): verdict + the
    expression it would buy + rationale. Never a gate — a second pair of eyes. */
function AnalystBlock({ s }: { s: Signal }) {
  const a = (s as any).extraction?.analyst;
  if (!a) return null;
  const cls = a.verdict === "take" ? "ok" : a.verdict === "watch" ? "wait" : "bad";
  const suggest = a.contract_label || a.contract
    ? `${a.contract_label ?? a.contract}${a.limit_price ? ` @ ≤${a.limit_price}` : ""}${a.quantity ? ` ×${a.quantity}` : ""}`
    : a.instrument === "shares" && a.quantity ? `${a.quantity} shares${a.limit_price ? ` @ ≤${a.limit_price}` : ""}` : null;
  return (
    <div style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
      <span>
        <span className={`status-pill ${cls}`}
          title={`Analyst confidence ${Math.round((a.confidence ?? 0.5) * 100)}% · ${(a.toolsUsed ?? []).length} tool call(s)`}>
          analyst: {a.verdict}
        </span>
        {suggest && <> <b>{suggest}</b></>}
      </span>
      {a.rationale && <span className="muted">{a.rationale}</span>}
      {a.invalidation && <span className="muted">Invalid if: {a.invalidation}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- proposals */

function ProposalCard({ p }: { p: Proposal }) {
  const toast = useStore((s) => s.toast);
  const [busy, setBusy] = useState(false);
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const act = async (fn: () => Promise<any>, label: string) => {
    setBusy(true);
    try {
      await fn();
      toast("success", label);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  const checks = p.context?.verification?.checks ?? [];
  const sizing = p.context?.sizing;
  const vehicle = p.context?.vehicle;
  const analyst = p.context?.analyst;
  const openAnalystRun = useStore((s) => s.openAnalystRun);
  const isOpt = p.secType === "OPT";
  return (
    <div className="proposal-card">
      <div className="head">
        <span className="sym">{vehicle?.underlying ?? p.symbol}</span>
        <span className={p.side === "BUY" ? "pos" : "neg"}>
          <b>{p.side}</b> {p.qty} × {isOpt ? (vehicle?.display ?? p.symbol) : "shares"} @ {p.orderType} {p.limitPrice ? fmtMoney(p.limitPrice) : ""}
        </span>
        {isOpt && vehicle?.optionType && (
          <span className={`status-pill ${vehicle.optionType === "call" ? "ok" : "bad"}`}>
            {vehicle.optionType === "call" ? "call · bullish" : "put · bearish"}
          </span>
        )}
        {vehicle?.substituted && (
          <span className="status-pill bad" title="The proposed contract differs from the one the tip/analyst named">
            substituted: {vehicle.substituted}
          </span>
        )}
        <span className="ttl"><IconClock size={11} /> {timeUntil(p.expiresAt)}</span>
        {p.signalId && <CopyChip value={p.signalId}
          title={`tip ${p.signalId} — click to copy; quote this id to review the tip behind this proposal`} />}
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        {p.context?.sourceName ?? "unknown source"} · {p.context?.confidence ?? "?"}
        {sizing?.budget != null && <> · ${fmtMoney(sizing.budget, 0)} per-tip budget</>}
        {p.bracket?.take_profit && <> · target {fmtMoney(p.bracket.take_profit)}</>}
        {p.bracket?.stop_loss && <> · stop {fmtMoney(p.bracket.stop_loss)}</>}
      </div>
      {p.rationale && <div style={{ margin: "6px 0", fontStyle: "italic" }}>{p.rationale}</div>}
      {analyst?.verdict && (
        <div style={{ fontSize: 12, margin: "4px 0" }}>
          <span className={`status-pill ${analyst.verdict === "take" ? "ok" : analyst.verdict === "watch" ? "wait" : "bad"}`}>
            analyst: {analyst.verdict}
          </span>
          {analyst.rationale && <span className="muted"> {analyst.rationale}</span>}
          {p.context?.analystRunId && (
            <button className="link-btn" onClick={() => openAnalystRun(p.context.analystRunId)}
              title="open this proposal's analyst run — the full play-by-play">
              view the analysis
            </button>
          )}
        </div>
      )}
      {p.context?.explain && (
        <div className="prop-explain">{p.context.explain}</div>
      )}
      {p.context?.riskWarning && (
        <div className="neg" style={{ fontSize: 12, margin: "4px 0" }}
          title="Preflight check against the platform risk caps — align Settings → Risk with the tip budget, or approve half size">
          ⚠ {p.context.riskWarning}
        </div>
      )}
      {checks.some((c: any) => !c.passed) && (
        <ul className="check-list">
          {checks.filter((c: any) => !c.passed).map((c: any) => (
            <li key={c.name} className="check-item fail">
              <b>{c.name.replace(/_/g, " ")}</b>{c.detail ? ` — ${c.detail}` : ""}
            </li>
          ))}
        </ul>
      )}
      <div className="proposal-actions">
        <button className="approve-btn" disabled={busy}
          onClick={() => act(() => api.approveProposal(p.id), `Approved ${p.symbol}`)}>
          <IconCheck size={12} /> Approve
        </button>
        <button className="half-btn" disabled={busy}
          onClick={() => act(() => api.approveProposal(p.id, true), `Approved ${p.symbol} (half)`)}>
          <IconHalf size={12} /> half size
        </button>
        <button className="reject-btn" disabled={busy}
          onClick={() => act(() => api.rejectProposal(p.id), `Rejected ${p.symbol}`)}>
          <IconX size={12} /> Reject
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- tips list */

function TipsTab() {
  const live = useStore((s) => s.signals);
  const toast = useStore((s) => s.toast);
  const loadedState = useAsync(
    () => api.get<Signal[]>("/api/signals?limit=50"), [live.length]);
  const merged = [...live];
  for (const s of loadedState.data ?? []) if (!merged.some((m) => m.id === s.id)) merged.push(s);
  // deleted tips leave the list immediately (the WS update flips them to dismissed)
  const visible = merged.filter((s) => s.status !== "dismissed");
  const { isPhone } = useViewport();
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const selIds = Object.keys(sel).filter((k) => sel[k]);
  const toggleSel = (id: string) => setSel((p) => ({ ...p, [id]: !p[id] }));
  const bulkDelete = async () => {
    if (!selIds.length) return;
    if (!confirm(`Delete ${selIds.length} tip(s)? Waiting armed plans disarm and pending proposals expire.`)) return;
    try {
      const r = await api.dismissSignals(selIds);
      toast("info", `${r.dismissed} tip(s) deleted`);
      setSel({});
      loadedState.reload();
    } catch (e: any) { toast("error", e.message); }
  };

  if (isPhone) {
    return (
      <div className="panel mb">
        <div className="panel-head">Tips</div>
        <div className="bl-cards">
          {loadedState.loading && merged.length === 0 ? <Spinner />
            : merged.length === 0 ? <div className="empty">No tips yet — add one from the New tip tab.</div>
            : visible.slice(0, 30).map((s) => {
              const failed = (s.verification?.checks ?? []).filter((c) => !c.passed);
              const contract = contractLabel(s);
              return (
                <div key={s.id} className="bl-card bl-card--static">
                  <span className="bl-card-l">
                    <span className="bl-card-sym">{s.ticker} <span className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</span>
                      {contract && <span className="muted"> {contract}</span>}
                      <span className={`status-pill ${statusPill(s.status)}`}>{statusLabel(s.status)}</span>
                      {(s.seenCount ?? 1) > 1 && <span className="status-pill dim">×{s.seenCount}</span>}
                      <FlowChip sym={s.ticker} />
                    </span>
                    <span className="bl-card-sub">entry {s.entryPrice ? fmtMoney(s.entryPrice) : "—"} · target {s.targetPrice ? fmtMoney(s.targetPrice) : "—"} · stop {s.stopPrice ? fmtMoney(s.stopPrice) : "—"} · {s.confidence.replace("_", " ")}</span>
                    {s.thesisSummary && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.thesisSummary}</span>}
                    {s.verification?.flowContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.verification.flowContext}</span>}
                    {s.verification?.calendarContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>⚠ {s.verification.calendarContext}</span>}
                    {failed.length > 0 && <span className="bl-card-sub neg" style={{ whiteSpace: "normal" }}>{failed.map((c) => c.detail || c.name).join("; ")}</span>}
                    <span className="bl-card-sub">{s.sourceName ?? "—"} · {fmtDateTime(s.createdAt)} <CopyChip value={s.id} title={`tip ${s.id} — click to copy`} /> <ArmButton s={s} /> <AnalystLink s={s} /> <ArmedChip s={s} /> <DeleteTipButton s={s} onDone={loadedState.reload} /></span>
                  </span>
                </div>
              );
            })}
        </div>
      </div>
    );
  }

  return (
    <div className="panel mb">
      <div className="panel-head">Tips <span className="sub">every tip the app has read, newest first</span>
        {selIds.length > 0 && (
          <button className="ghost-btn neg" style={{ marginLeft: "auto" }} onClick={bulkDelete}>
            Delete {selIds.length} selected
          </button>
        )}
      </div>
      <div className="scroll-x">
        {loadedState.loading && merged.length === 0 ? (
          <Spinner />
        ) : loadedState.error && merged.length === 0 ? (
          <ErrorState message={loadedState.error} onRetry={loadedState.reload} />
        ) : merged.length === 0 ? (
          <div className="empty">No tips yet — add one from the New tip tab.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 26 }}><input type="checkbox" title="select all shown"
                  checked={visible.length > 0 && selIds.length === Math.min(visible.length, 50)}
                  onChange={(e) => setSel(e.target.checked
                    ? Object.fromEntries(visible.slice(0, 50).map((s) => [s.id, true])) : {})} /></th>
                <th>Ticker</th><th>Dir</th><th>Contract</th><th>Book vehicle</th><th>Conf</th><th className="num">Entry</th>
                <th className="num">Tgt/Stop</th><th>Status</th><th>Source</th><th>When</th>
                <th title="Quote a tip's id to review its extract & verify">Id</th>
              </tr>
            </thead>
            <tbody>
              {visible.slice(0, 50).map((s) => (
                <tr key={s.id}
                  title={[s.thesisSummary, s.verification?.flowContext,
                    s.verification?.calendarContext].filter(Boolean).join("\n")}>
                  <td><input type="checkbox" checked={!!sel[s.id]} onChange={() => toggleSel(s.id)} /></td>
                  <td><b>{s.ticker}</b>{(s.seenCount ?? 1) > 1 && <span className="muted"> ×{s.seenCount}</span>} <FlowChip sym={s.ticker} /></td>
                  <td className="muted">{s.direction === "short" ? <span className="neg">short ↓</span> : "long"}</td>
                  <td className="muted">{contractLabel(s) ?? "—"}</td>
                  <td>{vehicleChip(s) ?? <span className="muted">—</span>}</td>
                  <td className="muted">{s.confidence.replace("_", " ")}</td>
                  <td className="num">{s.entryPrice ? fmtMoney(s.entryPrice) : "—"}</td>
                  <td className="num muted">
                    {s.targetPrice ? fmtMoney(s.targetPrice) : "—"}/{s.stopPrice ? fmtMoney(s.stopPrice) : "—"}
                  </td>
                  <td>
                    <span className={`status-pill ${statusPill(s.status)}`}
                      title={(s.verification?.checks ?? [])
                        .filter((c) => !c.passed).map((c) => c.detail || c.name).join("; ")}>
                      {statusLabel(s.status)}
                    </span>
                  </td>
                  <td className="muted">{s.sourceName ?? "—"}</td>
                  <td className="muted">{fmtDateTime(s.createdAt)} <ArmButton s={s} /> <AnalystLink s={s} /> <ArmedChip s={s} /></td>
                  <td><CopyChip value={s.id} title={`tip ${s.id} — click to copy`} /> <DeleteTipButton s={s} onDone={loadedState.reload} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- sources */

function BookVal({ b }: { b?: { pnl?: number | null; pnlPct?: number | null } }) {
  const pnl = b?.pnl;
  if (pnl == null) return <span className="muted">—</span>;
  return (
    <span className={pnl > 0 ? "pos" : pnl < 0 ? "neg" : "muted"}>
      {fmtMoney(pnl)} ({(b?.pnlPct ?? 0).toFixed(1)}%)
    </span>
  );
}

function BookCell({ b }: { b?: { pnl?: number | null; pnlPct?: number | null } }) {
  return <td className="num"><BookVal b={b} /></td>;
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function PeekButton({ channelId, label }: { channelId: string; label?: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [res, setRes] = useState<any>(null);
  const test = async () => {
    setState("loading"); setRes(null);
    try {
      await api.discordPeek(channelId);
      for (let i = 0; i < 12; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const out = await api.discordPeekResult(channelId);
        if (out.result) { setRes(out.result); setState("done"); return; }
      }
      setRes({ error: "no response — is the intake running?" }); setState("done");
    } catch (e: any) { setRes({ error: e.message }); setState("done"); }
  };
  const toast = useStore((s) => s.toast);
  const setPageTab = useStore((s) => s.setPageTab);
  const setTipProcess = useStore((s) => s.setTipProcess);
  const [processing, setProcessing] = useState(false);
  const process = async () => {
    setProcessing(true);
    try {
      await api.discordProcessLast(channelId);
      // take the user to the Analyst tab, which tracks this request until the
      // gateway reports what happened (a non-tip message must not look like silence)
      setTipProcess({ channelId, label: label ?? channelId, startedAt: Date.now() });
      setPageTab("analyst");
    } catch (e: any) { toast("error", e.message); }
    finally { setProcessing(false); }
  };
  return (
    <span className="disc-peek">
      <button className="disc-act" disabled={state === "loading"} onClick={test}
        title="Test the connection: fetch this channel's last message">
        {state === "loading" ? "…" : "⟳"}
      </button>
      <button className="disc-act" disabled={processing} onClick={process}
        title="Process this channel's last message as a tip (extraction + analyst)">
        {processing ? "…" : "▶"}
      </button>
      {state === "done" && res && (
        res.error
          ? <span className="neg" style={{ fontSize: 11 }}> {res.error}</span>
          : <span className="muted" style={{ fontSize: 11 }}>
              {" "}last: <b>{res.author}</b> {timeAgo(res.messageAt)} — {(res.text || "(no text)").slice(0, 80)}
            </span>
      )}
    </span>
  );
}

function DiscordSourcesPanel() {
  const toast = useStore((s) => s.toast);
  const catState = useAsync(() => api.discordCatalog(), []);
  const watchState = useAsync(() => api.discordWatch(), []);
  const [sel, setSel] = useState<Record<string, import("../types").DiscordWatch>>({});
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [monitoredOnly, setMonitoredOnly] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const w = watchState.data?.watch;
    if (w) setSel(Object.fromEntries(w.map((e) => [e.channelId, e])));
  }, [watchState.data]);

  const cat = catState.data;
  const toggle = (channelId: string, kind: "dm" | "channel", label: string,
                  guildName: string, defaultName: string) =>
    setSel((prev) => {
      const next = { ...prev };
      if (next[channelId]) delete next[channelId];
      else next[channelId] = {
        channelId, kind, label, guildName, sourceName: defaultName,
        botsOnly: kind === "channel", enabled: true, onboardDays: 7,
      };
      return next;
    });
  const setField = (channelId: string, patch: Partial<import("../types").DiscordWatch>) =>
    setSel((prev) => ({ ...prev, [channelId]: { ...prev[channelId], ...patch } }));

  const save = async () => {
    setBusy(true);
    try {
      await api.setDiscordWatch(Object.values(sel));
      toast("success", `Monitoring ${Object.keys(sel).length} Discord source(s)`);
    } catch (e: any) { toast("error", e.message); }
    finally { setBusy(false); }
  };

  const needle = q.trim().toLowerCase();
  const hit = (s: string) => !needle || s.toLowerCase().includes(needle);
  const ageMin = cat?.at ? Math.round((Date.now() - new Date(cat.at).getTime()) / 60000) : null;
  const selCount = Object.keys(sel).length;

  const Row = ({ channelId, name, kind, guildName, isBot }:
    { channelId: string; name: string; kind: "dm" | "channel"; guildName?: string; isBot?: boolean }) => {
    const on = !!sel[channelId];
    return (
      <div className="disc-row">
        <div className="disc-row-main">
          <label className="disc-toggle">
            <input type="checkbox" checked={on}
              onChange={() => toggle(channelId, kind, name, guildName ?? "", name)} />
            <span>{kind === "channel" ? "#" : ""}{name}{isBot ? <span className="muted"> · bot</span> : null}</span>
          </label>
          <PeekButton channelId={channelId} label={`${kind === "channel" ? "#" : ""}${name}`} />
        </div>
        {on && (
          <div className="disc-opts">
            <input className="disc-src" value={sel[channelId].sourceName}
              title="source name (its own scorecard)"
              onChange={(e) => setField(channelId, { sourceName: e.target.value })} />
            <label className="muted" title="ON: only bot posts become tips — right for alert-bot rooms. Turn it OFF when the tips come from a HUMAN posting as themselves (e.g. a trader's own channel), or that source can never auto-intake a tip.">
              <input type="checkbox" checked={!!sel[channelId].botsOnly}
                onChange={(e) => setField(channelId, { botsOnly: e.target.checked })} /> bots only
            </label>
            <label className="muted" title="onboard: mirror this many days of the channel's history (max 17) so the analyst has the backstory — no re-downloads">
              onboard <input className="disc-days" type="number" min={0} max={17}
                value={sel[channelId].onboardDays ?? 0}
                onChange={(e) => setField(channelId, {
                  onboardDays: Math.max(0, Math.min(17, Number(e.target.value) || 0)) })} />d
            </label>
          </div>
        )}
      </div>
    );
  };

  const dms = (cat?.dms ?? []).filter((d) => hit(d.name) && (!monitoredOnly || sel[d.channelId]));
  const guilds = (cat?.guilds ?? []).map((g) => {
    const chans = g.channels.filter((c) => (hit(c.name) || hit(g.guildName) || hit(c.category ?? ""))
      && (!monitoredOnly || sel[c.channelId]));
    return { ...g, shown: chans };
  }).filter((g) => g.shown.length > 0);

  // Discord's folder structure: channels arrive sorted by category — group the
  // consecutive runs so each category renders as a collapsible folder
  const byCategory = (chans: import("../types").DiscordCatalogChannel[]) => {
    const groups: { category: string; chans: typeof chans }[] = [];
    for (const c of chans) {
      const catName = c.category ?? "";
      const last = groups[groups.length - 1];
      if (last && last.category === catName) last.chans.push(c);
      else groups.push({ category: catName, chans: [c] });
    }
    return groups;
  };

  return (
    <div className="panel mb">
      <div className="panel-head">
        Discord intake
        <span className="sub">
          {catState.loading ? "loading…"
            : !cat?.user ? "no catalog yet — start the intake (scripts\\start.ps1)"
            : `connected as ${cat.user.username} · ${selCount} monitored · catalog ${ageMin ?? "?"} min ago`}
        </span>
        <span style={{ flex: 1 }} />
        <button className="link-btn" onClick={() => catState.reload()}>refresh</button>
        <button className="primary-btn" disabled={busy} onClick={save}>Save</button>
      </div>
      <div className="panel-body">
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Pick which DMs and channels feed the pipeline — nothing else is read. Use <b>test</b> to
          confirm a source is connected (shows its last message). Each enabled source keeps its own scorecard.
        </div>
        <div className="disc-controls">
          <input className="disc-search" placeholder="Filter by name (e.g. jon, alerts, OWLS)…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="muted"><input type="checkbox" checked={monitoredOnly}
            onChange={(e) => setMonitoredOnly(e.target.checked)} /> monitored only</label>
        </div>
        {catState.loading ? <Spinner />
          : !cat?.user ? (
            <div className="empty">Start the intake (it launches with the app) — it reports the
              DMs and channels you can see here, then pick sources.</div>
          ) : (
            <div className="disc-cols">
              <div>
                <div className="disc-head">Servers {guilds.length ? `(${guilds.length})` : ""}</div>
                {guilds.length === 0 ? <div className="muted">none match</div>
                  : guilds.map((g) => {
                    const isOpen = !!open[g.guildId] || !!needle || monitoredOnly;
                    const enabledHere = g.shown.filter((c) => sel[c.channelId]).length;
                    return (
                      <div key={g.guildId} className="disc-guild">
                        <button className="disc-guild-name" onClick={() =>
                          setOpen((p) => ({ ...p, [g.guildId]: !isOpen }))}>
                          <span>{isOpen ? "▾" : "▸"} {g.guildName}</span>
                          <span className="muted"> {g.shown.length} ch{enabledHere ? ` · ${enabledHere} on` : ""}</span>
                        </button>
                        {isOpen && byCategory(g.shown).map(({ category, chans }) => {
                          const key = `${g.guildId}/${category}`;
                          const catOpen = open[key] !== false || !!needle || monitoredOnly;
                          const onHere = chans.filter((c) => sel[c.channelId]).length;
                          return (
                            <div key={key || "_"} className="disc-cat">
                              {category && (
                                <button className="disc-cat-name" onClick={() =>
                                  setOpen((p) => ({ ...p, [key]: !catOpen }))}>
                                  <span>{catOpen ? "▾" : "▸"} {category}</span>
                                  <span className="muted"> {chans.length}{onHere ? ` · ${onHere} on` : ""}</span>
                                </button>
                              )}
                              {catOpen && chans.map((c) => (
                                <Row key={c.channelId} channelId={c.channelId} name={c.name}
                                  kind="channel" guildName={g.guildName} />
                              ))}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
              </div>
              <div>
                <div className="disc-head">Direct messages {dms.length ? `(${dms.length})` : ""}</div>
                {dms.length === 0 ? <div className="muted">none match</div>
                  : dms.map((d) => (
                    <Row key={d.channelId} channelId={d.channelId} name={d.name} kind="dm" isBot={d.isBot} />
                  ))}
              </div>
            </div>
          )}
      </div>
    </div>
  );
}

/** Discord-style read-only viewer over the mirror — proof the history the
    analyst reads is actually in OUR database. Newest at the bottom, "load
    older" prepends, search filters server-side. */
function MirrorViewer() {
  const toast = useStore((s) => s.toast);
  const setTipProcess = useStore((s) => s.setTipProcess);
  const setPageTab = useStore((s) => s.setPageTab);
  const analyze = async (m: import("../types").DiscordMirrorMessage) => {
    try {
      const { key } = await api.discordAnalyzeMessage(m.id);
      // same progress banner as "▶ tip" — it polls the key until the outcome lands
      setTipProcess({ channelId: key,
        label: `${m.author} · ${(m.postedAt ?? "").slice(0, 16)}`, startedAt: Date.now() });
      setPageTab("analyst");
    } catch (e: any) { toast("error", e.message); }
  };
  const watchState = useAsync(() => api.discordWatch(), []);
  const sources = [...new Set((watchState.data?.watch ?? [])
    .map((w) => w.sourceName).filter(Boolean))];
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState<import("../types").DiscordMirrorMessage[] | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const load = async (before?: string) => {
    const batch = await api.discordMessages({
      source: source || undefined, contains: q.trim() || undefined,
      before, limit: 80 });
    const asc = [...batch].reverse();               // API is newest-first; chat reads oldest→newest
    setExhausted(batch.length < 80);
    if (before) {
      const el = scrollRef.current;
      const keep = el ? el.scrollHeight - el.scrollTop : 0;
      setMsgs((prev) => [...asc, ...(prev ?? [])]);
      requestAnimationFrame(() => {                 // keep the reading position
        if (el) el.scrollTop = el.scrollHeight - keep;
      });
    } else {
      setMsgs(asc);
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;     // open at the newest, like Discord
      });
    }
  };
  useEffect(() => { load().catch(() => setMsgs([])); }, [source]);
  const search = () => load().catch(() => undefined);
  let lastDay = "";
  return (
    <div className="panel mb">
      <div className="panel-head">
        Mirror
        <span className="sub">the messages the analyst can search — cached in our database</span>
        <span style={{ flex: 1 }} />
        <select className="mir-src" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">all sources</option>
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="mir-search" placeholder="search text…" value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()} />
        <button className="link-btn" onClick={search}>search</button>
      </div>
      <div className="mir-scroll" ref={scrollRef}>
        {msgs == null ? <Spinner />
          : msgs.length === 0 ? (
            <div className="empty">Nothing mirrored{source ? ` for ${source}` : ""} yet — the
              intake mirrors watched channels while it runs; “onboard Nd” on a source backfills
              its history.</div>
          ) : (
            <>
              {!exhausted && (
                <div className="mir-older">
                  <button className="link-btn"
                    onClick={() => msgs[0]?.postedAt && load(msgs[0].postedAt!).catch(() => undefined)}>
                    ↑ load older
                  </button>
                </div>
              )}
              {msgs.map((m) => {
                const day = (m.postedAt ?? "").slice(0, 10);
                const divider = day && day !== lastDay;
                lastDay = day || lastDay;
                return (
                  <div key={m.id}>
                    {divider && <div className="mir-day">{day}</div>}
                    <div className="mir-msg">
                      <div className="mir-meta">
                        <b>{m.author}</b>
                        {m.isBot && <span className="status-pill dim">bot</span>}
                        {!source && m.source && <span className="mir-chan">{m.source}</span>}
                        <span className="muted">{(m.postedAt ?? "").slice(11, 16)}</span>
                        <button className="disc-act" onClick={() => analyze(m)}
                          title="Analyse THIS message as a tip (ad-hoc — extraction + analyst; stale messages replay on history)">
                          ▶
                        </button>
                      </div>
                      <div className="mir-text">{m.text || <span className="muted">(no text)</span>}</div>
                      {m.images.length > 0 && (
                        <div className="mir-imgs">
                          {(m.localImages?.length ?? 0) > 0
                            ? m.localImages!.map((_, i) => (
                              <a key={i} href={`/api/tip/discord/media/${m.id}/${i}`}
                                target="_blank" rel="noreferrer">
                                <img className="mir-thumb" loading="lazy" alt={`image ${i + 1}`}
                                  src={`/api/tip/discord/media/${m.id}/${i}`} />
                              </a>
                            ))
                            : m.images.map((u, i) => (
                              <a key={i} href={u} target="_blank" rel="noreferrer">image {i + 1} ↗</a>
                            ))}
                          {(m.localImages?.length ?? 0) === 0 && (
                            <span className="muted"> (not yet in our store — CDN links may expire)</span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </>
          )}
      </div>
    </div>
  );
}

function DeleteTipButton({ s, onDone }: { s: any; onDone: () => void }) {
  const toast = useStore((st) => st.toast);
  const del = async (e: any) => {
    e.stopPropagation();
    if (!confirm(`Delete the ${s.ticker} tip from ${s.sourceName ?? "?"}? Any waiting armed plan disarms and any pending proposal expires.`)) return;
    try { await api.dismissSignals([s.id]); toast("info", `${s.ticker} tip deleted`); onDone(); }
    catch (err: any) { toast("error", err.message); }
  };
  return <button className="an-note-del" title="delete this tip (waiting plans disarm, pending proposals expire)"
    onClick={del}>×</button>;
}

function ArmedChip({ s }: { s: any }) {
  // ARM-GAPS F2: the tip row says when a live armed plan is waiting for it
  const rid = s?.extraction?.analyst?.armedRunId;
  const armed = useStore((st) => st.techniqueArmed);
  const openArmedPlan = useStore((st) => st.openArmedPlan);
  const live = rid ? armed.find((a) => a.runId === rid && (a.status === "armed" || a.status === "paused")) : undefined;
  if (!live) return null;
  const waiting = (live.triggers ?? []).filter((t) => ["waiting", "observed"].includes(t.status)).map((t) => t.entry);
  return (
    <button className="link-btn" onClick={() => openArmedPlan(live.runId)}
      title="this tip has a LIVE armed plan waiting for its level — opens the Armed page">
      ⚡ armed{waiting.length ? ` @ ${waiting.map((x) => Number(x).toFixed(2)).join("/")}` : ""}
      {(live.horizonSessions ?? 1) > 1 ? ` · day ${live.sessionDay}/${live.horizonSessions}` : ""}
    </button>
  );
}

function SourcePoliciesPanel() {
  // ARM-GAPS E6: per-source policy editor — writes techniques.tip.sources
  // (the same overlay resolve_policy reads); blank = the platform default
  const toast = useStore((s) => s.toast);
  const settings = useStore((s) => s.settings);
  const cardsState = useAsync(() => api.sourceScorecards(), []);
  const [overrides, setOverrides] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setOverrides({ ...((settings["techniques.tip.sources"] as any) ?? {}) });
  }, [settings]);
  const names = Array.from(new Set([
    ...Object.keys(overrides),
    ...((cardsState.data ?? []).map((c) => c.source)),
  ])).sort();
  const setF = (name: string, key: string, val: any) =>
    setOverrides((prev) => ({ ...prev, [name]: { ...(prev[name] ?? {}), [key]: val } }));
  const save = async () => {
    setBusy(true);
    try {
      await api.patchSettings({ "techniques.tip.sources": overrides });
      toast("success", "Per-source policies saved");
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  if (!names.length) return null;
  return (
    <div className="panel mb">
      <div className="panel-head">Per-source policy
        <span className="sub">mode, entry doctrine and budget per source — tip-time entry is EARNED on the scorecard below</span>
        <button className="ghost-btn" style={{ marginLeft: "auto" }} disabled={busy} onClick={save}>Save policies</button>
      </div>
      <div className="scroll-x">
        <table className="tbl">
          <thead><tr><th>Source</th><th>Mode</th><th>Entry</th>
            <th className="num">Budget/tip ($)</th><th className="num">Horizon (sess)</th><th>Min conviction</th></tr></thead>
          <tbody>
            {names.map((n) => {
              const o = overrides[n] ?? {};
              return (
                <tr key={n}>
                  <td><b>{n}</b></td>
                  <td><select value={o.mode ?? ""} onChange={(e) => setF(n, "mode", e.target.value || undefined)}>
                    <option value="">default (proposal)</option><option value="shadow">shadow</option>
                    <option value="alert">alert</option><option value="proposal">proposal</option>
                    <option value="auto">auto</option></select></td>
                  <td><select value={o.entry ?? ""} onChange={(e) => setF(n, "entry", e.target.value || undefined)}>
                    <option value="">default (level_touch)</option>
                    <option value="level_touch">level_touch</option>
                    <option value="tip_time">tip_time (earned)</option></select></td>
                  <td className="num"><input type="number" style={{ width: 90 }} value={o.budget_per_tip ?? ""}
                    placeholder="1000" onChange={(e) => setF(n, "budget_per_tip", e.target.value === "" ? undefined : Number(e.target.value))} /></td>
                  <td className="num"><input type="number" style={{ width: 70 }} value={o.horizon_sessions ?? ""}
                    placeholder="15" onChange={(e) => setF(n, "horizon_sessions", e.target.value === "" ? undefined : Number(e.target.value))} /></td>
                  <td><select value={o.min_conviction ?? ""} onChange={(e) => setF(n, "min_conviction", e.target.value || undefined)}>
                    <option value="">default (implied)</option>
                    <option value="implied">implied</option>
                    <option value="explicit_call">explicit_call</option></select></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SourcesTab() {
  const signalCount = useStore((s) => s.signals.length);
  const state = useAsync(() => api.sourceScorecards(), [signalCount]);
  const cards = state.data ?? [];
  return (
    <>
    <DiscordSourcesPanel />
    <SourcePoliciesPanel />
    <MirrorViewer />
    <div className="panel">
      <div className="panel-head">
        Source scorecards
        <span className="sub">a source earns trust here — tip-time entry and real money are both evidence-gated</span>
      </div>
      <div className="scroll-x">
        {state.loading && cards.length === 0 ? <Spinner />
          : cards.length === 0 ? (
            <div className="empty">No sources yet — every tip source gets two shadow books and a track record.</div>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Source</th><th className="num">Tips</th>
                  <th className="num" title="verified / parked / failed / expired-unfilled">V/P/F/X</th>
                  <th className="num" title="Immediate book: buy the moment the tip verified — the source's raw quality">Tip-time P&amp;L</th>
                  <th className="num" title="Armed book: wait for the level, managed exits — what the app actually does">Level-touch P&amp;L</th>
                  <th>Policy</th><th>Trust</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((c: SourceScorecard) => (
                  <tr key={c.source}>
                    <td><b>{c.source}</b>{(c.seenAgain ?? 0) > 0 && <span className="muted"> ·{c.seenAgain} repeats</span>}</td>
                    <td className="num">{c.signals}</td>
                    <td className="num muted">{c.verified}/{c.parked}/{c.failed}/{c.expiredUnfilled ?? 0}</td>
                    <BookCell b={c.books?.immediate ?? { pnl: c.shadowPnl, pnlPct: c.shadowPnlPct }} />
                    <td className="num">
                      <BookVal b={c.books?.armed} />
                      {c.books?.armed?.outcomes?.expectancyR != null && (
                        <div className={`mono ${(c.books.armed.outcomes.expectancyR ?? 0) > 0 ? "pos" : "neg"}`}
                          style={{ fontSize: 11 }}
                          title={`Per tip taken (unfilled = 0R): ${c.books.armed.outcomes.fired} fired, ${c.books.armed.outcomes.neverTriggered} never triggered, win rate ${c.books.armed.outcomes.winRate ?? "—"}`}>
                          E[R] {c.books.armed.outcomes.expectancyR > 0 ? "+" : ""}{c.books.armed.outcomes.expectancyR} · {c.books.armed.outcomes.scored} scored
                        </div>
                      )}
                    </td>
                    <td className="muted">{c.policy ? `${c.policy.entry.replace("_", " ")} · ${c.policy.mode}` : "—"}</td>
                    <td>
                      <span className={`status-pill ${c.barCleared ? "ok" : "dim"}`}
                        title="Bar: enough verified tips AND a positive ARMED book — required before real money">
                        {c.barCleared ? "cleared" : "shadow"}
                      </span>
                      {c.tipTimeEarned && (
                        <span className="status-pill wait" style={{ marginLeft: 4 }}
                          title="Buying immediately beats waiting for this source — their tips run away; consider tip_time entry in the source policy">
                          tip-time?
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
    </>
  );
}

/* ---------------------------------------------------------------- analyst */

/** Tiny inline markdown for the analyst's prose: **bold**, `code`, paragraphs
    and "- " bullets. Enough to read well without a markdown dependency. */
function RichText({ text }: { text: string }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
      p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b>
        : p.startsWith("`") && p.endsWith("`") ? <code key={i}>{p.slice(1, -1)}</code>
        : p);
  return (
    <div className="an-rich">
      {text.split(/\n{2,}/).map((para, i) => {
        const ls = para.split("\n").filter((l) => l.trim());
        if (ls.length > 0 && ls.every((l) => /^\s*[-•*]\s+/.test(l))) {
          return <ul key={i}>{ls.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-•*]\s+/, ""))}</li>)}</ul>;
        }
        return (
          <p key={i}>
            {ls.map((l, j) => <span key={j}>{inline(l)}{j < ls.length - 1 && <br />}</span>)}
          </p>
        );
      })}
    </div>
  );
}

const STEP_ICON: Record<string, { path: JSX.Element; cls: string; label: string }> = {
  start: { cls: "dim", label: "start", path: <path d="M5 3l8 5-8 5z" fill="currentColor" stroke="none" /> },
  llm: { cls: "llm", label: "analyst", path: <path d="M8 1.5l1.6 4 4.4.4-3.3 2.9 1 4.3L8 10.8l-3.7 2.3 1-4.3L2 5.9l4.4-.4z" fill="currentColor" stroke="none" /> },
  tool_call: { cls: "call", label: "tool call", path: <path d="M2.5 8h9m0 0L8 4.5M11.5 8L8 11.5" /> },
  tool_result: { cls: "result", label: "result", path: <path d="M13.5 8h-9m0 0L8 4.5M4.5 8L8 11.5" /> },
  note: { cls: "dim", label: "note", path: <path d="M8 4.2v4.6m0 2.6v.1" /> },
  final: { cls: "final", label: "verdict", path: <path d="M3 8.5l3.2 3L13 4.5" /> },
  error: { cls: "error", label: "error", path: <path d="M4.5 4.5l7 7m0-7l-7 7" /> },
  extract: { cls: "llm", label: "extraction", path: <path d="M3 3.5h10M3 8h10M3 12.5h6" /> },
  signal: { cls: "call", label: "verification", path: <path d="M2.5 9.5l3-3 2.5 2.5L13.5 4" /> },
  handoff: { cls: "final", label: "hand-off", path: <path d="M2.5 8h8m0 0L7.5 4.5M10.5 8L7.5 11.5m4-7.5v7" /> },
};

function StepNode({ kind }: { kind: string }) {
  const m = STEP_ICON[kind] ?? STEP_ICON.note;
  return (
    <span className={`an-node an-node--${m.cls}`} title={m.label}>
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
        stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {m.path}
      </svg>
    </span>
  );
}

/** One-line human summary of a tool result, so the JSON can stay folded. */
function resultSummary(s: AnalystStep): string {
  const r = s.result;
  if (r == null || typeof r !== "object") return "done";
  if (r.error) return String(r.error);
  if (r.note) return String(r.note);
  if (s.tool === "get_quote" && r.last != null) return `${r.symbol} last ${r.last} (bid ${r.bid} / ask ${r.ask})`;
  if (s.tool === "get_chain" && r.expiry) return `${r.underlying} ${r.expiry} · ${r.dte} DTE · spot ${r.spot} · ${(r.strikes ?? []).length} strikes`;
  if (s.tool === "get_expiries") return `${(r.expiries ?? []).length} expiries · spot ${r.spot ?? "?"}`;
  if (s.tool === "get_bars") return `${r.bars ?? "?"} bars · range ${r.low ?? "?"}–${r.high ?? "?"}`;
  if (s.tool === "get_flow") {
    if (r.score != null) {
      return `${r.lean ?? "?"} · score ${r.score} · ${(r.flags ?? []).length} flags · ` +
        `${(r.confirmedOvernight ?? []).length} OI-confirmed · story ${(r.story ?? []).length}d`;
    }
    return String(r.flow ?? "no read");
  }
  if (s.tool === "get_earnings") return r.daysToEarnings != null ? `earnings in ~${r.daysToEarnings}d` : "no date known";
  if (s.tool === "get_source_stats") return `${r.signals ?? 0} signals · ${r.verified ?? 0} verified`;
  if (s.tool === "save_note") return `note saved to ${r.scope}`;
  const keys = Object.keys(r).slice(0, 4);
  return keys.map((k) => `${k}: ${JSON.stringify(r[k])}`).join(" · ").slice(0, 120);
}

function ArgChips({ args }: { args: any }) {
  if (!args || typeof args !== "object") return null;
  return (
    <span className="an-args">
      {Object.entries(args).map(([k, v]) => (
        <span key={k} className="an-arg"><span className="an-arg-k">{k}</span>{String(v)}</span>
      ))}
    </span>
  );
}

function StepRow({ s, openRun }: { s: AnalystStep; openRun?: (id: string) => void }) {
  const m = STEP_ICON[s.kind] ?? STEP_ICON.note;
  const at = s.at ? new Date(s.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
  let body: JSX.Element;
  if (s.kind === "tool_call") {
    body = (
      <div className="an-card an-card--call">
        <span className="an-tool">{s.tool}</span>
        <ArgChips args={s.args} />
      </div>
    );
  } else if (s.kind === "tool_result") {
    body = (
      <div className="an-card an-card--result">
        <div className="an-result-line"><span className="an-tool an-tool--dim">{s.tool}</span> {resultSummary(s)}</div>
        {s.result != null && typeof s.result === "object" && (
          <details className="an-fold">
            <summary>data</summary>
            <pre className="an-json">{JSON.stringify(s.result, null, 2).slice(0, 4000)}</pre>
          </details>
        )}
      </div>
    );
  } else if (s.kind === "final") {
    const o = s.opinion ?? {};
    const cls = o.verdict === "take" ? "ok" : o.verdict === "watch" ? "wait"
      : o.verdict === "review" ? "dim" : "bad";
    body = (
      <div className={`an-card an-card--final an-final--${o.verdict ?? "none"}`}>
        <div className="an-final-head">
          <span className={`status-pill ${cls}`}>{(o.verdict ?? "?").toUpperCase()}</span>
          {(o.contract_label || o.contract) && <b>{o.contract_label ?? o.contract}</b>}
          {o.limit_price != null && <span>@ ≤{o.limit_price}</span>}
          {o.quantity != null && <span>×{o.quantity}</span>}
          {o.confidence != null && <span className="muted">{Math.round(o.confidence * 100)}% confident</span>}
        </div>
        {o.rationale && <RichText text={String(o.rationale)} />}
        {o.invalidation && <div className="an-invalid">Invalid if: {o.invalidation}</div>}
      </div>
    );
  } else if (s.kind === "llm") {
    const t = s.text.trim();
    // the model's last turn is often the raw JSON opinion — the verdict card
    // below renders it readably, so fold the blob instead of duplicating it
    body = t.startsWith("{") && t.endsWith("}")
      ? (
        <div className="an-card an-card--llm">
          <details className="an-fold">
            <summary>final answer as raw JSON — the verdict card below is the readable form</summary>
            <pre className="an-json">{t}</pre>
          </details>
        </div>
      )
      : <div className="an-card an-card--llm"><RichText text={s.text} /></div>;
  } else {
    body = (
      <div className={`an-card an-card--plain ${s.kind === "error" ? "neg" : ""}`}>
        {s.text}
        {s.runId && openRun && (
          <button className="link-btn" style={{ marginLeft: 8 }}
            onClick={() => openRun(s.runId!)}>open the appraisal run →</button>
        )}
      </div>
    );
  }
  return (
    <div className="an-ev">
      <StepNode kind={s.kind} />
      <div className="an-ev-body">
        <div className="an-ev-meta">{m.label}{at && <span> · {at}</span>}</div>
        {body}
      </div>
    </div>
  );
}

/** "So what happened?" — one plain sentence per verdict, because a WATCH chip
    alone doesn't say whether anything was asked of the user or ordered. */
function outcomeLine(run: AnalystRun): string | null {
  if (run.status === "running") return null;
  if (run.status === "failed") return "The run failed — nothing was asked or ordered.";
  const v = run.verdict ?? "";
  if (run.kind === "retro") {
    return "Retro — lessons went to Knowledge (and the rulebook if the grade earned it). No orders.";
  }
  if (run.kind === "intake") {
    if (v === "review") return "Bookkeeping review — nothing tradable, so the analyst reconciled the update against our notes/positions (see the play-by-play). No new tips, no orders.";
    if (v === "no signals") return "Nothing tradable in the message — no action anywhere.";
    return "Each tradable tip got its own appraisal run (linked above) — the verdicts and any proposals live there.";
  }
  if (v === "take") {
    if (run.opinion?.entry_mode === "at_level") {
      return `TAKE at the level — a plan was ARMED waiting for ${run.opinion?.entry_level ?? "the tip's entry"} on the underlying (see the Armed page). No market order now; if the level never comes, the plan expires with the tip's horizon.`;
    }
    return "TAKE — a proposal was created: approve/reject it in the strip at the top of this page (an auto-mode source self-approves through the risk gate). On the fill it becomes a managed position running the analyst's exit plan.";
  }
  if (v === "watch") return "WATCH — right idea, wrong moment: nothing was ordered and nothing needs your approval. The tip stays on the Tips tab (arm it there if you want the level watched); the shadow books still track the source's call.";
  if (v === "skip") return "SKIP — the analyst passed: nothing was ordered, nothing needs you. The shadow books may still record it for the source's scorecard.";
  return null;
}

function AnalystRunDetail({ id }: { id: string }) {
  const setFocus = useStore((s) => s.setAnalystFocus);
  const [run, setRun] = useState<AnalystRun | null>(null);
  const [live, setLive] = useState<AnalystStep[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);          // follow the tail only while the user is at it
  useEffect(() => {
    setRun(null); setLive([]); stickRef.current = true;
    let dead = false;
    api.analystRun(id).then((r) => !dead && setRun(r)).catch(() => undefined);
    // live: append steps for THIS run as they stream in
    const off = onAnalystStep(({ runId, step }) => {
      if (runId === id) setLive((prev) => prev.some((p) => p.seq === step.seq) ? prev : [...prev, step]);
    });
    return () => { dead = true; off(); };
  }, [id]);
  // poll as a fallback while the run is live (a missed WS frame never strands the view)
  useEffect(() => {
    if (run && run.status === "running") {
      const t = setInterval(() => api.analystRun(id).then((r) => {
        setRun(r); if (r.status !== "running") clearInterval(t);
      }).catch(() => undefined), 2500);
      return () => clearInterval(t);
    }
  }, [run?.status, id]);

  // merge persisted trace with any live steps not yet persisted
  const bySeq = new Map<number, AnalystStep>();
  for (const s of run?.trace ?? []) bySeq.set(s.seq, s);
  for (const s of live) if (!bySeq.has(s.seq)) bySeq.set(s.seq, s);
  const steps = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  const running = run?.status === "running";

  // auto-scroll to the newest step, but only when already reading the tail
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [steps.length, running]);

  if (!run) return <div className="panel an-detail"><div className="panel-body"><Spinner /></div></div>;
  return (
    <div className="panel an-detail">
      <div className="panel-head">
        <b>{run.ticker}</b> <span className="muted">· {run.source ?? "?"}</span>
        {run.kind === "intake" && <span className="status-pill dim" title="the whole message's intake: extraction, verification, hand-offs, review">intake</span>}
        <span className={`status-pill ${running ? "wait" : run.verdict === "take" ? "ok" : run.verdict === "skip" ? "bad" : "dim"}`}>
          {running ? "running…" : run.verdict ?? run.status}
        </span>
        <CopyChip value={run.id} title={`analyst run ${run.id} — click to copy; quote it to review/tune`} />
        {run.parentId && (
          <button className="link-btn" onClick={() => useStore.getState().openAnalystRun(run.parentId!)}
            title="the message-level intake run that spawned this appraisal">
            ⇡ intake #{run.parentId.slice(0, 8)}
          </button>
        )}
        {(run.opinion as any)?.armedRunId && (
          <button className="link-btn" onClick={() => useStore.getState().openArmedPlan((run.opinion as any).armedRunId)}
            title="the armed plan this appraisal created — opens the Armed page">
            ⚡ armed #{String((run.opinion as any).armedRunId).slice(0, 8)}
          </button>
        )}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 11 }}
          title={`Tools available: ${run.tools.join(", ")}`}>
          {run.model} · {run.tools.length} tools
        </span>
      </div>
      {(run.children?.length ?? 0) > 0 && (
        <div className="an-kids">
          spawned appraisals:
          {run.children!.map((c) => (
            <button key={c.id} className="link-btn"
              onClick={() => useStore.getState().openAnalystRun(c.id)}>
              {c.ticker} → {(c.verdict ?? c.status).replace("_", " ")}
            </button>
          ))}
        </div>
      )}
      {outcomeLine(run) && <div className="an-outcome">{outcomeLine(run)}</div>}
      <div className="an-flow-wrap" ref={scrollRef}
        onScroll={() => {
          const el = scrollRef.current;
          if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}>
        <div className="an-flow">
          {steps.map((s) => <StepRow key={s.seq} s={s} openRun={setFocus} />)}
          {running && (
            <div className="an-ev">
              <span className="an-node an-node--pulse"><span className="an-dot" /></span>
              <div className="an-ev-body"><div className="an-card an-card--plain muted">thinking…</div></div>
            </div>
          )}
        </div>
        {run.error && <div className="neg" style={{ fontSize: 12, margin: "8px 12px" }}>{run.error}</div>}
      </div>
    </div>
  );
}

const NOTE_SCOPES = ["general", "rule", "ticker:", "source:"];

function NotesPanel() {
  const toast = useStore((s) => s.toast);
  const [notes, setNotes] = useState<import("../types").TipNote[] | null>(null);
  const [text, setText] = useState("");
  const [scope, setScope] = useState("general");
  const load = () => api.tipNotes().then(setNotes).catch(() => undefined);
  useEffect(() => { load(); }, []);
  const add = async () => {
    if (!text.trim()) return;
    try {
      await api.addTipNote(scope.trim() || "general", text.trim());
      setText(""); load();
    } catch (e: any) { toast("error", e.message); }
  };
  const del = async (id: string) => {
    try { await api.deleteTipNote(id); load(); } catch (e: any) { toast("error", e.message); }
  };
  return (
    <div className="panel an-notes">
      <div className="panel-head">Knowledge
        <span className="sub">shared notes — every analyst run reads the ones matching its tip</span>
      </div>
      <div className="an-notes-body">
        {notes == null ? <Spinner />
          : notes.length === 0 ? <div className="empty">No notes yet — the analyst saves durable context here (hedges, source habits); you can too.</div>
          : notes.map((n) => (
            <div key={n.id} className="an-note">
              <div className="an-note-head">
                <span className={`an-note-scope ${n.scope === "rule" ? "an-note-scope--rule" : ""}`}>
                  {n.scope === "rule" ? "⚖ rule" : n.scope}</span>
                {(n as any).needsHuman && (
                  <span className="status-pill bad"
                    title="the weekly rule audit found rules pulling in opposite directions — keep one, delete the other, or keep both deliberately, then tick ✓">
                    needs your call
                  </span>
                )}
                <span className="muted">{n.author}{n.createdAt ? ` · ${timeAgo(n.createdAt)}` : ""}</span>
                {n.runId && <button className="link-btn" title="open the run that saved this note"
                  onClick={() => useStore.getState().openAnalystRun(n.runId!)}>run</button>}
                {(n as any).needsHuman && (
                  <button className="link-btn" title="I've decided — clear the flag (journaled)"
                    onClick={async () => { try { await api.resolveTipNote(n.id); load(); } catch (e: any) { toast("error", e.message); } }}>✓</button>
                )}
                <button className="an-note-del" title="delete this note" onClick={() => del(n.id)}>×</button>
              </div>
              <div className="an-note-text">{n.text}</div>
            </div>
          ))}
      </div>
      <div className="an-note-add">
        <input className="an-note-scope-in" list="note-scopes" value={scope}
          onChange={(e) => setScope(e.target.value)}
          title='scope: "general", "ticker:SPY" or "source:name"' />
        <datalist id="note-scopes">{NOTE_SCOPES.map((s) => <option key={s} value={s} />)}</datalist>
        <input className="an-note-text-in" placeholder="Add a note the analyst should know…"
          value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="link-btn" onClick={add}>save</button>
      </div>
    </div>
  );
}

/** Tracks a "▶ tip" request until the gateway reports what happened, so a
    message that extracts as no tip (or an intake that's down) never looks
    like silence. */
function ProcessBanner() {
  const pending = useStore((s) => s.tipProcess);
  const setTipProcess = useStore((s) => s.setTipProcess);
  const setFocus = useStore((s) => s.setAnalystFocus);
  const toast = useStore((s) => s.toast);
  const [outcome, setOutcome] = useState<{ cls: string; msg: string; detail?: string } | null>(null);
  useEffect(() => {
    if (!pending) return;
    setOutcome(null);
    let dead = false;
    const preview = (r: any) =>
      r?.author ? `Last message — ${r.author}: “${(r.text || "").slice(0, 140)}”` : undefined;
    const isAdhoc = pending.channelId.startsWith("msg:");   // app-side, no gateway involved
    const t = setInterval(async () => {
      try {
        const { result } = await api.discordProcessResult(pending.channelId);
        if (dead) return;
        if (result?.pending) return;                        // alive and working — keep pulsing
        if (!result) {
          if (Date.now() - pending.startedAt > 90_000) {
            setTipProcess(null);
            setOutcome(isAdhoc
              ? { cls: "", msg: "No progress reported — check the run list on the left; the analysis may still be streaming there." }
              : { cls: "neg", msg: "No response from the intake — is the Discord intake window running? (scripts\\start.ps1 launches it)" });
          }
          return;
        }
        setTipProcess(null);
        if (result.error) {
          setOutcome({ cls: "neg", msg: result.error, detail: preview(result) });
          return;
        }
        const sigs: any[] = result.signals ?? [];
        const withRun = sigs.find((s) => s.analystRunId);
        if (withRun) {
          toast("success", `Tip ${withRun.ticker} (${withRun.status}) — opening its analyst run`);
          setFocus(withRun.analystRunId);
          setOutcome(null);
        } else if (result.intakeRunId) {
          if (sigs.length > 0) {
            toast("success", "Nothing tradable — the analyst reviewed the update against your book");
            setOutcome({
              cls: "",
              msg: `Extracted ${sigs.map((s) => `${s.ticker} [${(s.status || "").replace("_", " ")}]`).join(", ")} — nothing tradable, so the analyst reviewed the update (open run below).`,
              detail: preview(result),
            });
          } else {
            setOutcome({ cls: "", msg: result.note || "The message did not extract as a trade tip — the intake run below shows why.", detail: preview(result) });
          }
          setFocus(result.intakeRunId);
        } else if (sigs.length > 0) {
          setOutcome({
            cls: "",
            msg: `Extracted ${sigs.map((s) => `${s.ticker} [${(s.status || "").replace("_", " ")}]`).join(", ")} — see the Tips tab.`,
            detail: preview(result),
          });
        } else {
          setOutcome({ cls: "", msg: result.note || "The message did not extract as a trade tip.", detail: preview(result) });
        }
      } catch { /* keep polling */ }
    }, 2000);
    return () => { dead = true; clearInterval(t); };
  }, [pending?.channelId, pending?.startedAt]);
  if (!pending && !outcome) return null;
  return (
    <div className="an-procbar">
      {pending ? (
        <>
          <span className="an-dot an-dot--bar" />
          <span>
            {pending.channelId.startsWith("msg:")
              ? <>Analysing the message from <b>{pending.label}</b>… a multi-signal message spawns one appraisal run per tip and can take a few minutes — watch them appear in the list.</>
              : <>Processing the last message from <b>{pending.label}</b>… extraction + appraisal can take ~30 s.</>}
          </span>
        </>
      ) : (
        <>
          <span className={outcome!.cls}>{outcome!.msg}</span>
          {outcome!.detail && <span className="muted">{outcome!.detail}</span>}
          <button className="an-note-del" title="dismiss" onClick={() => setOutcome(null)}>×</button>
        </>
      )}
    </div>
  );
}

function AnalystTab() {
  const focus = useStore((s) => s.analystFocusRunId);
  const setFocus = useStore((s) => s.setAnalystFocus);
  const [runs, setRuns] = useState<import("../types").AnalystRunSummary[] | null>(null);
  useEffect(() => {
    let dead = false;
    const load = () => api.analystRuns(50).then((r) => !dead && setRuns(r)).catch(() => undefined);
    load();
    const t = setInterval(load, 4000);      // a run kicked off elsewhere shows within seconds
    // a fresh run streaming in auto-opens + refreshes the list immediately
    const off = onAnalystStep(({ runId, step }) => {
      if (step.kind === "start") setFocus(runId);
      load();
    });
    return () => { dead = true; clearInterval(t); off(); };
  }, [setFocus]);
  const { isPhone } = useViewport();
  const sel = focus ?? runs?.[0]?.id ?? null;
  const list = (
    <div className="panel an-list">
      <div className="panel-head">Analyst runs <span className="sub">the play-by-play of each appraisal</span></div>
      <div className="an-list-body">
        {runs == null ? <Spinner />
          : runs.length === 0 ? (
            <div className="empty">No analyst runs yet — a tip triggers one.
              After “▶ tip” on a Discord source, the run appears here within a few seconds.</div>
          )
          : runs.map((r) => (
            <button key={r.id} className={`an-run ${!isPhone && r.id === sel ? "active" : ""}`}
              onClick={() => setFocus(r.id)}>
              <span className="an-run-l">
                <b>{r.ticker}</b>
                {r.kind === "intake" && <span className="status-pill dim">intake</span>}
                {r.kind === "retro" && <span className="status-pill dim">retro</span>}
                <span className={`status-pill ${r.status === "running" ? "wait" : r.verdict === "take" ? "ok" : r.verdict === "skip" ? "bad" : "dim"}`}>
                  {r.status === "running" ? "running" : r.verdict ?? r.status}
                </span>
              </span>
              <span className="an-run-sub">{r.source ?? "?"} · {r.traceSteps} steps · {r.createdAt ? fmtDateTime(r.createdAt) : ""}</span>
            </button>
          ))}
      </div>
    </div>
  );
  // phone: the two-column desk stacks the detail below the fold, so a tap looked
  // dead — the play-by-play opens as a full sheet instead (a live run pops it too)
  if (isPhone) {
    const focusRun = focus ? runs?.find((r) => r.id === focus) : null;
    return (
      <>
        <ProcessBanner />
        {list}
        <NotesPanel />
        {focus && (
          <Sheet title={`${focusRun?.ticker ?? "Analyst"} — play-by-play`} full className="an-sheet"
            onClose={() => setFocus(null)}>
            <AnalystRunDetail id={focus} />
          </Sheet>
        )}
      </>
    );
  }
  return (
    <>
    <ProcessBanner />
    <div className="an-layout">
      <div className="an-side">
        {list}
        <NotesPanel />
      </div>
      <div className="an-main">
        {sel ? <AnalystRunDetail id={sel} />
          : <div className="panel"><div className="panel-body empty">Select a run to see its play-by-play.</div></div>}
      </div>
    </div>
    </>
  );
}

/* ---------------------------------------------------------------- inbox */

// the latest scan's per-symbol flow reads, fetched once per page load
type FlowMap = Record<string, { score: number; lean: string }>;
let _flowCache: FlowMap | null = null;
let _flowFetch: Promise<FlowMap> | null = null;

export function useFlowMap(): FlowMap {
  const [flow, setFlow] = useState<FlowMap>(_flowCache ?? {});
  useEffect(() => {
    if (_flowCache) return;
    _flowFetch ??= api.flowDays(1)
      .then((d) => (d.length ? api.flowReads(d[0].day) : Promise.resolve([])))
      .then((reads) => (_flowCache = Object.fromEntries(
        reads.filter((r) => r.score > 0).map((r) => [r.symbol, { score: r.score, lean: r.lean }]))));
    _flowFetch.then((m) => setFlow(m ?? {})).catch(() => undefined);
  }, []);
  return flow;
}

/** "flow 7" chip when the options tape has something to say about a ticker —
    clicking opens the symbol's Flow story. */
export function FlowChip({ sym }: { sym: string }) {
  const setPage = useStore((s) => s.setPage);
  const setFlowFocus = useStore((s) => s.setFlowFocus);
  const flow = useFlowMap();
  const f = flow[sym];
  if (!f) return null;
  // quiet by design (less is more): the lean shows as a tiny glyph, not a color block
  const glyph = f.lean === "bull" ? "↑" : f.lean === "bear" ? "↓" : "·";
  return (
    <button className="status-pill dim" style={{ cursor: "pointer", border: "none" }}
      title={`options flow: ${f.lean}, score ${f.score} — open the story`}
      onClick={(e) => { e.stopPropagation(); setFlowFocus(sym); setPage("flow"); }}>
      flow {f.score}{glyph}
    </button>
  );
}

function InboxTab() {
  const signalCount = useStore((s) => s.signals.length);
  const itemsState = useAsync(
    () => api.get<RawContentItem[]>("/api/content?limit=25"), [signalCount]);
  const items = itemsState.data ?? [];
  const { isPhone } = useViewport();
  if (isPhone) {
    return (
      <div className="panel">
        <div className="panel-head">Inbound content</div>
        <div className="bl-cards">
          {items.length === 0 ? <div className="empty">Nothing received yet — email ingestion and pastes land here.</div>
            : items.map((c) => (
              <div key={c.id} className="bl-card bl-card--static">
                <span className="bl-card-l">
                  <span className="bl-card-sym">{c.subject || <span className="muted">(no subject)</span>}
                    <span className={`status-pill ${c.status === "extracted" ? "ok" : c.status === "error" ? "bad" : "dim"}`}>{c.status}</span></span>
                  <span className="bl-card-sub">{c.sourceName ?? c.sender ?? "—"} · {c.sourceType} · {fmtDateTime(c.receivedAt)} <CopyChip value={c.id} title={`extraction ${c.id} — click to copy`} /></span>
                  {c.preview && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{c.preview}</span>}
                </span>
              </div>
            ))}
        </div>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="panel-head">Inbound content <span className="sub">the raw material every tip was read from</span></div>
      <div className="scroll-x">
        {itemsState.loading && items.length === 0 ? (
          <Spinner />
        ) : itemsState.error ? (
          <ErrorState message={itemsState.error} onRetry={itemsState.reload} />
        ) : items.length === 0 ? (
          <div className="empty">Nothing received yet — email ingestion and pastes land here.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Source</th><th>Subject</th><th>Type</th><th>Status</th><th>Received</th>
                <th title="Quote an extraction's id to review how the content was read">Id</th></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} title={c.preview}>
                  <td>{c.sourceName ?? c.sender ?? "—"}</td>
                  <td>{c.subject || <span className="muted">(no subject)</span>}</td>
                  <td className="muted">{c.sourceType}</td>
                  <td><span className={`status-pill ${c.status === "extracted" ? "ok" : c.status === "error" ? "bad" : "dim"}`}>{c.status}</span></td>
                  <td className="muted">{fmtDateTime(c.receivedAt)}</td>
                  <td><CopyChip value={c.id} title={`extraction ${c.id} — click to copy`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
