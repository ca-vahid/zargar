import { memo, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtSigned, fmtPct } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { useQuote, useStore } from "../store";
import type { Execution, Order, Position } from "../types";
import { LivePrice, ValuePill } from "./quotekit";
import { useWorkspace } from "../lib/workspace";
import { AsyncSection, EmptyState, StatusPill } from "./ui";
import { useViewport } from "../lib/viewport";
import { ConfirmDialog } from "./Modal";
import { SymIcon } from "./SymIcon";
import { ResearchBadge } from "./ResearchBadge";

type Tab = "positions" | "orders" | "history" | "fills";
type Scope = "real" | "practice" | "all";
type ResearchMode = "hide" | "dim" | "show";

const REAL_KINDS = new Set(["live", "paper"]);

/** portfolioId -> passes the current real/practice scope */
function useScopeFilter(scope: Scope): (portfolioId: string) => boolean {
  const portfolios = useStore((s) => s.portfolios);
  return useMemo(() => {
    if (scope === "all") return () => true;
    const wanted = new Set(
      portfolios
        .filter((p) => REAL_KINDS.has(p.kind) === (scope === "real"))
        .map((p) => p.id));
    return (pid: string) => wanted.has(pid);
  }, [portfolios, scope]);
}

/** The research (shadow) books' visibility (POST-SOAK 3.1): they are the tip
    track record, not trades — phones hide them by default, desktops dim them.
    Per-viewer convenience, remembered in localStorage. */
const RESEARCH_KEY = "zargar.researchRows";

function useResearch(): { shadowPids: Set<string>; mode: ResearchMode; setMode: (m: ResearchMode) => void } {
  const portfolios = useStore((s) => s.portfolios);
  const { isPhone } = useViewport();
  const [mode, setModeState] = useState<ResearchMode>(() => {
    try {
      const v = localStorage.getItem(RESEARCH_KEY);
      if (v === "hide" || v === "dim" || v === "show") return v;
    } catch { /* storage unavailable */ }
    return isPhone ? "hide" : "dim";
  });
  const setMode = (m: ResearchMode) => {
    setModeState(m);
    try { localStorage.setItem(RESEARCH_KEY, m); } catch { /* fine */ }
  };
  const shadowPids = useMemo(
    () => new Set(portfolios.filter((p) => p.kind === "shadow").map((p) => p.id)),
    [portfolios]);
  return { shadowPids, mode, setMode };
}

type Research = ReturnType<typeof useResearch>;

