import { useEffect, useState } from "react";
import { IconCheck, IconClock, IconHalf, IconX } from "../components/icons";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney, timeUntil } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useStore } from "../store";
import type { Proposal, RawContentItem, Signal, SourceScorecard } from "../types";
import { useViewport } from "../lib/viewport";

export function InboxPage() {
  const proposals = useStore((s) => s.proposals);
  return (
    <div>
      <h2 className="page-title">Tips &amp; proposals</h2>
      <div className="grid-2col">
        <div>
          <div className="panel mb">
            <div className="panel-head">
              Pending proposals
              <span className="sub">{proposals.length} awaiting your decision</span>
            </div>
            <div className="panel-body">
              {proposals.length === 0 && <div className="empty">Nothing waiting for approval</div>}
              {proposals.map((p) => <ProposalCard key={p.id} p={p} />)}
            </div>
          </div>
          <ManualIngest />
          <SourcesPanel />
        </div>
        <div>
          <SignalsPanel />
          <ContentPanel />
        </div>
      </div>
    </div>
  );
}

function statusPill(status: string): string {
  if (status === "verified" || status === "proposed") return "ok";
  if (status === "parked") return "wait";
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
      <div className="check-grid">
        {checks.filter((c: any) => c.passed).map((c: any) => (
          <span key={c.name} className="check-item ok" title={c.detail}>
            <IconCheck size={10} /> {c.name.replace(/_/g, " ")}
          </span>
        ))}
      </div>
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

function ManualIngest() {
  const toast = useStore((s) => s.toast);
  const [text, setText] = useState("");
  const [source, setSource] = useState("manual");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>("");
  const [image, setImage] = useState<string | null>(null);   // data URL

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

  const run = async () => {
    setBusy(true);
    setResult("");
    try {
      const out = await api.ingestManual(text, source, "manual paste", image ?? undefined);
      if (out.note) setResult(out.note);
      else {
        const n = out.signals?.length ?? 0;
        setResult(`Extracted ${n} signal${n === 1 ? "" : "s"}.`);
        if (n > 0) toast("success", `Extracted ${n} signal(s)`);
      }
      if (!out.note) setImage(null);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel mb">
      <div className="panel-head">
        Add a tip <span className="sub">paste text or a screenshot of your own chat client</span>
      </div>
      <div className="panel-body">
        <label className="field">
          <span>Source name (builds this source's track record)</span>
          <input type="text" value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label className="field">
          <span>Content — text, or paste a screenshot right here</span>
          <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} onPaste={onPaste}
            placeholder="NVDA 180c 9/19 🚀 … or: ALERT: buying AAPL, entry $230, stop $220, target $260" />
        </label>
        {image && (
          <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <img src={image} alt="tip screenshot" style={{ maxHeight: 90, maxWidth: "60%", borderRadius: 4 }} />
            <button className="link-btn danger" onClick={() => setImage(null)}>remove screenshot</button>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="primary-btn" disabled={busy || (!text.trim() && !image)} onClick={run}>
            {busy ? "Extracting…" : "Run extraction"}
          </button>
          <label className="link-btn" style={{ cursor: "pointer" }}>
            attach screenshot…
            <input type="file" accept="image/*" style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ""; }} />
          </label>
        </div>
        {result && <div className="muted" style={{ marginTop: 8 }}>{result}</div>}
      </div>
    </div>
  );
}

function BookCell({ b }: { b?: { pnl?: number | null; pnlPct?: number | null } }) {
  const pnl = b?.pnl;
  if (pnl == null) return <td className="num muted">—</td>;
  return (
    <td className={`num ${pnl > 0 ? "pos" : pnl < 0 ? "neg" : "muted"}`}>
      {fmtMoney(pnl)} ({(b?.pnlPct ?? 0).toFixed(1)}%)
    </td>
  );
}

function SourcesPanel() {
  const signalCount = useStore((s) => s.signals.length);
  const state = useAsync(() => api.sourceScorecards(), [signalCount]);
  const cards = state.data ?? [];
  return (
    <div className="panel">
      <div className="panel-head">
        Source scorecards
        <span className="sub">two books per source: buy-at-tip-time vs wait-for-the-level</span>
      </div>
      <div className="scroll-x">
        {state.loading && cards.length === 0 ? <Spinner />
          : cards.length === 0 ? (
            <EmptyState title="No sources yet" hint="Every tip source gets two shadow books and a track record." />
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
                    <BookCell b={c.books?.armed} />
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
  );
}

function ArmButton({ s }: { s: Signal }) {
  const toast = useStore((st) => st.toast);
  const [busy, setBusy] = useState(false);
  if (s.status !== "verified" && s.status !== "parked") return null;
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

function SignalsPanel() {
  const live = useStore((s) => s.signals);
  const loadedState = useAsync(
    () => api.get<Signal[]>("/api/signals?limit=50"), [live.length]);
  const merged = [...live];
  for (const s of loadedState.data ?? []) if (!merged.some((m) => m.id === s.id)) merged.push(s);
  const { isPhone } = useViewport();

  if (isPhone) {
    return (
      <div className="panel mb">
        <div className="panel-head">Extracted signals</div>
        <div className="bl-cards">
          {loadedState.loading && merged.length === 0 ? <Spinner />
            : merged.length === 0 ? <EmptyState title="No signals yet" hint="Ingest an email or paste text below." />
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
                    </span>
                    <span className="bl-card-sub">entry {s.entryPrice ? fmtMoney(s.entryPrice) : "—"} · target {s.targetPrice ? fmtMoney(s.targetPrice) : "—"} · stop {s.stopPrice ? fmtMoney(s.stopPrice) : "—"} · {s.confidence.replace("_", " ")}</span>
                    {s.thesisSummary && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.thesisSummary}</span>}
                    {s.verification?.flowContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>{s.verification.flowContext}</span>}
                    {s.verification?.calendarContext && <span className="bl-card-sub" style={{ whiteSpace: "normal" }}>⚠ {s.verification.calendarContext}</span>}
                    {failed.length > 0 && <span className="bl-card-sub neg" style={{ whiteSpace: "normal" }}>{failed.map((c) => c.detail || c.name).join("; ")}</span>}
                    <span className="bl-card-sub">{s.sourceName ?? "—"} · {fmtDateTime(s.createdAt)} <ArmButton s={s} /></span>
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
      <div className="panel-head">Extracted signals</div>
      <div className="scroll-x">
        {loadedState.loading && merged.length === 0 ? (
          <Spinner />
        ) : loadedState.error && merged.length === 0 ? (
          <ErrorState message={loadedState.error} onRetry={loadedState.reload} />
        ) : merged.length === 0 ? (
          <EmptyState title="No signals yet" hint="Ingest an email or paste text below." />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Ticker</th><th>Dir</th><th>Contract</th><th>Conf</th><th className="num">Entry</th>
                <th className="num">Tgt/Stop</th><th>Status</th><th>Source</th><th>When</th>
              </tr>
            </thead>
            <tbody>
              {merged.slice(0, 50).map((s) => (
                <tr key={s.id}
                  title={[s.thesisSummary, s.verification?.flowContext,
                    s.verification?.calendarContext].filter(Boolean).join("\n")}>
                  <td><b>{s.ticker}</b>{(s.seenCount ?? 1) > 1 && <span className="muted"> ×{s.seenCount}</span>}</td>
                  <td className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</td>
                  <td className="muted">{contractLabel(s) ?? "—"}</td>
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ContentPanel() {
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
          {items.length === 0 ? <EmptyState title="Nothing received yet" hint="Email ingestion and manual paste both land here." />
            : items.map((c) => (
              <div key={c.id} className="bl-card bl-card--static">
                <span className="bl-card-l">
                  <span className="bl-card-sym">{c.subject || <span className="muted">(no subject)</span>}
                    <span className={`status-pill ${c.status === "extracted" ? "ok" : c.status === "error" ? "bad" : "dim"}`}>{c.status}</span></span>
                  <span className="bl-card-sub">{c.sourceName ?? c.sender ?? "—"} · {c.sourceType} · {fmtDateTime(c.receivedAt)}</span>
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
      <div className="panel-head">Inbound content</div>
      <div className="scroll-x">
        {itemsState.loading && items.length === 0 ? (
          <Spinner />
        ) : itemsState.error ? (
          <ErrorState message={itemsState.error} onRetry={itemsState.reload} />
        ) : items.length === 0 ? (
          <EmptyState title="Nothing received yet"
            hint="Email ingestion and manual paste both land here." />
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Source</th><th>Subject</th><th>Type</th><th>Status</th><th>Received</th></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} title={c.preview}>
                  <td>{c.sourceName ?? c.sender ?? "—"}</td>
                  <td>{c.subject || <span className="muted">(no subject)</span>}</td>
                  <td className="muted">{c.sourceType}</td>
                  <td><span className={`status-pill ${c.status === "extracted" ? "ok" : c.status === "error" ? "bad" : "dim"}`}>{c.status}</span></td>
                  <td className="muted">{fmtDateTime(c.receivedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
