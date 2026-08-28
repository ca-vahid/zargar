// The drill-down (Option D): how a read was built day by day — snapshot →
// flags → overnight OI verdict → repeat streak → score — plus the score/premium
// buildup chart and "where this read went" (journaled context deliveries).
import type { FlowStory } from "../../types";
import { useStore } from "../../store";
import { fmtOcc, fmtPrem, leanColor, leanPill } from "./lib";

function DayColumn({ story, idx }: { story: FlowStory; idx: number }) {
  const r = story.reads[idx];
  const next = story.reads[idx + 1];
  const isLast = idx === story.reads.length - 1;
  // the verdict on THIS day's flags arrives with the NEXT day's read
  const verdicts = (next?.confirmed || []).filter((c) => (r.flags || []).some((f) => f.contract === c.contract));
  const rep = Math.max(0, ...Object.values(r.repeatHits || {}), 0);
  return (
    <div className={`flow-daycol ${isLast ? "flow-daycol-now" : ""}`} style={{ opacity: isLast ? 1 : 0.55 + 0.45 * (idx / Math.max(1, story.reads.length - 1)) }}>
      <div className="flow-daycol-head">
        <b>{r.day.slice(5)}</b>
        <span className="mono-num" style={{ fontSize: "var(--fs-0)", color: r.score > 0 ? leanColor(r.lean) : "var(--text-3)" }}>score {r.score}</span>
      </div>
      {(r.flags || []).length === 0
        ? <div className="flow-stage"><span className="flow-stage-dot" style={{ background: "var(--surface-3)" }} /><span className="muted">quiet day — no flags</span></div>
        : r.flags.slice(0, 2).map((f) => (
          <div key={f.contract} className="flow-stage">
            <span className="flow-stage-dot" style={{ background: "var(--up)" }} />
            <span>flag <span style={{ fontFamily: "var(--mono)" }}>{fmtOcc(f.contract)}</span> {fmtPrem(f.premium)} · V/OI {f.volOi.toFixed(1)}{f.strong ? " · strong" : ""}</span>
          </div>
        ))}
      {verdicts.length > 0 && (
        <div className="flow-stage">
          <span className="flow-stage-dot" style={{ background: "var(--up)" }} />
          <span>next morning: <b className="pos">OI ✓ +{(verdicts[0].oiDelta ?? 0).toLocaleString()}</b></span>
        </div>
      )}
      {isLast && (r.flags || []).length > 0 && verdicts.length === 0 && (
        <div className="flow-stage"><span className="flow-stage-dot" style={{ background: "var(--surface-3)" }} /><span className="muted">OI verdict tomorrow ~09:00</span></div>
      )}
      {rep > 0 && (
        <div className="flow-stage">
          <span className="flow-stage-dot" style={{ background: "var(--warn)" }} />
          <span style={{ color: rep >= 3 ? "var(--warn)" : undefined }}>repeat {rep}/5{rep >= 3 ? " — accumulation" : ""}</span>
        </div>
      )}
    </div>
  );
}

function BuildupChart({ story }: { story: FlowStory }) {
  const reads = story.reads;
  if (reads.length < 2) return <div className="empty">not enough sessions yet — the story grows one scan a day</div>;
  const W = 640; const H = 240; const padB = 26; const padT = 10;
  const maxScore = Math.max(10, ...reads.map((r) => r.score));
  const maxPrem = Math.max(1, ...reads.map((r) => (r.flags || []).reduce((s, f) => s + f.premium, 0)));
  const n = reads.length;
  const slot = W / n;
  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="score and premium buildup">
      {[0.25, 0.5, 0.75].map((g) => (
        <line key={g} x1="0" y1={padT + (H - padT - padB) * g} x2={W} y2={padT + (H - padT - padB) * g} stroke="var(--grid)" strokeWidth="1" />
      ))}
      {reads.map((r, i) => {
        const prem = (r.flags || []).reduce((s, f) => s + f.premium, 0);
        const bh = ((H - padT - padB) * prem) / maxPrem;
        return <rect key={r.day} x={i * slot + slot * 0.22} y={H - padB - bh} width={slot * 0.4} height={bh} fill="rgba(12,163,12,0.3)" />;
      })}
      <polyline fill="none" stroke="var(--up)" strokeWidth="2.5"
        points={reads.map((r, i) => `${i * slot + slot * 0.42},${padT + (H - padT - padB) * (1 - r.score / maxScore)}`).join(" ")} />
      {reads.map((r, i) => (
        <text key={r.day} x={i * slot + slot * 0.42} y={H - 8} fill="var(--text-3)" fontSize="12" textAnchor="middle">{r.day.slice(5)}</text>
      ))}
    </svg>
  );
}

