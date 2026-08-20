import { memo, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtDateTime, fmtMoney, fmtQty, fmtSigned, fmtPct } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useQuote, useStore } from "../store";
import type { Execution, Order, Position } from "../types";
import { AsyncSection, EmptyState, StatusPill } from "./ui";

type Tab = "positions" | "orders" | "history" | "fills";

export function Blotter() {
  const [tab, setTab] = useState<Tab>("positions");
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
      </div>
      <div className="scroll-x">
        {tab === "positions" && <PositionsTable />}
        {tab === "orders" && <OpenOrdersTable />}
        {tab === "history" && <OrderHistoryTable />}
        {tab === "fills" && <FillsTable />}
      </div>
    </div>
  );
}

function portfolioName(portfolios: { id: string; name: string }[], id: string) {
  return portfolios.find((p) => p.id === id)?.name ?? id.slice(0, 6);
}

/** One row subscribes to its own quote — 10 Hz updates re-render rows, not the table. */
const PositionRow = memo(function PositionRow({ p }: { p: Position }) {
  const quote = useQuote(p.symbol);
  const portfolios = useStore((s) => s.portfolios);
  const setActiveSymbol = useStore((s) => s.setActiveSymbol);
  const last = quote?.last ?? p.last ?? p.avgCost;
  const mult = p.secType === "OPT" ? 100 : 1;
  const unreal = (last - p.avgCost) * p.qty * mult;
  const pct = p.avgCost > 0 ? ((last / p.avgCost - 1) * 100) * Math.sign(p.qty) : 0;
  return (
    <tr onClick={() => setActiveSymbol(p.symbol)} style={{ cursor: "pointer" }}>
      <td><b>{p.symbol}</b>{p.secType !== "STK" && <span className="muted"> {p.secType}</span>}</td>
      <td className="muted">{portfolioName(portfolios, p.portfolioId)}</td>
      <td className="num">{fmtQty(p.qty)}</td>
      <td className="num">{fmtMoney(p.avgCost)}</td>
      <td className="num">{fmtMoney(last)}</td>
      <td className="num">{fmtCcy(p.qty * last * mult, p.currency ?? "USD")}</td>
      <td className={`num ${unreal >= 0 ? "pos" : "neg"}`}>
        {fmtSigned(unreal)} ({fmtPct(pct)})
      </td>
      <td className={`num ${p.realizedPnl >= 0 ? "pos" : "neg"}`}>{fmtSigned(p.realizedPnl)}</td>
    </tr>
  );
});

function PositionsTable() {
  const positionsMap = useStore((s) => s.positions);
  const positions = useMemo(
    () => Object.values(positionsMap).filter((p) => Math.abs(p.qty) > 1e-9),
    [positionsMap]);
  if (!positions.length) {
    return <EmptyState title="No positions yet"
      hint="Fill an order from the ticket and it appears here." />;
  }
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Symbol</th><th>Portfolio</th><th className="num">Qty</th>
          <th className="num">Avg cost</th><th className="num">Last</th>
          <th className="num">Mkt value</th><th className="num">Unrealized</th>
          <th className="num">Realized</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <PositionRow key={`${p.portfolioId}:${p.symbol}:${p.secType}`} p={p} />
        ))}
      </tbody>
    </table>
  );
}

function OrderRow({ o, cancellable }: { o: Order; cancellable: boolean }) {
  const portfolios = useStore((s) => s.portfolios);
  const toast = useStore((s) => s.toast);
  return (
    <tr title={o.rejectReason ?? undefined}>
      <td><b>{o.symbol}</b></td>
      <td className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</td>
      <td className="num">{fmtQty(o.filledQty)}/{fmtQty(o.qty)}</td>
      <td>{o.orderType}{o.source !== "manual" && <span className="muted"> · {o.source}</span>}</td>
      <td className="num">
        {o.limitPrice ? fmtMoney(o.limitPrice) : o.stopPrice ? `stp ${fmtMoney(o.stopPrice)}` : "mkt"}
      </td>
      <td className="num">{o.avgFillPrice ? fmtMoney(o.avgFillPrice) : "—"}</td>
      <td><StatusPill status={o.status} /></td>
      <td className="muted">{portfolioName(portfolios, o.portfolioId)}</td>
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

function OpenOrdersTable() {
  const openMap = useStore((s) => s.openOrders);
  const open = useMemo(() => Object.values(openMap), [openMap]);
  if (!open.length) return <EmptyState title="No working orders" />;
  return (
    <table className="tbl">
      <thead>{HEAD}</thead>
      <tbody>
        {open.map((o) => <OrderRow key={o.id} o={o} cancellable />)}
      </tbody>
    </table>
  );
}

function OrderHistoryTable() {
  const recent = useStore((s) => s.recentOrders);
  const loaded = useAsync(() => api.get<Order[]>("/api/orders?limit=100"), []);
  const merged = useMemo(() => {
    const out = [...recent];
    for (const o of loaded.data ?? []) if (!out.some((r) => r.id === o.id)) out.push(o);
    return out.slice(0, 100);
  }, [recent, loaded.data]);
  return (
    <AsyncSection state={loaded}
      isEmpty={() => merged.length === 0}
      empty={<EmptyState title="No orders yet" />}>
      {() => (
        <table className="tbl">
          <thead>{HEAD}</thead>
          <tbody>
            {merged.map((o) => (
              <OrderRow key={o.id} o={o}
                cancellable={["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(o.status)} />
            ))}
          </tbody>
        </table>
      )}
    </AsyncSection>
  );
}

function FillsTable() {
  const live = useStore((s) => s.executions);
  const portfolios = useStore((s) => s.portfolios);
  const loaded = useAsync(() => api.get<Execution[]>("/api/executions?limit=100"), []);
  const merged = useMemo(() => {
    const out = [...live];
    for (const e of loaded.data ?? []) if (!out.some((r) => r.id === e.id)) out.push(e);
    return out.slice(0, 100);
  }, [live, loaded.data]);
  return (
    <AsyncSection state={loaded}
      isEmpty={() => merged.length === 0}
      empty={<EmptyState title="No fills yet" />}>
      {() => (
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
              <tr key={e.id}>
                <td><b>{e.symbol}</b></td>
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
