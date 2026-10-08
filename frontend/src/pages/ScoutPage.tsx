// Scout (research only, 2026-10-07): rules find candidates in SEC filings, two LLM lanes filter and
// explain them, simulated research books measure each lane. Nothing here places an order.
import { Fragment, useMemo, useState } from "react";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useStore } from "../store";
import type { ScoutCandidate, ScoutLane, ScoutStatus, ScoutVerdict } from "../types";

const TABS = [
  { key: "candidates", label: "Candidates" },
  { key: "lanes", label: "Lanes" },
  { key: "status", label: "Status" },
] as const;
type Tab = (typeof TABS)[number]["key"];

const KIND: Record<string, string> = { s1_insider: "S1", s1_unclassified: "S1 unclassified", s2_earnings: "S2", random: "random" };
const GATE_ORDER = ["price", "adv", "spread", "marketCap", "earningsInHold", "corporateActions", "tipsMention"];

function money(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${v < 0 ? "−" : ""}$${s}`;
}
function signed(v: number | null | undefined) {
  if (v == null) return <span className="muted">—</span>;
  return <span className={v > 0 ? "pos" : v < 0 ? "neg" : ""}>{v > 0 ? "+" : ""}{money(v)}</span>;
}
function pill(status: string | undefined) {
  const cls = status === "pass" ? "ok" : status === "fail" ? "bad" : "";
  return <span className={`status-pill ${cls}`}>{status ?? "—"}</span>;
}

export function ScoutPage() {
  const pageTab = useStore((s) => s.pageTab);
  const setPageTab = useStore((s) => s.setPageTab);
  const tab: Tab = (TABS.some((t) => t.key === pageTab) ? pageTab : "candidates") as Tab;
  return (
    <div className="tips-page">
      <div className="tips-head">
        <div className="tabs" role="tablist" style={{ flex: 1 }}>
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""}
              onClick={() => setPageTab(t.key)}>{t.label}</button>
          ))}
        </div>
        <span className="muted">research only · simulated books, never a broker</span>
      </div>
      {tab === "candidates" && <CandidatesTab />}
      {tab === "lanes" && <LanesTab />}
      {tab === "status" && <StatusTab />}
    </div>
  );
}

// ------------------------------------------------------------------ Candidates
function CandidatesTab() {
  const [days, setDays] = useState(14);
  const st = useAsync(() => api.scoutCandidates(days), [days]);
  const [open, setOpen] = useState<string | null>(null);
  const rows = st.data ?? [];
  return (
    <div className="panel mb">
      <div className="panel-head">Candidates <span className="sub">found by the rules (never by a model); a model only keeps or drops one</span>
        <span style={{ flex: 1 }} />
        <div className="tabs" role="tablist">
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
            <table className="tbl">
              <thead><tr><th>Signal</th><th>Ticker</th><th>Found</th><th>Entry</th><th>Gates</th><th>Claude</th><th>GPT</th><th>Books</th><th>Filing</th></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <Fragment key={c.id}>
                    <tr className="clickable" style={{ cursor: "pointer" }} tabIndex={0} aria-expanded={open === c.id}
                      onClick={() => setOpen(open === c.id ? null : c.id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === c.id ? null : c.id); } }}>
                      <td>{KIND[c.kind] ?? c.kind}</td>
                      <td className="mono-num">{c.ticker}</td>
                      <td className="muted">{c.signalDate}</td>
                      <td className="muted">{c.entryDate ?? "—"}</td>
                      <td title={gateTitle(c)}>{pill(c.status)}{c.status !== c.preEntry ? <span className="muted"> · before entry {c.preEntry}</span> : null}</td>
                      <td><VerdictCell v={c.verdicts.find((v) => v.lane === "claude")} /></td>
                      <td><VerdictCell v={c.verdicts.find((v) => v.lane === "gpt")} /></td>
                      <td className="muted">{c.entries.length ? c.entries.map((e) => `${e.bookLabel.replace("Scout ", "")}: ${e.status}`).join(" · ") : "—"}</td>
                      <td>{c.links[0] ? <a href={c.links[0].url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>SEC ↗</a> : <span className="muted">—</span>}</td>
                    </tr>
                    {open === c.id && <tr><td colSpan={9}><CandidateDetail c={c} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </div>
  );
}

function gateTitle(c: ScoutCandidate) {
  return GATE_ORDER.filter((g) => c.gates[g]).map((g) => `${g}: ${c.gates[g].status} - ${c.gates[g].why}`).join("\n");
}

function VerdictCell({ v }: { v?: ScoutVerdict }) {
  if (!v) return <span className="muted">—</span>;
  if (v.status !== "ok") return <span className="muted" title={v.reason ?? ""}>{v.status}</span>;
  return <span title={v.reason ?? ""}>{v.verdict}{v.conviction ? <span className="muted"> {v.conviction}/5</span> : null}{v.reason?.startsWith("ungrounded") ? <span className="muted"> · ungrounded</span> : null}</span>;
}

function CandidateDetail({ c }: { c: ScoutCandidate }) {
  const ev = c.evidence ?? {};
  return (
    <div className="panel-body" style={{ display: "grid", gap: 10 }}>
      <div className="muted">
        {c.kind.startsWith("s1") && <>{(ev.insiders?.length ?? 0)} insiders · {money(ev.totalValue, 0)} · window {(ev.window ?? []).join(" → ")}</>}
        {c.kind === "s2_earnings" && ev.abnormalReturn != null && <>abnormal return {(ev.abnormalReturn * 100).toFixed(1)}% · volume {Number(ev.volumeRatio ?? 0).toFixed(1)}× · rank {ev.rank}/{ev.of}</>}
        {c.kind === "random" && <>random twin of {ev.matchedTicker} ({KIND[ev.matchedKind] ?? ev.matchedKind}) · offset {ev.offsetSessions} sessions · pool {ev.poolSize}</>}
      </div>
      <table className="tbl"><tbody>
        {GATE_ORDER.filter((g) => c.gates[g]).map((g) => (
          <tr key={g}><td>{g}</td><td>{pill(c.gates[g].status)}</td><td className="muted">{c.gates[g].why}</td></tr>
        ))}
      </tbody></table>
      {c.verdicts.map((v) => <VerdictDetail key={v.id} v={v} />)}
      {c.entries.length > 0 && (
        <table className="tbl"><tbody>
          {c.entries.map((e) => (
            <tr key={e.id}><td>{e.bookLabel}</td><td>{e.status}</td>
              <td className="muted">{e.entryPrice != null ? `${e.qty} @ ${e.entryPrice.toFixed(2)} · stop ${e.stopPrice?.toFixed(2)}` : e.reason ?? ""}</td>
              <td>{e.netPnl != null ? signed(e.netPnl) : null}</td></tr>
          ))}
        </tbody></table>
      )}
      {c.links.length > 1 && <div className="muted">{c.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer" style={{ marginRight: 10 }}>{l.label} ↗</a>)}</div>}
    </div>
  );
}

function VerdictDetail({ v }: { v: ScoutVerdict }) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <div>
        <b>{v.lane === "claude" ? "Claude" : "GPT"}</b> <span className="muted">{v.model}</span>{" · "}
        {v.status === "ok" ? <>{v.verdict} {v.conviction ? `${v.conviction}/5` : ""}{v.reason ? ` · ${v.reason}` : ""}</> : <span className="muted">{v.reason ?? v.status}</span>}
        <span className="muted"> · ${v.costUsd.toFixed(4)} · {v.tokensIn + v.cacheRead}/{v.tokensOut} tok</span>
        {(v.claims.length > 0 || v.droppedClaims.length > 0) && (
          <button className="link-btn" onClick={() => setShow(!show)} aria-expanded={show}>{show ? "hide claims" : `claims (${v.claims.length}${v.droppedClaims.length ? `, ${v.droppedClaims.length} dropped` : ""})`}</button>
        )}
      </div>
      {v.reasons.length > 0 && <ul style={{ margin: "4px 0 0 18px" }}>{v.reasons.map((r, i) => <li key={i}>{r.text} <span className="muted">[{r.claims.map((x) => x + 1).join(", ")}]</span></li>)}</ul>}
      {show && (
        <ol style={{ margin: "4px 0 0 18px" }}>
          {v.claims.map((c, i) => <li key={i}>{c.text} <span className="muted">— “{c.quote}” ({c.sourceId})</span></li>)}
          {v.droppedClaims.map((c, i) => <li key={`d${i}`} className="muted"><s>{c.text}</s> — dropped: {c.why}</li>)}
        </ol>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Lanes
function LanesTab() {
  const st = useAsync(() => api.scoutLanes(), []);
  const openPortfolios = useStore((s) => s.openPortfolios);
  const [open, setOpen] = useState<string | null>(null);
  if (st.loading && !st.data) return <Spinner label="loading lanes…" />;
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  const lanes = st.data ?? [];
  return (
    <div className="panel mb">
      <div className="panel-head">Lanes <span className="sub">one simulated book per lane · US$600 per entry, stop 2× daily ATR, time exit · after $1/order (the half spread is in the ask/bid fills)</span></div>
      <div className="scroll-x">
        <table className="tbl">
          <thead><tr><th>Book</th><th>Open</th><th>Closed</th><th>Skipped</th><th>Hit rate</th><th>Realized</th><th>Open P&amp;L</th><th>Total</th></tr></thead>
          <tbody>
            {lanes.map((l) => (
              <Fragment key={l.lane}>
                <tr className="clickable" style={{ cursor: "pointer" }} tabIndex={0} aria-expanded={open === l.lane}
                  onClick={() => setOpen(open === l.lane ? null : l.lane)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === l.lane ? null : l.lane); } }}>
                  <td>{l.portfolioId ? <button className="link-btn" onClick={(e) => { e.stopPropagation(); openPortfolios(l.portfolioId!); }}>{l.label}</button> : <span className="muted">{l.label}</span>}</td>
                  <td>{l.open}</td><td>{l.closed}</td><td className="muted">{l.skipped}</td>
                  <td>{l.hitRate == null ? <span className="muted">—</span> : `${Math.round(l.hitRate * 100)}%`}</td>
                  <td>{signed(l.closed ? l.realizedNet : null)}</td><td>{signed(l.open ? l.openNet : null)}</td><td>{signed(l.entries ? l.totalNet : null)}</td>
                </tr>
                {open === l.lane && <tr><td colSpan={8}><LaneTrades l={l} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LaneTrades({ l }: { l: ScoutLane }) {
  const rows = [...l.openTrades, ...l.closedTrades];
  if (!rows.length) return <div className="muted panel-body">no trades yet</div>;
  return (
    <table className="tbl"><tbody>
      {rows.map((t) => (
        <tr key={t.id}>
          <td className="mono-num">{t.ticker}</td><td className="muted">{t.entryDate}</td><td>{t.status}</td>
          <td className="muted">{t.qty} @ {t.entryPrice?.toFixed(2)} · stop {t.stopPrice?.toFixed(2)}{t.exitPrice != null ? ` → ${t.exitPrice.toFixed(2)} (${t.exitReason ?? ""})` : t.mark != null ? ` · mark ${t.mark.toFixed(2)}` : ""}</td>
          <td>{signed(t.netPnl ?? t.openNetPnl ?? null)}</td>
        </tr>
      ))}
    </tbody></table>
  );
}

// ------------------------------------------------------------------ Status
function StatusTab() {
  const st = useAsync(() => api.scoutStatus(), []);
  const setPage = useStore((s) => s.setPage);
  if (st.loading && !st.data) return <Spinner label="loading status…" />;
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  const s = st.data as ScoutStatus;
  return <StatusBody s={s} onSettings={() => setPage("settings")} />;
}

function StatusBody({ s, onSettings }: { s: ScoutStatus; onSettings: () => void }) {
  const settings = useMemo(() => Object.entries(s.settings ?? {}), [s.settings]);
  const lr = s.lastRun as Record<string, any> | null;
  const report = s.reports?.[0];
  return (
    <>
      <div className="panel mb">
        <div className="panel-head">Today <span className="sub">{lr?.at ? `last daily run ${String(lr.at).slice(0, 16).replace("T", " ")}` : "no daily run yet"}</span></div>
        <div className="panel-body" style={{ display: "grid", gap: 4 }}>
          <div>S1 {s.enabled.s1 ? "on" : "off"} · S2 {s.enabled.s2 ? "on" : "off"} · daily job {s.enabled.daily ? "on" : "off"}{s.running ? " · running now" : ""}</div>
          {lr?.s1 && <div className="muted">S1: {lr.s1.purchases} purchases · {lr.s1.clusters} clusters · {lr.s1.new} new</div>}
          {lr?.s2 && <div className="muted">S2: {lr.s2.events} releases · {lr.s2.hits} hits · {lr.s2.new} new</div>}
          <div className="muted">schedule: {s.schedule.map((j) => `${j.name.replace("scout_", "")} ${j.at}`).join(" · ")}</div>
        </div>
      </div>
      <div className="panel mb">
        <div className="panel-head">LLM spend <span className="sub">both lanes share one daily budget; a lane stops calling once it is used</span></div>
        <div className="panel-body" style={{ display: "grid", gap: 4 }}>
          <div>{money(s.llm.total, 4)} of {money(s.llm.budgetUsd)} today</div>
          {(["claude", "gpt"] as const).map((k) => {
            const lane = s.llm.lanes[k];
            const by = s.llm.byLane[k];
            return <div key={k} className="muted">{k === "claude" ? "Claude" : "GPT"} · {lane.model} ({lane.effort}) · {lane.enabled ? "on" : "off"} · {lane.keyPresent ? "key set" : "no API key — lane skipped"} · {money(by?.usd ?? 0, 4)} in {by?.calls ?? 0} call(s)</div>;
          })}
        </div>
      </div>
      <div className="panel mb">
        <div className="panel-head">Ingest <span className="sub">SEC EDGAR</span></div>
        <div className="panel-body muted" style={{ display: "grid", gap: 4 }}>
          <div>coverage from {s.ingest.coverageStart ?? "—"} · {s.ingest.datasetsDone.length} quarterly data sets · {s.ingest.dailyDaysCount} daily indexes</div>
          {Object.entries(s.ingest).filter(([, v]) => typeof v === "number").map(([k, v]) => <span key={k}>{k}: {Number(v).toLocaleString()}</span>)}
        </div>
      </div>
      {report && (
        <div className="panel mb">
          <div className="panel-head">Daily report <span className="sub">{report.day}</span></div>
          <div className="panel-body" style={{ display: "grid", gap: 4 }}>
            <div className="muted">candidates {report.candidates.reduce((a, c) => a + c.n, 0)} · verdicts {report.verdicts.reduce((a, v) => a + v.n, 0)} · entries {report.entries.length} · exits {report.exits.length} · LLM {money(report.llm.total, 4)}</div>
            {report.lanes.filter((l) => l.entries > 0).map((l) => <div key={l.lane}>{l.label}: {l.open} open · {l.closed} closed · {signed(l.totalNet)}</div>)}
          </div>
        </div>
      )}
      <div className="panel mb">
        <div className="panel-head">Settings <span className="sub">read-only here · preregistered, not tuned during the paper run</span>
          <span style={{ flex: 1 }} /><button className="link-btn" onClick={onSettings}>open Settings</button></div>
        <div className="scroll-x">
          <table className="tbl"><tbody>
            {settings.map(([k, v]) => <tr key={k}><td className="mono-num">{k}</td><td className="muted">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>)}
          </tbody></table>
        </div>
      </div>
    </>
  );
}
