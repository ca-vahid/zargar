import { memo, useEffect, useMemo, useRef } from "react";
import { fmtMoney } from "../lib/format";
import { useQuote } from "../store";
import type { OptionCell, OptionChain as OptionChainData, OptionChainRow } from "../types";

/** Strike ladder: calls | strike | puts, centred on the money. Clicking a
 * call/put half selects that contract for the ticket. Bid/ask come from the
 * (delayed) chain; `last` prefers the live contract quote when we have one. */
export function OptionChain({
  chain,
  selected,
  onSelect,
}: {
  chain: OptionChainData;
  selected: string | null;
  onSelect: (symbol: string) => void;
}) {
  const atmRef = useRef<HTMLTableRowElement>(null);
  const scrolledFor = useRef<string>("");

  // the strike nearest spot — ITM/OTM shading pivots here and the view opens on it
  const atmStrike = useMemo(() => {
    if (!chain.rows.length) return null;
    const spot = chain.spot ?? 0;
    if (spot <= 0) return chain.rows[Math.floor(chain.rows.length / 2)].strike;
    return chain.rows.reduce((best, r) =>
      Math.abs(r.strike - spot) < Math.abs(best - spot) ? r.strike : best, chain.rows[0].strike);
  }, [chain]);

  useEffect(() => {
    const key = `${chain.underlying}:${chain.expiry}`;
    if (scrolledFor.current === key) return;
    scrolledFor.current = key;
    // scroll the ladder's own container (never the page) so the money sits mid-view
    const row = atmRef.current;
    const box = row?.closest(".opt-ladder-scroll") as HTMLElement | null;
    if (row && box) box.scrollTop = Math.max(0, row.offsetTop - box.clientHeight / 2);
  }, [chain.underlying, chain.expiry, atmStrike]);

  if (!chain.rows.length) return <div className="empty">no contracts for this expiry</div>;

  return (
    <div className="opt-ladder-wrap">
      <table className="tbl opt-ladder">
        <thead>
          <tr>
            <th colSpan={7} className="opt-side-head">Calls</th>
            <th className="opt-strike-head">Strike</th>
            <th colSpan={7} className="opt-side-head">Puts</th>
          </tr>
          <tr>
            <th className="num">OI</th><th className="num">Vol</th><th className="num">IV</th>
            <th className="num">Δ</th><th className="num">Bid</th><th className="num">Ask</th>
            <th className="num">Last</th>
            <th className="num opt-strike-head" />
            <th className="num">Last</th><th className="num">Bid</th><th className="num">Ask</th>
            <th className="num">Δ</th><th className="num">IV</th><th className="num">Vol</th>
            <th className="num">OI</th>
          </tr>
        </thead>
        <tbody>
          {chain.rows.map((row) => (
            <LadderRow key={row.strike} row={row} spot={chain.spot ?? 0}
              atm={row.strike === atmStrike} selected={selected} onSelect={onSelect}
              rowRef={row.strike === atmStrike ? atmRef : undefined} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LadderRow = memo(function LadderRow({
  row, spot, atm, selected, onSelect, rowRef,
}: {
  row: OptionChainRow; spot: number; atm: boolean; selected: string | null;
  onSelect: (s: string) => void; rowRef?: React.Ref<HTMLTableRowElement>;
}) {
  const callItm = spot > 0 && row.strike < spot;
  const putItm = spot > 0 && row.strike > spot;
  return (
    <tr ref={rowRef} className={`opt-row ${atm ? "opt-row--atm" : ""}`}>
      <Half cell={row.call} side="call" itm={callItm} selected={selected} onSelect={onSelect}
        order={["openInterest", "volume", "iv", "delta", "bid", "ask", "last"]} />
      <td className="num opt-strike">{fmtStrike(row.strike)}</td>
      <Half cell={row.put} side="put" itm={putItm} selected={selected} onSelect={onSelect}
        order={["last", "bid", "ask", "delta", "iv", "volume", "openInterest"]} />
    </tr>
  );
});

type Col = "openInterest" | "volume" | "iv" | "delta" | "bid" | "ask" | "last";

function Half({ cell, side, itm, selected, onSelect, order }: {
  cell: OptionCell | null; side: "call" | "put"; itm: boolean; selected: string | null;
  onSelect: (s: string) => void; order: Col[];
}) {
  const live = useQuote(cell?.symbol ?? "");
  if (!cell) {
    return <>{order.map((c) => <td key={c} className="num opt-cell opt-cell--none">—</td>)}</>;
  }
  const isSel = selected === cell.symbol;
  const last = live && live.last > 0 ? live.last : cell.last;
  const bid = live && live.bid > 0 ? live.bid : cell.bid;
  const ask = live && live.ask > 0 ? live.ask : cell.ask;
  const val = (c: Col) => {
    switch (c) {
      case "openInterest": return fmtInt(cell.openInterest);
      case "volume": return fmtInt(cell.volume);
      case "iv": return cell.iv != null ? `${(cell.iv * 100).toFixed(0)}%` : "—";
      case "delta": return cell.delta != null ? (Math.abs(cell.delta) < 0.005 ? "0.00" : cell.delta.toFixed(2)) : "—";
      case "bid": return fmtMoney(bid);
      case "ask": return fmtMoney(ask);
      case "last": return last != null && last > 0 ? fmtMoney(last) : "—";
    }
  };
  const cls = `num opt-cell opt-cell--${side} ${itm ? "itm" : "otm"} ${isSel ? "sel" : ""}`;
  return (
    <>
      {order.map((c) => (
        <td key={c} className={`${cls} ${c === "bid" || c === "ask" ? "opt-ba" : ""}`}
          onClick={() => onSelect(cell.symbol)}
          title={`${cell.symbol} · click to load into the ticket`}>
          {val(c)}
        </td>
      ))}
    </>
  );
}

function fmtInt(v: number): string {
  return v >= 10_000 ? `${(v / 1000).toFixed(1)}k` : String(v);
}

export function fmtStrike(strike: number): string {
  return Number.isInteger(strike) ? String(strike) : String(Number(strike.toFixed(3)));
}
