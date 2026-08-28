// The Desk's pinned right pane: why this score, what to do about it, the
// flagged contracts, the repeat tracker + score sparkline, the context line,
// and the two actions that matter: the Story drill-down and Send to Tips.
import { useState } from "react";
import type { FlowReadItem, FlowStory } from "../../types";
import { api } from "../../lib/api";
import { useStore } from "../../store";
import { fmtOcc, fmtPrem, leanColor, leanPill, maxRepeat } from "./lib";

/** Plain-language "so what?" derived from the read's state — the answer to
    "wtf am I looking at" that raw evidence tables never give. */
export function whatNow(read: FlowReadItem): string {
  const flags = read.flags || [];
  const confirmed = (read.confirmed || []).length > 0;
  const repeat = maxRepeat(read);
  const tradeable = flags.some((f) => (f.dte ?? 0) >= 2);
  if (repeat >= 3 && confirmed) {
    return "Strongest pattern this scanner produces: the same contract bought day after day, and " +
      "yesterday's buying became real open positions overnight. Worth judging as a trade — send it to Tips.";
  }
  if (confirmed) {
    return "Yesterday's flagged buying was REAL (open interest rose overnight — new positions, not churn). " +
      "If it repeats again tomorrow, this becomes an accumulation story.";
  }
  if (!tradeable) {
    return "Everything flagged here expires within a day — expiry-board noise. The overnight verdict never " +
      "arrives for these; nothing to act on.";
  }
  return "First sighting — someone bought unusual size today, but it isn't proof yet. Tomorrow ~09:00 the " +
    "open-interest check says whether this was real position-taking or churn. Watch; don't chase.";
}

