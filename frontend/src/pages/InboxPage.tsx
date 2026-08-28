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

/* The Tips page (redesigned 2026-08-28): the composer is the product — paste
   text or a screenshot, the app extracts the trade AND the source, verifies it
   against the live market and shows what both shadow books did with it.
   Tabs: New tip · Tips · Sources · Inbox; pending proposals ride above the
   tabs as an attention strip (they expire in minutes). */

type Tab = "compose" | "tips" | "sources" | "analyst" | "inbox";
const TABS: Tab[] = ["compose", "tips", "sources", "analyst", "inbox"];

export function InboxPage() {
  const pageTab = useStore((s) => s.pageTab);
  const setPageTab = useStore((s) => s.setPageTab);
  const tab: Tab = (TABS as string[]).includes(pageTab) ? (pageTab as Tab) : "compose";
  const setTab = (t: Tab) => setPageTab(t);
  const proposals = useStore((s) => s.proposals);
  const signals = useStore((s) => s.signals);
  return (
    <div className="tips-page">
      <div className="tips-head">
        <h2 className="page-title">Tips</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "compose"} className={tab === "compose" ? "active" : ""}
            onClick={() => setTab("compose")}>New tip</button>
          <button role="tab" aria-selected={tab === "tips"} className={tab === "tips" ? "active" : ""}
            onClick={() => setTab("tips")}>Tips{signals.length ? ` · ${signals.length}` : ""}</button>
          <button role="tab" aria-selected={tab === "sources"} className={tab === "sources" ? "active" : ""}
            onClick={() => setTab("sources")}>Sources</button>
          <button role="tab" aria-selected={tab === "analyst"} className={tab === "analyst" ? "active" : ""}
            onClick={() => setTab("analyst")}>Analyst</button>
          <button role="tab" aria-selected={tab === "inbox"} className={tab === "inbox" ? "active" : ""}
            onClick={() => setTab("inbox")}>Inbox</button>
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

function statusPill(status: string): string {
  if (status === "verified" || status === "proposed") return "ok";
  if (status === "parked" || status === "shadow") return "wait";
  if (status === "verification_failed") return "bad";
  return "dim";
}

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
    return <span className="status-pill dim" title={`Immediate book bought ${expr.contracts ?? "?"}× ${expr.display ?? expr.contract}`}>
      {expr.display ?? "option"}{expr.contracts ? ` ×${expr.contracts}` : ""}</span>;
  }
  if (expr.fallback) {
    return <span className="status-pill wait" title={`Wanted the option but: ${expr.fallback}`}>shares (fallback)</span>;
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
  return (
    <div className="proposal-card">
      <div className="head">
        <span className="sym">{p.symbol}</span>
        <span className={p.side === "BUY" ? "pos" : "neg"}>
          <b>{p.side}</b> {p.qty} @ {p.orderType} {p.limitPrice ? fmtMoney(p.limitPrice) : ""}
        </span>
        <span className="ttl"><IconClock size={11} /> {timeUntil(p.expiresAt)}</span>
        {p.signalId && <CopyChip value={p.signalId}
          title={`tip ${p.signalId} — click to copy; quote this id to review the tip behind this proposal`} />}
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        {p.context?.sourceName ?? "unknown source"} · {p.context?.confidence ?? "?"}
        {sizing && <> · sized at {sizing.pct}% of ${fmtMoney(sizing.equity, 0)}</>}
        {p.bracket?.take_profit && <> · target {fmtMoney(p.bracket.take_profit)}</>}
        {p.bracket?.stop_loss && <> · stop {fmtMoney(p.bracket.stop_loss)}</>}
      </div>
      {p.rationale && <div style={{ margin: "6px 0", fontStyle: "italic" }}>{p.rationale}</div>}
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
  const loadedState = useAsync(
    () => api.get<Signal[]>("/api/signals?limit=50"), [live.length]);
  const merged = [...live];
  for (const s of loadedState.data ?? []) if (!merged.some((m) => m.id === s.id)) merged.push(s);
  const { isPhone } = useViewport();

  if (isPhone) {
    return (
      <div className="panel mb">
        <div className="panel-head">Tips</div>
        <div className="bl-cards">
          {loadedState.loading && merged.length === 0 ? <Spinner />
            : merged.length === 0 ? <div className="empty">No tips yet — add one from the New tip tab.</div>
            : merged.slice(0, 30).map((s) => {
              const failed = (s.verification?.checks ?? []).filter((c) => !c.passed);
              const contract = contractLabel(s);
              return (
                <div key={s.id} className="bl-card bl-card--static">
                  <span className="bl-card-l">
                    <span className="bl-card-sym">{s.ticker} <span className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</span>
                      {contract && <span className="muted"> {contract}</span>}
                      <span className={`status-pill ${statusPill(s.status)}`}>{s.status.replace("_", " ")}</span>
                      {(s.seenCount ?? 1) > 1 && <span className="status-pill dim">×{s.seenCount}</span>}
                      <FlowChip sym={s.ticker} />
                    </span>
                    <span className="bl-card-sub">entry {s.entryPrice ? fmtMoney(s.entryPrice) : "—"} · target {s.targetPrice ? fmtMoney(s.targetPrice) : "—"} · stop {s.stopPrice ? fmtMoney(s.stopPrice) : "—"} · {s.confidence.replace("_", " ")}</span>
                    {s.thesisSummary && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.thesisSummary}</span>}
                    {s.verification?.flowContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.verification.flowContext}</span>}
                    {s.verification?.calendarContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>⚠ {s.verification.calendarContext}</span>}
                    {failed.length > 0 && <span className="bl-card-sub neg" style={{ whiteSpace: "normal" }}>{failed.map((c) => c.detail || c.name).join("; ")}</span>}
                    <span className="bl-card-sub">{s.sourceName ?? "—"} · {fmtDateTime(s.createdAt)} <CopyChip value={s.id} title={`tip ${s.id} — click to copy`} /> <ArmButton s={s} /></span>
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
      <div className="panel-head">Tips <span className="sub">every tip the app has read, newest first</span></div>
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
                <th>Ticker</th><th>Dir</th><th>Contract</th><th>Book vehicle</th><th>Conf</th><th className="num">Entry</th>
                <th className="num">Tgt/Stop</th><th>Status</th><th>Source</th><th>When</th>
                <th title="Quote a tip's id to review its extract & verify">Id</th>
              </tr>
            </thead>
            <tbody>
              {merged.slice(0, 50).map((s) => (
                <tr key={s.id}
                  title={[s.thesisSummary, s.verification?.flowContext,
                    s.verification?.calendarContext].filter(Boolean).join("\n")}>
                  <td><b>{s.ticker}</b>{(s.seenCount ?? 1) > 1 && <span className="muted"> ×{s.seenCount}</span>} <FlowChip sym={s.ticker} /></td>
                  <td className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</td>
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
                      {s.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="muted">{s.sourceName ?? "—"}</td>
                  <td className="muted">{fmtDateTime(s.createdAt)} <ArmButton s={s} /></td>
                  <td><CopyChip value={s.id} title={`tip ${s.id} — click to copy`} /></td>
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

function PeekButton({ channelId }: { channelId: string }) {
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
  const [processing, setProcessing] = useState(false);
  const process = async () => {
    setProcessing(true);
    try {
      await api.discordProcessLast(channelId);
      toast("info", "Processing last message as a tip — watch the Analyst tab");
    } catch (e: any) { toast("error", e.message); }
    finally { setProcessing(false); }
  };
  return (
    <span className="disc-peek">
      <button className="link-btn" disabled={state === "loading"} onClick={test}
        title="Fetch this channel's last message to confirm it's connected">
        {state === "loading" ? "testing…" : "test"}
      </button>
      <button className="link-btn" disabled={processing} onClick={process}
        title="Process this channel's last message as a tip (runs extraction + analyst)">
        {processing ? "…" : "▶ tip"}
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
        botsOnly: kind === "channel", enabled: true,
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
        <label className="disc-toggle">
          <input type="checkbox" checked={on}
            onChange={() => toggle(channelId, kind, name, guildName ?? "", name)} />
          <span>{kind === "channel" ? "#" : ""}{name}{isBot ? <span className="muted"> · bot</span> : null}</span>
        </label>
        <PeekButton channelId={channelId} />
        {on && (
          <span className="disc-opts">
            <input className="disc-src" value={sel[channelId].sourceName}
              title="source name (its own scorecard)"
              onChange={(e) => setField(channelId, { sourceName: e.target.value })} />
            <label className="muted" title="only ingest posts from a bot in this channel">
              <input type="checkbox" checked={!!sel[channelId].botsOnly}
                onChange={(e) => setField(channelId, { botsOnly: e.target.checked })} /> bots only
            </label>
          </span>
        )}
      </div>
    );
  };

  const dms = (cat?.dms ?? []).filter((d) => hit(d.name) && (!monitoredOnly || sel[d.channelId]));
  const guilds = (cat?.guilds ?? []).map((g) => {
    const chans = g.channels.filter((c) => (hit(c.name) || hit(g.guildName))
      && (!monitoredOnly || sel[c.channelId]));
    return { ...g, shown: chans };
  }).filter((g) => g.shown.length > 0);

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
                <div className="disc-head">Direct messages {dms.length ? `(${dms.length})` : ""}</div>
                {dms.length === 0 ? <div className="muted">none match</div>
                  : dms.map((d) => (
                    <Row key={d.channelId} channelId={d.channelId} name={d.name} kind="dm" isBot={d.isBot} />
                  ))}
              </div>
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
                        {isOpen && g.shown.map((c) => (
                          <Row key={c.channelId} channelId={c.channelId} name={c.name}
                            kind="channel" guildName={g.guildName} />
                        ))}
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
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

const STEP_META: Record<string, { icon: string; cls: string; label: string }> = {
  start: { icon: "▶", cls: "dim", label: "start" },
  llm: { icon: "🧠", cls: "", label: "analyst" },
  tool_call: { icon: "→", cls: "wait", label: "tool call" },
  tool_result: { icon: "←", cls: "ok", label: "tool result" },
  note: { icon: "•", cls: "dim", label: "note" },
  final: { icon: "✓", cls: "ok", label: "verdict" },
  error: { icon: "✕", cls: "bad", label: "error" },
};

function StepRow({ s }: { s: AnalystStep }) {
  const m = STEP_META[s.kind] ?? { icon: "•", cls: "dim", label: s.kind };
  return (
    <div className="an-step">
      <span className={`an-kind status-pill ${m.cls}`}>{m.icon} {m.label}</span>
      <div className="an-body">
        <div className="an-text">{s.text}</div>
        {s.kind === "tool_result" && s.result != null && (
          <pre className="an-json">{JSON.stringify(s.result, null, 1).slice(0, 1200)}</pre>
        )}
      </div>
    </div>
  );
}

function AnalystRunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<AnalystRun | null>(null);
  const [live, setLive] = useState<AnalystStep[]>([]);
  useEffect(() => {
    setRun(null); setLive([]);
    let dead = false;
    api.analystRun(id).then((r) => !dead && setRun(r)).catch(() => undefined);
    // live: append steps for THIS run as they stream in
    const off = onAnalystStep(({ runId, step }) => {
      if (runId === id) setLive((prev) => prev.some((p) => p.seq === step.seq) ? prev : [...prev, step]);
    });
    return () => { dead = true; off(); };
  }, [id]);
  // if the run is still running, poll once more when live stops arriving
  useEffect(() => {
    if (run && run.status === "running") {
      const t = setInterval(() => api.analystRun(id).then((r) => {
        setRun(r); if (r.status !== "running") clearInterval(t);
      }).catch(() => undefined), 4000);
      return () => clearInterval(t);
    }
  }, [run?.status, id]);

  if (!run) return <Spinner />;
  // merge persisted trace with any live steps not yet persisted
  const bySeq = new Map<number, AnalystStep>();
  for (const s of run.trace) bySeq.set(s.seq, s);
  for (const s of live) if (!bySeq.has(s.seq)) bySeq.set(s.seq, s);
  const steps = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  const running = run.status === "running";
  return (
    <div className="panel an-detail">
      <div className="panel-head">
        {run.ticker} · {run.source ?? "?"}
        <span className={`status-pill ${running ? "wait" : run.verdict === "take" ? "ok" : run.verdict === "skip" ? "bad" : "dim"}`}>
          {running ? "running…" : run.verdict ?? run.status}
        </span>
        <CopyChip value={run.id} title={`analyst run ${run.id} — click to copy; quote it to review/tune`} />
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 11 }}>
          {run.model} · {run.tools.length} tools available
        </span>
      </div>
      <div className="panel-body">
        <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
          Tools available: {run.tools.join(", ")}
        </div>
        <div className="an-steps">
          {steps.map((s) => <StepRow key={s.seq} s={s} />)}
          {running && <div className="an-step"><span className="an-kind status-pill wait">…</span>
            <div className="an-body"><div className="muted">working…</div></div></div>}
        </div>
        {run.error && <div className="neg" style={{ fontSize: 12, marginTop: 8 }}>{run.error}</div>}
      </div>
    </div>
  );
}

function AnalystTab() {
  const signalCount = useStore((s) => s.signals.length);
  const state = useAsync(() => api.analystRuns(50), [signalCount]);
  const [selected, setSelected] = useState<string | null>(null);
  const [bump, setBump] = useState(0);
  // a fresh run streaming in refreshes the list + auto-opens the newest
  useEffect(() => {
    const off = onAnalystStep(({ runId, step }) => {
      if (step.kind === "start") { setSelected(runId); setBump((b) => b + 1); }
    });
    return off;
  }, []);
  useEffect(() => { if (bump) state.reload(); }, [bump]);
  const runs = state.data ?? [];
  const sel = selected ?? runs[0]?.id ?? null;
  return (
    <div className="an-layout">
      <div className="panel an-list">
        <div className="panel-head">Analyst runs <span className="sub">the play-by-play of each appraisal</span></div>
        <div className="an-list-body">
          {state.loading && runs.length === 0 ? <Spinner />
            : runs.length === 0 ? <div className="empty">No analyst runs yet — a tip triggers one.</div>
            : runs.map((r) => (
              <button key={r.id} className={`an-run ${r.id === sel ? "active" : ""}`}
                onClick={() => setSelected(r.id)}>
                <span className="an-run-l">
                  <b>{r.ticker}</b>
                  <span className={`status-pill ${r.status === "running" ? "wait" : r.verdict === "take" ? "ok" : r.verdict === "skip" ? "bad" : "dim"}`}>
                    {r.status === "running" ? "running" : r.verdict ?? r.status}
                  </span>
                </span>
                <span className="an-run-sub">{r.source ?? "?"} · {r.traceSteps} steps · {r.createdAt ? fmtDateTime(r.createdAt) : ""}</span>
              </button>
            ))}
        </div>
      </div>
      <div className="an-main">
        {sel ? <AnalystRunDetail id={sel} />
          : <div className="panel"><div className="panel-body empty">Select a run to see its play-by-play.</div></div>}
      </div>
    </div>
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
  const cls = f.lean === "bull" ? "ok" : f.lean === "bear" ? "bad" : "wait";
  return (
    <button className={`status-pill ${cls}`} style={{ cursor: "pointer", border: "none" }}
      title={`options flow: ${f.lean}, score ${f.score} — open the story`}
      onClick={(e) => { e.stopPropagation(); setFlowFocus(sym); setPage("flow"); }}>
      flow {f.score}
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
