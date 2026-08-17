import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney, timeUntil } from "../lib/format";
import { useStore } from "../store";
import type { Proposal, RawContentItem, Signal } from "../types";

export function InboxPage() {
  const proposals = useStore((s) => s.proposals);
  return (
    <div>
      <h2 className="page-title">Signals &amp; proposals</h2>
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
        </div>
        <div>
          <SignalsPanel />
          <ContentPanel />
        </div>
      </div>
    </div>
  );
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
        <span className="ttl">⏳ {timeUntil(p.expiresAt)}</span>
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        {p.context?.sourceName ?? "unknown source"} · {p.context?.confidence ?? "?"}
        {sizing && <> · sized at {sizing.pct}% of ${fmtMoney(sizing.equity, 0)}</>}
        {p.bracket?.take_profit && <> · target {fmtMoney(p.bracket.take_profit)}</>}
        {p.bracket?.stop_loss && <> · stop {fmtMoney(p.bracket.stop_loss)}</>}
      </div>
      {p.rationale && <div style={{ margin: "6px 0", fontStyle: "italic" }}>{p.rationale}</div>}
      <div className="check-grid">
        {checks.map((c: any) => (
          <span key={c.name} className={`check-item ${c.passed ? "ok" : "fail"}`}
            title={c.detail}>
            {c.passed ? "✓" : "✗"} {c.name.replace(/_/g, " ")}
          </span>
        ))}
      </div>
      <div className="proposal-actions">
        <button className="approve-btn" disabled={busy}
          onClick={() => act(() => api.approveProposal(p.id), `Approved ${p.symbol}`)}>
          ✓ Approve
        </button>
        <button className="half-btn" disabled={busy}
          onClick={() => act(() => api.approveProposal(p.id, true), `Approved ${p.symbol} (half)`)}>
          ½ size
        </button>
        <button className="reject-btn" disabled={busy}
          onClick={() => act(() => api.rejectProposal(p.id), `Rejected ${p.symbol}`)}>
          ✗ Reject
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

  const run = async () => {
    setBusy(true);
    setResult("");
    try {
      const out = await api.ingestManual(text, source, "manual paste");
      if (out.note) setResult(out.note);
      else {
        const n = out.signals?.length ?? 0;
        setResult(`Extracted ${n} signal${n === 1 ? "" : "s"}.`);
        if (n > 0) toast("success", `Extracted ${n} signal(s) from pasted text`);
      }
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        Test the pipeline <span className="sub">paste newsletter text, no email setup needed</span>
      </div>
      <div className="panel-body">
        <label className="field">
          <span>Source name (matches trust stats later)</span>
          <input type="text" value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label className="field">
          <span>Content</span>
          <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="ALERT: We are buying AAPL today. Entry at $230, stop $220, target $260…" />
        </label>
        <button className="primary-btn" disabled={busy || !text.trim()} onClick={run}>
          {busy ? "Extracting…" : "Run extraction"}
        </button>
        {result && <div className="muted" style={{ marginTop: 8 }}>{result}</div>}
      </div>
    </div>
  );
}

function SignalsPanel() {
  const live = useStore((s) => s.signals);
  const [loaded, setLoaded] = useState<Signal[]>([]);
  useEffect(() => {
    api.get<Signal[]>("/api/signals?limit=50").then(setLoaded).catch(() => undefined);
  }, [live.length]);
  const merged = [...live];
  for (const s of loaded) if (!merged.some((m) => m.id === s.id)) merged.push(s);

  return (
    <div className="panel mb">
      <div className="panel-head">Extracted signals</div>
      <div className="scroll-x">
        {merged.length === 0 ? (
          <div className="empty">No signals yet — ingest an email or paste text</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Ticker</th><th>Dir</th><th>Conf</th><th className="num">Entry</th>
                <th className="num">Tgt/Stop</th><th>Status</th><th>Source</th><th>When</th>
              </tr>
            </thead>
            <tbody>
              {merged.slice(0, 50).map((s) => (
                <tr key={s.id} title={s.thesisSummary ?? ""}>
                  <td><b>{s.ticker}</b></td>
                  <td className={s.direction === "long" ? "pos" : "neg"}>{s.direction}</td>
                  <td className="muted">{s.confidence.replace("_", " ")}</td>
                  <td className="num">{s.entryPrice ? fmtMoney(s.entryPrice) : "—"}</td>
                  <td className="num muted">
                    {s.targetPrice ? fmtMoney(s.targetPrice) : "—"}/{s.stopPrice ? fmtMoney(s.stopPrice) : "—"}
                  </td>
                  <td>
                    <span className={`status-pill ${
                      s.status === "verified" || s.status === "proposed" ? "ok"
                      : s.status === "verification_failed" ? "bad" : "dim"}`}
                      title={(s.verification?.checks ?? [])
                        .filter((c) => !c.passed).map((c) => c.detail || c.name).join("; ")}>
                      {s.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="muted">{s.sourceName ?? "—"}</td>
                  <td className="muted">{fmtDateTime(s.createdAt)}</td>
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
  const [items, setItems] = useState<RawContentItem[]>([]);
  const signalCount = useStore((s) => s.signals.length);
  useEffect(() => {
    api.get<RawContentItem[]>("/api/content?limit=25").then(setItems).catch(() => undefined);
  }, [signalCount]);
  return (
    <div className="panel">
      <div className="panel-head">Inbound content</div>
      <div className="scroll-x">
        {items.length === 0 ? (
          <div className="empty">Nothing received yet</div>
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
