// Scout dossier (2026-10-12): an on-demand research note for one ticker. Every number on the fact sheet is
// computed by the server from SEC filings and price data; the note cites those facts by id. Research only.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { SymIcon } from "../components/SymIcon";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import type { ScoutDossier, ScoutDossierFact, ScoutDossierPoint } from "../types";

// a ticker handed over from another tab (the candidate detail's "Research note" button)
let pendingTicker: string | null = null;
export function queueDossier(ticker: string) { pendingTicker = ticker.toUpperCase(); }

const LEAN: Record<string, { label: string; mark: string }> = {
  constructive: { label: "Constructive", mark: "▲" },
  neutral: { label: "Neutral", mark: "●" },
  cautious: { label: "Cautious", mark: "▼" },
};
const GROUPS: [string, string][] = [
  ["price", "Price"], ["valuation", "Valuation"], ["growth", "Growth"], ["profit", "Profitability"],
  ["cash", "Cash flow"], ["balance", "Balance sheet"], ["insiders", "Insiders"], ["events", "Events"],
];

function shortDay(d: string) {
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, day)).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit", timeZone: "UTC" });
}
function compact(v: number, cur = "USD") {
  const a = Math.abs(v), sym = cur === "USD" ? "$" : `${cur} `;
  const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${Math.round(a / 1e3)}K` : a.toFixed(0);
  return `${v < 0 ? "−" : ""}${sym}${s}`;
}

function LeanChip({ lean, confidence }: { lean: string | null; confidence?: number | null }) {
  if (!lean) return null;
  const l = LEAN[lean] ?? { label: lean, mark: "●" };
  return (
    <span className={`dossier-lean ${lean}`} title={confidence ? `confidence ${confidence} of 5` : undefined}>
      <span aria-hidden="true">{l.mark}</span>{l.label}
      {confidence ? <span className="scout-pips" aria-label={`confidence ${confidence} of 5`}>{[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= confidence ? "on" : ""} />)}</span> : null}
    </span>
  );
}

// ------------------------------------------------------------------ charts
type Pt = { d: string; c: number; ma50: number | null; ma200: number | null; bench?: number | null };

function PriceChart({ points }: { points: Pt[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = 200, L = 6, R = 52, T = 10, B = 20;
  const geo = useMemo(() => {
    const vals = points.flatMap((p) => [p.c, p.ma50, p.ma200, p.bench]).filter((v): v is number => v != null);
    const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.06 || 1;
    const x = (i: number) => L + (i / Math.max(1, points.length - 1)) * (W - L - R);
    const y = (v: number) => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
    const path = (key: keyof Pt) => {
      let d = "", pen = false;
      points.forEach((p, i) => {
        const v = p[key] as number | null | undefined;
        if (v == null) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    };
    const ticks = [lo, (lo + hi) / 2, hi];
    return { x, y, path, ticks };
  }, [points]);
  if (points.length < 2) return <div className="muted">No price history.</div>;
  const h = hover != null ? points[hover] : null;
  const last = points[points.length - 1], first = points[0];
  const up = last.c >= first.c;
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((fx - L) / (W - L - R)) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };
  const months = points.map((p, i) => ({ i, m: p.d.slice(0, 7) })).filter((p, k, a) => k > 0 && p.m !== a[k - 1].m).filter((_, k) => k % 2 === 0);
  return (
    <div className="dossier-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Price over ${points.length} sessions: ${first.c.toFixed(2)} to ${last.c.toFixed(2)}`}
        onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {geo.ticks.map((t) => (
          <g key={t}><line className="grid" x1={L} x2={W - R} y1={geo.y(t)} y2={geo.y(t)} /><text className="axis" x={W - R + 6} y={geo.y(t) + 4}>{t.toFixed(t >= 100 ? 0 : 2)}</text></g>
        ))}
        {months.map((m) => <text key={m.i} className="axis" x={geo.x(m.i)} y={H - 5} textAnchor="middle">{new Date(`${m.m}-01T00:00:00Z`).toLocaleDateString(undefined, { month: "short", timeZone: "UTC" })}</text>)}
        <path className="bench" d={geo.path("bench")} />
        <path className="ma200" d={geo.path("ma200")} />
        <path className="ma50" d={geo.path("ma50")} />
        <path className={`px ${up ? "up" : "down"}`} d={geo.path("c")} />
        {h && hover != null && (
          <g>
            <line className="cross" x1={geo.x(hover)} x2={geo.x(hover)} y1={T} y2={H - B} />
            <circle className={`dot ${up ? "up" : "down"}`} cx={geo.x(hover)} cy={geo.y(h.c)} r="4" />
          </g>
        )}
      </svg>
      <div className="dossier-legend">
        <span><i className={`sw px ${up ? "up" : "down"}`} />Price <b className="mono-num">{(h ?? last).c.toFixed(2)}</b></span>
        <span><i className="sw ma50" />50-day {(h ?? last).ma50 != null ? <b className="mono-num">{(h ?? last).ma50!.toFixed(2)}</b> : "—"}</span>
        <span><i className="sw ma200" />200-day {(h ?? last).ma200 != null ? <b className="mono-num">{(h ?? last).ma200!.toFixed(2)}</b> : "—"}</span>
        {points.some((p) => p.bench != null) && <span><i className="sw bench" />S&amp;P 500, same start</span>}
        <span className="muted" style={{ marginLeft: "auto" }}>{shortDay((h ?? last).d)}</span>
      </div>
    </div>
  );
}

