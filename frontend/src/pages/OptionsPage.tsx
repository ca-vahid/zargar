import { useEffect, useMemo, useState } from "react";
import { Blotter } from "../components/Blotter";
import { IconWarn } from "../components/icons";
import { OptionChain } from "../components/OptionChain";
import { OptionTicket } from "../components/OptionTicket";
import { DeltaPill, TickArrow } from "../components/quotekit";
import { AsyncSection, EmptyState } from "../components/ui";
import { api } from "../lib/api";
import { fmtMoney } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { useDaySeries } from "../lib/useDaySeries";
import { watchSymbol } from "../lib/ws";
import { useQuote, useStore } from "../store";

/** Options page: underlying header → expiry strip → strike ladder, with the
 * option ticket on the right and the blotter below (same frame as Trade). */
export function OptionsPage() {
  const underlying = useStore((s) => s.optionsUnderlying);
  const expiry = useStore((s) => s.optionsExpiry);
  const contract = useStore((s) => s.optionsContract);
  const setOptionsView = useStore((s) => s.setOptionsView);
  const quote = useQuote(underlying);
  const day = useDaySeries(underlying);
  const [symInput, setSymInput] = useState(underlying);
  useEffect(() => setSymInput(underlying), [underlying]);

  useEffect(() => {
    if (!underlying) return;
    watchSymbol(underlying);
    api.watchSymbol(underlying).catch(() => undefined);
  }, [underlying]);

  const expiries = useAsync(
    () => (underlying ? api.optionsExpiries(underlying) : Promise.resolve(null)), [underlying]);

  // default expiry = the route's, else the contract's, else the nearest listed
  useEffect(() => {
    const list = expiries.data?.expiries ?? [];
    if (!list.length) return;
    const fromContract = parseOcc(contract)?.expiry;
    const want = expiry && list.some((e) => e.date === expiry) ? expiry
      : fromContract && list.some((e) => e.date === fromContract) ? fromContract
        : list[0].date;
    if (want !== expiry) setOptionsView({ expiry: want });
  }, [expiries.data, expiry, contract, setOptionsView]);

  const chain = useAsync(
    () => (underlying && expiry ? api.optionsChain(underlying, expiry) : Promise.resolve(null)),
    [underlying, expiry]);
  useEffect(() => {
    const t = setInterval(chain.reload, 30_000);   // greeks/OI move slowly; bid/ask are ~15-min delayed anyway
    return () => clearInterval(t);
  }, [chain.reload]);

  const commit = () => {
    const s = symInput.trim().toUpperCase();
    if (s && s !== underlying) setOptionsView({ underlying: s, expiry: null, contract: null });
  };

  const spot = chain.data?.spot ?? expiries.data?.spot ?? null;
  const expList = useMemo(() => expiries.data?.expiries ?? [], [expiries.data]);

  return (
    <div className="trade-grid opt-grid">
      <div className="panel chart-area opt-chain-area">
        <div className="quote-head">
          <input className="symbol-input" value={symInput}
            onChange={(e) => setSymInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commit()}
            onBlur={commit} spellCheck={false} aria-label="Underlying symbol" />
          {quote && (
            <>
              <span className="last"><TickArrow symbol={underlying} /> {fmtMoney(quote.last)}</span>
              <DeltaPill quote={quote} fallbackOpen={day.open} size="md" />
              <span className="ba">bid {fmtMoney(quote.bid)} · ask {fmtMoney(quote.ask)}</span>
            </>
          )}
          {expiries.data?.iv30 != null && (
            <span className="ba" title="30-day implied volatility of the underlying (CBOE)">
              IV30 {Number(expiries.data.iv30).toFixed(1)}%
            </span>
          )}
          {expiries.data?.delayed && (
            <span className="status-pill dim"
              title="Chain bid/ask, greeks and IV come from CBOE's free delayed feed (~15 min). Contract last trades stream live via Yahoo once a contract is selected.">
              <IconWarn size={11} /> chain delayed ~15m
            </span>
          )}
          {spot != null && chain.data && (
            <span className="ba" style={{ marginLeft: "auto" }}>
              chain spot {fmtMoney(spot)} · {chain.data.rows.length} strikes
            </span>
          )}
        </div>
        <div className="opt-expiries">
          <AsyncSection state={expiries}
            empty={<EmptyState title={`No US-listed options for ${underlying}`} art={false}
              hint="CBOE lists US options only — .TO/.V symbols have no chain here." />}
            isEmpty={(d) => !d || d.expiries.length === 0}>
            {() => (
              <>
                {expList.map((e) => (
                  <button key={e.date}
                    className={`chip-btn opt-exp ${e.date === expiry ? "active" : ""} ${e.is0dte ? "opt-exp--0dte" : ""}`}
                    onClick={() => setOptionsView({ expiry: e.date })}
                    title={`${e.weekday} ${e.date} · ${e.dte} day${e.dte === 1 ? "" : "s"} to expiry`}>
                    <span className="opt-exp-date">{fmtExp(e.date)}</span>
                    <span className="opt-exp-dte">{e.is0dte ? "0DTE" : `${e.dte}d`}</span>
                  </button>
                ))}
              </>
            )}
          </AsyncSection>
        </div>
        <div className="opt-ladder-scroll">
          <AsyncSection state={chain}
            empty={<EmptyState title="Pick an expiry" art={false} />}
            isEmpty={(d) => !d}>
            {(d) => d ? (
              <OptionChain chain={d} selected={contract}
                onSelect={(sym) => setOptionsView({ contract: sym })} />
            ) : null}
          </AsyncSection>
        </div>
      </div>
      <OptionTicket contract={contract} />
      <Blotter />
    </div>
  );
}

function fmtExp(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[m - 1]} ${d} ’${String(y).slice(2)}`;
}