export function Blotter() {
  const [tab, setTab] = useState<Tab>("positions");
  const ws = useWorkspace();
  const research = useResearch();
  const scope: Scope = ws === "live" ? "real" : "practice";   // the workspace IS the scope
  return (
    <div className="panel blotter-area">
      <div className="panel-head panel-head--tabs">
        <div className="tabs" role="tablist">
          {(["positions", "orders", "history", "fills"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t}
              className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {t === "orders" ? "Open orders" : t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        {ws !== "live" && (
          <div className="seg sm research-seg" role="group" aria-label="Research books"
            title="🔬 the shadow research books — the per-source track record, not your trades">
            {(["hide", "dim", "show"] as ResearchMode[]).map((m) => (
              <button key={m} className={research.mode === m ? "on" : ""}
                onClick={() => research.setMode(m)}>{m === "hide" ? "hide 🔬" : m}</button>
            ))}
          </div>
        )}
        <span className="muted small" style={{ marginLeft: "auto" }}
          title="The blotter shows the active workspace only — switch Practice/LIVE in the top bar">
          {ws === "live" ? "live accounts" : "practice"}
        </span>
      </div>
      <div className="scroll-x">
        {tab === "positions" && <PositionsTable scope={scope} research={research} />}
        {tab === "orders" && <OpenOrdersTable scope={scope} research={research} />}
        {tab === "history" && <OrderHistoryTable scope={scope} research={research} />}
        {tab === "fills" && <FillsTable scope={scope} research={research} />}
      </div>
    </div>
  );
}

function portfolioName(portfolios: { id: string; name: string }[], id: string) {
  return portfolios.find((p) => p.id === id)?.name ?? id.slice(0, 6);
}

/** Where a position came from: the tip/source behind its entry order, and
    whether the durable manager runs it. Hover carries the thesis + the buy. */
function OriginCell({ c }: { c?: any }) {
  const setPage = useStore((s) => s.setPage);
  const tip = [
    c?.thesis,
    c?.orderAt
      ? `bought ${fmtDateTime(c.orderAt)}${c.fillPrice ? ` @ ${fmtMoney(c.fillPrice)}` : ""}`
      : null,
  ].filter(Boolean).join("\n");
  return (
    <td className="muted bl-origin" onClick={(e) => e.stopPropagation()}
      title={tip || undefined}>
      {c?.managedId && (
        <button className="link-btn" onClick={() => setPage("portfolios")}
          title="Run by the durable manager — its exit plan is on Portfolios">
          managed
        </button>
      )}
      {c?.sourceName
        ? <>{c.managedId ? " · " : ""}tip · {c.sourceName}</>
        : c?.origin && c.origin !== "manual"
          ? <>{c.managedId ? " · " : ""}{c.technique ?? c.origin}</>
          : c && !c.managedId ? "manual" : !c ? "—" : null}
    </td>
  );
}

/** One row subscribes to its own quote — 10 Hz updates re-render rows, not the table. */
const PositionRow = memo(function PositionRow({ p, c, linkHue, research }: {
  p: Position; c?: any; linkHue?: number; research?: boolean;
}) {
  const quote = useQuote(p.symbol);
  const portfolios = useStore((s) => s.portfolios);
  const openTrade = useStore((s) => s.openTrade);
  const openOptions = useStore((s) => s.openOptions);
  const last = quote?.last ?? p.last ?? p.avgCost;
  const isOpt = p.secType === "OPT";
  const occ = isOpt ? parseOcc(p.symbol) : null;
  const mult = isOpt ? 100 : 1;
  const unreal = (last - p.avgCost) * p.qty * mult;
  const pct = p.avgCost > 0 ? ((last / p.avgCost - 1) * 100) * Math.sign(p.qty) : 0;
  const open = () => occ
    ? openOptions({ contract: occ.symbol, side: p.qty > 0 ? "SELL" : "BUY", qty: Math.abs(p.qty), portfolioId: p.portfolioId })
    : openTrade(p.symbol, p.portfolioId);
  return (
    <tr onClick={open} style={{ cursor: "pointer" }}
      className={research ? "research-row" : undefined}
      title={occ ? `${occ.symbol} — open the option ticket to close this position` : "Open in Trade with this account preselected"}>
      <td className="sym-cell">
        {linkHue != null && (
          <span className="pos-link" style={{ background: `hsl(${linkHue} 65% 48%)` }}
            title={`Same tip${c?.sourceName ? ` (${c.sourceName})` : ""} — rows with this dot are the shadow book's take and the actual purchase of one tip`} />
        )}
        <SymIcon sym={occ ? occ.underlying : p.symbol} size={18} />
        {occ ? (
          <>
            {occ.display}
            <span className={`opt-dte ${occ.dte < 0 ? "bad" : occ.dte <= 1 ? "warn" : ""}`}>
              {occ.dte < 0 ? "expired" : occ.dte === 0 ? "0DTE" : `${occ.dte}d`}
            </span>
          </>
        ) : (
          <>{p.symbol}{p.secType !== "STK" && <span className="muted"> {p.secType}</span>}</>
        )}
      </td>
      <td className="muted">{portfolioName(portfolios, p.portfolioId)}
        {portfolios.find((x) => x.id === p.portfolioId)?.kind === "shadow" && <> <ResearchBadge compact /></>}</td>
      <OriginCell c={c} />
      <td className="num">{fmtQty(p.qty)}</td>
      <td className="num">{fmtMoney(p.avgCost)}</td>
      <td className="num"><LivePrice symbol={p.symbol} fallback={last} /></td>
      <td className="num">{fmtCcy(p.qty * last * mult, p.currency ?? "USD")}</td>
      <td className="num">
        <ValuePill value={unreal} text={`${fmtSigned(unreal)} (${fmtPct(pct)})`} />
      </td>
      <td className={`num ${p.realizedPnl >= 0 ? "pos" : "neg"}`}>{fmtSigned(p.realizedPnl)}</td>
    </tr>
  );
});

/** Phone: one card per position — symbol + value, qty@avg, live P&L pill. */
const PositionCard = memo(function PositionCard({ p, research }: { p: Position; research?: boolean }) {
  const quote = useQuote(p.symbol);
  const portfolios = useStore((s) => s.portfolios);
  const openTrade = useStore((s) => s.openTrade);
  const openOptions = useStore((s) => s.openOptions);
  const last = quote?.last ?? p.last ?? p.avgCost;
  const isOpt = p.secType === "OPT";
  const occ = isOpt ? parseOcc(p.symbol) : null;
  const mult = isOpt ? 100 : 1;
  const unreal = (last - p.avgCost) * p.qty * mult;
  const pct = p.avgCost > 0 ? ((last / p.avgCost - 1) * 100) * Math.sign(p.qty) : 0;
  const open = () => occ
    ? openOptions({ contract: occ.symbol, side: p.qty > 0 ? "SELL" : "BUY", qty: Math.abs(p.qty), portfolioId: p.portfolioId })
    : openTrade(p.symbol, p.portfolioId);
  return (
    <button type="button" className={`bl-card${research ? " research-row" : ""}`} onClick={open}>
      <span className="bl-card-l">
        <span className="bl-card-sym">{occ ? occ.display : p.symbol}
          {occ && <span className={`opt-dte ${occ.dte < 0 ? "bad" : occ.dte <= 1 ? "warn" : ""}`}>{occ.dte < 0 ? "expired" : occ.dte === 0 ? "0DTE" : `${occ.dte}d`}</span>}
        </span>
        <span className="bl-card-sub">{fmtQty(p.qty)} @ {fmtMoney(p.avgCost)} · {portfolioName(portfolios, p.portfolioId)}</span>
      </span>
      <span className="bl-card-r">
        <span className="bl-card-val"><LivePrice symbol={p.symbol} fallback={last} /></span>
        <ValuePill value={unreal} text={`${fmtSigned(unreal)} (${fmtPct(pct)})`} />
        <span className="bl-card-sub">{fmtCcy(p.qty * last * mult, p.currency ?? "USD")}</span>
      </span>
    </button>
  );
});

function OrderCard({ o, cancellable, research }: { o: Order; cancellable: boolean; research?: boolean }) {
  const portfolios = useStore((s) => s.portfolios);
  const toast = useStore((s) => s.toast);
  const [confirm, setConfirm] = useState(false);
  const occ = o.secType === "OPT" ? parseOcc(o.symbol) : null;
  return (
    <div className={`bl-card bl-card--static${research ? " research-row" : ""}`}>
      <span className="bl-card-l">
        <span className="bl-card-sym"><span className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</span> {fmtQty(o.qty)} {occ ? occ.display : o.symbol}</span>
        <span className="bl-card-sub">
          {o.orderType} {o.limitPrice ? `@ ${fmtMoney(o.limitPrice)}` : o.stopPrice ? `stp ${fmtMoney(o.stopPrice)}` : "mkt"}
          {o.avgFillPrice ? ` · filled ${fmtQty(o.filledQty)} @ ${fmtMoney(o.avgFillPrice)}` : ""} · {portfolioName(portfolios, o.portfolioId)}
        </span>
        <span className="bl-card-sub">{fmtDateTime(o.createdAt)}{o.source !== "manual" ? ` · ${o.source}` : ""}</span>
        {o.rejectReason && <span className="bl-card-sub neg">{o.rejectReason}</span>}
      </span>
      <span className="bl-card-r">
        <StatusPill status={o.status} />
        {cancellable && (
          <button type="button" className="danger-btn bl-cancel" onClick={() => setConfirm(true)}>Cancel</button>
        )}
      </span>
      {confirm && (
        <ConfirmDialog title={`Cancel ${o.side} ${fmtQty(o.qty)} ${occ ? occ.display : o.symbol}?`} danger confirmLabel="Cancel order"
          body={<p style={{ margin: 0 }}>The working order is pulled from the broker. Any part already filled stays filled.</p>}
          onConfirm={() => { setConfirm(false); api.cancelOrder(o.id).catch((e) => toast("error", e.message)); }}
          onCancel={() => setConfirm(false)} />
      )}
    </div>
  );
}

function PositionsTable({ scope, research }: { scope: Scope; research: Research }) {
  const positionsMap = useStore((s) => s.positions);
  const inScope = useScopeFilter(scope);
  const { isPhone } = useViewport();
  const positions = useMemo(
    () => Object.values(positionsMap)
      .filter((p) => Math.abs(p.qty) > 1e-9 && inScope(p.portfolioId)
        && (research.mode !== "hide" || !research.shadowPids.has(p.portfolioId))),
    [positionsMap, inScope, research.mode, research.shadowPids]);
  // provenance (tip/source/managed) per (portfolio, symbol) — a cheap join
  const ctxState = useAsync(() => api.positionsContext(), [positions.length]);
  const ctxMap = useMemo(() => {
    const m: Record<string, any> = {};
    for (const c of ctxState.data ?? []) m[`${c.portfolioId}:${c.symbol}`] = c;
    return m;
  }, [ctxState.data]);
  // rows tracing to the SAME tip (shadow take + actual purchase) share a hue
  const linkHues = useMemo(() => {
    const count: Record<string, number> = {};
    for (const p of positions) {
      const sid = ctxMap[`${p.portfolioId}:${p.symbol}`]?.signalId;
      if (sid) count[sid] = (count[sid] ?? 0) + 1;
    }
    const hues: Record<string, number> = {};
    const PALETTE = [212, 288, 152, 32, 336, 190];
    let i = 0;
    for (const sid of Object.keys(count)) {
      if (count[sid] > 1) hues[sid] = PALETTE[i++ % PALETTE.length];
    }
    return hues;
  }, [positions, ctxMap]);
  if (!positions.length) {
    return <EmptyState title={scope === "all" ? "No positions yet" : `No ${scope} positions`}
      hint="Fill an order from the ticket and it appears here." />;
  }
  const dim = (pid: string) => research.mode === "dim" && research.shadowPids.has(pid);
  if (isPhone) {
    return (
      <div className="bl-cards">
        {positions.map((p) => <PositionCard key={`${p.portfolioId}:${p.symbol}:${p.secType}`} p={p}
          research={dim(p.portfolioId)} />)}
      </div>
    );
  }
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Symbol</th><th>Portfolio</th><th>Origin</th><th className="num">Qty</th>
          <th className="num">Avg cost</th><th className="num">Last</th>
          <th className="num">Mkt value</th><th className="num">Unrealized</th>
          <th className="num">Realized</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const c = ctxMap[`${p.portfolioId}:${p.symbol}`];
          return (
            <PositionRow key={`${p.portfolioId}:${p.symbol}:${p.secType}`} p={p} c={c}
              linkHue={c?.signalId != null ? linkHues[c.signalId] : undefined}
              research={dim(p.portfolioId)} />
          );
        })}
      </tbody>
    </table>
  );
}

