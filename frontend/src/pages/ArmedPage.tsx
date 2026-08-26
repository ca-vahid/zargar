import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useStore } from "../store";
import { useWorkspace, workspaceOf } from "../lib/workspace";
import { useDaySeries } from "../lib/useDaySeries";
import type { ArmedPlan } from "../types";
import { InfoTip } from "../components/InfoTip";
import {
  ArmedCard, fleetRank, fmt, nearestPct, pnlCls, WINDOW_SHORT,
} from "../components/technique/ArmedTab";

/* The Armed hub: every armed plan from every technique, its own page.
   Layout toggle: split (table left, detail pinned right) / strip (chip bar,
   detail full width). Table toggle: dense / rich. Live | History sub-tabs.

   Anti-jump rules learned the hard way: row ORDER is frozen between explicit
   sorts (data refreshes patch values in place), selection never auto-moves
   after first load, and detail updates never touch the scroll position. */

type SubTab = "live" | "history";
type Layout = "split" | "strip";
type TableStyle = "dense" | "rich";

function lsGet(k: string, dflt: string): string {
  try { return localStorage.getItem(k) ?? dflt; } catch { return dflt; }
}
function lsSet(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

const TECH_LABEL = "EM Options";   // per-plan once multiple techniques arm

export function ArmedPage() {
  const allArmed = useStore((s) => s.techniqueArmed);
  const setArmed = useStore((s) => s.setTechniqueArmed);
  const halt = useStore((s) => s.halt);
  const settings = useStore((s) => s.settings);
  const toast = useStore((s) => s.toast);
  const ws = useWorkspace();
  const portfolios = useStore((s) => s.portfolios);
  const pmap = useMemo(() => Object.fromEntries(portfolios.map((p) => [p.id, p])), [portfolios]);
  const armed = useMemo(() => allArmed.filter((a) => workspaceOf(a.portfolio?.kind) === ws), [allArmed, ws]);
  const otherArmed = allArmed.length - armed.length;

  const [sub, setSub] = useState<SubTab>("live");
  const [layout, setLayoutRaw] = useState<Layout>(() => (lsGet("zargar_armed_layout", "split") as Layout));
  const [tstyle, setTstyleRaw] = useState<TableStyle>(() => (lsGet("zargar_armed_table", "dense") as TableStyle));
  const setLayout = (v: Layout) => { setLayoutRaw(v); lsSet("zargar_armed_layout", v); };
  const setTstyle = (v: TableStyle) => { setTstyleRaw(v); lsSet("zargar_armed_table", v); };

  // selection: pick the most interesting plan ONCE; after that only the user moves it
  const [selId, setSelId] = useState<string>("");
  const pickedOnce = useRef(false);
  useEffect(() => {
    if (pickedOnce.current || !armed.length) return;
    pickedOnce.current = true;
    setSelId(armed.slice().sort((x, y) => fleetRank(x) - fleetRank(y) || nearestPct(x) - nearestPct(y)
      || x.symbol.localeCompare(y.symbol))[0].runId);
  }, [armed]);
  const selArmed = useMemo(() => armed.find((a) => a.runId === selId)
    ?? (armed.length ? armed[0] : null), [armed, selId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (armed.length < 2) return;
      const i = Math.max(0, armed.findIndex((a) => a.runId === (selArmed?.runId ?? "")));
      setSelId(armed[(i + (e.key === "ArrowRight" ? 1 : armed.length - 1)) % armed.length].runId);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [armed, selArmed]);

  const [history, setHistory] = useState<any[]>([]);
  const refresh = useCallback(() => {
    api.techniqueArmed().then(setArmed).catch(() => undefined);
    api.techniqueArmedHistory().then(setHistory).catch(() => undefined);
  }, [setArmed]);
  useEffect(() => { refresh(); const id = setInterval(refresh, 30_000); return () => clearInterval(id); }, [refresh]);

  const tradingMode = String(settings["trading.mode"] ?? "practice");
  const openCount = useMemo(() => armed.reduce((n, a) => n + a.openPositions, 0), [armed]);
  const pnl = useMemo(() => armed.reduce((n, a) => n + (a.realizedPnl ?? 0), 0), [armed]);
  const stopAll = async (flatten: boolean) => {
    if (!confirm(flatten ? "Sell every open armed position at market and disarm all plans?" : "Disarm all armed plans? Open positions stay open.")) return;
    try { const r = await api.techniqueStopAll(flatten); toast("info", `Disarmed ${r.disarmed} plan(s)`); refresh(); }
    catch (e: any) { toast("error", e.message); }
  };

  return (
    <div className="armed-page">
      <div className="armed-head">
        <h2 className="page-title">Armed</h2>
        <div className="tabs armed-subtabs" role="tablist">
          <button role="tab" aria-selected={sub === "live"} className={sub === "live" ? "active" : ""}
            onClick={() => setSub("live")}>Live{armed.length ? ` · ${armed.length}` : ""}</button>
          <button role="tab" aria-selected={sub === "history"} className={sub === "history" ? "active" : ""}
            onClick={() => setSub("history")}>History</button>
        </div>
        {sub === "live" && (
          <div className="armed-viewtoggles">
            <div className="seg" role="group" aria-label="Layout">
              <button className={layout === "split" ? "on" : ""} title="Split view — table left, detail pinned right"
                onClick={() => setLayout("split")}>⫞ split</button>
              <button className={layout === "strip" ? "on" : ""} title="Strip view — symbol chips on top, full-width detail (laptop friendly)"
                onClick={() => setLayout("strip")}>☰ strip</button>
            </div>
            {layout === "split" && (
              <div className="seg" role="group" aria-label="Table style">
                <button className={tstyle === "dense" ? "on" : ""} title="Dense table — most rows per screen"
                  onClick={() => setTstyle("dense")}>dense</button>
                <button className={tstyle === "rich" ? "on" : ""} title="Rich rows — sparkline + distance-to-trigger meter"
                  onClick={() => setTstyle("rich")}>rich</button>
              </div>
            )}
          </div>
        )}
      </div>

      {sub === "live" && (
        <>
          <div className="panel mb tq-armed-top">
            <div className="panel-body tq-armed-topbar">
              <div className="tq-armed-kpi"><small>Armed</small><b>{armed.length}</b></div>
              <div className="tq-armed-kpi"><small>In trade</small><b className={openCount ? "pos" : ""}>{openCount}</b></div>
              <div className="tq-armed-kpi"><small>Realized today</small><b className={pnlCls(pnl)}>{fmt(pnl)}</b></div>
              <div className="tq-armed-kpi"><small>Workspace <InfoTip>Everything on this page belongs to the active workspace. PRACTICE = the simulator, fake money. LIVE = your real accounts. Switch it next to HALT in the top bar.</InfoTip></small><b className={tradingMode === "live" ? "neg" : ""}>{tradingMode.toUpperCase()}</b></div>
              <div className="tq-armed-kpi"><small>Kill switch <InfoTip>The big red HALT stops all new buys instantly. Stops and flatten can still sell so you're never trapped.</InfoTip></small><b className={halt.engaged ? "neg" : "pos"}>{halt.engaged ? "ENGAGED" : "off"}</b></div>
              <div className="tq-armed-topactions">
                {armed.length > 0 && (
                  <button className="ghost-btn" onClick={() => stopAll(false)}
                    title="Disarm every plan — open positions stay open">Stop all</button>
                )}
                {openCount > 0 && (
                  <button className="ghost-btn neg" onClick={() => stopAll(true)}
                    title="Sell everything the plans hold at market, then disarm every plan">Flatten &amp; stop all</button>
                )}
              </div>
            </div>
          </div>
          {otherArmed > 0 && (
            <div className="panel mb"><div className="panel-body tq-ws-note">
              <b>{otherArmed}</b> plan{otherArmed === 1 ? " is" : "s are"} armed in the <b>{ws === "live" ? "Practice" : "LIVE"}</b> workspace and stay{otherArmed === 1 ? "s" : ""} active —
              switch the workspace (next to HALT) to manage {otherArmed === 1 ? "it" : "them"}.
            </div></div>
          )}
          {armed.length === 0 && (
            <div className="panel mb"><div className="panel-body muted">
              Nothing armed in this workspace. Arm plans from Technique — the graded sheet
              (Check &amp; arm) or any run's <b>Arm for live triggers</b>. Armed plans watch live
              1-minute bars and, depending on mode, alert, propose, or trade.
            </div></div>
          )}

          {armed.length > 0 && layout === "split" && (
            <div className="armed-split">
              <div className="armed-fleet-pane">
                <FleetSortTable armed={armed} selId={selArmed?.runId ?? ""} onSel={setSelId} rich={tstyle === "rich"} />
              </div>
              <div className="armed-detail-pane">
                {selArmed && <ArmedCard key={selArmed.runId} a={selArmed} onChanged={refresh} />}
              </div>
            </div>
          )}
          {armed.length > 0 && layout === "strip" && (
            <>
              <FleetStrip armed={armed} selId={selArmed?.runId ?? ""} onSel={setSelId} />
              {selArmed && <ArmedCard key={selArmed.runId} a={selArmed} onChanged={refresh} />}
            </>
          )}
        </>
      )}

      {sub === "history" && (
        <HistoryTable history={history} pmap={pmap} ws={ws} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ strip */

function chipState(a: ArmedPlan): string {
  const inTrade = a.openPositions > 0 || (a.trades ?? []).some((t) => ["open", "working", "submitting"].includes(t.status));
  if (a.needsAttention) return "attn";
  if (inTrade) return "intrade";
  if ((a.trades ?? []).length) return "fired";
  if (a.status !== "armed") return "off";
  const anyLive = (a.triggers ?? []).some((t) => t.status === "waiting" || t.status === "observed");
  return anyLive ? "watching" : "void";
}

function FleetStrip({ armed, selId, onSel }: { armed: ArmedPlan[]; selId: string; onSel: (id: string) => void }) {
  return (
    <div className="armed-strip panel mb" role="tablist" aria-label="Armed plans">
      <div className="panel-body armed-strip-body">
        {armed.map((a) => (
          <button key={a.runId} role="tab" aria-selected={a.runId === selId}
            className={`armed-chip st-${chipState(a)} ${a.runId === selId ? "sel" : ""}`}
            title={`${a.symbol} · ${a.grade ?? "?"} · ${a.summary ?? a.status}`}
            onClick={() => onSel(a.runId)}>
            <b>{a.symbol}</b>{a.grade ? <span className="g">{a.grade}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ table */

type SortKey = "symbol" | "grade" | "mode" | "window" | "dist" | "status" | "pnl";
const SORTERS: Record<SortKey, (a: ArmedPlan, b: ArmedPlan) => number> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol),
  grade: (a, b) => String(a.grade ?? "Z").localeCompare(String(b.grade ?? "Z")),
  mode: (a, b) => a.config.mode.localeCompare(b.config.mode),
  window: (a, b) => (a.sessionWindowNow ?? "").localeCompare(b.sessionWindowNow ?? ""),
  dist: (a, b) => nearestPct(a) - nearestPct(b),
  status: (a, b) => fleetRank(a) - fleetRank(b),
  pnl: (a, b) => (b.realizedPnl ?? 0) - (a.realizedPnl ?? 0),
};

function FleetSortTable({ armed, selId, onSel, rich }: {
  armed: ArmedPlan[]; selId: string; onSel: (id: string) => void; rich: boolean;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "status", dir: 1 });
  // FROZEN ORDER: recompute only when the sort or the membership changes —
  // never on a data heartbeat, so rows stop leaping around under the cursor
  const memberKey = armed.map((a) => a.runId).sort().join(",");
  const order = useMemo(() => {
    const cmp = SORTERS[sort.key];
    return armed.slice().sort((a, b) => (cmp(a, b) || a.symbol.localeCompare(b.symbol)) * sort.dir)
      .map((a) => a.runId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sort.key, sort.dir, memberKey]);
  const byId = useMemo(() => Object.fromEntries(armed.map((a) => [a.runId, a])), [armed]);
  const clickSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: 1 }));
  const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : "");
  const TH = ({ k, children, title }: { k: SortKey; children: any; title?: string }) => (
    <th className="sortable" title={title ?? "Click to sort"} onClick={() => clickSort(k)}>{children}{arrow(k)}</th>
  );
  return (
    <div className="panel armed-fleet-panel">
      <div className="panel-head">Fleet <span className="sub">{armed.length} plan(s) · ← → to move</span></div>
      <div className="panel-body armed-fleet-scroll" style={{ padding: 0 }}>
        <table className={`tq-table tq-fleet armed-fleet ${rich ? "rich" : ""}`}>
          <thead><tr>
            <TH k="symbol">Symbol</TH>
            <TH k="grade" title="Deterministic plan grade — tracked against outcomes (TRADING-RULES 1.2)">Gr</TH>
            <th title="Technique that armed this plan">Tech</th>
            <TH k="window">Window</TH>
            {rich && <th title="Today's price path">Day</th>}
            <TH k="dist" title="Distance from the nearest trigger">{rich ? "To trigger" : "Dist"}</TH>
            <TH k="status">Status</TH>
            <TH k="pnl">P&amp;L</TH>
          </tr></thead>
          <tbody>
            {order.map((id) => {
              const a = byId[id];
              if (!a) return null;
              return <FleetRow key={id} a={a} sel={id === selId} rich={rich} onSel={() => onSel(id)} />;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FleetRow({ a, sel, rich, onSel }: { a: ArmedPlan; sel: boolean; rich: boolean; onSel: () => void }) {
  const near = (a.triggers ?? []).slice().sort((x, y) => Math.abs(x.distancePct ?? 99) - Math.abs(y.distancePct ?? 99))[0];
  const [wTxt, wCls] = WINDOW_SHORT[a.sessionWindowNow] ?? [a.sessionWindowNow, "nosetup"];
  const st = chipState(a);
  const trigStatuses = (a.triggers ?? []).map((t) => t.status);
  // "void" = armed but every trigger is dead — say WHY, not just "done"
  const voidLabel = trigStatuses.every((s) => s === "gap_void") ? "gap-voided"
    : trigStatuses.every((s) => s === "gapped_past" || s === "gapped_through") ? "gapped past"
    : "no triggers left";
  const voidTitle = "Every trigger died at the open: the overnight gap either repriced the risk "
    + "(gap rule, TRADING-RULES 1.1 — these are the experiment's counterfactual samples) or "
    + "jumped past the level (chasing is forbidden). Nothing can fire today.";
  const stLabel = st === "attn" ? "⚠ ATTENTION" : st === "intrade" ? "IN TRADE"
    : st === "fired" ? `FIRED ${(a.trades ?? []).length}` : st === "off" ? a.status.toUpperCase()
    : st === "void" ? voidLabel : `watching ${(a.triggers ?? []).filter((t) => t.status === "waiting" || t.status === "observed").length}`;
  const d = near?.distancePct;
  return (
    <tr className={`clickable ${sel ? "tq-fleet-sel" : ""}`} onClick={onSel}>
      <td className="nowrap"><b>{a.symbol}</b></td>
      <td>{a.grade ? <span className={`tq-grade g${a.grade}`}>{a.grade}</span> : <span className="muted small">—</span>}</td>
      <td className="nowrap"><span className="armed-tech-chip">{TECH_LABEL}</span></td>
      <td className="nowrap"><span className={`tq-badge ${wCls}`}>{wTxt}</span></td>
      {rich && <td className="armed-spark-cell"><Spark symbol={a.symbol} /></td>}
      <td className="nowrap small">
        {rich
          ? <DistMeter pct={d} />
          : d !== undefined ? <span className="muted">{d > 0 ? "+" : ""}{d.toFixed(2)}%</span> : "—"}
      </td>
      <td className="nowrap">
        {st === "attn" ? <span className="tq-badge failed">{stLabel}</span>
          : st === "intrade" ? <span className="tq-badge setup">{stLabel}</span>
          : st === "fired" ? <span className="tq-badge plan">{stLabel}</span>
          : st === "off" ? <span className="tq-badge nosetup">{stLabel}</span>
          : st === "void" ? <span className="muted small" title={voidTitle} style={{ textDecoration: "underline dotted", textUnderlineOffset: 3 }}>{stLabel}</span>
          : <span className="muted small">{stLabel}</span>}
        {a.stale && <span className="tq-badge failed" title="no fresh bars">STALE</span>}
      </td>
      <td className={`nowrap ${pnlCls(a.realizedPnl)}`}>{fmt(a.realizedPnl)}</td>
    </tr>
  );
}

/** Tiny day sparkline reusing the same cached series as the watch rows. */
function Spark({ symbol }: { symbol: string }) {
  const day = useDaySeries(symbol);
  const path = useMemo(() => {
    const ys = (day?.closes ?? []).filter((v) => Number.isFinite(v));
    if (ys.length < 2) return null;
    const w = 72, h = 18;
    const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const step = w / (ys.length - 1);
    const up = ys[ys.length - 1] >= ys[0];
    return { up, d: ys.map((v, i) =>
      `${i ? "L" : "M"}${(i * step).toFixed(1)} ${(h - 2 - ((v - lo) / span) * (h - 4)).toFixed(1)}`).join(" ") };
  }, [day]);
  if (!path) return <span className="muted small">—</span>;
  return (
    <svg width="72" height="18" aria-hidden="true">
      <path d={path.d} fill="none" strokeWidth="1.4"
        stroke={path.up ? "var(--up)" : "var(--down)"} />
    </svg>
  );
}

/** Distance-to-trigger meter: full bar = price at the trigger. */
function DistMeter({ pct }: { pct?: number }) {
  if (pct === undefined) return <span className="muted small">—</span>;
  const closeness = Math.max(0, Math.min(1, 1 - Math.abs(pct) / 3));
  return (
    <span className="armed-dist" title={`${pct > 0 ? "+" : ""}${pct.toFixed(2)}% from the nearest trigger`}>
      <span className="bar"><span className="fill" style={{ width: `${Math.round(closeness * 100)}%` }} /></span>
      <span className="muted">{pct > 0 ? "+" : ""}{pct.toFixed(2)}%</span>
    </span>
  );
}

/* ---------------------------------------------------------------- history */

function HistoryTable({ history, pmap, ws }: { history: any[]; pmap: Record<string, any>; ws: string }) {
  const rows = useMemo(
    () => history.filter((h) => workspaceOf(pmap[h.portfolioId]?.kind) === ws),
    [history, pmap, ws]);
  const byDay = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const h of rows) {
      const k = h.planFor || "—";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(h);
    }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [rows]);
  if (!rows.length) {
    return <div className="panel"><div className="panel-body muted">No armed history yet in this workspace.</div></div>;
  }
  return (
    <div className="armed-history">
      {byDay.map(([day, hs]) => {
        const pnl = hs.reduce((n, h) => n + (h.state?.realizedPnl ?? 0), 0);
        const fired = hs.reduce((n, h) => n + (h.state?.trades ?? []).length, 0);
        return (
          <div className="panel mb" key={day}>
            <div className="panel-head">{day}
              <span className="sub">{hs.length} plan(s) · {fired} fired · <span className={pnlCls(pnl)}>{fmt(pnl)}</span> realized</span></div>
            <div className="panel-body" style={{ padding: 0 }}>
              <table className="tq-table tq-wf">
                <thead><tr><th>Symbol</th><th>Grade</th><th>Mode</th><th>Account</th><th>Status</th><th>Fired</th><th>Realized</th><th>Armed at</th></tr></thead>
                <tbody>{hs.map((h) => (
                  <tr key={h.runId} className="clickable" onClick={() => useStore.getState().openTechniqueRun(h.runId)}>
                    <td><b>{h.symbol}</b></td>
                    <td>{h.state?.grade || h.grade
                      ? <span className={`tq-grade g${h.state?.grade ?? h.grade}`}>{h.state?.grade ?? h.grade}</span>
                      : <span className="muted small">—</span>}</td>
                    <td>{h.mode}</td>
                    <td className="muted">{pmap[h.portfolioId]?.name ?? h.portfolioId?.slice(0, 8)}{" "}
                      <span className={`status-pill ${workspaceOf(pmap[h.portfolioId]?.kind) === "live" ? "bad" : "dim"}`}>{workspaceOf(pmap[h.portfolioId]?.kind) === "live" ? "live" : "practice"}</span></td>
                    <td>{h.status}</td><td>{(h.state?.trades ?? []).length}</td>
                    <td className={pnlCls(h.state?.realizedPnl)}>{fmt(h.state?.realizedPnl)}</td>
                    <td className="muted">{h.createdAt ? fmtDateTime(h.createdAt) : ""}</td></tr>))}</tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
