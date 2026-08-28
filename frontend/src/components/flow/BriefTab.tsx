// The Morning Brief tab (Option E): a zero-click daily report composed
// server-side (GET /api/flow/brief). The UI only lays it out.
import type { FlowBrief } from "../../types";
import { EmptyState } from "../ui";
import { fmtOcc, fmtPrem, leanPill } from "./lib";

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flow-brief-row">{children}</div>;
}

export function BriefTab({ brief, onScanNow, scanning }: {
  brief: FlowBrief | null;
  onScanNow: () => void;
  scanning: boolean;
}) {
  if (!brief || brief.empty) {
    return <EmptyState title="No scans yet" hint="The first flow brief appears after the 16:45 ET scan (or run one now from the header)." />;
  }
  const s = brief.sections;
  return (
    <div className="flow-brief">
      <div className="flow-brief-head">
        <span style={{ fontSize: "var(--fs-5)", fontWeight: 800 }}>Flow brief</span>
        <span className="muted" style={{ fontSize: "var(--fs-2)" }}>
          {brief.day}{brief.summary ? <> · {brief.summary.scanned} symbols, {brief.summary.flagged} flagged, {fmtPrem((brief.summary.callPremium || 0) + (brief.summary.putPremium || 0))} premium</> : null}
        </span>
      </div>

      <div className="panel flow-brief-sect">
        <div className="flow-brief-title">Confirmed overnight
          <span className="sub muted">yesterday's volume that became real open interest this morning — new positions, not churn</span>
        </div>
        {s.confirmedOvernight.length === 0 && s.churn.length === 0 &&
          <div className="muted flow-brief-none">nothing to confirm — yesterday had no flags</div>}
        {s.confirmedOvernight.map((c) => (
          <Row key={`${c.symbol}-${c.contract}`}>
            <b className="flow-brief-sym">{c.symbol}</b>
            <span className="flow-brief-contract">{fmtOcc(c.contract)}</span>
            <span className="status-pill ok">OI +{(c.oiDelta ?? 0).toLocaleString()}</span>
            <span className="muted" style={{ flex: 1 }}>against {(c.volume ?? 0).toLocaleString()} traded</span>
            <span className="mono-num pos">score {c.score}</span>
          </Row>
        ))}
        {s.churn.map((c) => (
          <Row key={`churn-${c.symbol}-${c.contract}`}>
            <b className="flow-brief-sym">{c.symbol}</b>
            <span className="flow-brief-contract">{fmtOcc(c.contract)}</span>
            <span className="status-pill bad">OI flat</span>
            <span className="muted" style={{ flex: 1 }}>yesterday's {fmtPrem(c.premium)} was churn, not opening — flag dropped</span>
          </Row>
        ))}
      </div>

      <div className="panel flow-brief-sect">
        <div className="flow-brief-title">Accumulation watch
          <span className="sub muted">the same contract, flagged again and again</span>
        </div>
        {s.accumulation.length === 0 && <div className="muted flow-brief-none">no live streaks</div>}
        {s.accumulation.map((a) => (
          <Row key={`${a.symbol}-${a.contract}`}>
            <b className="flow-brief-sym">{a.symbol}</b>
            <span className="flow-brief-contract">{fmtOcc(a.contract)}</span>
            <span className="flow-dots">
              {[...Array(5)].map((_, i) => (
                <span key={i} className="flow-dot" style={{ background: i >= 5 - a.days ? "var(--up)" : "var(--surface-3)" }} />
              ))}
            </span>
            <span className="muted" style={{ flex: 1 }}>{a.days} of 5 sessions{a.premium != null ? <> · {fmtPrem(a.premium)} today</> : null}</span>
            {a.dte != null && <span className={`status-pill ${a.dte <= 3 ? "wait" : "dim"}`}>{a.dte} DTE</span>}
          </Row>
        ))}
      </div>

      <div className="flow-brief-duo">
        <div className="panel flow-brief-sect">
          <div className="flow-brief-title">New today</div>
          {s.newToday.length === 0 && <div className="muted flow-brief-none">no first-time flags</div>}
          {s.newToday.map((n) => (
            <Row key={`${n.symbol}-${n.contract}`}>
              <b className="flow-brief-sym">{n.symbol}</b>
              <span className="flow-brief-contract">{fmtOcc(n.contract)}</span>
              <span className="muted" style={{ flex: 1 }}>{fmtPrem(n.premium)} at V/OI {n.volOi?.toFixed?.(1) ?? n.volOi}{n.strong ? " — aggressive" : ""}</span>
              <span className={`status-pill ${leanPill(n.lean)}`}>{n.lean}</span>
            </Row>
          ))}
        </div>
        <div className="panel flow-brief-sect">
          <div className="flow-brief-title">Dying flags</div>
          {s.dying.length === 0 && <div className="muted flow-brief-none">nothing expiring or breaking</div>}
          {s.dying.map((d, i) => (
            <Row key={i}>
              <b className="flow-brief-sym">{d.symbol ?? "—"}</b>
              <span className="flow-brief-contract">{fmtOcc(d.contract)}</span>
              <span className="muted" style={{ flex: 1 }}>{d.reason}</span>
              {d.dte != null && <span className="status-pill bad">{d.dte} DTE</span>}
            </Row>
          ))}
        </div>
      </div>

      <div className="panel flow-brief-sect flow-context-box" style={{ border: "1px solid color-mix(in srgb, var(--accent) 35%, transparent)" }}>
        <div className="flow-brief-title" style={{ color: "var(--accent)" }}>What Tips &amp; EM receive today
          <span className="sub muted">verbatim context lines, attached automatically</span>
        </div>
        {s.contextLines.length === 0 && <div className="muted flow-brief-none">no reads above the context threshold</div>}
        {s.contextLines.map((c) => (
          <div key={c.symbol} className="flow-context-line" style={{ padding: "3px 0" }}>
            <b>{c.symbol}</b> → "{c.line}"
          </div>
        ))}
      </div>

      <div className="flow-brief-foot">
        <span className="muted">Next scan: 16:45 ET after the close · OI verdicts for today's flags arrive tomorrow ~09:00</span>
        <span style={{ flex: 1 }} />
        <button className="ghost-btn" disabled={scanning} onClick={onScanNow}>{scanning ? "Scanning…" : "Scan now"}</button>
      </div>
    </div>
  );
}