function OrderRow({ o, cancellable, research }: { o: Order; cancellable: boolean; research?: boolean }) {
  const portfolios = useStore((s) => s.portfolios);
  const toast = useStore((s) => s.toast);
  const occ = o.secType === "OPT" ? parseOcc(o.symbol) : null;
  return (
    <tr className={research ? "research-row" : undefined}
      title={o.rejectReason ?? (occ ? o.symbol : undefined)}>
      <td><b>{occ ? occ.display : o.symbol}</b>{occ && <span className="muted"> opt</span>}</td>
      <td className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</td>
      <td className="num">{fmtQty(o.filledQty)}/{fmtQty(o.qty)}</td>
      <td>{o.orderType}{o.source !== "manual" && <span className="muted"> · {o.source}</span>}</td>
      <td className="num">
        {o.limitPrice ? fmtMoney(o.limitPrice) : o.stopPrice ? `stp ${fmtMoney(o.stopPrice)}` : "mkt"}
      </td>
      <td className="num">{o.avgFillPrice ? fmtMoney(o.avgFillPrice) : "—"}</td>
      <td><StatusPill status={o.status} /></td>
      <td className="muted">{portfolioName(portfolios, o.portfolioId)}
        {portfolios.find((x) => x.id === o.portfolioId)?.kind === "shadow" && <> <ResearchBadge compact /></>}</td>
      <td className="muted">{fmtDateTime(o.createdAt)}</td>
      <td>
        {cancellable && (
          <button className="danger-btn" onClick={() =>
            api.cancelOrder(o.id).catch((e) => toast("error", e.message))}>
            Cancel
          </button>
        )}
      </td>
    </tr>
  );
}