function QuarterBars({ rows, field, title, cur }: { rows: any[]; field: "revenue" | "netIncome"; title: string; cur: string }) {
  const data = rows.filter((r) => r[field] != null);
  if (data.length < 2) return null;
  const hi = Math.max(0, ...data.map((r) => r[field])), lo = Math.min(0, ...data.map((r) => r[field])), span = hi - lo || 1;
  const zero = (hi / span) * 100;
  return (
    <div className="dossier-bars">
      <div className="dossier-bars-title">{title}<span className="muted"> · by quarter</span></div>
      <div className="dossier-bars-plot">
        <i className="zero" style={{ top: `${zero}%` }} />
        {data.map((r) => {
          const v = r[field] as number, h = (Math.abs(v) / span) * 100;
          const yoy = field === "revenue" && r.revenueYoy != null ? ` · ${r.revenueYoy >= 0 ? "+" : "−"}${Math.abs(r.revenueYoy * 100).toFixed(1)}% on a year earlier` : "";
          return (
            <span key={r.end} title={`Quarter to ${r.end}: ${compact(v, cur)}${yoy}`}>
              <i className={v >= 0 ? "pos" : "neg"} style={v >= 0 ? { top: `${zero - h}%`, height: `${h}%` } : { top: `${zero}%`, height: `${h}%` }} />
            </span>
          );
        })}
      </div>
      <div className="dossier-bars-foot muted"><span>{shortDay(data[0].end)}</span><b className="mono-num">{compact(data[data.length - 1][field], cur)}</b><span>{shortDay(data[data.length - 1].end)}</span></div>
    </div>
  );
}

