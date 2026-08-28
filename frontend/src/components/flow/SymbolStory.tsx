// The drill-down (Option D): the stock's price with the flagged strikes drawn
// on it (where the money is betting vs where price is), how the read was built
// day by day, the score/premium buildup, today's contracts, and "where this
// read went" (journaled context deliveries). Self-sufficient: what-now verdict
// and Send to Tips live here too, so a row's "story ›" link lands somewhere
// you can actually act.
import { useEffect, useState } from "react";
import type { FlowFlag, FlowStory } from "../../types";
import { api } from "../../lib/api";
import { useStore } from "../../store";
import { Occ, fmtPrem, leanColor, leanPill, occColor } from "./lib";
import { whatNow } from "./ReadDetail";
import { SendToTipsButton } from "./SendToTips";

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
            <span className="flow-stage-dot" style={{ background: occColor(f.contract) ?? "var(--up)" }} />
            <span>flag <Occ contract={f.contract} /> {fmtPrem(f.premium)} · V/OI {f.volOi.toFixed(1)}{f.strong ? " · strong" : ""}</span>
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

/** ~3 months of daily closes with the flagged strikes as dashed levels: the
    picture of what the flow is betting on relative to where price is. */
function PriceMap({ symbol, flags, last }: { symbol: string; flags: FlowFlag[]; last?: number }) {
  const [bars, setBars] = useState<number[][] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let dead = false;
    setBars(null); setFailed(false);
    api.get<{ bars: number[][] }>(`/api/chart/${symbol}?tf=1d&range=3mo&limit=90`)
      .then((d) => { if (!dead) (d.bars?.length ? setBars(d.bars) : setFailed(true)); })
      .catch(() => !dead && setFailed(true));
    return () => { dead = true; };
  }, [symbol]);
  if (failed) return <div className="empty">no daily price history for {symbol}</div>;
  if (!bars) return <div className="empty">loading price history…</div>;

  const closes = bars.map((b) => b[4]);
  const lastPx = last ?? closes[closes.length - 1];
  // largest bet per strike+side; every flagged strike joins the y-domain
  // (the scan caps OTM at ~12%, so they never blow the scale out)
  const byLevel = new Map<string, FlowFlag>();
  for (const f of flags) {
    const k = `${f.strike}-${f.optionType}`;
    const cur = byLevel.get(k);
    if (!cur || f.premium > cur.premium) byLevel.set(k, f);
  }
  const levels = [...byLevel.values()].sort((a, b) => b.premium - a.premium).slice(0, 8);
  const lo0 = Math.min(...closes, ...levels.map((l) => l.strike), lastPx);
  const hi0 = Math.max(...closes, ...levels.map((l) => l.strike), lastPx);
  const pad = Math.max((hi0 - lo0) * 0.06, hi0 * 0.002);
  const lo = lo0 - pad, hi = hi0 + pad;

  const W = 760, H = 300, mL = 8, mR = 148, mT = 10, mB = 24;
  const x = (i: number) => mL + (i * (W - mL - mR)) / Math.max(1, closes.length - 1);
  const y = (p: number) => mT + (H - mT - mB) * (1 - (p - lo) / Math.max(1e-9, hi - lo));
  const line = closes.map((c, i) => `${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" ");
  const maxPrem = Math.max(1, ...levels.map((l) => l.premium));
  // stagger labels: strikes can sit a dollar apart, text can't
  const labeled = levels.map((l) => ({ l, ly: y(l.strike) })).sort((a, b) => a.ly - b.ly);
  for (let i = 1; i < labeled.length; i++) {
    if (labeled[i].ly - labeled[i - 1].ly < 14) labeled[i].ly = labeled[i - 1].ly + 14;
  }
  const grid = [0.25, 0.5, 0.75].map((g) => ({ yy: mT + (H - mT - mB) * g, px: hi - (hi - lo) * g }));
  const dt = (ts: number) => new Date(ts).toLocaleDateString([], { month: "short", day: "numeric" });
  const upnow = lastPx >= closes[0];
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} aria-label={`${symbol} price with flagged strikes`}
      style={{ display: "block" }}>
      {grid.map((g) => (
        <g key={g.yy}>
          <line x1={mL} y1={g.yy} x2={W - mR} y2={g.yy} stroke="var(--grid)" strokeWidth="1" />
          <text x={mL + 2} y={g.yy - 3} fill="var(--text-3)" fontSize="10">{g.px.toFixed(g.px >= 100 ? 0 : 2)}</text>
        </g>
      ))}
      <polyline points={line} fill="none" stroke={upnow ? "var(--up)" : "var(--down)"} strokeWidth="1.8" opacity="0.9" />
      {labeled.map(({ l, ly }) => {
        const col = l.optionType === "put" ? "var(--down)" : "var(--up)";
        const wgt = 1 + 2.2 * (l.premium / maxPrem);
        return (
          <g key={`${l.strike}-${l.optionType}`}>
            <line x1={mL} y1={y(l.strike)} x2={W - mR + 4} y2={y(l.strike)}
              stroke={col} strokeWidth={wgt} strokeDasharray="7 5" opacity="0.65" />
            <text x={W - mR + 8} y={ly + 4} fill={col} fontSize="12" fontFamily="var(--mono)" fontWeight="700">
              {l.strike % 1 === 0 ? l.strike : l.strike.toFixed(2)}{l.optionType === "put" ? "P" : "C"} · {fmtPrem(l.premium)}
            </text>
          </g>
        );
      })}
      <circle cx={x(closes.length - 1)} cy={y(lastPx)} r="4" fill="var(--accent)" />
      <text x={x(closes.length - 1) - 6} y={y(lastPx) - 8} fill="var(--accent)" fontSize="12" fontWeight="700" textAnchor="end" fontFamily="var(--mono)">
        {lastPx.toFixed(2)}
      </text>
      <text x={mL} y={H - 6} fill="var(--text-3)" fontSize="11">{dt(bars[0][0])}</text>
      <text x={W - mR} y={H - 6} fill="var(--text-3)" fontSize="11" textAnchor="end">{dt(bars[bars.length - 1][0])}</text>
    </svg>
  );
}

function BuildupChart({ story }: { story: FlowStory }) {
  const reads = story.reads;
  const col = leanColor(reads[reads.length - 1]?.lean || "none");
  const W = 640; const H = 200; const padB = 26; const padT = 10;
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
        return <rect key={r.day} x={i * slot + slot * 0.22} y={H - padB - bh} width={slot * 0.4} height={bh} fill={col} opacity="0.28" />;
      })}
      <polyline fill="none" stroke={col} strokeWidth="2.5"
        points={reads.map((r, i) => `${i * slot + slot * 0.42},${padT + (H - padT - padB) * (1 - r.score / maxScore)}`).join(" ")} />
      {reads.map((r, i) => (
        <text key={r.day} x={i * slot + slot * 0.42} y={H - 8} fill="var(--text-3)" fontSize="12" textAnchor="middle">{r.day.slice(5)}</text>
      ))}
    </svg>
  );
}

const CONSUMER_LABEL: Record<string, string> = { tip: "Tip", em: "EM", api: "API" };

export function SymbolStory({ story, onBack, last }: { story: FlowStory; onBack: () => void; last?: number }) {
  const setPage = useStore((s) => s.setPage);
  const openTrade = useStore((s) => s.openTrade);
  const latest = story.reads[story.reads.length - 1];
  const flags = latest?.flags ?? [];
  return (
    <div className="flow-story">
      <div className="flow-story-head">
        <button className="link-btn" onClick={onBack}>← back to the read</button>
        <span className="flow-detail-sym">{story.symbol}</span>
        {last != null && <span className="mono-num muted" style={{ fontSize: "var(--fs-3)" }}>{last.toFixed(2)}</span>}
        {latest && <span className={`status-pill ${leanPill(latest.lean)}`}>{latest.lean}</span>}
        {latest && <span className="mono-num" style={{ fontSize: "var(--fs-5)", fontWeight: 700, color: leanColor(latest?.lean || "none") }}>score {latest.score}</span>}
        <span style={{ flex: 1 }} />
        {latest && <SendToTipsButton symbol={story.symbol} lean={latest.lean} />}
        <button className="ghost-btn" onClick={() => useStore.setState({ optionsUnderlying: story.symbol, page: "options" })}>Open chain</button>
        <button className="ghost-btn" onClick={() => openTrade(story.symbol)}>Chart</button>
      </div>
      {latest && (
        <div className="flow-whatnow">
          <div className="flow-lbl">What now</div>
          <div style={{ fontSize: "var(--fs-2)", color: "var(--text-2)", lineHeight: 1.5 }}>{whatNow(latest)}</div>
        </div>
      )}

      <div className="flow-daycols">
        {story.reads.map((_, i) => <DayColumn key={story.reads[i].day} story={story} idx={i} />)}
      </div>

      <div className="flow-story-grid">
        <div className="flow-story-main">
          <div className="panel">
            <div className="panel-head">
              Price &amp; the bets{" "}
              <span className="sub">3 months of daily closes · dashed lines = flagged strikes, thicker = more premium ·{" "}
                <b style={{ color: "var(--up)" }}>calls</b> / <b style={{ color: "var(--down)" }}>puts</b></span>
            </div>
            <div style={{ padding: "var(--sp-3)" }}>
              <PriceMap symbol={story.symbol} flags={flags} last={last} />
            </div>
          </div>
          {story.reads.length >= 2 && (
            <div className="panel">
              <div className="panel-head">Score &amp; flagged premium <span className="sub">line = score · bars = premium</span></div>
              <div style={{ height: 210, padding: "var(--sp-3)" }}><BuildupChart story={story} /></div>
            </div>
          )}
        </div>

        <div className="flow-story-side">
          {flags.length > 0 && (
            <div className="panel">
              <div className="panel-head">Today's flagged contracts <span className="sub">{latest.day}</span></div>
              <div className="scroll-x">
                <table className="tbl">
                  <thead><tr><th>Contract</th><th className="num">Prem</th><th className="num">V/OI</th><th className="num">DTE</th></tr></thead>
                  <tbody>
                    {flags.slice(0, 8).map((f) => (
                      <tr key={f.contract}>
                        <td><Occ contract={f.contract} />{f.strong ? <span className="status-pill dim" style={{ marginLeft: 6 }}>Strong</span> : null}</td>
                        <td className="num">{fmtPrem(f.premium)}</td>
                        <td className="num">{f.volOi.toFixed(1)}</td>
                        <td className="num">{f.dte}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
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