const HEAD = (
  <tr>
    <th>Symbol</th><th>Side</th><th className="num">Filled/Qty</th><th>Type</th>
    <th className="num">Price</th><th className="num">Avg fill</th><th>Status</th>
    <th>Portfolio</th><th>Time</th><th></th>
  </tr>
);

function OpenOrdersTable({ scope, research }: { scope: Scope; research: Research }) {
  const openMap = useStore((s) => s.openOrders);
  const inScope = useScopeFilter(scope);
  const { isPhone } = useViewport();
  const open = useMemo(
    () => Object.values(openMap).filter((o) => inScope(o.portfolioId)
      && (research.mode !== "hide" || !research.shadowPids.has(o.portfolioId))),
    [openMap, inScope, research.mode, research.shadowPids]);
  const dim = (pid: string) => research.mode === "dim" && research.shadowPids.has(pid);
  if (!open.length) return <EmptyState title="No working orders" />;
  if (isPhone) return <div className="bl-cards">{open.map((o) => <OrderCard key={o.id} o={o} cancellable research={dim(o.portfolioId)} />)}</div>;
  return (
    <table className="tbl">
      <thead>{HEAD}</thead>
      <tbody>
        {open.map((o) => <OrderRow key={o.id} o={o} cancellable research={dim(o.portfolioId)} />)}
      </tbody>
    </table>
  );
}

