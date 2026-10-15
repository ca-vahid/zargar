// Scout (research only, 2026-10-07): rules find candidates in SEC filings, two LLM lanes filter and
// explain them, simulated research books measure each lane. Nothing here places an order.
// 2026-10-11: visual pass - funnel, evidence/gate/verdict marks, lane scoreboard, price ladders, day timeline.
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Collapse, DisclosureHead } from "../components/Collapse";
import { SymIcon } from "../components/SymIcon";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useStore } from "../store";
import { AgentTab } from "./ScoutAgent";
import { DossierTab, queueDossier } from "./ScoutDossier";
import type { ScoutCandidate, ScoutEntry, ScoutLane, ScoutReport, ScoutStatus, ScoutVerdict } from "../types";

const TABS = [
  { key: "agent", label: "Agent" },
  { key: "candidates", label: "Candidates" },
  { key: "lanes", label: "Lanes" },
  { key: "dossier", label: "Research" },
  { key: "status", label: "Status" },
] as const;
type Tab = (typeof TABS)[number]["key"];

const SIG: Record<string, { code: string; name: string }> = {
  s1_insider: { code: "S1", name: "Insider cluster" },
  s1_unclassified: { code: "S1U", name: "Insider cluster, new buyers" },
  s2_earnings: { code: "S2", name: "Earnings reaction" },
  random: { code: "RND", name: "Random twin" },
};
const GROUPS = [
  { key: "s2", title: "Earnings reaction", code: "S2" },
  { key: "s1", title: "Insider cluster", code: "S1" },
  { key: "s1u", title: "Insider cluster, new buyers", code: "S1U" },
] as const;
const GATE_ORDER = ["price", "adv", "spread", "marketCap", "earningsInHold", "corporateActions", "tipsMention"];
const GATE_LABEL: Record<string, string> = {
  price: "Price", adv: "Liquidity", spread: "Spread", marketCap: "Market cap", earningsInHold: "Earnings in hold",
  corporateActions: "Corporate actions", tipsMention: "Not a Tips name",
};
const CLOSED_TARGET = 40;        // PLAN 3.4: closed trades a lane needs before it can be judged