export function ScoreSparkline({ story, lean }: { story: FlowStory | null; lean: string }) {
  const reads = story?.reads ?? [];
  if (reads.length < 2) return <span className="muted" style={{ fontSize: "var(--fs-1)" }}>not enough history yet</span>;
  const max = Math.max(10, ...reads.map((r) => r.score));
  const w = 170; const h = 34; const pad = 4;
  const pts = reads.map((r, i) => {
    const x = pad + (i * (w - 2 * pad)) / Math.max(1, reads.length - 1);
    const y = h - pad - (r.score / max) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const [lx, ly] = pts[pts.length - 1].split(",");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-label="score history">
      <polyline points={pts.join(" ")} fill="none" stroke={leanColor(lean)} strokeWidth="2" />
      <circle cx={lx} cy={ly} r="3" fill={leanColor(lean)} />
    </svg>
  );
}

export function RepeatDots({ story, symbol }: { story: FlowStory | null; symbol: string }) {
  const reads = story?.reads ?? [];
  const window = reads.slice(-5);
  if (!window.length) return <span className="muted" style={{ fontSize: "var(--fs-1)" }}>—</span>;
  const flaggedDays = window.map((r) => (r.flags || []).length > 0);
  const n = flaggedDays.filter(Boolean).length;
  return (
    <span className="flow-dots" title={`${symbol} flagged on ${n} of the last ${window.length} scanned sessions`}>
      {window.map((on, i) => (
        <span key={i} className="flow-dot" style={{ background: on ? "var(--up)" : "var(--surface-3)" }} title={window[i] ? reads[reads.length - window.length + i].day : ""} />
      ))}
      <span className="muted" style={{ fontSize: "var(--fs-0)", marginLeft: 4 }}>{n} / {window.length}</span>
    </span>
  );
}

export function ReadDetail({ read, story, last, onStory }: {
  read: FlowReadItem;
  story: FlowStory | null;
  last: number | undefined;
  onStory: () => void;
}) {
  const setPage = useStore((s) => s.setPage);
  const setTechniqueTab = useStore((s) => s.setTechniqueTab);
  const openTrade = useStore((s) => s.openTrade);
  const toast = useStore((s) => s.toast);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const directional = read.lean === "bull" || read.lean === "bear";
  const sendToTips = async () => {
    if (sent) { setPage("inbox"); return; }
    setSending(true);
    try {
      const out = await api.flowToTip(read.symbol);
      const st = out?.signal?.status ?? "created";
      setSent(true);
      toast("success", `${read.symbol} sent to Tips (${String(st).replace("_", " ")}) — arm it there, or the morning sweep arms it in shadow`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSending(false);
    }
  };
  const contextLine = story?.deliveries?.[0]?.line
    ?? (read.reasons?.length ? `Options flow ${read.day}: score ${read.score} — ${read.reasons[0]}` : null);
  return (
    <div className="panel flow-detail">
      <div className="flow-detail-head">
        <span className="flow-detail-sym">{read.symbol}</span>
        {last != null && <span className="mono-num muted" style={{ fontSize: "var(--fs-3)" }}>{last.toFixed(2)}</span>}
        <span className={`status-pill ${leanPill(read.lean)}`}>{read.lean}</span>
        <span style={{ flex: 1 }} />
        <span className="mono-num" style={{ fontSize: "var(--fs-6)", fontWeight: 700 }}>
          {read.score}<span className="muted" style={{ fontSize: "var(--fs-1)" }}>/score</span>
        </span>
        <button className="ghost-btn flow-story-btn" onClick={onStory}
          title="The drill-down: how this read was built day by day, and where it went">
          The story →
        </button>
      </div>
      <div className="flow-detail-body">
        <div className="flow-whatnow">
          <div className="flow-lbl">What now</div>
          <div style={{ fontSize: "var(--fs-2)", color: "var(--text-2)", lineHeight: 1.5 }}>{whatNow(read)}</div>
        </div>

        <div>
          <div className="flow-lbl">Why this score</div>
          <div className="flow-reasons">
            {(read.reasons || []).map((r, i) => <div key={i}>• {r}</div>)}
            {(read.reasons || []).length === 0 && <div className="muted">no flags — a quiet chain this day</div>}
          </div>
        </div>

        {(read.flags || []).length > 0 && (
          <div>
            <div className="flow-lbl">Flagged contracts{read.flags.length > 6 ? ` — largest 6 of ${read.flags.length}` : ""}</div>
            <div className="scroll-x">
            <table className="tbl">
              <thead><tr><th>Contract</th><th className="num">Vol</th><th className="num">OI</th><th className="num">V/OI</th><th className="num">Prem</th><th className="num">OTM</th><th className="num">DTE</th></tr></thead>
              <tbody>
                {read.flags.slice(0, 6).map((f) => (
                  <tr key={f.contract}>
                    <td style={{ fontFamily: "var(--mono)" }}>{fmtOcc(f.contract)}</td>
                    <td className="num">{f.volume.toLocaleString()}</td>
                    <td className="num">{f.openInterest.toLocaleString()}</td>
                    <td className="num">{f.volOi.toFixed(1)}</td>
                    <td className="num">{fmtPrem(f.premium)}</td>
                    <td className="num">{f.otmPct.toFixed(1)}%</td>
                    <td className="num">{f.dte}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        )}

        {(read.confirmed || []).length > 0 && (
          <div>
            <div className="flow-lbl">Confirmed overnight</div>
            <div className="flow-reasons">
              {read.confirmed.map((c) => (
                <div key={c.contract}>
                  <span className="status-pill ok">OI +{(c.oiDelta ?? 0).toLocaleString()}</span>{" "}
                  <span style={{ fontFamily: "var(--mono)" }}>{fmtOcc(c.contract)}</span>{" "}
                  <span className="muted">vs {c.volume.toLocaleString()} traded — the volume really opened positions</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flow-detail-duo">
          <div className="flow-mini-card">
            <div className="flow-lbl">Repeat tracker</div>
            <RepeatDots story={story} symbol={read.symbol} />
            {maxRepeat(read) > 0 && <div className="muted" style={{ fontSize: "var(--fs-0)", marginTop: 4 }}>hot: {Object.entries(read.repeatHits).map(([c, n]) => `${fmtOcc(c)} ×${n}`).join(", ")}</div>}
          </div>
          <div className="flow-mini-card">
            <div className="flow-lbl">Score history</div>
            <ScoreSparkline story={story} lean={read.lean} />
          </div>
        </div>

        {contextLine && (
          <div className="flow-context-box">
            <div className="flow-lbl" style={{ color: "var(--accent)" }}>What Tips &amp; EM see</div>
            <div className="flow-context-line">{contextLine}</div>
          </div>
        )}

        <div className="flow-actions">
          <button className="primary-btn" disabled={sending || !directional}
            title={directional
              ? "Make this read a TIP (source: flow-scan): it enters both shadow books, can be armed at a level, and builds flow-scan's own track record — YOU are the judge, Flow is just the evidence"
              : "Two-sided or directionless flow — no side to trade"}
            onClick={sendToTips}>
            {sending ? "Sending…" : sent ? "View in Tips →" : "Send to Tips"}
          </button>
          <button className="ghost-btn" onClick={() => { setTechniqueTab("analyse"); setPage("technique"); }}>Analyze in EM</button>
          <button className="ghost-btn" onClick={() => useStore.setState({ optionsUnderlying: read.symbol, page: "options" })}>Open chain</button>
          <button className="ghost-btn" onClick={() => openTrade(read.symbol)}>Chart</button>
        </div>
      </div>
    </div>
  );
}