// ------------------------------------------------------------------ note
function Points({ title, tone, pts, facts }: { title: string; tone?: string; pts: ScoutDossierPoint[]; facts: Map<string, ScoutDossierFact> }) {
  if (!pts.length) return null;
  return (
    <section className={`dossier-sec ${tone ?? ""}`}>
      <h4>{title}</h4>
      <ul>
        {pts.map((p, i) => (
          <li key={i}>
            <span>{p.text}</span>
            {p.quote && <q>{p.quote}</q>}
            {p.facts.length > 0 && <span className="dossier-cites">{p.facts.map((id) => {
              const f = facts.get(id);
              return <a key={id} href={`#fact-${id}`} title={f ? `${f.label}: ${f.value}` : id}>{id}</a>;
            })}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FactSheet({ facts }: { facts: ScoutDossierFact[] }) {
  return (
    <div className="dossier-facts">
      {GROUPS.map(([g, title]) => {
        const fs = facts.filter((f) => f.group === g);
        if (!fs.length) return null;
        return (
          <section key={g}>
            <h4>{title}</h4>
            <dl>
              {fs.map((f) => (
                <div key={f.id} id={`fact-${f.id}`} className="dossier-fact">
                  <dt><span className="fid">{f.id}</span>{f.label}{f.asOf ? <span className="muted"> · {shortDay(f.asOf)}</span> : null}</dt>
                  <dd className={f.tone ?? ""}>{f.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
    </div>
  );
}

function DossierView({ d, onRefresh }: { d: ScoutDossier; onRefresh: () => void }) {
  const facts = useMemo(() => new Map((d.facts ?? []).map((f) => [f.id, f])), [d.facts]);
  const [showDropped, setShowDropped] = useState(false);
  const n = d.note;
  const price = (d.charts?.price ?? []) as Pt[];
  const quarters = (d.charts?.quarters ?? []) as any[];
  const cur = d.charts?.currency ?? "USD";
  return (
    <div className="panel dossier">
      <div className="dossier-head">
        <SymIcon sym={d.ticker} size={28} />
        <div className="dossier-title"><b>{d.ticker}</b><span className="muted">{d.name}</span></div>
        <LeanChip lean={d.lean} confidence={d.confidence} />
        <span style={{ flex: 1 }} />
        <span className="muted dossier-meta">{shortDay(d.day)}{d.costUsd ? ` · $${d.costUsd.toFixed(2)}` : ""}</span>
        {d.sources?.edgar && <a className="link-btn" href={d.sources.edgar} target="_blank" rel="noreferrer">SEC filings ↗</a>}
        <button className="link-btn" onClick={onRefresh}>Refresh</button>
      </div>
      {d.status === "error" && <div className="dossier-body"><ErrorState message={d.reason ?? "The note could not be built."} /></div>}
      {d.status !== "error" && (
        <div className="dossier-body">
          {n ? (
            <div className="dossier-lede">
              <p className="dossier-summary">{n.summary}</p>
              {n.leanWhy && <p><b>Why {LEAN[n.lean]?.label.toLowerCase() ?? n.lean}:</b> {n.leanWhy.text}</p>}
              {n.background && <p className="muted">{n.background} <span className="dossier-tag">background · not checked</span></p>}
            </div>
          ) : d.reason ? <p className="muted">{d.reason}. The fact sheet below stands on its own.</p> : null}
          <div className="dossier-charts">
            <PriceChart points={price} />
            <div className="dossier-quarters">
              <QuarterBars rows={quarters} field="revenue" title="Revenue" cur={cur} />
              <QuarterBars rows={quarters} field="netIncome" title="Net income" cur={cur} />
            </div>
          </div>
          {n && (
            <>
              <div className="dossier-cols">
                <Points title="Strengths" tone="good" pts={n.strengths} facts={facts} />
                <Points title="Concerns" tone="bad" pts={n.concerns} facts={facts} />
              </div>
              <div className="dossier-cols">
                <Points title="Valuation" pts={n.valuation} facts={facts} />
                <Points title="What to watch" pts={n.watch} facts={facts} />
              </div>
              {n.questions.length > 0 && (
                <section className="dossier-sec"><h4>Open questions <span className="muted">· not answered by the data here</span></h4>
                  <ul>{n.questions.map((q, i) => <li key={i}><span>{q}</span></li>)}</ul></section>
              )}
              {d.dropped.length > 0 && (
                <div className="muted">
                  <button className="link-btn" onClick={() => setShowDropped(!showDropped)} aria-expanded={showDropped}>
                    {d.dropped.length} point{d.dropped.length === 1 ? "" : "s"} removed for lacking a valid citation</button>
                  {showDropped && <ul className="dossier-dropped">{d.dropped.map((x, i) => <li key={i}><s>{typeof x.point === "object" ? x.point?.text : String(x.point)}</s> — {x.why}</li>)}</ul>}
                </div>
              )}
            </>
          )}
          <h3 className="dossier-h3">Fact sheet <span className="muted">· computed from SEC filings and price data{d.sources?.release ? <> · quotes are from the <a href={d.sources.release.url} target="_blank" rel="noreferrer">results release of {shortDay(d.sources.release.filed)} ↗</a></> : null}</span></h3>
          <FactSheet facts={d.facts ?? []} />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ tab
export function DossierTab() {
  const list = useAsync(() => api.scoutDossiers(40), []);
  const [ticker, setTicker] = useState("");
  const [current, setCurrent] = useState<ScoutDossier | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const started = useRef(false);

  const stop = () => { if (timer.current != null) { window.clearInterval(timer.current); timer.current = null; } };
  const watch = (id: string) => {
    stop();
    timer.current = window.setInterval(async () => {
      try {
        const d = await api.scoutDossier(id);
        setCurrent(d);
        if (d.status !== "running") { stop(); setBusy(false); list.reload(); }
      } catch { /* keep polling; the next tick retries */ }
    }, 2500);
  };
  const run = async (t: string, refresh = false) => {
    const sym = t.trim().toUpperCase();
    if (!sym) return;
    setErr(null); setBusy(true);
    try {
      const d = await api.scoutDossierRequest(sym, refresh);
      setCurrent(d);
      if (d.status === "running") watch(d.id); else { setBusy(false); list.reload(); }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e)); setBusy(false);
    }
  };
  const open = async (id: string) => {
    stop(); setErr(null);
    try {
      const d = await api.scoutDossier(id);
      setCurrent(d);
      if (d.status === "running") { setBusy(true); watch(id); } else setBusy(false);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  useEffect(() => () => stop(), []);
  useEffect(() => {
    if (started.current) return;
    if (pendingTicker) { started.current = true; const t = pendingTicker; pendingTicker = null; setTicker(t); void run(t); return; }
    if (list.data && list.data.length > 0) { started.current = true; void open(list.data[0].id); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data]);

  const submit = (e: FormEvent) => { e.preventDefault(); void run(ticker); };
  const recent = useMemo(() => {
    const seen = new Set<string>();
    return (list.data ?? []).filter((d) => (seen.has(d.ticker) ? false : (seen.add(d.ticker), true))).slice(0, 14);
  }, [list.data]);

  return (
    <>
      <div className="panel dossier-bar">
        <form onSubmit={submit}>
          <input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="Ticker, e.g. LW" aria-label="Ticker"
            maxLength={10} autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
          <button type="submit" className="chip-btn" disabled={busy || !ticker.trim()}>{busy ? "Working…" : "Research"}</button>
        </form>
        <div className="dossier-recent">
          {recent.map((d) => (
            <button key={d.id} className={`dossier-pick ${current?.ticker === d.ticker ? "active" : ""}`} onClick={() => void open(d.id)}
              title={`${d.name ?? d.ticker} · ${shortDay(d.day)}${d.lean ? ` · ${d.lean}` : ""}`}>
              <span className={`dossier-mark ${d.lean ?? d.status}`} aria-hidden="true">{d.lean ? LEAN[d.lean]?.mark : "·"}</span>{d.ticker}
            </button>
          ))}
        </div>
      </div>
      {err && <ErrorState message={err} />}
      {current?.status === "running" && (
        <div className="panel dossier-wait"><Spinner /> Reading {current.ticker}'s filings and prices, then writing the note. This takes about half a minute.</div>
      )}
      {current && current.status !== "running" && <DossierView d={current} onRefresh={() => void run(current.ticker, true)} />}
      {!current && !busy && !list.loading && (
        <EmptyState title="No research notes yet" hint="Type a US-listed ticker. The note is built from the company's SEC filings and price history; every point cites the numbers it rests on." />
      )}
    </>
  );
}