function OrderHistoryTable({ scope, research }: { scope: Scope; research: Research }) {
  const recent = useStore((s) => s.recentOrders);
  const inScope = useScopeFilter(scope);
  const loaded = useAsync(() => api.get<Order[]>("/api/orders?limit=100"), []);
  const merged = useMemo(() => {
    const out = [...recent];
    for (const o of loaded.data ?? []) if (!out.some((r) => r.id === o.id)) out.push(o);
    return out.filter((o) => inScope(o.portfolioId)
      && (research.mode !== "hide" || !research.shadowPids.has(o.portfolioId))).slice(0, 100);
  }, [recent, loaded.data, inScope, research.mode, research.shadowPids]);
  const dim = (pid: string) => research.mode === "dim" && research.shadowPids.has(pid);
  const { isPhone } = useViewport();
  return (
    <AsyncSection state={loaded}
      isEmpty={() => merged.length === 0}
      empty={<EmptyState title="No orders yet" />}>
      {() => isPhone ? (
        <div className="bl-cards">
          {merged.slice(0, 40).map((o) => (
            <OrderCard key={o.id} o={o} cancellable={["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(o.status)}
              research={dim(o.portfolioId)} />
          ))}
        </div>
      ) : (
        <table className="tbl">
          <thead>{HEAD}</thead>
          <tbody>
            {merged.map((o) => (
              <OrderRow key={o.id} o={o}
                cancellable={["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(o.status)}
                research={dim(o.portfolioId)} />
            ))}
          </tbody>
        </table>
      )}
    </AsyncSection>
  );
}

function FillsTable({ scope, research }: { scope: Scope; research: Research }) {
  const live = useStore((s) => s.executions);
  const portfolios = useStore((s) => s.portfolios);
  const inScope = useScopeFilter(scope);
  const loaded = useAsync(() => api.get<Execution[]>("/api/executions?limit=100"), []);
  const merged = useMemo(() => {
    const out = [...live];
    for (const e of loaded.data ?? []) if (!out.some((r) => r.id === e.id)) out.push(e);
    return out.filter((e) => inScope(e.portfolioId)
      && (research.mode !== "hide" || !research.shadowPids.has(e.portfolioId))).slice(0, 100);
  }, [live, loaded.data, inScope, research.mode, research.shadowPids]);
  const dim = (pid: string) => research.mode === "dim" && research.shadowPids.has(pid);
  const { isPhone } = useViewport();
  return (
    <AsyncSection state={loaded}
      isEmpty={() => merged.length === 0}
      empty={<EmptyState title="No fills yet" />}>
      {() => isPhone ? (
        <div className="bl-cards">
          {merged.slice(0, 40).map((e) => (
            <div key={e.id} className={`bl-card bl-card--static${dim(e.portfolioId) ? " research-row" : ""}`}>
              <span className="bl-card-l">
                <span className="bl-card-sym"><span className={e.side === "BUY" ? "pos" : "neg"}>{e.side}</span> {fmtQty(e.qty)} {parseOcc(e.symbol)?.display ?? e.symbol}</span>
                <span className="bl-card-sub">@ {fmtMoney(e.price)} · fee {fmtMoney(e.commission)} · {portfolioName(portfolios, e.portfolioId)}</span>
              </span>
              <span className="bl-card-r"><span className="bl-card-sub">{fmtDateTime(e.ts)}</span></span>
            </div>
          ))}
        </div>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Symbol</th><th>Side</th><th className="num">Qty</th>
              <th className="num">Price</th><th className="num">Commission</th>
              <th>Portfolio</th><th>Time</th>
            </tr>
          </thead>
          <tbody>
            {merged.map((e) => (
              <tr key={e.id} className={dim(e.portfolioId) ? "research-row" : undefined}>
                <td><b>{parseOcc(e.symbol)?.display ?? e.symbol}</b></td>
                <td className={e.side === "BUY" ? "pos" : "neg"}>{e.side}</td>
                <td className="num">{fmtQty(e.qty)}</td>
                <td className="num">{fmtMoney(e.price)}</td>
                <td className="num muted">{fmtMoney(e.commission)}</td>
                <td className="muted">{portfolioName(portfolios, e.portfolioId)}</td>
                <td className="muted">{fmtDateTime(e.ts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AsyncSection>
  );
}