// ------------------------------------------------------------------ formatting
function money(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${v < 0 ? "−" : ""}$${s}`;
}
function compactUsd(v: number | null | undefined) {
  if (v == null) return "—";
  const a = Math.abs(v);
  return a >= 1e9 ? `$${(a / 1e9).toFixed(1)}bn` : a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `$${Math.round(a / 1e3)}k` : `$${Math.round(a)}`;
}
function signed(v: number | null | undefined, digits = 2) {
  if (v == null) return <span className="muted">—</span>;
  return <span className={v > 0 ? "pos" : v < 0 ? "neg" : ""}>{v > 0 ? "+" : ""}{money(v, digits)}</span>;
}
function pct(v: number | null | undefined, digits = 1) {
  if (v == null) return <span className="muted">—</span>;
  const p = v * 100;
  return <span className={p > 0 ? "pos" : p < 0 ? "neg" : ""}>{p > 0 ? "+" : p < 0 ? "−" : ""}{Math.abs(p).toFixed(digits)}%</span>;
}
function shortDate(d: string | null | undefined) {
  if (!d) return "—";
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, day)).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}
function todayET() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}
/** Weekday sessions from `from` to today (ET), inclusive - holidays are not known here. */
function sessionsSince(from: string) {
  const end = new Date(`${todayET()}T00:00:00Z`);
  let n = 0;
  for (let d = new Date(`${from.slice(0, 10)}T00:00:00Z`); d <= end; d = new Date(d.getTime() + 86_400_000)) {
    const w = d.getUTCDay();
    if (w !== 0 && w !== 6) n += 1;
  }
  return n;
}
function laneShort(lane: string) {
  if (lane === "random") return "Random";
  const rest = lane.split("_").slice(1);
  if (rest[0] === "screen") return "Screen";
  return `${rest[0] === "gpt" ? "GPT" : "Claude"} ${rest[1]}`;
}

// ------------------------------------------------------------------ small marks
function SigChip({ kind }: { kind: string }) {
  const s = SIG[kind] ?? { code: kind, name: kind };
  return <span className="scout-sig" aria-label={s.name}>{s.code}</span>;
}

function GateDots({ c }: { c: ScoutCandidate }) {
  const gates = GATE_ORDER.filter((g) => c.gates[g]);
  const failed = gates.filter((g) => c.gates[g].status === "fail");
  const passed = gates.filter((g) => c.gates[g].status === "pass").length;
  const label = `${passed} of ${gates.length} gates pass${failed.length ? `, failed: ${failed.map((g) => GATE_LABEL[g]).join(", ")}` : ""}`;
  return (
    <span className="scout-gates" role="img" aria-label={label}>
      {gates.map((g) => <span key={g} className={`scout-dot ${c.gates[g].status}`} title={`${GATE_LABEL[g]}: ${c.gates[g].why}`} />)}
      {failed.length > 0 ? <span className="scout-gates-note neg">{GATE_LABEL[failed[0]].toLowerCase()}{failed.length > 1 ? ` +${failed.length - 1}` : ""}</span>
        : passed < gates.length ? <span className="scout-gates-note muted">{gates.length - passed} unknown</span> : null}
    </span>
  );
}

function Pips({ n }: { n: number | null }) {
  if (!n) return null;
  return <span className="scout-pips" role="img" aria-label={`conviction ${n} of 5`}>{[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= n ? "on" : ""} />)}</span>;
}

function Verdict({ v }: { v?: ScoutVerdict }) {
  if (!v) return <span className="muted">—</span>;
  if (v.status !== "ok") return <span className="muted">{v.status}</span>;
  return <span className={`scout-verdict ${v.verdict}`}>{v.verdict}<Pips n={v.conviction} /></span>;
}

function Evidence({ c }: { c: ScoutCandidate }) {
  const ev = c.evidence ?? {};
  if (c.kind === "s2_earnings" && ev.abnormalReturn != null) {
    const w = Math.max(4, Math.min(100, (ev.abnormalReturn / 0.25) * 100));
    return (
      <span className="scout-ev">
        <span className="scout-bar" role="img" aria-label={`abnormal return ${(ev.abnormalReturn * 100).toFixed(1)}%`}><i style={{ width: `${w}%` }} /></span>
        <span className="mono-num">+{(ev.abnormalReturn * 100).toFixed(1)}%</span>
        <span className="muted mono-num">{Number(ev.volumeRatio ?? 0).toFixed(1)}× vol</span>
      </span>
    );
  }
  if (c.kind.startsWith("s1")) {
    const n = ev.insiders?.length ?? 0;
    return (
      <span className="scout-ev">
        <span className="scout-people" role="img" aria-label={`${n} insiders`}>
          {Array.from({ length: Math.min(n, 6) }, (_, i) => <i key={i} />)}{n > 6 ? <span className="muted">+{n - 6}</span> : null}
        </span>
        <span className="mono-num">{compactUsd(ev.totalValue)}</span>
      </span>
    );
  }
  if (c.kind === "random") return <span className="muted">twin of {ev.matchedTicker}</span>;
  return <span className="muted">—</span>;
}

/** stop | entry | mark on one track. The track spans the stop to one risk above the entry (wider if the mark is beyond). */
function PriceLadder({ stop, entry, mark, exit }: { stop: number; entry: number; mark?: number | null; exit?: number | null }) {
  const now = exit ?? mark ?? null;
  const risk = Math.max(entry - stop, entry * 0.001);
  const lo = Math.min(stop, now ?? stop) - risk * 0.08;
  const hi = Math.max(entry + risk, now ?? entry) + risk * 0.08;
  const x = (p: number) => `${((p - lo) / (hi - lo)) * 100}%`;
  const up = now != null && now >= entry;
  return (
    <div className="scout-ladder" role="img"
      aria-label={`stop ${stop.toFixed(2)}, entry ${entry.toFixed(2)}${now != null ? `, ${exit != null ? "exit" : "now"} ${now.toFixed(2)}` : ""}`}>
      <div className="scout-ladder-track">
        <i className="risk" style={{ left: x(stop), width: `calc(${x(entry)} - ${x(stop)})` }} />
        {now != null && <i className={`move ${up ? "up" : "down"}`} style={{ left: x(Math.min(entry, now)), width: `calc(${x(Math.max(entry, now))} - ${x(Math.min(entry, now))})` }} />}
        <b className="stop" style={{ left: x(stop) }} />
        <b className="entry" style={{ left: x(entry) }} />
        {now != null && <b className={`now ${up ? "up" : "down"}`} style={{ left: x(now) }} />}
      </div>
      <div className="scout-ladder-labels mono-num">
        <span style={{ left: x(stop) }}>{stop.toFixed(2)}</span>
        <span style={{ left: x(entry) }}>{entry.toFixed(2)}</span>
        {now != null && Math.abs(now - entry) / risk > 0.35 && <span className="strong" style={{ left: x(now) }}>{now.toFixed(2)}</span>}
      </div>
    </div>
  );
}

function HoldProgress({ entryDate, hold }: { entryDate: string; hold: number }) {
  const day = Math.min(hold, Math.max(1, sessionsSince(entryDate)));
  return (
    <span className="scout-hold" role="img" aria-label={`session ${day} of ${hold}`}>
      <span className="scout-meter"><i style={{ width: `${(day / hold) * 100}%` }} /></span>
      <span className="muted mono-num">{day}/{hold}</span>
    </span>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 3) return null;
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 58 + 1},${15 - ((v - lo) / span) * 14}`).join(" ");
  const last = values[values.length - 1];
  return (
    <svg className={`scout-spark ${last > 0 ? "up" : last < 0 ? "down" : ""}`} width="60" height="16" viewBox="0 0 60 16" role="img" aria-label={`trend over ${values.length} reports`}>
      <line x1="0" x2="60" y1={15 - ((0 - lo) / span) * 14} y2={15 - ((0 - lo) / span) * 14} className="zero" />
      <polyline points={pts} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return <div className="scout-stat"><div className="scout-stat-label">{label}</div><div className="scout-stat-value mono-num">{value}</div>{sub ? <div className="muted scout-stat-sub">{sub}</div> : null}</div>;
}

