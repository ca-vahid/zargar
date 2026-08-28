// The Desk's left pane: ranked reads with Option C's verdict badges in the
// Evidence column. Row order frozen between data refreshes; selection never
// auto-moves (the Armed page's anti-jump rules).
import { useMemo, useState } from "react";
import type { FlowReadItem } from "../../types";
import { fmtOcc, fmtPrem, leanColor, leanPill, maxRepeat, topFlag } from "./lib";

const MAX_SCORE = 10;

export function EvidenceBadges({ r, compact = false }: { r: FlowReadItem; compact?: boolean }) {
  const rep = maxRepeat(r);
  const conf = (r.confirmed || []).length;
  const strong = (r.flags || []).some((f) => f.strong);
  const bearOs = (r.aggregates?.osRatio ?? 0) >= 0.5;
  return (
    <span className="flow-badges">
      {rep > 0 && <span className="status-pill wait" title="same contract flagged n of the last 5 sessions">Rpt {rep}/5</span>}
      {conf > 0 && <span className="status-pill ok" title="yesterday's flagged volume became open interest overnight — real new positions">OI ✓{!compact && conf > 1 ? ` ×${conf}` : ""}</span>}
      {strong && <span className="status-pill dim" title="volume ≥ 5× open interest — aggressive">Strong</span>}
      {bearOs && !compact && <span className="status-pill bad" title="options/stock volume ratio — historically bearish (Johnson-So)">O/S {r.aggregates?.osRatio}</span>}
    </span>
  );
}

export function ScoreCell({ score, lean }: { score: number; lean: string }) {
  const pct = Math.min(100, Math.round((score / MAX_SCORE) * 100));
  return (
    <span className="flow-score">
      <span className="flow-score-bar"><span style={{ width: `${pct}%`, background: leanColor(lean) }} /></span>
      <b className="mono-num">{score}</b>
    </span>
  );
}

export function ReadsTable({ reads, selected, onSelect, onStory, quotes }: {
  reads: FlowReadItem[];
  selected: string | null;
  onSelect: (sym: string) => void;
  onStory: (sym: string) => void;
  quotes: Record<string, number | undefined>;
}) {
  const [showQuiet, setShowQuiet] = useState(false);
  // freeze order: sort once per day of data, not per refresh
  const dayKey = reads.length ? reads[0].day : "";
  const ordered = useMemo(() => reads.slice().sort((a, b) => b.score - a.score || a.symbol.localeCompare(b.symbol)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dayKey, reads.length]);
  const flagged = ordered.filter((r) => r.score > 0);
  const quiet = ordered.filter((r) => r.score <= 0);
  const rows = showQuiet ? ordered : flagged;
  return (
    <div className="panel flow-table-panel">
      <div className="panel-head">
        Reads <span className="sub">{flagged.length} flagged · ranked by score</span>
      </div>
      <div className="flow-legend">
        <b>Strong</b> = urgent size (Vol/OI ≥ 5) · <b>OI ✓</b> = yesterday's buying became real open
        positions overnight · <b>Rpt n/5</b> = the same contract bought n of the last 5 sessions — the
        strongest signal here. Flow suggests <i>where to look</i>, never what to buy: pick a row, read
        <b> What now</b>, drill into the <b>story</b>, and <b>Send to Tips</b> when you judge it tradeable.
      </div>
      <div className="scroll-x flow-table-scroll">
        <table className="tbl">
          <thead>
            <tr>
              <th>Sym</th><th className="num">Last</th><th className="num">Score</th><th>Lean</th>
              <th>Top contract</th><th className="num">Premium</th><th className="num">Vol/OI</th><th>Evidence</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const f = topFlag(r);
              const last = quotes[r.symbol];
              return (
                <tr key={r.symbol} className={r.symbol === selected ? "flow-row-sel" : ""}
                  onClick={() => onSelect(r.symbol)} style={{ cursor: "pointer" }}>
                  <td className="sym-cell">{r.symbol}</td>
                  <td className="num">{last != null ? last.toFixed(2) : "—"}</td>
                  <td className="num"><ScoreCell score={r.score} lean={r.lean} /></td>
                  <td><span className={`status-pill ${leanPill(r.lean)}`}>{r.lean}</span></td>
                  <td className="num" style={{ textAlign: "left", fontFamily: "var(--mono)" }}>{f ? fmtOcc(f.contract) : "—"}</td>
                  <td className="num">{f ? fmtPrem(f.premium) : "—"}</td>
                  <td className="num">{f ? f.volOi.toFixed(1) : "—"}</td>
                  <td><EvidenceBadges r={r} /></td>
                  <td>
                    <button className="link-btn" title="Drill down: how this read was built, day by day"
                      onClick={(e) => { e.stopPropagation(); onSelect(r.symbol); onStory(r.symbol); }}>
                      story ›
                    </button>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={9} className="empty">Nothing flagged this day — the scan found only routine activity.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flow-table-foot">
        {quiet.length} symbols scanned quiet ·{" "}
        <button className="link-btn" onClick={() => setShowQuiet((v) => !v)}>
          {showQuiet ? "hide them" : "show all"}
        </button>
      </div>
    </div>
  );
}
