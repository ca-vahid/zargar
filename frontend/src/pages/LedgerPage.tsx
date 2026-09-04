import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney, fmtSigned, fmtTime } from "../lib/format";
import { parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { SymIcon } from "../components/SymIcon";
import { AsyncSection, EmptyState } from "../components/ui";
import { useStore } from "../store";
import type { Ledger, LedgerTrip } from "../types";

/** The plain-language money view (user 2026-09-01), in three shapes the user
    picked on 2026-09-03: Timeline (the week's story), Sheet (audit + filters)
    and Chart (a real waterfall). All three share one model, and all three fix
    the same four faults of the first cut:
      · a day's total must never look like a trade's P&L,
      · today is ALWAYS on the page — "nothing closed" is a state, not a gap
        (Sep 3 was simply absent, and open positions carried no date at all),
      · the headline is a balance with context, not an equation,
      · the decorative day bars are gone; the balance column and the waterfall
        carry the trend instead. */

const VIEWS = [
  { key: "timeline", label: "Timeline" },
  { key: "sheet", label: "Sheet" },
  { key: "chart", label: "Chart" },
] as const;
type View = typeof VIEWS[number]["key"];

const ET_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
const VIEW_KEY = "zargar_ledger_view";
const r2 = (n: number) => Math.round(n * 100) / 100;

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
function weekday(date: string): string {
  return new Date(date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long" });
}
function shortDate(date: string): string {
  return new Date(date + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
/** How long the position was held, and whether it slept through a session. */
function held(t: LedgerTrip): { ms: number; label: string; overnight: boolean } {
  const ms = Math.max(0, new Date(t.outAt).getTime() - new Date(t.inAt).getTime());
  const mins = Math.round(ms / 60000);
  const label = mins < 60 ? `${mins}m`
    : mins < 60 * 24 ? `${Math.floor(mins / 60)}h ${mins % 60}m`
      : `${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h`;
  return { ms, label, overnight: ET_DAY.format(new Date(t.inAt)) !== ET_DAY.format(new Date(t.outAt)) };
}

/* ── one model, three views ─────────────────────────────────────────────── */

interface DayModel {
  date: string;
  realized: number | null;          // null = nothing closed (a real state, not zero)
  closing: number;                  // book balance at the end of that day
  trips: (LedgerTrip & { running: number })[];
  adjustments: Ledger["days"][number]["adjustments"];
  isToday: boolean;
}

function useModel(led: Ledger | undefined) {
  return useMemo(() => {
    if (!led) return null;
    const today = ET_DAY.format(new Date());
    // Closing balances walk BACKWARDS from a number we know exactly:
    // total − riding == starting cash + everything banked to date. That stays
    // correct however the day window is trimmed.
    let running = r2(led.total - led.riding);
    const days: DayModel[] = led.days.map((d) => {
      const closing = running;
      running = r2(running - d.realized);
      const opening = running;
      let acc = opening;
      const trips = [...d.trips]
        .sort((a, b) => new Date(a.outAt).getTime() - new Date(b.outAt).getTime())
        .map((t) => { acc = r2(acc + t.gain); return { ...t, running: acc }; });
      return { date: d.date, realized: d.realized, closing, trips,
        adjustments: d.adjustments, isToday: d.date === today };
    });
    // Today ALWAYS has a row. A day the market spent quiet is information;
    // an absent day just looks like the page is broken.
    if (!days.some((d) => d.isToday)) {
      days.unshift({ date: today, realized: null, closing: r2(led.total - led.riding),
        trips: [], adjustments: [], isToday: true });
    }
    const openValue = led.open.reduce((s, o) => s + o.cost, 0);
    return { days, today, openValue };
  }, [led]);
}

/* ── shared pieces ──────────────────────────────────────────────────────── */

function TripDetail({ t }: { t: LedgerTrip }) {
  const h = held(t);
  return (
    <div className="led-detail" onClick={(e) => e.stopPropagation()}>
      <div className="led-detail-grid">
        <span className="muted">In</span>
        <span>{fmtDateTime(t.inAt)} · {t.qty}× @ {fmtMoney(t.inPrice)} = <b>{fmtMoney(t.cost)}</b></span>
        <span className="muted">Why in</span><span>{t.inReason ?? "—"}</span>
        <span className="muted">Out</span>
        <span>{fmtDateTime(t.outAt)} · {t.qty}× @ {fmtMoney(t.outPrice)} = <b>{fmtMoney(t.proceeds)}</b></span>
        <span className="muted">Why out</span><span>{t.outReason ?? "—"}</span>
        <span className="muted">Held</span>
        <span>{h.label}{h.overnight ? " · held overnight" : ""}</span>
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
  );
}

/** The headline: a balance and one line of context. Never an equation. */
function Headline({ led, model, days, setDays, view, setView }: {
  led: Ledger; model: NonNullable<ReturnType<typeof useModel>>;
  days: number; setDays: (d: number) => void; view: View; setView: (v: View) => void;
}) {
  const live = led.workspace === "live";
  const todayRow = model.days.find((d) => d.isToday);
  const windowNet = led.days.reduce((s, d) => s + d.realized, 0);
  return (
    <div className="panel mb led-head2">
      <div className="led-balance">
        <div className="led-bal-lbl">{live ? "Brokerage total" : "Balance now"}</div>
        <div className="led-bal-num">{fmtMoney(led.total, 2)}</div>
        <div className="led-bal-sub">
          {live
            ? <>all accounts · Zargar banked <span className={led.banked >= 0 ? "pos" : "neg"}>{fmtSigned(led.banked)}</span> and is riding <span className={led.riding >= 0 ? "pos" : "neg"}>{fmtSigned(led.riding)}</span></>
            : <>from {fmtMoney(led.startingCash ?? 0, 0)}{led.startedAt ? ` on ${shortDate(led.startedAt)}` : ""}
              {" · "}<span className={(led.sinceStart ?? 0) >= 0 ? "pos" : "neg"}>{fmtSigned(led.sinceStart ?? 0)}</span> since you started</>}
        </div>
      </div>
      <div className="led-stats">
        <div className="led-stat2">
          <span className="k">Today</span>
          <span className={`v ${todayRow?.realized == null ? "muted" : todayRow.realized >= 0 ? "pos" : "neg"}`}>
            {todayRow?.realized == null ? "—" : fmtSigned(todayRow.realized)}
          </span>
          <span className="s">{todayRow?.realized == null ? "nothing closed" : `${todayRow.trips.length} closed`}</span>
        </div>
        <div className="led-stat2">
          <span className="k">Riding</span>
          <span className={`v ${led.riding >= 0 ? "pos" : "neg"}`}>{fmtSigned(led.riding)}</span>
          <span className="s">{led.open.length} open · {fmtMoney(model.openValue, 0)} at cost</span>
        </div>
        <div className="led-stat2">
          <span className="k">Last {led.windowDays}d</span>
          <span className={`v ${windowNet >= 0 ? "pos" : "neg"}`}>{fmtSigned(windowNet)}</span>
          <span className="s">{led.days.reduce((s, d) => s + d.trips.length, 0)} closed</span>
        </div>
      </div>
      <div className="led-controls">
        <div className="seg sm" role="group" aria-label="Ledger view">
          {VIEWS.map((v) => (
            <button key={v.key} className={view === v.key ? "on" : ""}
              aria-pressed={view === v.key}
              onClick={() => { setView(v.key); try { localStorage.setItem(VIEW_KEY, v.key); } catch { /* private mode */ } }}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="seg sm" role="group" aria-label="Day range">
          {[7, 30, 90].map((d) => (
            <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d}d</button>
          ))}
        </div>
        {led.unexplained != null && Math.abs(led.unexplained) >= 1 && (
          <span className="status-pill bad"
            title="start + banked + riding should equal the total; this gap needs an audit">
            {fmtSigned(led.unexplained)} unexplained
          </span>
        )}
      </div>
    </div>
  );
}

/* ── B · Timeline ───────────────────────────────────────────────────────── */

function TimelineView({ led, model }: { led: Ledger; model: NonNullable<ReturnType<typeof useModel>> }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="panel mb led-tl-panel">
      <div className="led-tl">
        {model.days.map((d) => {
          const dir = d.realized == null ? "flat" : d.realized >= 0 ? "up" : "dn";
          return (
            <div className="led-node" key={d.date}>
              <div className="led-when">
                <b>{d.isToday ? "Today" : weekday(d.date).slice(0, 3)}</b>
                <span>{shortDate(d.date)}</span>
              </div>
              <div className={`led-dot ${dir} ${d.isToday ? "now" : ""}`} aria-hidden="true">
                {d.realized == null ? "●" : d.realized >= 0 ? "▲" : "▼"}
              </div>
              <div className="led-node-body">
                <div className="led-daytot">
                  <span className={`n ${d.realized == null ? "muted" : d.realized >= 0 ? "pos" : "neg"}`}>
                    {d.realized == null ? "no closes" : fmtSigned(d.realized)}
                  </span>
                  <span className="l">
                    {d.realized == null
                      ? `${led.open.length} position${led.open.length === 1 ? "" : "s"} still riding`
                      : `${d.trips.length} closed · balance ${fmtMoney(d.closing, 2)}`}
                  </span>
                </div>
                {d.isToday && led.open.map((o, i) => (
                  <div className="led-ev live" key={`o${i}`} title={o.inReason ?? undefined}>
                    <SymIcon sym={underlying(o.symbol)} size={20} />
                    <span className="led-ev-name">{Math.abs(o.qty)}× {niceName(o.symbol)}
                      <span>bought {fmtDateTime(o.inAt)} · {o.label} · {o.portfolio}</span></span>
                    <span className="led-ev-flow">
                      <span className="led-tick" aria-hidden="true" />
                      {fmtMoney(o.inPrice)} → {o.mark != null ? fmtMoney(o.mark) : "—"} live
                    </span>
                    {o.unrealized != null && (
                      <span className={`led-ev-net ${o.unrealized >= 0 ? "pos" : "neg"}`}>{fmtSigned(o.unrealized)}</span>
                    )}
                  </div>
                ))}
                {d.trips.map((t, i) => {
                  const id = `${d.date}-${i}`;
                  const h = held(t);
                  return (
                    <div key={id} className={`led-ev clickable${open === id ? " open" : ""}`}
                      role="button" tabIndex={0} onClick={() => setOpen(open === id ? null : id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === id ? null : id); } }}>
                      <SymIcon sym={underlying(t.symbol)} size={20} />
                      <span className="led-ev-name">{t.qty}× {niceName(t.symbol)}
                        <span>held {h.label}{h.overnight ? " · overnight" : ""} · {t.label}</span></span>
                      <span className="led-ev-flow">{fmtMoney(t.inPrice)} → {fmtMoney(t.outPrice)}</span>
                      <span className={`led-ev-net ${t.gain >= 0 ? "pos" : "neg"}`}>{fmtSigned(t.gain)}</span>
                      {open === id && <TripDetail t={t} />}
                    </div>
                  );
                })}
                {d.adjustments.map((a, i) => (
                  <div className="led-ev led-ev--adj" key={`a${i}`} title={a.reason}>
                    <span className="led-ev-name">Book correction<span>{a.reason.slice(0, 90)}</span></span>
                    <span className={`led-ev-net ${a.amount >= 0 ? "pos" : "neg"}`}>{fmtSigned(a.amount)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {led.startedAt && (
          <div className="led-node">
            <div className="led-when"><b>Start</b><span>{shortDate(led.startedAt)}</span></div>
            <div className="led-dot" aria-hidden="true">◆</div>
            <div className="led-node-body">
              <div className="led-daytot">
                <span className="n muted">{fmtMoney(led.startingCash ?? 0, 2)}</span>
                <span className="l">book opened — everything above is what you did with it</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── D · Sheet ──────────────────────────────────────────────────────────── */

type SortKey = "date" | "symbol" | "in" | "out" | "held" | "fees" | "net" | "balance";
interface Filters {
  q: string; techniques: Set<string>; books: Set<string>;
  result: "all" | "wins" | "losses"; kind: "all" | "options" | "shares";
  hold: "all" | "intraday" | "overnight"; showOpen: boolean;
}
const NO_FILTERS: Filters = {
  q: "", techniques: new Set(), books: new Set(),
  result: "all", kind: "all", hold: "all", showOpen: true,
};

function SheetView({ led, model }: { led: Ledger; model: NonNullable<ReturnType<typeof useModel>> }) {
  const [f, setF] = useState<Filters>(NO_FILTERS);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "date", dir: -1 });
  const [open, setOpen] = useState<string | null>(null);

  const allTrips = useMemo(
    () => model.days.flatMap((d) => d.trips.map((t) => ({ ...t, _day: d.date }))), [model]);
  const techniques = useMemo(
    () => [...new Set(allTrips.map((t) => t.label))].sort(), [allTrips]);
  const books = useMemo(
    () => [...new Set([...allTrips.map((t) => t.portfolio), ...led.open.map((o) => o.portfolio)])].sort(),
    [allTrips, led.open]);

  const match = (t: LedgerTrip): boolean => {
    const q = f.q.trim().toUpperCase();
    if (q && !underlying(t.symbol).includes(q) && !niceName(t.symbol).toUpperCase().includes(q)
      && !t.label.toUpperCase().includes(q)) return false;
    if (f.techniques.size && !f.techniques.has(t.label)) return false;
    if (f.books.size && !f.books.has(t.portfolio)) return false;
    if (f.result === "wins" && t.gain < 0) return false;
    if (f.result === "losses" && t.gain >= 0) return false;
    if (f.kind === "options" && t.secType !== "OPT") return false;
    if (f.kind === "shares" && t.secType === "OPT") return false;
    if (f.hold === "intraday" && held(t).overnight) return false;
    if (f.hold === "overnight" && !held(t).overnight) return false;
    return true;
  };
  const openMatch = (o: Ledger["open"][number]): boolean => {
    const q = f.q.trim().toUpperCase();
    if (!f.showOpen) return false;
    if (q && !underlying(o.symbol).includes(q) && !niceName(o.symbol).toUpperCase().includes(q)
      && !o.label.toUpperCase().includes(q)) return false;
    if (f.techniques.size && !f.techniques.has(o.label)) return false;
    if (f.books.size && !f.books.has(o.portfolio)) return false;
    if (f.result === "wins" && (o.unrealized ?? 0) < 0) return false;
    if (f.result === "losses" && (o.unrealized ?? 0) >= 0) return false;
    if (f.kind === "options" && !parseOcc(o.symbol)) return false;
    if (f.kind === "shares" && parseOcc(o.symbol)) return false;
    return true;
  };

  const shown = allTrips.filter(match);
  const shownOpen = led.open.filter(openMatch);
  const netShown = r2(shown.reduce((s, t) => s + t.gain, 0));
  const feesShown = r2(shown.reduce((s, t) => s + t.fees, 0));
  const wins = shown.filter((t) => t.gain >= 0).length;
  const dirty = f.q !== "" || f.techniques.size > 0 || f.books.size > 0
    || f.result !== "all" || f.kind !== "all" || f.hold !== "all" || !f.showOpen;
  const grouped = sort.key === "date";

  const flat = useMemo(() => {
    const val = (t: typeof shown[number]): number | string => {
      switch (sort.key) {
        case "symbol": return underlying(t.symbol);
        case "in": return t.inPrice;
        case "out": return t.outPrice;
        case "held": return held(t).ms;
        case "fees": return t.fees;
        case "net": return t.gain;
        case "balance": return t.running;
        default: return new Date(t.outAt).getTime();
      }
    };
    return [...shown].sort((a, b) => {
      const x = val(a), y = val(b);
      return (typeof x === "string" ? String(x).localeCompare(String(y)) : (x as number) - (y as number)) * sort.dir;
    });
  }, [shown, sort]);

  const toggleSet = (key: "techniques" | "books", v: string) => setF((p) => {
    const next = new Set(p[key]);
    if (next.has(v)) next.delete(v); else next.add(v);
    return { ...p, [key]: next };
  });
  const Th = ({ k, children, num = true, title }: { k: SortKey; children: React.ReactNode; num?: boolean; title?: string }) => (
    <th className={num ? "num" : ""} title={title}>
      <button className="led-sort" onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : -1 }))}
        aria-label={`Sort by ${k}`}>
        {children}<span className="led-sort-i" aria-hidden="true">{sort.key === k ? (sort.dir === 1 ? "↑" : "↓") : ""}</span>
      </button>
    </th>
  );
  const tripRow = (t: typeof shown[number], id: string) => {
    const h = held(t);
    return [
      <tr key={id} className={`led-tr${open === id ? " open" : ""}`} onClick={() => setOpen(open === id ? null : id)}>
        <td className="led-td-when">{grouped ? fmtTime(t.outAt) : shortDate(t._day)}</td>
        <td className="led-td-what">
          <SymIcon sym={underlying(t.symbol)} size={16} />
          <span>{t.qty}× {niceName(t.symbol)} <span className="led-tiny">{t.label}</span></span>
        </td>
        <td className="num">{fmtMoney(t.inPrice)}</td>
        <td className="num">{fmtMoney(t.outPrice)}</td>
        <td className="num">{h.label}{h.overnight ? <span className="led-tiny"> ON</span> : null}</td>
        <td className="num muted">−{fmtMoney(t.fees)}</td>
        <td className={`num ${t.gain >= 0 ? "pos" : "neg"}`}><b>{fmtSigned(t.gain)}</b></td>
        <td className="num muted">{fmtMoney(t.running, 2)}</td>
      </tr>,
      open === id
        ? <tr key={`${id}d`} className="led-tr-detail"><td colSpan={8}><TripDetail t={t} /></td></tr>
        : null,
    ];
  };

  return (
    <>
      <div className="panel mb led-filters">
        <div className="led-frow">
          <input className="led-search" type="search" placeholder="Filter by symbol, contract or source…"
            value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Filter trades" />
          <div className="seg sm" role="group" aria-label="Result">
            {(["all", "wins", "losses"] as const).map((k) => (
              <button key={k} className={f.result === k ? "on" : ""} onClick={() => setF({ ...f, result: k })}>
                {k === "all" ? "All" : k === "wins" ? "Wins" : "Losses"}
              </button>
            ))}
          </div>
          <div className="seg sm" role="group" aria-label="Instrument">
            {(["all", "options", "shares"] as const).map((k) => (
              <button key={k} className={f.kind === k ? "on" : ""} onClick={() => setF({ ...f, kind: k })}>
                {k === "all" ? "Any" : k === "options" ? "Options" : "Shares"}
              </button>
            ))}
          </div>
          <div className="seg sm" role="group" aria-label="Hold time">
            {(["all", "intraday", "overnight"] as const).map((k) => (
              <button key={k} className={f.hold === k ? "on" : ""} onClick={() => setF({ ...f, hold: k })}>
                {k === "all" ? "Any hold" : k === "intraday" ? "Intraday" : "Overnight"}
              </button>
            ))}
          </div>
          <button className={`led-chip${f.showOpen ? " on" : ""}`} aria-pressed={f.showOpen}
            onClick={() => setF({ ...f, showOpen: !f.showOpen })}>Open positions</button>
          {dirty && <button className="led-chip led-clear" onClick={() => setF(NO_FILTERS)}>Clear filters</button>}
        </div>
        {(techniques.length > 1 || books.length > 1) && (
          <div className="led-frow led-frow--sets">
            {techniques.length > 1 && (
              <span className="led-set"><span className="led-set-lbl">Source</span>
                {techniques.map((t) => (
                  <button key={t} className={`led-chip${f.techniques.has(t) ? " on" : ""}`}
                    aria-pressed={f.techniques.has(t)} onClick={() => toggleSet("techniques", t)}>{t}</button>
                ))}
              </span>
            )}
            {books.length > 1 && (
              <span className="led-set"><span className="led-set-lbl">Book</span>
                {books.map((b) => (
                  <button key={b} className={`led-chip${f.books.has(b) ? " on" : ""}`}
                    aria-pressed={f.books.has(b)} onClick={() => toggleSet("books", b)}>{b}</button>
                ))}
              </span>
            )}
          </div>
        )}
        <div className="led-fsum">
          <b>{shown.length}</b> trade{shown.length === 1 ? "" : "s"}
          {shownOpen.length > 0 && <> · <b>{shownOpen.length}</b> open</>}
          {shown.length > 0 && <> · {wins}W/{shown.length - wins}L · net{" "}
            <b className={netShown >= 0 ? "pos" : "neg"}>{fmtSigned(netShown)}</b>
            {" · fees "}<span className="neg">−{fmtMoney(feesShown)}</span></>}
          {!grouped && <> · sorted by {sort.key}, days ungrouped</>}
        </div>
      </div>

      <div className="panel mb">
        <div className="scroll-x">
          <table className="tbl led-sheet">
            <thead>
              <tr>
                <Th k="date" num={false}>{grouped ? "Time" : "Date"}</Th>
                <Th k="symbol" num={false}>Position</Th>
                <Th k="in">In</Th><Th k="out">Out</Th><Th k="held">Held</Th>
                <Th k="fees">Fees</Th><Th k="net">Net</Th>
                <Th k="balance" title="Money actually banked. What open positions are worth shows as Riding in the headline, and only lands here when you sell.">Balance</Th>
              </tr>
            </thead>
            <tbody>
              {grouped ? model.days.map((d) => {
                const trips = d.trips.filter(match);
                const openHere = d.isToday ? shownOpen : [];
                if (!trips.length && !openHere.length && !d.isToday && !d.adjustments.length) return null;
                return [
                  <tr className="led-sub" key={`s${d.date}`}>
                    <td className="led-sub-date">{d.isToday ? "Today" : weekday(d.date)}
                      <span className="led-tiny"> {shortDate(d.date)}</span></td>
                    <td className="led-sub-what">
                      {d.realized == null ? <span className="led-tiny">nothing closed{openHere.length ? ` · ${openHere.length} riding` : ""}</span>
                        : `${trips.length} close${trips.length === 1 ? "" : "s"}`}
                    </td>
                    <td colSpan={4}></td>
                    <td className="num">
                      <span className={`led-box ${d.realized == null ? "flat" : d.realized >= 0 ? "up" : "dn"}`}>
                        {d.realized == null ? "—" : fmtSigned(d.realized)}
                      </span>
                    </td>
                    <td className="num">{fmtMoney(d.closing, 2)}</td>
                  </tr>,
                  ...openHere.map((o, i) => (
                    <tr className="led-tr led-tr--open" key={`o${i}`}>
                      <td className="led-td-when led-tiny">open</td>
                      <td className="led-td-what">
                        <SymIcon sym={underlying(o.symbol)} size={16} />
                        <span>{Math.abs(o.qty)}× {niceName(o.symbol)} <span className="led-tiny">{o.label} · in {shortDate(ET_DAY.format(new Date(o.inAt)))}</span></span>
                      </td>
                      <td className="num">{fmtMoney(o.inPrice)}</td>
                      <td className="num muted">{o.mark != null ? `${fmtMoney(o.mark)} mark` : "—"}</td>
                      <td className="num">{held({ inAt: o.inAt, outAt: new Date().toISOString() } as LedgerTrip).label}</td>
                      <td className="num muted">−{fmtMoney(o.fees)}</td>
                      <td className={`num ${(o.unrealized ?? 0) >= 0 ? "pos" : "neg"}`}>
                        {o.unrealized != null ? fmtSigned(o.unrealized) : "—"}</td>
                      <td className="num led-tiny">unrealised</td>
                    </tr>
                  )),
                  ...trips.flatMap((t, i) => tripRow({ ...t, _day: d.date }, `${d.date}-${i}`)),
                  ...d.adjustments.map((a, i) => (
                    <tr className="led-tr" key={`adj${i}`}>
                      <td className="led-td-when led-tiny">adj</td>
                      <td className="led-td-what" colSpan={5}>Book correction <span className="led-tiny">{a.reason.slice(0, 80)}</span></td>
                      <td className={`num ${a.amount >= 0 ? "pos" : "neg"}`}>{fmtSigned(a.amount)}</td>
                      <td></td>
                    </tr>
                  )),
                ];
              }) : flat.flatMap((t, i) => tripRow(t, `f${i}`))}
              {shown.length === 0 && shownOpen.length === 0 && (
                <tr><td colSpan={8} className="empty">Nothing matches these filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

/* ── E · Waterfall ──────────────────────────────────────────────────────── */

function ChartView({ led, model }: { led: Ledger; model: NonNullable<ReturnType<typeof useModel>> }) {
  const [openDay, setOpenDay] = useState<string | null>(null);
  const H = 220;
  const chron = [...model.days].reverse();                 // oldest → newest
  const bars = useMemo(() => {
    const out: { key: string; label: string; sub: string; from: number; to: number;
      delta: number | null; kind: "up" | "dn" | "flat" | "ride" }[] = [];
    let level = chron.length ? r2(chron[0].closing - (chron[0].realized ?? 0)) : led.total;
    for (const d of chron) {
      const delta = d.realized;
      const to = delta == null ? level : r2(level + delta);
      out.push({ key: d.date, label: d.isToday ? "Today" : weekday(d.date).slice(0, 3),
        sub: shortDate(d.date), from: level, to, delta,
        kind: delta == null ? "flat" : delta >= 0 ? "up" : "dn" });
      level = to;
    }
    if (Math.abs(led.riding) > 0.005 || led.open.length) {
      out.push({ key: "riding", label: "Riding", sub: `${led.open.length} open`,
        from: level, to: r2(level + led.riding), delta: led.riding, kind: "ride" });
      level = r2(level + led.riding);
    }
    return out;
  }, [chron, led]);

  const start = bars.length ? bars[0].from : led.total;
  const vals = [start, ...bars.map((b) => b.to), ...bars.map((b) => b.from)];
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals);
  const pad = Math.max((hi0 - lo0) * 0.18, Math.abs(hi0) * 0.002, 1);
  const lo = lo0 - pad, hi = hi0 + pad;
  const y = (v: number) => ((hi - v) / (hi - lo)) * H;
  const ticks = [hi0, (hi0 + lo0) / 2, lo0];

  return (
    <>
      <div className="panel mb led-chart-panel">
        <div className="led-chart">
          <div className="led-yaxis" aria-hidden="true">
            {ticks.map((t, i) => (
              <span className="led-ylab" key={i} style={{ top: `${y(t)}px` }}>{fmtMoney(t, 0)}</span>
            ))}
          </div>
          <div className="led-plot" style={{ height: H }}
            role="img" aria-label={`Balance from ${fmtMoney(start, 0)} to ${fmtMoney(led.total, 0)}, one bar per day`}>
            {ticks.map((t, i) => <div className="led-gridline" key={i} style={{ top: `${y(t)}px` }} />)}
            <div className="led-startline" style={{ top: `${y(start)}px` }}>
              <span className="led-startlab">start {fmtMoney(start, 0)}</span>
            </div>
            <div className="led-cols">
              {bars.map((b, i) => {
                const top = Math.min(y(b.from), y(b.to));
                const h = Math.max(3, Math.abs(y(b.to) - y(b.from)));
                const labelAbove = (b.delta ?? 0) >= 0;
                return (
                  <button className={`led-col${openDay === b.key ? " on" : ""}`} key={b.key}
                    onClick={() => setOpenDay(openDay === b.key ? null : b.key)}
                    title={`${b.label} ${b.sub}: ${b.delta == null ? "nothing closed" : fmtSigned(b.delta)}`}>
                    <span className={`led-bar ${b.kind}`} style={{ top: `${top}px`, height: `${h}px` }} />
                    {i < bars.length - 1 && <span className="led-conn" style={{ top: `${y(b.to)}px` }} />}
                    <span className={`led-bval ${b.delta == null ? "muted" : b.delta >= 0 ? "pos" : "neg"}`}
                      style={{ top: `${labelAbove ? Math.max(0, top - 16) : Math.min(H - 14, top + h + 2)}px` }}>
                      {b.delta == null ? "none" : fmtSigned(b.delta)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="led-xaxis">
            {bars.map((b) => (
              <span className="led-xlab" key={b.key}>{b.label}<span>{b.sub}</span></span>
            ))}
          </div>
        </div>
        <div className="led-legend">
          <span><i className="led-sw up" />banked gain</span>
          <span><i className="led-sw dn" />banked loss</span>
          <span><i className="led-sw ride" />riding, not banked yet</span>
          <span className="muted">balance now <b>{fmtMoney(led.total, 2)}</b></span>
        </div>
      </div>

      <div className="panel mb">
        {model.days.map((d) => (
          <div key={d.date}>
            <button className={`led-drow${openDay === d.date ? " on" : ""}`}
              onClick={() => setOpenDay(openDay === d.date ? null : d.date)}
              aria-expanded={openDay === d.date}>
              <span className="led-drow-date">{d.isToday ? "Today" : weekday(d.date)}
                <span className="led-tiny"> {shortDate(d.date)}</span></span>
              <span className="led-drow-what">
                {d.realized == null
                  ? `nothing closed · ${led.open.length} position${led.open.length === 1 ? "" : "s"} riding`
                  : d.trips.map((t) => `${niceName(t.symbol)} ${fmtSigned(t.gain)}`).join(" · ")}
              </span>
              <span className={`led-drow-net ${d.realized == null ? "muted" : d.realized >= 0 ? "pos" : "neg"}`}>
                {d.realized == null ? "—" : fmtSigned(d.realized)}
              </span>
            </button>
            {openDay === d.date && (
              <div className="led-drow-body">
                {d.isToday && led.open.map((o, i) => (
                  <div className="led-ev live" key={`o${i}`}>
                    <SymIcon sym={underlying(o.symbol)} size={20} />
                    <span className="led-ev-name">{Math.abs(o.qty)}× {niceName(o.symbol)}
                      <span>bought {fmtDateTime(o.inAt)} · {o.label}</span></span>
                    <span className="led-ev-flow">{fmtMoney(o.inPrice)} → {o.mark != null ? fmtMoney(o.mark) : "—"}</span>
                    {o.unrealized != null && (
                      <span className={`led-ev-net ${o.unrealized >= 0 ? "pos" : "neg"}`}>{fmtSigned(o.unrealized)}</span>
                    )}
                  </div>
                ))}
                {d.trips.map((t, i) => <TripDetail key={i} t={t} />)}
                {d.realized == null && !led.open.length && (
                  <div className="empty">Quiet day — nothing bought, nothing sold.</div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

/* ── page ───────────────────────────────────────────────────────────────── */

export function LedgerPage() {
  const [days, setDays] = useState(30);
  const [view, setView] = useState<View>(() => {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      return (VIEWS.some((x) => x.key === v) ? v : "timeline") as View;
    } catch { return "timeline"; }
  });
  // the ledger follows the workspace: switching Practice/LIVE re-fetches
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const state = useAsync(() => api.deskLedger(days), [days, mode]);
  const led: Ledger | undefined = state.data;
  const model = useModel(led);
  const live = led?.workspace === "live";

  return (
    <div className="ledger-page">
      <h2 className="page-title">Ledger — your money, in plain terms</h2>

      <AsyncSection state={state} isEmpty={() => !led}
        empty={<EmptyState title="No trades yet" />}>
        {() => led && model && (
          <>
            <Headline led={led} model={model} days={days} setDays={setDays} view={view} setView={setView} />

            {led.days.length === 0 && led.open.length === 0 ? (
              <EmptyState title={live
                ? "No trades through Zargar on your live accounts yet"
                : `No completed trades in the last ${led.windowDays} days`}
                hint={live ? "The brokerage total above includes everything the accounts hold; this page only ever shows what Zargar bought and sold." : undefined} />
            ) : view === "timeline" ? <TimelineView led={led} model={model} />
              : view === "sheet" ? <SheetView led={led} model={model} />
                : <ChartView led={led} model={model} />}

            <p className="muted led-foot">
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
