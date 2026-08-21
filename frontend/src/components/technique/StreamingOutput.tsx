import { useMemo } from "react";
import { decodeEscapes, parsePartialJson } from "../../lib/partialJson";

const LABELS: Record<string, string> = {
  observations: "Observations",
  candidate_levels: "Candidate levels",
  pattern_hypothesis: "Pattern hypothesis",
  trend: "Trend",
  concerns: "Concerns",
  verdict: "Verdict",
  setup_type: "Setup type",
  direction: "Direction",
  levels: "Levels that matter",
  rationale: "Rationale",
  no_trade_reasons: "No-trade reasons",
  rules_fired: "Rules fired",
  volume_verdict: "Volume",
  risk_reward: "Reward : risk",
  confidence: "Confidence",
  entry_price: "Entry",
  stop_price: "Stop",
  targets: "Targets",
  pattern_notes: "Pattern notes",
  breakout_verdict: "Breakout verdict",
  kill: "Kill the setup?",
  fakeout_risk: "Fakeout risk",
  violations: "Violations",
  adjustments: "Adjustments",
  summary: "Summary",
  confidence_adjustment: "Confidence adjustment",
};

const HIDE = new Set(["symbol", "runner_pct", "options_strike_guidance", "options_expiry_guidance"]);

function humanKey(k: string) {
  return LABELS[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function Value({ k, v }: { k: string; v: any }) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "boolean") return <span className={v ? "pos" : "muted"}>{v ? "yes" : "no"}</span>;
  if (typeof v === "number") return <span className="tq-num">{v}</span>;
  if (typeof v === "string") return <span>{decodeEscapes(v)}</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="muted">none</span>;
    if (v.every((x) => typeof x === "number")) {
      return <span className="tq-num">{v.join(" · ")}</span>;
    }
    if (v.every((x) => typeof x === "string")) {
      // rule-id lists render as chips, prose lists as bullets
      const chips = k === "rules_fired" || v.every((x) => /^[TR]\d/.test(x));
      return chips
        ? <span className="tq-chips">{v.map((x, i) => <span key={i} className="tq-chip">{x}</span>)}</span>
        : <ul className="tq-reasons">{v.map((x, i) => <li key={i}>{decodeEscapes(x)}</li>)}</ul>;
    }
    return (
      <ul className="tq-reasons">
        {v.map((x, i) => (
          <li key={i}>
            {typeof x === "object" && x
              ? Object.entries(x).filter(([, y]) => y !== null && y !== "")
                  .map(([kk, vv]) => `${kk.replace(/_/g, " ")}: ${typeof vv === "string" ? decodeEscapes(vv) : vv}`)
                  .join(" · ")
              : String(x)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof v === "object") {
    return (
      <ul className="tq-reasons">
        {Object.entries(v).map(([kk, vv]) => (
          <li key={kk}><b>{humanKey(kk)}:</b> <Value k={kk} v={vv} /></li>
        ))}
      </ul>
    );
  }
  return <span>{String(v)}</span>;
}

/** Renders a model's structured output while it is still streaming: parses what
 *  has arrived and shows it as labelled sections instead of raw escaped JSON. */
export function StreamingOutput({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const parsed = useMemo(() => parsePartialJson(text), [text]);
  if (!text.trim()) return null;

  if (!parsed || typeof parsed !== "object") {
    return <div className="tq-stream-rich">{decodeEscapes(text)}{streaming && <span className="tq-caret" />}</div>;
  }
  const entries = Object.entries(parsed).filter(
    ([k, v]) => !HIDE.has(k) && v !== null && v !== undefined && v !== "" &&
      !(Array.isArray(v) && v.length === 0),
  );
  return (
    <div className="tq-stream-rich">
      {entries.map(([k, v]) => (
        <div className="tq-field" key={k}>
          <div className="tq-field-k">{humanKey(k)}</div>
          <div className="tq-field-v"><Value k={k} v={v} /></div>
        </div>
      ))}
      {streaming && <span className="tq-caret" />}
    </div>
  );
}

// --- FACTS -------------------------------------------------------------------

function num(v: any, d = 2) {
  return typeof v === "number" ? v.toFixed(d) : "—";
}

/** Readable view of the deterministic FACTS blob (levels, volume, trend,
 *  candidates) instead of a wall of JSON. */
export function FactsView({ facts }: { facts: any }) {
  if (!facts || typeof facts !== "object") return <div className="muted">no facts recorded</div>;
  const levels: any[] = facts.keyLevels ?? [];
  const vol = facts.volume ?? {};
  const trend = facts.trend ?? {};
  const wedge = facts.wedge ?? {};
  const sess = facts.session ?? {};
  const cands: any[] = facts.candidateSetups ?? [];
  const asOf = facts.asOf ? new Date(facts.asOf).toLocaleString() : null;

  return (
    <div className="tq-facts-view">
      <div className="tq-facts-head">
        <b>{facts.symbol}</b>
        {facts.lastClose !== undefined && <> · last <span className="tq-num">{num(facts.lastClose)}</span></>}
        {facts.primaryTf && <> · primary {facts.primaryTf}</>}
        {asOf && <> · {asOf}</>}
      </div>

      {(sess.prev || sess.today) && (
        <div className="tq-fact-block">
          <div className="tq-label">Sessions</div>
          {sess.prev && (
            <div>prev {sess.prev.date}: HOD <span className="tq-num">{num(sess.prev.hod)}</span> ·
              LOD <span className="tq-num">{num(sess.prev.lod)}</span> ·
              close <span className="tq-num">{num(sess.prev.close)}</span></div>
          )}
          {sess.today && (
            <div>today: open <span className="tq-num">{num(sess.today.open)}</span> ·
              HOD <span className="tq-num">{num(sess.today.hod)}</span> ·
              LOD <span className="tq-num">{num(sess.today.lod)}</span> ·
              {sess.today.bars} bars</div>
          )}
        </div>
      )}

      {levels.length > 0 && (
        <div className="tq-fact-block">
          <div className="tq-label">Levels detected ({levels.length})</div>
          <table className="tq-table tq-facts-table">
            <thead><tr><th>Price</th><th>Kind</th><th>Touches</th><th>Where</th><th>Source</th><th>Timeframes</th></tr></thead>
            <tbody>
              {levels.map((lv, i) => (
                <tr key={i}>
                  <td className="tq-num">{num(lv.price)}</td>
                  <td className={lv.effectiveKind === "support" ? "lvl-sup" : "lvl-res"}>{lv.effectiveKind ?? lv.kind}</td>
                  <td>{lv.touches}{lv.touches >= 3 ? " (strong)" : ""}</td>
                  <td className="muted">{lv.position}</td>
                  <td className="muted">{(lv.sources ?? []).join(", ")}</td>
                  <td className="muted">{(lv.timeframes ?? []).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(vol).length > 0 && (
        <div className="tq-fact-block">
          <div className="tq-label">Volume vs time-of-day baseline</div>
          <table className="tq-table tq-facts-table">
            <thead><tr><th>TF</th><th>Relative</th><th>Vol trend</th><th>Price trend</th><th>Flags</th></tr></thead>
            <tbody>
              {Object.entries(vol).map(([tf, v]: any) => (
                <tr key={tf}>
                  <td>{tf}</td>
                  <td className="tq-num">{v.relativeToTimeOfDayAvg}×</td>
                  <td>{v.trend}</td>
                  <td>{v.priceTrend}</td>
                  <td className="muted">
                    {[v.isSpike && "spike", v.isDryup && "dry-up", v.belowFloor && "BELOW FLOOR",
                      !v.measurable && "not measurable"].filter(Boolean).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(trend).length > 0 && (
        <div className="tq-fact-block">
          <div className="tq-label">Trend structure</div>
          {Object.entries(trend).map(([tf, t]: any) => (
            <div key={tf}>{tf}: <b>{t.direction}</b> <span className="muted">
              (HH {t.higherHighs ? "✓" : "✗"} · HL {t.higherLows ? "✓" : "✗"} ·
              LH {t.lowerHighs ? "✓" : "✗"} · LL {t.lowerLows ? "✓" : "✗"})</span></div>
          ))}
        </div>
      )}

      <div className="tq-fact-block">
        <div className="tq-label">Falling wedge</div>
        {Object.entries(wedge).map(([tf, w]: any) => (
          <div key={tf}>{tf}: {w
            ? <>found · height <span className="tq-num">{num(w.widestHeight)}</span> · low <span className="tq-num">{num(w.lowestPrice)}</span> · break level <span className="tq-num">{num(w.breakoutLevelNow)}</span>{w.volumeDeclining ? " · volume declining" : ""}</>
            : <span className="muted">none</span>}</div>
        ))}
      </div>

      <div className="tq-fact-block">
        <div className="tq-label">Recent break</div>
        {facts.recentBreak
          ? <div>through <span className="tq-num">{num(facts.recentBreak.levelPrice)}</span> —
              {facts.recentBreak.isBreakout ? " genuine breakout" : " fakeout"}
              <span className="muted"> ({(facts.recentBreak.reasons ?? []).join("; ") || "all tests passed"})</span></div>
          : <span className="muted">none in the lookback window</span>}
      </div>

      {cands.length > 0 && (
        <div className="tq-fact-block">
          <div className="tq-label">Deterministic candidates (before the model judged)</div>
          {cands.map((c, i) => (
            <div key={i} className="tq-cand">
              <div>
                <b>{c.setupType.replace(/_/g, " ")}</b> · entry <span className="tq-num">{num(c.entry?.price)}</span>
                {" "}· stop <span className="tq-num">{num(c.stop?.price)}</span>
                {" "}· R:R <span className={c.riskReward >= 3 ? "pos" : "neg"}>{num(c.riskReward)}</span>
                {" "}· {c.valid ? <span className="pos">valid</span> : <span className="neg">rejected</span>}
              </div>
              {(c.noTradeReasons ?? []).length > 0 && (
                <ul className="tq-reasons">{c.noTradeReasons.map((r: string, j: number) => <li key={j}>{r}</li>)}</ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
