import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtMoney, fmtSigned, fmtTime } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { SymIcon } from "../components/SymIcon";
import { AsyncSection, EmptyState } from "../components/ui";

/** The plain-language money view (user 2026-09-01): what was bought, what was
    sold, the gain each time — day by day, real books only. The Journal stays
    the audit trail; this page is the human answer. */

function niceName(symbol: string): string {
  const occ = parseOcc(symbol);
  return occ ? occ.display : symbol;
}

function underlying(symbol: string): string {
  return parseOcc(symbol)?.underlying ?? symbol;
}

export function LedgerPage() {
  const [days, setDays] = useState(30);
  const state = useAsync(() => api.deskLedger(days), [days]);
  const led = state.data;
  const unreal = useMemo(
    () => (led?.open ?? []).reduce((a, o) => a + (o.unrealized ?? 0), 0), [led]);
  const maxDay = useMemo(
    () => Math.max(1, ...(led?.days ?? []).map((d) => Math.abs(d.realized))), [led]);
  return (
    <div className="ledger-page">
      <h2 className="page-title">Ledger — your money, in plain terms</h2>

      <AsyncSection state={state} isEmpty={() => !led}
        empty={<EmptyState title="No trades yet" />}>
        {() => led && (
          <>
            <div className="led-headline">
              <div className="led-stat">
                <span className="led-num">{fmtMoney(led.total, 0)}</span>
                <span className="led-lbl">total right now<br />(cash + positions)</span>
              </div>
              <div className="led-stat">
                <span className={`led-num ${led.realized >= 0 ? "pos" : "neg"}`}>{fmtSigned(led.realized)}</span>
                <span className="led-lbl">banked, last {led.windowDays}d<br />(sold − bought)</span>
              </div>
              <div className="led-stat">
                <span className={`led-num ${unreal >= 0 ? "pos" : "neg"}`}>{fmtSigned(unreal)}</span>
                <span className="led-lbl">riding on open<br />positions (unsold)</span>
              </div>
              <div className="seg sm led-range" role="group" aria-label="Range">
                {[7, 30, 90].map((d) => (
                  <button key={d} className={days === d ? "on" : ""}
                    onClick={() => setDays(d)}>{d}d</button>
                ))}
              </div>
            </div>

            {led.open.length > 0 && (
              <div className="panel mb">
                <div className="panel-head">Still open
                  <span className="sub">bought, not yet sold — nothing is won or lost until the sell</span>
                </div>
                <div className="led-rows">
                  {led.open.map((o, i) => (
                    <div className="led-row" key={i}>
                      <SymIcon sym={underlying(o.symbol)} size={20} />
                      <span className="led-what">
                        <b>{Math.abs(o.qty)}× {niceName(o.symbol)}</b>
                        <span className="muted">{o.label} · {o.portfolio}</span>
                      </span>
                      <span className="led-math muted">
                        bought @ {fmtMoney(o.inPrice)} = {fmtMoney(o.cost, 0)}
                        {o.mark != null && <> · now @ {fmtMoney(o.mark)}</>}
                      </span>
                      {o.unrealized != null && (
                        <span className={`led-gain ${o.unrealized >= 0 ? "pos" : "neg"}`}>
                          {fmtSigned(o.unrealized)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {led.days.length === 0 ? (
              <EmptyState title={`No completed trades in the last ${led.windowDays} days`} />
            ) : led.days.map((d) => (
              <div className="panel mb" key={d.date}>
                <div className="panel-head led-dayhead">
                  <span>{new Date(d.date + "T12:00:00").toLocaleDateString(undefined,
                    { weekday: "short", month: "short", day: "numeric" })}</span>
                  <span className="led-daybar" aria-hidden="true">
                    <span className={d.realized >= 0 ? "led-bar pos-bg" : "led-bar neg-bg"}
                      style={{ width: `${Math.min(100, Math.abs(d.realized) / maxDay * 100)}%` }} />
                  </span>
                  <span className={`led-gain ${d.realized >= 0 ? "pos" : "neg"}`}>{fmtSigned(d.realized)}</span>
                </div>
                <div className="led-rows">
                  {d.trips.map((t, i) => (
                    <div className="led-row" key={i}>
                      <SymIcon sym={underlying(t.symbol)} size={20} />
                      <span className="led-what">
                        <b>{t.qty}× {niceName(t.symbol)}</b>
                        <span className="muted">{t.label} · {t.portfolio}{t.short ? " · short" : ""}</span>
                      </span>
                      <span className="led-math muted">
                        {t.short ? "sold" : "bought"} @ {fmtMoney(t.inPrice)} → {t.short ? "bought back" : "sold"} @ {fmtMoney(t.outPrice)}
                        <span className="led-times"> · {fmtTime(t.inAt)}–{fmtTime(t.outAt)}</span>
                      </span>
                      <span className={`led-gain ${t.gain >= 0 ? "pos" : "neg"}`}>{fmtSigned(t.gain)}</span>
                    </div>
                  ))}
                  {d.adjustments.map((a, i) => (
                    <div className="led-row led-row--adj" key={`a${i}`} title={a.reason}>
                      <span className="led-what"><b>Book correction</b>
                        <span className="muted">{a.reason.slice(0, 90)}…</span></span>
                      <span className={`led-gain ${a.amount >= 0 ? "pos" : "neg"}`}>{fmtSigned(a.amount)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <p className="muted" style={{ fontSize: 12, maxWidth: 640 }}>
              Real books only — the research (shadow) books that grade each tip source are
              not money and never appear here. The Journal keeps the full audit trail.
            </p>
          </>
        )}
      </AsyncSection>
    </div>
  );
}
