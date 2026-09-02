import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import Highcharts from "highcharts/esm/highstock.js";
import { memo } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtPct, fmtQty, fmtSigned } from "../lib/format";
import { baseChartOptions, seriesPalette } from "../lib/highchartsTheme";
import { symbolLabel } from "../lib/occ";
import { SymIcon } from "../components/SymIcon";
import { useAsync } from "../lib/useAsync";
import { groupPositions, useQuote, useStore } from "../store";
import { useViewport } from "../lib/viewport";
import type {
  BrokeragePosition, BrokerageProvider, ManagedPosition, Portfolio, Position,
} from "../types";
import { BrokerIcon } from "../components/BrokerIcon";
import { IconRefresh } from "../components/icons";
import { LivePrice, ValuePill } from "../components/quotekit";
import { cashText, providerTotal } from "../lib/brokerage";
import { AsyncSection, EmptyState } from "../components/ui";
import { ResearchBadge } from "../components/ResearchBadge";

const KIND_LABEL: Record<string, string> = {
  live: "Live", paper: "Paper", sim: "Practice", shadow: "Shadow",
};
const REAL_KINDS = new Set(["live", "paper"]);

function PortfolioCard({
  portfolio,
  positions,
  visible,
  onToggle,
}: {
  portfolio: Portfolio;
  positions: Position[];
  visible: boolean;
  onToggle: (v: boolean) => void;
}) {
  const p = portfolio;
  const ccy = p.baseCurrency ?? "USD";
  const equity = p.equity ?? p.cash;
  const pnl = equity - p.startingCash;
  const positionCount = positions.length;
  return (
    <div className="panel">
      <div className="panel-head">
        {p.name}
        <span className={`status-pill ${p.kind === "live" ? "bad" : p.kind === "shadow" ? "dim" : "ok"}`}>
          {KIND_LABEL[p.kind] ?? p.kind}
        </span>
        {p.venue === "snaptrade" && <span className="status-pill dim">snaptrade</span>}
        <label className="switch" style={{ marginLeft: "auto" }} title="Show on equity chart">
          <input type="checkbox" checked={visible}
            onChange={(e) => onToggle(e.target.checked)} />
          <span className="track" />
        </label>
      </div>
      <div className="panel-body">
        <div className="metric-lg">
          {fmtCcy(equity, ccy)}
          {p.todayPct !== null && p.todayPct !== undefined && (
            <span style={{ marginLeft: 8, verticalAlign: "middle" }}
              title="Equity change vs today's first quote-backed observation">
              <ValuePill value={p.todayPct}
                text={`${p.todayPct >= 0 ? "+" : ""}${p.todayPct.toFixed(2)}% today`} />
            </span>
          )}
        </div>
        {p.kind !== "live" && (
          <div className={pnl >= 0 ? "pos" : "neg"} style={{ fontSize: "var(--fs-2)" }}>
            {fmtSigned(pnl)} since start
          </div>
        )}
        <div className="metric-sub" style={{ marginTop: 6 }}>
          cash {fmtCcy(p.cash, ccy)} · invested {fmtCcy(Math.max(equity - p.cash, 0), ccy)}
          · {positionCount} position{positionCount === 1 ? "" : "s"}
          {p.sourceName && p.sourceName !== "snaptrade" && <> · tracks "{p.sourceName}"</>}
        </div>
        {positionCount > 0 && (
          <div className="scroll-x" style={{ marginTop: 8 }}>
            <EnginePosTable positions={positions} />
          </div>
        )}
      </div>
    </div>
  );
}

/* ── engine positions (practice/shadow books): live-priced breakdown ──── */

const EnginePosRow = memo(function EnginePosRow({ pos }: { pos: Position }) {
  const quote = useQuote(pos.symbol);
  const openTrade = useStore((s) => s.openTrade);
  const mult = pos.option?.multiplier ?? (pos.secType === "OPT" ? 100 : 1);
  const live = quote?.last && quote.last > 0 ? quote.last : pos.last ?? 0;
  const pnl = live > 0 ? (live - pos.avgCost) * pos.qty * mult : null;
  const pnlPct = live > 0 && pos.avgCost > 0 ? (live / pos.avgCost - 1) * 100 : null;
  const underlying = pos.option?.underlying ?? pos.symbol;
  return (
    <tr onClick={() => openTrade(underlying)} style={{ cursor: "pointer" }}
      title={`Open ${underlying} in Trade`}>
      <td className="sym-cell"><SymIcon sym={underlying} size={18} />{pos.option?.display ?? symbolLabel(pos.symbol)}</td>
      <td className="num">{fmtQty(pos.qty)}</td>
      <td className="num">{fmtMoney(pos.avgCost)}</td>
      <td className="num">{live > 0 ? fmtMoney(live) : "—"}</td>
      <td className="num">
        {pnlPct !== null && pnl !== null
          ? <ValuePill value={pnlPct} text={`${fmtSigned(pnl)} (${fmtPct(pnlPct)})`} />
          : "—"}
      </td>
      <td className="num">{live > 0 ? fmtMoney(pos.qty * live * mult) : "—"}</td>
    </tr>
  );
});