export function ScoutPage() {
  const pageTab = useStore((s) => s.pageTab);
  const setPageTab = useStore((s) => s.setPageTab);
  const tab: Tab = (TABS.some((t) => t.key === pageTab) ? pageTab : "agent") as Tab;
  return (
    <div className="tips-page scout-page">
      <div className="tips-head">
        <div className="tabs" role="tablist" style={{ flex: 1 }}>
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""}
              onClick={() => setPageTab(t.key)}>{t.label}</button>
          ))}
        </div>
        <span className="muted tips-head-sub">research only · simulated books, never a broker</span>
      </div>
      {tab === "agent" && <AgentTab />}
      {tab === "candidates" && <CandidatesTab />}
      {tab === "lanes" && <LanesTab />}
      {tab === "dossier" && <DossierTab />}
      {tab === "status" && <StatusTab />}
    </div>
  );
}

// ------------------------------------------------------------------ Candidates
const FILTERS = [
  { key: "all", label: "All" }, { key: "s2_earnings", label: "S2" }, { key: "s1_insider", label: "S1" },
  { key: "s1_unclassified", label: "S1U" }, { key: "random", label: "Random" },
] as const;

function Funnel({ rows }: { rows: ScoutCandidate[] }) {
  const real = rows.filter((c) => c.kind !== "random");
  const steps = [
    { label: "Found by the rules", n: real.length },
    { label: "Passed the gates", n: real.filter((c) => c.preEntry === "pass").length },
    { label: "Kept by a model", n: real.filter((c) => c.verdicts.some((v) => v.status === "ok" && v.verdict === "keep")).length },
    { label: "Entered a book", n: real.filter((c) => c.entries.some((e) => e.status === "entered" || e.status === "closed")).length },
  ];
  const top = Math.max(1, steps[0].n);
  return (
    <div className="scout-funnel">
      {steps.map((s, i) => (
        <div key={s.label} className="scout-funnel-step">
          <div className="scout-stat-label">{s.label}</div>
          <div className="scout-funnel-n mono-num">{s.n}{i > 0 && steps[0].n > 0 ? <span className="muted"> {Math.round((s.n / top) * 100)}%</span> : null}</div>
          <div className="scout-meter wide"><i style={{ width: `${(s.n / top) * 100}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

function PositionCell({ c, marks }: { c: ScoutCandidate; marks: Map<string, ScoutEntry> }) {
  if (!c.entries.length) return <span className="muted">—</span>;
  const live = c.entries.filter((e) => e.status === "entered");
  const closed = c.entries.filter((e) => e.status === "closed");
  const books = <span className="muted"> · {c.entries.length} {c.entries.length === 1 ? "book" : "books"}</span>;
  if (live.length) {
    const e = live[0];
    const m = marks.get(e.id)?.mark;
    return <span>{m != null && e.entryPrice ? pct(m / e.entryPrice - 1) : <span className="muted">open</span>}{books}</span>;
  }
  if (closed.length) {
    const e = closed[0];
    return <span>{e.exitPrice != null && e.entryPrice ? pct(e.exitPrice / e.entryPrice - 1) : null}<span className="muted"> closed</span>{books}</span>;
  }
  const st = [...new Set(c.entries.map((e) => e.status))].join(", ");
  return <span className="muted">{st}{st === "pending" && c.entryDate ? ` ${shortDate(c.entryDate)}` : ""}</span>;
}

function CandidatesTab() {
  const [days, setDays] = useState(14);
  const [filter, setFilter] = useState<string>("all");
  const st = useAsync(() => api.scoutCandidates(days), [days]);
  const lanes = useAsync(() => api.scoutLanes(), []);
  const [open, setOpen] = useState<string | null>(null);
  const all = st.data ?? [];
  const marks = useMemo(() => {
    const m = new Map<string, ScoutEntry>();
    for (const l of lanes.data ?? []) for (const t of l.openTrades) m.set(t.id, t);
    return m;
  }, [lanes.data]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: all.filter((x) => x.kind !== "random").length };
    for (const x of all) c[x.kind] = (c[x.kind] ?? 0) + 1;
    return c;
  }, [all]);
  const rows = filter === "all" ? all.filter((c) => c.kind !== "random") : all.filter((c) => c.kind === filter);
  return (
    <>
      {all.length > 0 && <div className="panel mb"><Funnel rows={all} /></div>}
      <div className="panel mb">
        <div className="panel-head panel-head--tabs">
          <div className="tabs small" role="tablist" aria-label="Signal">
            {FILTERS.filter((f) => f.key === "all" || counts[f.key]).map((f) => (
              <button key={f.key} role="tab" aria-selected={filter === f.key} className={filter === f.key ? "active" : ""} onClick={() => setFilter(f.key)}>
                {f.label} <span className="muted">{counts[f.key] ?? 0}</span></button>
            ))}
          </div>
          <span style={{ flex: 1 }} />
          <div className="tabs small" role="tablist" aria-label="Window">
            {[7, 14, 30].map((d) => (
              <button key={d} role="tab" aria-selected={days === d} className={days === d ? "active" : ""} onClick={() => setDays(d)}>{d}d</button>
            ))}
          </div>
        </div>
        {st.loading && !st.data ? <Spinner label="loading candidates…" />
          : st.error ? <ErrorState message={st.error} onRetry={st.reload} />
          : rows.length === 0 ? <EmptyState title="No candidates in this window" hint="The 07:00 ET job writes yesterday's screen hits; verdicts follow at 09:00 ET." />
          : (
            <div className="scroll-x">
              <table className="tbl scout-tbl">
                <thead><tr><th>Candidate</th><th>Evidence</th><th>Entry</th><th>Gates</th><th>Claude</th><th>GPT</th><th>Position</th><th aria-label="Filing" /></tr></thead>
                <tbody>
                  {rows.map((c) => (
                    <Fragment key={c.id}>
                      <tr className={`clickable ${open === c.id ? "is-open" : ""}`} tabIndex={0} aria-expanded={open === c.id}
                        onClick={() => setOpen(open === c.id ? null : c.id)}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === c.id ? null : c.id); } }}>
                        <td><span className="scout-cand"><SymIcon sym={c.ticker} size={20} /><b>{c.ticker}</b><SigChip kind={c.kind} /></span></td>
                        <td><Evidence c={c} /></td>
                        <td className="muted">{shortDate(c.entryDate)}</td>
                        <td><GateDots c={c} /></td>
                        <td><Verdict v={c.verdicts.find((v) => v.lane === "claude")} /></td>
                        <td><Verdict v={c.verdicts.find((v) => v.lane === "gpt")} /></td>
                        <td><PositionCell c={c} marks={marks} /></td>
                        <td>{c.links[0] ? <a href={c.links[0].url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>SEC ↗</a> : null}</td>
                      </tr>
                      {open === c.id && <tr className="scout-detail-row"><td colSpan={8}><CandidateDetail c={c} marks={marks} /></td></tr>}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>
    </>
  );
}

function CandidateDetail({ c, marks }: { c: ScoutCandidate; marks: Map<string, ScoutEntry> }) {
  const ev = c.evidence ?? {};
  const setPageTab = useStore((s) => s.setPageTab);
  const fills = useMemo(() => {
    const m = new Map<string, { e: ScoutEntry; books: string[] }>();
    for (const e of c.entries) {
      const k = `${e.status}|${e.entryPrice ?? ""}|${e.reason ?? ""}`;
      const cur = m.get(k) ?? { e, books: [] };
      cur.books.push(laneShort(e.book));
      m.set(k, cur);
    }
    return [...m.values()];
  }, [c.entries]);
  const insiders: any[] = ev.insiders ?? [];
  const topValue = Math.max(1, ...insiders.map((i) => Number(i.value) || 0));
  return (
    <div className="scout-detail">
      <section>
        <h4>{SIG[c.kind]?.name ?? c.kind}<span className="muted"> · found {shortDate(c.signalDate)}</span></h4>
        {c.kind === "s2_earnings" && ev.abnormalReturn != null && (
          <div className="scout-stats">
            <Stat label="Abnormal return" value={pct(ev.abnormalReturn)} sub={`stock ${(ev.stockReturn * 100).toFixed(1)}% vs ${ev.benchmark} ${(ev.benchReturn * 100).toFixed(1)}%`} />
            <Stat label="Day-0 volume" value={`${Number(ev.volumeRatio ?? 0).toFixed(1)}×`} sub="of its 20-day average" />
            <Stat label="Rank that day" value={`${ev.rank} of ${ev.of}`} sub={`reaction ${shortDate(ev.day0)}`} />
          </div>
        )}
        {c.kind.startsWith("s1") && (
          <div className="scout-insiders">
            {insiders.slice(0, 8).map((i) => (
              <div key={i.insiderCik} className="scout-insider">
                <span className="who">{i.title || (i.director ? "Director" : "Officer")}</span>
                <span className="scout-bar"><i style={{ width: `${Math.max(3, (Number(i.value) / topValue) * 100)}%` }} /></span>
                <span className="mono-num">{compactUsd(i.value)}</span>
                <span className="muted">{i.class}</span>
              </div>
            ))}
            {insiders.length > 8 && <div className="muted">+{insiders.length - 8} more · {compactUsd(ev.totalValue)} in total</div>}
          </div>
        )}
        {c.kind === "random" && <div className="muted">Random twin of {ev.matchedTicker} ({SIG[ev.matchedKind]?.code ?? ev.matchedKind}) · {ev.poolKind === "peers" ? "drawn from its peers" : "drawn from the fallback list"} · entry offset {ev.offsetSessions} sessions</div>}
        <div className="scout-gatelist">
          {GATE_ORDER.filter((g) => c.gates[g]).map((g) => (
            <Fragment key={g}><span className={`scout-dot ${c.gates[g].status}`} /><span>{GATE_LABEL[g]}</span><span className="muted">{c.gates[g].why}</span></Fragment>
          ))}
        </div>
      </section>
      <section>
        {c.verdicts.length === 0 ? <div className="muted">No analyst read: {c.preEntry === "pass" ? "verdicts run at 09:00 ET on the entry day" : "only candidates that pass the gates are read"}.</div>
          : <div className="scout-verdicts">{c.verdicts.map((v) => <VerdictCard key={v.id} v={v} />)}</div>}
      </section>
      <section className="span">
        {fills.map(({ e, books }) => (
          <div key={e.id} className="scout-fill">
            <div className="scout-fill-head">
              <span>{e.status === "entered" ? `${e.qty} @ ${e.entryPrice?.toFixed(2)}` : e.status}</span>
              <span className="muted">{books.join(" · ")}</span>
              <span style={{ flex: 1 }} />
              {e.status === "entered" && <HoldProgress entryDate={e.entryDate} hold={e.holdSessions} />}
              {e.netPnl != null ? signed(e.netPnl) : marks.get(e.id)?.openNetPnl != null ? signed(marks.get(e.id)!.openNetPnl) : null}
            </div>
            {e.entryPrice != null && e.stopPrice != null
              ? <PriceLadder stop={e.stopPrice} entry={e.entryPrice} mark={marks.get(e.id)?.mark} exit={e.exitPrice} />
              : e.reason ? <div className="muted">{e.reason}</div> : null}
          </div>
        ))}
        <div><button className="link-btn" onClick={() => { queueDossier(c.ticker); setPageTab("dossier"); }}>Research note on {c.ticker} →</button></div>
        {c.links.length > 1 && <div className="muted">{c.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer" style={{ marginRight: 10 }}>{l.label} ↗</a>)}</div>}
      </section>
    </div>
  );
}

function VerdictCard({ v }: { v: ScoutVerdict }) {
  const [show, setShow] = useState(false);
  return (
    <div className={`scout-vcard ${v.lane}`}>
      <div className="scout-vcard-head">
        <b>{v.lane === "claude" ? "Claude" : "GPT"}</b>
        {v.status === "ok" ? <Verdict v={v} /> : <span className="muted">{v.reason ?? v.status}</span>}
        <span style={{ flex: 1 }} />
        <span className="muted mono-num">${v.costUsd.toFixed(3)}</span>
      </div>
      {v.reason && v.status === "ok" && <div className="muted">{v.reason}</div>}
      {v.reasons.length > 0 && <ul>{v.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>}
      {(v.claims.length > 0 || v.droppedClaims.length > 0) && (
        <button className="link-btn" onClick={() => setShow(!show)} aria-expanded={show}>
          {show ? "hide quotes" : `${v.claims.length} quoted facts${v.droppedClaims.length ? `, ${v.droppedClaims.length} discarded` : ""}`}</button>
      )}
      {show && (
        <ol>
          {v.claims.map((c, i) => <li key={i}>{c.text} <span className="muted">— “{c.quote}” ({c.sourceId})</span></li>)}
          {v.droppedClaims.map((c, i) => <li key={`d${i}`} className="muted"><s>{c.text}</s> — discarded: {c.why}</li>)}
        </ol>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Lanes
function LaneRow({ l, scale, trend, open, onToggle }: { l: ScoutLane; scale: number; trend: number[]; open: boolean; onToggle: () => void }) {
  const who = l.lane === "random" ? "random" : l.lane.includes("claude") ? "claude" : l.lane.includes("gpt") ? "gpt" : "screen";
  const drop = l.lane.endsWith("_drop");
  const v = l.entries ? l.totalNet : 0;
  const w = Math.min(50, (Math.abs(v) / scale) * 50);
  const traded = l.open + l.closed;
  return (
    <>
      <button type="button" className={`scout-lane ${traded ? "" : "empty"}`} onClick={onToggle} aria-expanded={open}>
        <span className="scout-lane-name"><i className={`scout-swatch ${who} ${drop ? "drop" : ""}`} aria-hidden="true" />{laneShort(l.lane)}</span>
        <span className="scout-div" role="img" aria-label={traded ? `total ${money(v)}` : "no trades"}>
          {traded > 0 && <i className={v >= 0 ? "up" : "down"} style={v >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />}
        </span>
        <span className="scout-lane-val mono-num">{traded ? signed(v, 0) : <span className="muted">—</span>}</span>
        <span className="scout-lane-n muted mono-num">{traded ? `${l.open} open${l.closed ? ` · ${l.closed} closed` : ""}` : l.pending ? `${l.pending} pending` : ""}</span>
        <Sparkline values={trend} />
      </button>
      <Collapse open={open}><LaneTrades l={l} /></Collapse>
    </>
  );
}

function OpenPositions({ lanes }: { lanes: ScoutLane[] }) {
  const rows = useMemo(() => {
    const m = new Map<string, { t: ScoutEntry; lanes: string[] }>();
    for (const l of lanes) for (const t of l.openTrades) {
      const k = `${t.ticker}|${t.entryPrice}`;
      const cur = m.get(k) ?? { t, lanes: [] };
      cur.lanes.push(l.lane === "random" ? "Random" : `${l.lane.split("_")[0].toUpperCase()} ${laneShort(l.lane)}`);
      m.set(k, cur);
    }
    return [...m.values()].sort((a, b) => a.t.entryDate.localeCompare(b.t.entryDate));
  }, [lanes]);
  if (!rows.length) return null;
  return (
    <div className="panel mb">
      <div className="panel-head">Open positions <span className="sub">stop · entry · now, and the session of the hold</span></div>
      <div className="scout-positions">
        {rows.map(({ t, lanes: ls }) => (
          <div key={t.id} className="scout-pos">
            <div className="scout-pos-head">
              <span className="scout-cand"><SymIcon sym={t.ticker} size={20} /><b>{t.ticker}</b></span>
              <span className="mono-num">{t.mark != null && t.entryPrice ? pct(t.mark / t.entryPrice - 1) : <span className="muted">no mark</span>}</span>
              <span style={{ flex: 1 }} />
              <HoldProgress entryDate={t.entryDate} hold={t.holdSessions} />
            </div>
            {t.entryPrice != null && t.stopPrice != null && <PriceLadder stop={t.stopPrice} entry={t.entryPrice} mark={t.mark} />}
            <div className="muted scout-pos-lanes">{ls.join(" · ")}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Agreement({ cands }: { cands: ScoutCandidate[] }) {
  const cell = { kk: 0, kd: 0, dk: 0, dd: 0 };
  let cost = 0, calls = 0;
  for (const c of cands) {
    for (const v of c.verdicts) { cost += v.costUsd; calls += v.status === "ok" ? 1 : 0; }
    const a = c.verdicts.find((v) => v.lane === "claude" && v.status === "ok")?.verdict;
    const b = c.verdicts.find((v) => v.lane === "gpt" && v.status === "ok")?.verdict;
    if (a && b) cell[`${a[0]}${b[0]}` as keyof typeof cell] += 1;
  }
  const n = cell.kk + cell.kd + cell.dk + cell.dd;
  if (!n) return null;
  const top = Math.max(cell.kk, cell.kd, cell.dk, cell.dd, 1);
  const box = (v: number, label: string) => (
    <div className="scout-mx-cell" style={{ background: `color-mix(in srgb, var(--accent) ${Math.round((v / top) * 34)}%, transparent)` }} aria-label={`${label}: ${v}`}>{v}</div>
  );
  return (
    <div className="panel mb scout-agree">
      <div className="panel-head">Do the two models agree? <span className="sub">{n} candidates read by both, last 30 days</span></div>
      <div className="panel-body scout-agree-body">
        <div className="scout-mx" role="group" aria-label="Claude verdict by GPT verdict">
          <span /><span className="muted">GPT keep</span><span className="muted">GPT drop</span>
          <span className="muted">Claude keep</span>{box(cell.kk, "both keep")}{box(cell.kd, "Claude keep, GPT drop")}
          <span className="muted">Claude drop</span>{box(cell.dk, "Claude drop, GPT keep")}{box(cell.dd, "both drop")}
        </div>
        <div className="scout-stats">
          <Stat label="Agree" value={`${cell.kk + cell.dd} of ${n}`} sub={`${Math.round(((cell.kk + cell.dd) / n) * 100)}%`} />
          <Stat label="Model cost" value={`$${cost.toFixed(2)}`} sub={calls ? `$${(cost / calls).toFixed(3)} a read` : undefined} />
        </div>
      </div>
    </div>
  );
}

function LanesTab() {
  const st = useAsync(() => api.scoutLanes(), []);
  const reports = useAsync(() => api.scoutReports(60), []);
  const cands = useAsync(() => api.scoutCandidates(30), []);
  const [open, setOpen] = useState<string | null>(null);
  const lanes = (st.data ?? []).filter((l) => !l.lane.startsWith("agent_"));     // the agent's books: Agent tab
  const trend = useMemo(() => {
    const m: Record<string, number[]> = {};
    for (const r of [...(reports.data ?? [])].sort((a: ScoutReport, b: ScoutReport) => a.day.localeCompare(b.day))) {
      for (const l of r.lanes) if (l.entries > 0 || m[l.lane]) (m[l.lane] ??= []).push(l.totalNet);
    }
    return m;
  }, [reports.data]);
  if (st.loading && !st.data) return <Spinner label="loading lanes…" />;
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  const scale = Math.max(20, ...lanes.map((l) => Math.abs(l.entries ? l.totalNet : 0)));
  const random = lanes.find((l) => l.lane === "random");
  return (
    <>
      <div className="scout-board mb">
        {GROUPS.map((g) => {
          const mine = lanes.filter((l) => l.lane.startsWith(`${g.key}_`));
          const closed = Math.max(0, ...mine.map((l) => l.closed));
          return (
            <div key={g.key} className="panel scout-group">
              <div className="panel-head"><span className="scout-sig">{g.code}</span> {g.title}
                <span style={{ flex: 1 }} />
                <span className="scout-evidence" role="img" aria-label={`${closed} of ${CLOSED_TARGET} closed trades needed to judge a lane`}>
                  <span className="scout-meter"><i style={{ width: `${Math.min(100, (closed / CLOSED_TARGET) * 100)}%` }} /></span>
                  <span className="muted mono-num">{closed}/{CLOSED_TARGET} closed</span>
                </span>
              </div>
              {!mine.some((l) => l.entries > 0) ? <div className="panel-body muted">No candidate has reached these books yet.</div> : (
              <div className="scout-lanes">
                {mine.map((l) => <LaneRow key={l.lane} l={l} scale={scale} trend={trend[l.lane] ?? []} open={open === l.lane} onToggle={() => setOpen(open === l.lane ? null : l.lane)} />)}
                {random && g.key === "s2" && <LaneRow l={random} scale={scale} trend={trend.random ?? []} open={open === "random"} onToggle={() => setOpen(open === "random" ? null : "random")} />}
              </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="muted scout-note mb">Total after costs per book: US$600 a trade, $1 an order, stop 2× ATR, time exit. A lane is judged at {CLOSED_TARGET} closed trades, not before.</div>
      <OpenPositions lanes={lanes} />
      <Agreement cands={cands.data ?? []} />
    </>
  );
}

function LaneTrades({ l }: { l: ScoutLane }) {
  const openPortfolios = useStore((s) => s.openPortfolios);
  const rows = [...l.openTrades, ...l.closedTrades];
  return (
    <div className="scout-lane-trades">
      {rows.length === 0 ? <div className="muted">no trades yet{l.skipped ? ` · ${l.skipped} skipped or unfilled` : ""}</div> : (
        <table className="tbl"><tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td><b>{t.ticker}</b></td><td className="muted">{shortDate(t.entryDate)}</td>
              <td className="muted mono-num">{t.qty} @ {t.entryPrice?.toFixed(2)}{t.exitPrice != null ? ` → ${t.exitPrice.toFixed(2)} (${t.exitReason ?? ""})` : t.mark != null ? ` · now ${t.mark.toFixed(2)}` : ""}</td>
              <td className="num">{signed(t.netPnl ?? t.openNetPnl ?? null)}</td>
            </tr>
          ))}
        </tbody></table>
      )}
      {l.portfolioId && <button className="link-btn" onClick={() => openPortfolios(l.portfolioId!)}>open the book</button>}
    </div>
  );
}

// ------------------------------------------------------------------ Status
function StatusTab() {
  const st = useAsync(() => api.scoutStatus(), []);
  const setPage = useStore((s) => s.setPage);
  if (st.loading && !st.data) return <Spinner label="loading status…" />;
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  return <StatusBody s={st.data as ScoutStatus} onSettings={() => setPage("settings")} />;
}

function Timeline({ s }: { s: ScoutStatus }) {
  const today = todayET();
  const job = (name: string) => s.schedule.find((j) => j.name === name);
  const entries = s.schedule.filter((j) => j.name.startsWith("scout_entry_")).sort((a, b) => a.at.localeCompare(b.at));
  const steps = [
    { label: "Screen", at: job("scout_daily")?.at, done: job("scout_daily")?.lastDay === today, last: job("scout_daily")?.lastDay, sub: "filings → candidates" },
    { label: "Analysts", at: job("scout_verdicts")?.at, done: job("scout_verdicts")?.lastDay === today, last: job("scout_verdicts")?.lastDay, sub: "keep or drop" },
    { label: "Entries", at: entries.length ? `${entries[0].at}–${entries[entries.length - 1].at}` : undefined, done: entries.some((j) => j.lastDay === today), last: entries[0]?.lastDay, sub: "spread rule" },
    { label: "Report", at: job("scout_report")?.at, done: job("scout_report")?.lastDay === today, last: job("scout_report")?.lastDay, sub: "books marked" },
  ];
  return (
    <ol className="scout-timeline">
      {steps.map((x) => (
        <li key={x.label} className={x.done ? "done" : ""}>
          <span className="node" aria-hidden="true">{x.done ? "✓" : ""}</span>
          <b>{x.label}</b><span className="mono-num muted">{x.at ?? "—"} ET</span>
          <span className="muted">{x.done ? "done today" : x.last ? `last ran ${shortDate(x.last)}` : x.sub}</span>
        </li>
      ))}
    </ol>
  );
}

function StatusBody({ s, onSettings }: { s: ScoutStatus; onSettings: () => void }) {
  const settings = useMemo(() => Object.entries(s.settings ?? {}), [s.settings]);
  const [showSettings, setShowSettings] = useState(false);
  const lr = s.lastRun as Record<string, any> | null;
  const ing = s.ingest as Record<string, any>;
  const budget = Math.max(s.llm.budgetUsd, 0.0001);
  const spend = (k: "claude" | "gpt") => s.llm.byLane[k]?.usd ?? 0;
  const filings: { form: string; n: number }[] = Array.isArray(ing.filings) ? ing.filings : [];
  const nForm = (p: string) => filings.filter((x) => x.form.startsWith(p)).reduce((a, x) => a + x.n, 0);
  const days = [...(s.reports ?? [])].sort((a, b) => a.day.localeCompare(b.day)).slice(-14);
  const topSpend = Math.max(0.01, ...days.map((d) => d.llm.total));
  return (
    <>
      <div className="panel mb">
        <div className="panel-head">Today <span className="sub">{s.running ? "running now · " : ""}{lr?.at ? `last screen ${String(lr.at).slice(0, 16).replace("T", " ")} ET` : "no screen run yet"}</span>
          <span style={{ flex: 1 }} />
          <span className="muted">{[s.enabled.s1 && "S1", s.enabled.s2 && "S2"].filter(Boolean).join(" + ") || "all screens off"}{s.enabled.daily ? "" : " · daily job off"}</span>
        </div>
        <div className="panel-body">
          <Timeline s={s} />
          {(lr?.s1 || lr?.s2) && (
            <div className="scout-stats">
              {lr?.s1 && <Stat label="Insider purchases read" value={Number(lr.s1.purchases).toLocaleString()} sub={`${lr.s1.clusters} clusters · ${lr.s1.new} new`} />}
              {lr?.s2 && <Stat label="Earnings releases read" value={Number(lr.s2.events).toLocaleString()} sub={`${lr.s2.hits} hits · ${lr.s2.new} new`} />}

            </div>
          )}
        </div>
      </div>
      <div className="panel mb">
        <div className="panel-head">Model budget <span className="sub">{money(s.llm.total)} of {money(s.llm.budgetUsd, 0)} today, shared by both lanes</span></div>
        <div className="panel-body">
          <div className="scout-budget" role="img" aria-label={`${money(s.llm.total)} of ${money(s.llm.budgetUsd, 0)} spent`}>
            {spend("claude") > 0 && <i className="claude" style={{ width: `${Math.min(100, (spend("claude") / budget) * 100)}%` }} />}
            {spend("gpt") > 0 && <i className="gpt" style={{ width: `${Math.min(100, (spend("gpt") / budget) * 100)}%` }} />}
          </div>
          <div className="scout-legend">
            {(["claude", "gpt"] as const).map((k) => {
              const lane = s.llm.lanes[k];
              return (
                <span key={k}><i className={`scout-swatch ${k}`} aria-hidden="true" /><b>{k === "claude" ? "Claude" : "GPT"}</b>
                  <span className="mono-num"> {money(spend(k))}</span>
                  <span className="muted"> · {lane.model} · {!lane.enabled ? "off" : lane.keyPresent ? `${s.llm.byLane[k]?.calls ?? 0} reads` : "no API key, lane skipped"}</span></span>
              );
            })}
          </div>
          {days.length > 1 && (
            <div className="scout-days" role="img" aria-label={`model spend on the last ${days.length} report days`}>
              {days.map((d) => (
                <span key={d.day} title={`${shortDate(d.day)}: ${money(d.llm.total)}`}>
                  <i style={{ height: `${Math.max(2, (d.llm.total / topSpend) * 36)}px` }} />
                  <em className="mono-num">{shortDate(d.day).replace(/^\D+/, "")}</em>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="panel mb">
        <div className="panel-head">SEC data on file <span className="sub">since {String(s.ingest.coverageStart ?? "—").slice(0, 4)} · {s.ingest.datasetsDone.length} quarterly sets · {s.ingest.dailyDaysCount} daily indexes · screen {s.screenVersion}</span></div>
        <div className="panel-body scout-stats">
          <Stat label="Insider filings" value={compactUsd(nForm("4")).slice(1)} sub="Form 4" />
          <Stat label="Insider purchases" value={compactUsd(Number(ing.trades?.P ?? 0)).slice(1)} sub={`${compactUsd(Number(ing.trades?.S ?? 0)).slice(1)} sales`} />
          <Stat label="Earnings filings" value={nForm("8-K").toLocaleString()} sub="8-K, this quarter" />
        </div>
      </div>
      <div className="panel mb">
        <DisclosureHead open={showSettings} onToggle={() => setShowSettings(!showSettings)}
          extra={<button className="link-btn" onClick={onSettings}>open Settings</button>}>
          Rules in force <span className="muted">· {settings.length} settings, fixed for the paper run</span>
        </DisclosureHead>
        <Collapse open={showSettings}>
          <div className="scroll-x">
            <table className="tbl"><tbody>
              {settings.map(([k, v]) => <tr key={k}><td className="mono-num">{k}</td><td className="muted">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>)}
            </tbody></table>
          </div>
        </Collapse>
      </div>
    </>
  );
}