const CONSUMER_LABEL: Record<string, string> = { tip: "Tip", em: "EM", api: "API" };

export function SymbolStory({ story, onBack }: { story: FlowStory; onBack: () => void }) {
  const setPage = useStore((s) => s.setPage);
  const latest = story.reads[story.reads.length - 1];
  return (
    <div className="flow-story">
      <div className="flow-story-head">
        <button className="link-btn" onClick={onBack}>← back to the read</button>
        <span className="flow-detail-sym">{story.symbol}</span>
        {latest && <span className={`status-pill ${leanPill(latest.lean)}`}>{latest.lean}</span>}
        {latest && <span className="mono-num" style={{ fontSize: "var(--fs-5)", fontWeight: 700, color: leanColor(latest?.lean || "none") }}>score {latest.score}</span>}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: "var(--fs-1)" }}>how this read was built, day by day</span>
      </div>

      <div className="flow-daycols">
        {story.reads.map((_, i) => <DayColumn key={story.reads[i].day} story={story} idx={i} />)}
      </div>

      <div className="flow-story-grid">
        <div className="panel">
          <div className="panel-head">Score &amp; flagged premium <span className="sub">line = score · bars = premium</span></div>
          <div style={{ height: 250, padding: "var(--sp-3)" }}><BuildupChart story={story} /></div>
        </div>

        <div className="flow-story-side">
          <div className="panel">
            <div className="panel-head">Where this read went</div>
            <div className="panel-body flow-deliveries">
              {story.deliveries.length === 0 && <div className="muted" style={{ fontSize: "var(--fs-1)" }}>no technique has consumed this read yet — deliveries appear here the moment a tip verification or an EM run receives the context line</div>}
              {story.deliveries.map((d, i) => (
                <div key={i} className="flow-mini-card flow-delivery">
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className={`status-pill ${d.consumer === "tip" ? "ok" : "dim"}`}>{CONSUMER_LABEL[d.consumer] ?? d.consumer}</span>
                    <span style={{ fontSize: "var(--fs-1)", fontWeight: 600 }}>
                      {d.consumer === "tip" ? "tip verification context" : d.consumer === "em" ? "EM analyze context" : "context read"}
                    </span>
                    <span style={{ flex: 1 }} />
                    <span className="muted" style={{ fontSize: "var(--fs-0)" }}>{d.ts ? new Date(d.ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                  </div>
                  <div className="flow-context-line" style={{ marginTop: 4 }}>{d.line}</div>
                  {d.refId && (
                    <button className="link-btn" style={{ alignSelf: "flex-start" }}
                      onClick={() => setPage(d.consumer === "tip" ? "inbox" : "technique")}>
                      open the {d.consumer === "tip" ? "signal" : "run"} →
                    </button>
                  )}
                </div>
              ))}
              <div className="flow-mini-card" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="status-pill wait">Universe</span>
                <span style={{ fontSize: "var(--fs-1)", color: "var(--text-2)" }}>
                  {story.universe.inUniverse
                    ? <>in the working universe ({story.universe.provenance})</>
                    : <>not currently in the working universe</>}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