function EnginePosTable({ positions }: { positions: Position[] }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Position</th><th className="num">Qty</th><th className="num">Avg cost</th>
          <th className="num">Live</th><th className="num">P&L</th><th className="num">Value</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => <EnginePosRow key={`${p.symbol}:${p.secType}`} pos={p} />)}
      </tbody>
    </table>
  );
}

/* ── managed positions: the durable positions the engine runs ─────────── */

const attnText = (a: any): string =>
  typeof a === "string" ? a : a?.text ?? a?.reason ?? a?.event ?? "needs attention";

/** The exit plan as a price ladder (broker "bracket" view): stop → entry →
    targets on one rail, with the live underlying marked. Color is reserved
    for the live marker and the P&L — the rail itself stays quiet. */
function ExitLadder({ m, now }: { m: ManagedPosition; now: number | null }) {
  const lad = m.policy?.ladder ?? {};
  const targets: number[] = lad.targets ?? [];
  const fractions: number[] = lad.fractions ?? [];
  const trimsDone = m.state?.trimsDone ?? 0;
  const stop = m.state?.stop ?? m.policy?.stop?.price ?? null;
  type Pt = { v: number; lbl: string; kind: string; title: string };
  const pts: Pt[] = [];
  if (stop != null) pts.push({ v: stop, lbl: `stop ${stop}`, kind: "stop",
    title: m.state?.breakevenDone ? "stop (moved to breakeven)" : "protective stop — exits on the bar close through it" });
  if (m.entry) pts.push({ v: m.entry, lbl: `entry ${m.entry}`, kind: "entry", title: "underlying reference entry" });
  targets.forEach((t, i) => pts.push({
    v: t, lbl: `TP${i + 1} ${t}`, kind: i < trimsDone ? "done" : "tp",
    title: `take-profit ${i + 1}${fractions[i] != null ? ` — trims ${Math.round(fractions[i] * 100)}%` : ""}${i < trimsDone ? " (done)" : ""}`,
  }));
  if (pts.length < 2) return null;
  const vals = pts.map((p) => p.v).concat(now != null ? [now] : []);
  let min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min || 1) * 0.07;
  min -= pad; max += pad;
  const x = (v: number) => ((v - min) / (max - min)) * 100;
  return (
    <div className="mgd-ladder" aria-hidden>
      <div className="mgd-ladder-track" />
      {pts.map((p) => (
        <div key={p.lbl} className={`mgd-tick mgd-tick--${p.kind}`}
          style={{ left: `${x(p.v)}%` }} title={p.title}>
          <div className="mgd-tick-line" />
          <div className="mgd-tick-lbl">{p.lbl}{p.kind === "done" ? " ✓" : ""}</div>
        </div>
      ))}
      {now != null && (
        <div className="mgd-now" style={{ left: `${x(now)}%` }} title={`underlying now ${fmtMoney(now)}`}>
          <div className="mgd-now-dot" />
          <div className="mgd-now-lbl">{fmtMoney(now)}</div>
        </div>
      )}
    </div>
  );
}

