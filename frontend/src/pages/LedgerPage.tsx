import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney, fmtSigned, fmtTime } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { SymIcon } from "../components/SymIcon";
import { AsyncSection, EmptyState } from "../components/ui";
import type { Ledger, LedgerTrip } from "../types";

/** The plain-language money view (user 2026-09-01): what was bought, what was
    sold, the gain each time — day by day, real books only, after fees. The
    headline IS the identity (start + banked + riding = total), so it can never
    fail to add up without saying so. Tap a row for the full breakdown. */

function niceName(symbol: string): string {
  const occ = parseOcc(symbol);
  return occ ? occ.display : symbol;
}
function underlying(symbol: string): string {
  return parseOcc(symbol)?.underlying ?? symbol;
}
function dayLabel(date: string): string {
  return new Date(date + "T12:00:00").toLocaleDateString(undefined,
    { weekday: "short", month: "short", day: "numeric" });
}

function TripRow({ t }: { t: LedgerTrip }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`led-row${open ? " open" : ""}`} onClick={() => setOpen((o) => !o)}
      role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((o) => !o); }}
      title={open ? undefined : "tap for the full breakdown"}>
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
      {open && (
        <div className="led-detail" onClick={(e) => e.stopPropagation()}>
          <div className="led-detail-grid">
            <span className="muted">In</span>
            <span>{fmtDateTime(t.inAt)} · {t.qty}× @ {fmtMoney(t.inPrice)} = <b>{fmtMoney(t.cost)}</b></span>
            <span className="muted">Why in</span><span>{t.inReason ?? "—"}</span>
            <span className="muted">Out</span>
            <span>{fmtDateTime(t.outAt)} · {t.qty}× @ {fmtMoney(t.outPrice)} = <b>{fmtMoney(t.proceeds)}</b></span>
            <span className="muted">Why out</span><span>{t.outReason ?? "—"}</span>
            <span className="muted">Gross</span>
            <span className={t.gross >= 0 ? "pos" : "neg"}>{fmtSigned(t.gross)} <span className="muted">(price move × {t.qty}{t.secType === "OPT" ? " × 100" : ""})</span></span>
            <span className="muted">Fees</span>
            <span>−{fmtMoney(t.fees)} <span className="muted">(in {fmtMoney(t.feeIn)} + out {fmtMoney(t.feeOut)} — Webull CA: $0.99/contract + reg. fees; stocks $0)</span></span>
            <span className="muted">Net</span>
            <span className={t.gain >= 0 ? "pos" : "neg"}><b>{fmtSigned(t.gain)}</b></span>
            <span className="muted">Orders</span>
            <span className="mono muted">{(t.inOrderId ?? "").slice(0, 8)} → {(t.outOrderId ?? "").slice(0, 8)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export function LedgerPage() {
  const [days, setDays] = useState(30);
  const state = useAsync(() => api.deskLedger(days), [days]);
  const led: Ledger | undefined = state.data;
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
                <span className="led-num">{fmtMoney(led.startingCash, 0)}</span>
                <span className="led-lbl">started with{led.startedAt ? <><br />{led.startedAt}</> : null}</span>
              </div>
              <span className="led-op">+</span>
              <div className="led-stat">
                <span className={`led-num ${led.banked >= 0 ? "pos" : "neg"}`}>{fmtSigned(led.banked)}</span>
                <span className="led-lbl">banked<br />(sold − bought − fees)</span>
              </div>
              <span className="led-op">+</span>
              <div className="led-stat">
                <span className={`led-num ${led.riding >= 0 ? "pos" : "neg"}`}>{fmtSigned(led.riding)}</span>
                <span className="led-lbl">riding on open<br />positions, after fees</span>
              </div>
              <span className="led-op">=</span>
              <div className="led-stat">
                <span className="led-num">{fmtMoney(led.total, 0)}</span>
                <span className="led-lbl">total right now<br />(cash + positions)</span>
              </div>
              {Math.abs(led.unexplained) >= 1 && (
                <span className="status-pill bad"
                  title="start + banked + riding should equal the total; this gap needs an audit">
                  {fmtSigned(led.unexplained)} unexplained
                </span>
              )}
              <div className="seg sm led-range" role="group" aria-label="Day list range">
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
                    <div className="led-row" key={i} title={o.inReason ?? undefined}>
                      <SymIcon sym={underlying(o.symbol)} size={20} />
                      <span className="led-what">
                        <b>{Math.abs(o.qty)}× {niceName(o.symbol)}</b>
                        <span className="muted">{o.label} · {o.portfolio}</span>
                      </span>
                      <span className="led-math muted">
                        bought {fmtTime(o.inAt)} @ {fmtMoney(o.inPrice)} = {fmtMoney(o.cost, 0)} + {fmtMoney(o.fees)} fee
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
                  <span>{dayLabel(d.date)}</span>
                  <span className="led-daybar" aria-hidden="true">
                    <span className={d.realized >= 0 ? "led-bar pos-bg" : "led-bar neg-bg"}
                      style={{ width: `${Math.min(100, Math.abs(d.realized) / maxDay * 100)}%` }} />
                  </span>
                  <span className={`led-gain ${d.realized >= 0 ? "pos" : "neg"}`}>{fmtSigned(d.realized)}</span>
                </div>
                <div className="led-rows">
                  {d.trips.map((t, i) => <TripRow key={i} t={t} />)}
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
              Real books only, after commissions (Webull Canada: $0 on stocks, $0.99 + reg. fees
              per option contract). The research (shadow) books that grade each tip source are not
              money and never appear here. The Journal keeps the full audit trail.
            </p>
          </>
        )}
      </AsyncSection>
    </div>
  );
}
