// The slim day-summary strip above the reads table — Option C's rail, compressed
// to one line (UI-PLAN F2): premium bar, counts, repeat streaks.
import type { FlowDaySummary } from "../../types";
import { fmtOcc, fmtPrem } from "./lib";

export function DayStrip({ d }: { d: FlowDaySummary | null }) {
  if (!d) return null;
  const total = (d.callPremium || 0) + (d.putPremium || 0);
  const callPct = total > 0 ? Math.round((d.callPremium / total) * 100) : 50;
  return (
    <div className="panel flow-strip">
      <span className="flow-strip-lbl">Premium</span>
      <div className="flow-prem-bar" title={`${fmtPrem(d.callPremium)} calls / ${fmtPrem(d.putPremium)} puts`}>
        <span style={{ width: `${callPct}%`, background: "var(--up)" }} />
        <span style={{ width: `${100 - callPct}%`, background: "var(--down)" }} />
      </div>
      <span className="mono-num" style={{ fontSize: "var(--fs-1)" }}>
        <span className="pos">{fmtPrem(d.callPremium)}</span>
        <span className="muted"> / </span>
        <span className="neg">{fmtPrem(d.putPremium)}</span>
      </span>
      <span className="flow-strip-sep" />
      <span className="muted" style={{ fontSize: "var(--fs-1)" }}>
        <b style={{ color: "var(--text-1)" }}>{d.flagged}</b> flagged · <b className="pos">{d.confirmed}</b> confirmed
        {d.churn > 0 && <> · <b className="neg">{d.churn}</b> churn</>}
        {" "}· {d.scanned - d.flagged} quiet
      </span>
      {d.repeatStreaks.length > 0 && (
        <>
          <span className="flow-strip-sep" />
          <span className="muted" style={{ fontSize: "var(--fs-1)" }}>streaks:</span>
          {d.repeatStreaks.slice(0, 3).map((s) => (
            <span key={s.contract} className="status-pill wait" title={fmtOcc(s.contract)}>
              {s.symbol} {s.days}/5
            </span>
          ))}
        </>
      )}
    </div>
  );
}