function MgdCard({ m, onChanged }: { m: ManagedPosition; onChanged: () => void }) {
  const toast = useStore((s) => s.toast);
  const openTrade = useStore((s) => s.openTrade);
  const quotes = useStore((s) => s.quotes);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const uq = useQuote(m.symbol);
  const now = uq?.last && uq.last > 0 ? uq.last : null;
  // header P&L: sum over legs against live premiums (null until quotes exist)
  const totals = useMemo(() => {
    let cost = 0, val = 0, complete = m.legs.length > 0;
    for (const l of m.legs) {
      if (l.avgFill == null) { complete = false; continue; }
      cost += l.avgFill * l.qty * l.multiplier;
      const q = quotes[l.symbol]?.last;
      if (q && q > 0) val += q * l.qty * l.multiplier;
      else complete = false;
    }
    return complete && Math.abs(cost) > 1e-9
      ? { unreal: val - cost, pct: ((val - cost) / Math.abs(cost)) * 100 }
      : null;
  }, [quotes, m.legs]);
  const timeBox = m.policy?.time_stop_sessions;
  const events = (m.events ?? []).slice(-2).reverse();
  const close = async () => {
    setBusy(true);
    try {
      await api.closeManagedPosition(m.id);
      toast("success", `Closing ${m.symbol} (reduce-only, at market)`);
      onChanged();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };
  return (
    <div className={`mgd-card mgd-card--click ${m.status === "attention" ? "mgd-attn" : ""}`}
      role="button" tabIndex={0} onClick={() => openTrade(m.symbol)}
      onKeyDown={(e) => { if (e.key === "Enter") openTrade(m.symbol); }}
      title={`Open ${m.symbol} in Trade`}>
      <div className="mgd-head">
        <SymIcon sym={m.symbol} size={30} />
        <span>
          <span className="mgd-sym">{m.symbol}</span>
          <span className="mgd-contract">
            {m.legs.map((l) => `${l.qty > 0 ? "+" : ""}${fmtQty(l.qty)} × ${symbolLabel(l.symbol)}`).join("  ·  ")}
          </span>
        </span>
        <span className={`status-pill ${m.status === "open" ? "ok" : m.status === "attention" ? "bad" : "dim"}`}>
          {m.status}
        </span>
        <span className="mgd-headr">
          {totals ? (
            <ValuePill value={totals.unreal} text={`${fmtSigned(totals.unreal)} (${fmtPct(totals.pct)})`} />
          ) : (
            <span className="muted" style={{ fontSize: 12 }}>no live premium yet</span>
          )}
        </span>
      </div>
      <ExitLadder m={m} now={now} />
      <div className="mgd-meta">
        <span className="muted">
          {m.technique} · {m.direction} · opened {m.openedMs ? fmtDateTime(new Date(m.openedMs).toISOString()) : "—"}
          {" · "}held {m.sessionsHeld}{timeBox ? `/${timeBox}` : ""} session{m.sessionsHeld === 1 && !timeBox ? "" : "s"}
          {m.legs.map((l) => l.avgFill != null ? ` · in @ ${fmtMoney(l.avgFill)}` : "").join("")}
          {m.policy?.premium_stop_pct ? ` · premium stop ${m.policy.premium_stop_pct}%` : ""}
          {m.policy?.premium_ladder?.gains_pct?.length
            ? ` · take ${m.policy.premium_ladder.gains_pct.map((g: number, i: number) =>
                `${Math.round((m.policy.premium_ladder.fractions?.[i] ?? 0) * 100)}% at +${g}%`).join(", ")}`
              + (m.state?.premiumTrimsDone ? ` (${m.state.premiumTrimsDone} taken)` : "")
            : ""}
          {m.policy?.dte_close != null ? ` · closes by ${m.policy.dte_close} DTE` : ""}
          {m.policy?.stop?.kind === "none" ? " · no price stop (guarded)" : ""}
          {m.realizedPnl !== 0 ? <> · realized <span className={m.realizedPnl >= 0 ? "pos" : "neg"}>{fmtSigned(m.realizedPnl)}</span></> : ""}
        </span>
        {m.status !== "closed" && (
          <span className="mgd-actions" onClick={(e) => e.stopPropagation()}>
            {confirming ? (
              <>
                <span className="muted" style={{ fontSize: 12 }}>Close at market?</span>
                <button className="danger-btn" disabled={busy} onClick={close}>yes, close it</button>
                <button className="link-btn" onClick={() => setConfirming(false)}>keep it</button>
              </>
            ) : (
              <button className="link-btn danger" onClick={() => setConfirming(true)}
                title="Reduce-only market exit through the risk gate — never blocked by entry caps">
                close…
              </button>
            )}
          </span>
        )}
      </div>
      {(m.attention ?? []).length > 0 && (
        <div className="neg" style={{ fontSize: 12, marginTop: 4 }}>
          ⚠ {attnText(m.attention[m.attention.length - 1])}
        </div>
      )}
      {events.length > 0 && (
        <div className="mgd-events">
          {events.map((e) => (
            <span key={e.ts}>{fmtDateTime(new Date(e.ts).toISOString())} · {e.event}{e.text ? ` — ${e.text}` : ""}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function MgdClosedRow({ m }: { m: ManagedPosition }) {
  const lastExit = (m.exits ?? [])[Math.max(0, (m.exits ?? []).length - 1)] as any;
  const reason = lastExit?.reason ?? lastExit?.kind ?? "";
  return (
    <div className="mgd-closed">
      <span style={{ fontFamily: "var(--mono)" }}>
        {m.closedMs ? fmtDateTime(new Date(m.closedMs).toISOString()) : "—"}
      </span>
      <span><b>{m.symbol}</b> <span className="muted">{m.legs.map((l) => symbolLabel(l.symbol)).join(", ")}{reason ? ` · ${reason}` : ""}</span></span>
      <span className="muted">{m.technique} · {m.sessionsHeld}s held</span>
      <span className={`num ${m.realizedPnl >= 0 ? "pos" : "neg"}`} style={{ fontFamily: "var(--mono)", textAlign: "right" }}>
        {fmtSigned(m.realizedPnl)}
      </span>
    </div>
  );
}

function ManagedPanel() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 20000);
    return () => clearInterval(t);
  }, []);
  const st = useAsync(() => api.listManagedPositions(), [tick]);
  const rows = st.data ?? [];
  const active = rows.filter((m) => m.status !== "closed");
  const recent = rows.filter((m) => m.status === "closed")
    .sort((a, b) => (b.closedMs ?? 0) - (a.closedMs ?? 0)).slice(0, 6);
  if (rows.length === 0) return null;
  return (
    <div className="panel mb">
      <div className="panel-head">
        Managed positions
        <span className="sub">
          durable positions the engine runs — each follows its own exit plan (trims · stops · time box)
        </span>
      </div>
      <div className="panel-body">
        {active.length === 0 && <div className="empty">Nothing under management right now.</div>}
        {active.map((m) => <MgdCard key={m.id} m={m} onChanged={() => setTick((x) => x + 1)} />)}
        {recent.length > 0 && (
          <>
            <div className="muted" style={{ fontSize: 12, margin: "10px 0 6px" }}>Recently closed</div>
            {recent.map((m) => <MgdClosedRow key={m.id} m={m} />)}
          </>
        )}
      </div>
    </div>
  );
}

/* ── shadow research books: per-source scorecards, not accounts ───────── */

function ShadowBooksPanel({ books: allBooks, byPortfolio, hidden, onToggle }: {
  books: Portfolio[];
  byPortfolio: Record<string, Position[]>;
  hidden: Record<string, boolean>;
  onToggle: (pid: string, v: boolean) => void;
}) {
  const toast = useStore((s) => s.toast);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [removed, setRemoved] = useState<Record<string, boolean>>({});
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const books = allBooks.filter((p) => !removed[p.id]);
  const remove = async (p: Portfolio) => {
    setBusy(true);
    try {
      await api.removeShadowBook(p.id);
      setRemoved((r) => ({ ...r, [p.id]: true }));
      toast("info", `Removed the "${p.name}" research book`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
      setConfirmId(null);
    }
  };
  // one row per SOURCE (POST-SOAK 3.3): the immediate/armed pair is two lanes
  // of one question, not two accounts. Cash is bookkeeping — show the record.
  const trustState = useAsync(() => api.sourceScorecards(), [books.length]);
  const trustBySource = useMemo(() => {
    const m: Record<string, { graded: number; hits: number }> = {};
    for (const c of (trustState.data ?? []) as any[]) if (c.trust) m[c.source] = c.trust;
    return m;
  }, [trustState.data]);
  const sources = useMemo(() => {
    const m: Record<string, { immediate?: Portfolio; armed?: Portfolio }> = {};
    for (const p of books) {
      const src = p.sourceName || p.name.replace(/^Shadow:\s*/, "").replace(/\s*\(armed\)$/, "");
      const lane = (p.book === "armed" || / \(armed\)$/.test(p.name)) ? "armed" : "immediate";
      (m[src] ??= {})[lane] = p;
    }
    return m;
  }, [books]);
  const laneCell = (p?: Portfolio) => {
    if (!p) return <td className="num muted">—</td>;
    const pnl = (p.equity ?? p.cash) - p.startingCash;
    const pos = byPortfolio[p.id] ?? [];
    const committed = pos.reduce((a, x) => a + Math.abs(x.qty * x.avgCost * (x.secType === "OPT" ? 100 : 1)), 0);
    return (
      <td className={`num ${pnl >= 0 ? "pos" : "neg"}`} style={{ fontFamily: "var(--mono)" }}
        title={`${pos.length} open · committed ${fmtCcy(committed, p.baseCurrency ?? "USD")}`}>
        {fmtSigned(pnl)}{pos.length > 0 && <span className="muted"> ·{pos.length}</span>}
      </td>
    );
  };
  if (books.length === 0) return null;
  return (
    <div className="panel mb">
      <div className="panel-head">
        <ResearchBadge /> Research books
        <span className="sub">
          per tip source: the immediate lane buys at tip time, the armed lane waits for
          the level — the comparison IS the experiment; simulated, never funded
        </span>
      </div>
      <div className="panel-body">
        <div className="scroll-x">
          <table className="tbl">
            <thead>
              <tr>
                <th>Source</th><th className="num">Record</th>
                <th className="num" title="P&L of the buy-at-tip-time lane">Immediate</th>
                <th className="num" title="P&L of the wait-for-the-level lane (the judged one)">Armed</th>
                <th className="num">Open</th><th className="num">Chart</th><th></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(sources).map(([src, lanes]) => {
                const pair = [lanes.immediate, lanes.armed].filter(Boolean) as Portfolio[];
                const pos = pair.flatMap((p) => byPortfolio[p.id] ?? []);
                const isOpen = !!open[src];
                const t = trustBySource[src];
                const anyShown = pair.some((p) => !hidden[p.id]);
                return (
                  <Fragment key={src}>
                    <tr onClick={() => pos.length && setOpen((o) => ({ ...o, [src]: !isOpen }))}
                      style={{ cursor: pos.length ? "pointer" : "default" }}
                      title={pos.length ? "Show this source's open research positions" : undefined}>
                      <td>{src}</td>
                      <td className="num muted"
                        title="closed tip positions for this source: hits / graded — the earned-auto bar reads this">
                        {t ? `${t.hits}/${t.graded} hit` : "—"}
                      </td>
                      {laneCell(lanes.immediate)}
                      {laneCell(lanes.armed)}
                      <td className="num">{pos.length}{pos.length > 0 && <span className="muted"> {isOpen ? "▾" : "▸"}</span>}</td>
                      <td className="num">
                        <label className="switch" title="Show this source's lanes on the equity chart" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={anyShown}
                            onChange={(e) => pair.forEach((p) => onToggle(p.id, e.target.checked))} />
                          <span className="track" />
                        </label>
                      </td>
                      <td className="num" onClick={(e) => e.stopPropagation()}>
                        {confirmId === src ? (
                          <>
                            <button className="link-btn danger" disabled={busy}
                              onClick={async () => { for (const p of pair) await remove(p); }}>
                              delete both?</button>
                            <button className="link-btn" onClick={() => setConfirmId(null)}>keep</button>
                          </>
                        ) : (
                          <button className="link-btn danger"
                            title={`Remove BOTH of this source's research lanes${pos.length ? ` (${pos.length} simulated position(s) go with them)` : ""} — the journal keeps the audit trail; a future tip re-creates fresh books`}
                            onClick={() => setConfirmId(src)}>✕</button>
                        )}
                      </td>
                    </tr>
                    {isOpen && pos.length > 0 && (
                      <tr className="shadow-detail">
                        <td colSpan={7}><EnginePosTable positions={pos} /></td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/** Live-priced row: the sync price is only the fallback — quotes stream in. */
const LiveBrokerageRow = memo(function LiveBrokerageRow({
  pos,
  accountCurrency,
}: {
  pos: BrokeragePosition;
  accountCurrency: string;
}) {
  const quote = useQuote(pos.symbol);
  const openTrade = useStore((s) => s.openTrade);
  const live = quote?.last && quote.last > 0 ? quote.last : pos.price ?? 0;
  const ccy = pos.currency ?? accountCurrency;
  const pnlPct = pos.avgCost > 0 ? (live / pos.avgCost - 1) * 100 : null;
  return (
    <tr onClick={() => openTrade(pos.symbol)} style={{ cursor: "pointer" }}
      title={`Open ${pos.symbol} in Trade`}>
      <td className="sym-cell">{pos.symbol}</td>
      <td className="num">{fmtQty(pos.qty)}</td>
      <td className="num">{fmtMoney(pos.avgCost)}</td>
      <td className="num"><LivePrice symbol={pos.symbol} fallback={live || undefined} /></td>
      <td className="num">
        {pnlPct !== null ? <ValuePill value={pnlPct} text={fmtPct(pnlPct)} /> : "—"}
      </td>
      <td className="num">{live ? fmtCcy(pos.qty * live, ccy) : "—"}</td>
    </tr>
  );
});

const BrokeragePosCard = memo(function BrokeragePosCard({ pos, accountCurrency }: { pos: BrokeragePosition; accountCurrency: string }) {
  const quote = useQuote(pos.symbol);
  const openTrade = useStore((s) => s.openTrade);
  const live = quote?.last && quote.last > 0 ? quote.last : pos.price ?? 0;
  const ccy = pos.currency ?? accountCurrency;
  const pnlPct = pos.avgCost > 0 ? (live / pos.avgCost - 1) * 100 : null;
  return (
    <button type="button" className="bl-card" onClick={() => openTrade(pos.symbol)}>
      <span className="bl-card-l">
        <span className="bl-card-sym">{pos.symbol}</span>
        <span className="bl-card-sub">{fmtQty(pos.qty)} @ {fmtMoney(pos.avgCost)}</span>
      </span>
      <span className="bl-card-r">
        <span className="bl-card-val"><LivePrice symbol={pos.symbol} fallback={live || undefined} /></span>
        {pnlPct !== null && <ValuePill value={pnlPct} text={fmtPct(pnlPct)} />}
        <span className="bl-card-sub">{live ? fmtCcy(pos.qty * live, ccy) : "—"}</span>
      </span>
    </button>
  );
});

function BrokerageSection({
  provider,
  onRefresh,
  refreshing,
  lastSyncAt,
}: {
  provider: BrokerageProvider;
  onRefresh: () => void;
  refreshing: boolean;
  lastSyncAt: string | null;
}) {
  const { isPhone } = useViewport();
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  const total = providerTotal(provider.accounts, usdCad);
  const warnPill = provider.disabled
    ? { cls: "bad", text: "disconnected" }
    : provider.type !== "trade" ? { cls: "dim", text: "read-only" } : null;
  return (
    <div className="panel mb" id={`provider-${provider.connectionId || provider.broker}`}>
      <div className="panel-head">
        <BrokerIcon name={provider.broker} logoUrl={provider.logoUrl} />
        {provider.broker}
        {warnPill && <span className={`status-pill ${warnPill.cls}`}>{warnPill.text}</span>}
        <span className="sub">synced {lastSyncAt ? fmtDateTime(lastSyncAt) : "never"}</span>
        <span className="prov-total">{total}</span>
        <button className="icon-btn" onClick={onRefresh}
          disabled={refreshing} aria-label={`Refresh ${provider.broker}`}
          title="Refresh brokerage data">
          {refreshing ? <span className="spinner" /> : <IconRefresh />}
        </button>
      </div>
      <div className="panel-body">
        {provider.accounts.map((a) => (
          <div key={a.id} className="mb">
            <div className="acct-head" style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
              <strong>{a.name}</strong>
              {a.number && <span className="metric-sub">#{a.number}</span>}
              <span className="ccy-chip">{a.currency}</span>
              {a.mismatch && (
                <span className="status-pill wait"
                  title={`Our live-priced equity ${fmtCcy(a.mismatch.computedEquity, a.currency)} vs the broker's total ${fmtCcy(a.mismatch.brokerTotal, a.currency)} (${a.mismatch.pct > 0 ? "+" : ""}${a.mismatch.pct}%). The broker total comes from SnapTrade's overnight sync${a.brokerSyncedAt ? ` (${fmtDateTime(a.brokerSyncedAt)})` : ""} — small drift is price/FX vintage; large drift means something is missing. Details: Journal → Broker.`}>
                  Δ mismatch
                </span>
              )}
              <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", textAlign: "right" }}>
                <b>{fmtCcy(a.equity, a.currency)}</b>
                {a.equity > 0.005 && (
                  <span className="metric-sub">
                    {" "}· invested {fmtCcy(a.equity - a.cash, a.currency)} · cash {cashText(a)}
                  </span>
                )}
              </span>
            </div>
            {a.mismatch && (
              <div className="metric-sub mismatch-note">
                Δ {a.mismatch.pct > 0 ? "+" : ""}{a.mismatch.pct}%: our live-priced {fmtCcy(a.mismatch.computedEquity, a.currency)} vs the broker's overnight {fmtCcy(a.mismatch.brokerTotal, a.currency)} — small drift is price/FX vintage; large drift means something is missing (Journal → Broker).
              </div>
            )}
            {a.positions.length === 0 ? (
              <div className="metric-sub">no positions</div>
            ) : isPhone ? (
              <div className="bl-cards" style={{ padding: 0 }}>
                {a.positions.map((pos) => <BrokeragePosCard key={pos.symbol} pos={pos} accountCurrency={a.currency} />)}
              </div>
            ) : (
              <div className="scroll-x">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Symbol</th><th className="num">Qty</th>
                      <th className="num">Avg cost</th><th className="num">Live</th>
                      <th className="num">P&L</th><th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.positions.map((pos) => (
                      <LiveBrokerageRow key={pos.symbol} pos={pos}
                        accountCurrency={a.currency} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PortfoliosPage() {
  const portfolios = useStore((s) => s.portfolios);
  const positionsMap = useStore((s) => s.positions);
  const brokerages = useStore((s) => s.brokerages);
  const applyBrokerages = useStore((s) => s.applyBrokerages);
  const toast = useStore((s) => s.toast);
  const setPage = useStore((s) => s.setPage);
  const theme = useStore((s) => s.settings["ui.theme"]);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<Highcharts.Chart | null>(null);
  const { isPhone } = useViewport();
  const phoneRef = useRef(isPhone);
  phoneRef.current = isPhone;
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [refreshing, setRefreshing] = useState(false);

  const byPortfolio = useMemo(() => groupPositions(positionsMap), [positionsMap]);
  const portfolioIds = portfolios.map((p) => p.id).join(",");
  const snaptradePids = useMemo(() => new Set(
    (brokerages?.providers ?? []).flatMap((pr) => pr.accounts.map((a) => a.portfolioId))),
    [brokerages]);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const ibkrConnected = useStore((s) => !!s.broker?.ibkrConnected);
  // brokerage-backed portfolios render inside their provider section — the
  // card grid carries only what's left. The empty IBKR placeholder hides
  // until the gateway actually connects or holds money.
  const realCards = useMemo(
    () => portfolios.filter((p) => REAL_KINDS.has(p.kind) && !snaptradePids.has(p.id)
      && (ibkrConnected || (p.equity ?? p.cash) > 0.005)),
    [portfolios, snaptradePids, ibkrConnected]);
  const practiceCards = useMemo(
    () => portfolios.filter((p) => !REAL_KINDS.has(p.kind)),
    [portfolios]);
  // trading books (Practice sim) get full cards; per-source shadow scorecard
  // books are research instruments and live in their own compact panel
  const practiceMain = useMemo(
    () => practiceCards.filter((p) => p.kind !== "shadow"), [practiceCards]);
  const shadowBooks = useMemo(
    () => practiceCards.filter((p) => p.kind === "shadow"), [practiceCards]);
  const showPractice = mode !== "live"; // live board = real money only
  const [chartScope, setChartScope] = useState<"all" | "real" | "practice">(
    mode === "live" ? "real" : "all");
  const chartScopeRef = useRef(chartScope);
  chartScopeRef.current = chartScope;
  const portfoliosFocus = useStore((s) => s.portfoliosFocus);
  const clearPortfoliosFocus = useStore((s) => s.clearPortfoliosFocus);
  useEffect(() => {
    if (!portfoliosFocus) return;
    document.getElementById(`provider-${portfoliosFocus}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
    clearPortfoliosFocus();
  }, [portfoliosFocus, clearPortfoliosFocus]);

  const applyChartScope = (scope: "all" | "real" | "practice") => {
    setChartScope(scope);
    const chart = chartInstance.current;
    if (!chart) return;
    for (const p of portfolios) {
      const isReal = REAL_KINDS.has(p.kind);
      const visible = !hidden[p.id]
        && (scope === "all" || (scope === "real") === isReal);
      (chart.get(p.id) as Highcharts.Series | undefined)?.setVisible(visible, false);
    }
    chart.redraw();
  };

  const curves = useAsync(
    async () => {
      const series = await Promise.all(portfolios.map(async (p) => ({
        portfolio: p,
        points: await api.get<[number, number][]>(`/api/portfolios/${p.id}/equity?limit=2000`),
      })));
      return series;
    },
    [portfolioIds],
  );

  // build once per portfolio set / theme; visibility toggles reuse the instance
  useEffect(() => {
    if (!chartRef.current || !curves.data) return;
    const palette = seriesPalette();
    chartInstance.current?.destroy();
    chartInstance.current = Highcharts.stockChart(chartRef.current, {
      ...baseChartOptions(),
      chart: { ...baseChartOptions().chart, height: phoneRef.current ? 220 : 320 },
      navigator: { enabled: false },
      legend: { ...baseChartOptions().legend, enabled: !phoneRef.current },
      tooltip: { ...baseChartOptions().tooltip, valueDecimals: 2 },
      series: curves.data
        // live mode: practice series don't even enter the chart or legend
        .filter((s) => REAL_KINDS.has(s.portfolio.kind) === (mode === "live"))
        .map((s, i) => {
          const isReal = REAL_KINDS.has(s.portfolio.kind);
          const scope = chartScopeRef.current;
          return {
            type: "line" as const,
            id: s.portfolio.id,
            name: s.portfolio.name,
            color: palette[i % palette.length],
            data: s.points,
            visible: !hidden[s.portfolio.id]
              && (scope === "all" || (scope === "real") === isReal),
          };
        }),
    });
    return () => { chartInstance.current?.destroy(); chartInstance.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curves.data, theme, showPractice]);

  const toggleVisible = (pid: string, visible: boolean) => {
    setHidden((h) => ({ ...h, [pid]: !visible }));
    const series = chartInstance.current?.get(pid) as Highcharts.Series | undefined;
    series?.setVisible(visible, true);
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      applyBrokerages(await api.refreshBrokerages());
      toast("success", "Brokerage data refreshed");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div>
      <h2 className="page-title">Portfolios</h2>

      {mode === "live" && (
        <div className="section-head">
          Real accounts <span className="status-pill bad">real money</span>
        </div>
      )}
      {mode === "live" && (brokerages?.providers ?? []).map((provider) => (
        <BrokerageSection key={provider.connectionId || provider.broker}
          provider={provider} onRefresh={refresh} refreshing={refreshing}
          lastSyncAt={brokerages?.lastSyncAt ?? null} />
      ))}
      {mode === "live" && realCards.length > 0 && (
        <div className="settings-grid mb">
          {realCards.map((p) => (
            <PortfolioCard key={p.id} portfolio={p}
              positions={byPortfolio[p.id] ?? []}
              visible={!hidden[p.id]}
              onToggle={(v) => toggleVisible(p.id, v)} />
          ))}
        </div>
      )}
      {mode === "live" && (brokerages?.providers ?? []).length === 0 && realCards.length === 0 && (
        <div className="panel mb"><div className="panel-body">
          <EmptyState title="No real accounts connected"
            hint="Add SnapTrade credentials to backend/.env and enable SnapTrade."
            action={<button className="link-btn" onClick={() => setPage("settings")}>
              open Settings → Brokerages</button>} />
        </div></div>
      )}

      {showPractice && (
        <>
          <div className="section-head">
            Practice environment <span className="status-pill dim">simulated fills</span>
          </div>
          <div className="settings-grid mb">
            {practiceMain.map((p) => (
              <PortfolioCard key={p.id} portfolio={p}
                positions={byPortfolio[p.id] ?? []}
                visible={!hidden[p.id]}
                onToggle={(v) => toggleVisible(p.id, v)} />
            ))}
            {practiceMain.length === 0 && (
              <div className="panel"><div className="panel-body">
                <EmptyState title="No practice portfolios"
                  hint="The engine seeds one on first start." />
              </div></div>
            )}
          </div>
          <ManagedPanel />
          <ShadowBooksPanel books={shadowBooks} byPortfolio={byPortfolio}
            hidden={hidden} onToggle={toggleVisible} />
        </>
      )}

      <div className="panel">
        <div className="panel-head">
          Equity curves
          <span className="sub">
            {showPractice ? "your practice books over time" : "your real accounts over time"}
          </span>
        </div>
        <AsyncSection state={curves}
          empty={<EmptyState title="No equity history yet" />}>
          {() => <div ref={chartRef} />}
        </AsyncSection>
      </div>
    </div>
  );
}
