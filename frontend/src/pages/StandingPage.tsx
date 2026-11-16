import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import { BrokerIcon } from "../components/BrokerIcon";
import { SymIcon } from "../components/SymIcon";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { IconCheck, IconClock, IconWarn, IconX } from "../components/icons";

/** Standing orders (2026-11-14): the user's own order plans. Claude drafts them from what the user asked for;
 *  the user reviews here and arms a whole plan with one click (+ confirm). Real-money books also need the
 *  real-money switch, which only the user turns on. The app then executes: trigger -> limit off the live quote
 *  -> RiskGate -> venue, re-pricing an unfilled limit inside the user's guard, and gives a filled buy its exits. */

type Attempt = { n: number; qty: number; limit: number; status?: string };
type SO = {
  id: string; planId: string | null; planName: string | null; planArmConfirm: string | null;
  portfolioId: string; symbol: string; side: "BUY" | "SELL"; qty: number | null; budget: number | null;
  trigger: string; notBefore: string | null; expiresOn: string; maxPrice: number | null; minPrice: number | null;
  slippagePct: number; takeProfitPct: number | null; stopLossPct: number | null; status: string;
  note: string | null; lastError: string | null; filledQty: number; avgFillPrice: number | null;
  attempts: Attempt[]; armConfirm: string; positionId: string | null; armedBy?: string;
};
type Delegation = {
  id: string; portfolioIds: string[]; startsAt: string; endsAt: string; maxOrderNotional: number;
  maxTotalNotional: number; active: boolean; revokedAt: string | null; committed: number;
};
const DELEGATE_PHRASE = "I DELEGATE ARMING";

/** End of the chosen window as an ET wall-clock ISO string (the server reads it as ET). */
function windowEnd(choice: string, custom: string): string {
  const et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  if (choice === "today") return `${ymd(et)}T16:15:00`;
  if (choice === "week") {
    const fri = new Date(et); fri.setDate(et.getDate() + ((5 - et.getDay() + 7) % 7));
    return `${ymd(fri)}T16:15:00`;
  }
  if (choice === "7d") { const d = new Date(et); d.setDate(et.getDate() + 7); return `${ymd(d)}T16:15:00`; }
  return `${custom}T16:15:00`;
}
type Preflight = { ok: boolean; why?: string; reason?: string; limit?: number; qty?: number; notional?: number;
  failedChecks?: { name: string; detail: string }[] };

const OPEN = new Set(["draft", "armed", "placing", "working"]);
const LIVE_RUN = new Set(["placing", "working"]);
const PILL: Record<string, string> = {
  draft: "dim", armed: "wait", placing: "wait", working: "wait", done: "ok", failed: "bad", cancelled: "dim", expired: "dim",
};
const LABEL: Record<string, string> = {
  draft: "draft", armed: "armed", placing: "sending", working: "working", done: "filled", failed: "failed",
  cancelled: "cancelled", expired: "expired",
};

function planStatus(rows: SO[]): string {
  if (rows.some((r) => LIVE_RUN.has(r.status))) return "working";
  if (rows.some((r) => r.status === "armed")) return "armed";
  if (rows.some((r) => r.status === "draft")) return "draft";
  if (rows.some((r) => r.status === "failed")) return "failed";
  if (rows.every((r) => r.status === "done")) return "done";
  return rows.every((r) => r.status === "cancelled") ? "cancelled" : "expired";
}

export function StandingPage() {
  const portfolios = useStore((s) => s.portfolios);
  const brokerages = useStore((s) => s.brokerages);
  const [orders, setOrders] = useState<SO[] | null>(null);
  const [allowLive, setAllowLive] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actErr, setActErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [confirmLive, setConfirmLive] = useState(false);
  const [preflight, setPreflight] = useState<Record<string, Preflight>>({});
  const [showHistory, setShowHistory] = useState(false);
  const [delegations, setDelegations] = useState<Delegation[]>([]);
  const [delegating, setDelegating] = useState(false);
  const [dAccounts, setDAccounts] = useState<string[]>([]);
  const [dWindow, setDWindow] = useState("today");
  const [dDate, setDDate] = useState("");
  const [dPer, setDPer] = useState("500");
  const [dTotal, setDTotal] = useState("1000");
  const [dConfirm, setDConfirm] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ orders: SO[]; allowLive: boolean; delegations?: Delegation[] }>("/api/standing");
      setOrders(r.orders);
      setAllowLive(r.allowLive);
      setDelegations(r.delegations ?? []);
      setLoadErr(null);
    } catch (e) { setLoadErr(String((e as Error).message)); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  // account -> broker name + logo (SnapTrade connections), IBKR by venue
  const accountOf = useCallback((pid: string) => {
    const pf = portfolios.find((p) => p.id === pid);
    for (const pr of brokerages?.providers ?? []) {
      if (pr.accounts.some((a) => a.portfolioId === pid)) return { name: pf?.name ?? pr.broker, broker: pr.broker, logo: pr.logoUrl, kind: pf?.kind };
    }
    const broker = pf?.venue === "ibkr" || (pf?.name ?? "").includes("IBKR") ? "Interactive Brokers" : (pf?.name ?? "account");
    return { name: pf?.name ?? pid.slice(0, 8), broker, logo: null as string | null, kind: pf?.kind };
  }, [portfolios, brokerages]);

  const plans = useMemo(() => {
    const m = new Map<string, SO[]>();
    for (const o of orders ?? []) {
      const k = o.planId ?? `single:${o.id}`;
      m.set(k, [...(m.get(k) ?? []), o]);
    }
    const all = [...m.entries()].map(([key, rows]) => ({
      key, rows: [...rows].sort((a, b) => (a.notBefore ?? "").localeCompare(b.notBefore ?? "")), status: planStatus(rows),
    }));
    return { open: all.filter((p) => p.rows.some((r) => OPEN.has(r.status))), closed: all.filter((p) => !p.rows.some((r) => OPEN.has(r.status))) };
  }, [orders]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setActErr(null);
    try { await fn(); await load(); } catch (e) { setActErr(String((e as Error).message)); }
    setBusy(null);
  };

  const size = (o: SO) => (o.qty ? `${o.qty} sh` : `up to $${(o.budget ?? 0).toLocaleString()}`);
  const when = (o: SO) => (o.trigger === "listing" ? "when it starts trading" : o.trigger === "at" ? `from ${o.notBefore} ET` : "at the next open");
  const guard = (o: SO) => (o.side === "BUY"
    ? (o.maxPrice ? `pay ≤ $${o.maxPrice.toFixed(2)}` : "no price cap")
    : (o.minPrice ? `sell ≥ $${o.minPrice.toFixed(2)}` : "no price floor"));
  const exits = (o: SO) => [o.takeProfitPct && `+${o.takeProfitPct}% take profit`, o.stopLossPct && `−${o.stopLossPct}% stop`].filter(Boolean).join(" · ");

  if (orders === null && !loadErr) return <div className="tips-page"><Spinner label="loading standing orders…" /></div>;

  const renderPlan = ({ key, rows, status }: { key: string; rows: SO[]; status: string }, history = false) => {
    const first = rows[0];
    const isPlan = !!first.planId;
    const drafts = rows.filter((r) => r.status === "draft");
    const brokers = [...new Map(rows.map((r) => { const a = accountOf(r.portfolioId); return [a.broker, a]; })).values()];
    const real = rows.some((r) => ["live", "paper"].includes(accountOf(r.portfolioId).kind ?? ""));
    return (
      <div className={`panel so-plan${history ? " so-history" : ""}`} key={key}>
        <div className="panel-head so-plan-head">
          <span className="so-brokers">{brokers.map((b) => <BrokerIcon key={b.broker} name={b.broker} logoUrl={b.logo} size={22} />)}</span>
          <span className="so-plan-name">{isPlan ? first.planName : `${first.side} ${first.symbol}`}</span>
          <span className={`status-pill ${PILL[status]}`}>{LABEL[status]}</span>
          {real && <span className="status-pill bad">real money</span>}
          <span className="so-spacer" />
          {!history && drafts.length > 0 && confirming !== key && (
            <button className="primary-btn" disabled={!!busy} onClick={() => setConfirming(key)}>
              {isPlan ? `Arm plan (${drafts.length})` : "Arm order"}
            </button>
          )}
        </div>
        {confirming === key && (
          <div className="so-confirm" role="alertdialog" aria-label="Confirm arming">
            <IconWarn />
            <div className="so-confirm-text">
              <b>Arm {drafts.length} order{drafts.length > 1 ? "s" : ""}?</b> The app will place {drafts.length > 1 ? "them" : "it"} on {drafts.length > 1 ? "their" : "its"} triggers
              {real ? " with real money" : ""}: {drafts.map((d) => `${d.side} ${size(d)} ${d.symbol} ${when(d)}`).join("; ")}.
              {real && !allowLive && <div className="so-warn-line">The real-money switch is off — armed orders will wait until you turn it on.</div>}
            </div>
            <button className="primary-btn" disabled={!!busy} autoFocus onClick={() => act(`arm:${key}`, async () => {
              if (isPlan) await api.post(`/api/standing/plan/${first.planId}/arm`, { confirm: first.planArmConfirm });
              else await api.post(`/api/standing/${first.id}/arm`, { confirm: first.armConfirm });
              setConfirming(null);
            })}><IconCheck /> Confirm arm</button>
            <button className="ghost-btn" onClick={() => setConfirming(null)}>Cancel</button>
          </div>
        )}
        <div className="panel-body scroll-x">
          <table className="tbl so-table">
            <thead><tr><th>Account</th><th>Order</th><th>When</th><th>Price guard</th><th>After a buy</th><th>Status</th><th aria-label="actions" /></tr></thead>
            <tbody>
              {rows.map((o) => {
                const acct = accountOf(o.portfolioId);
                const pf = preflight[o.id];
                return (
                  <tr key={o.id}>
                    <td><span className="so-acct"><BrokerIcon name={acct.broker} logoUrl={acct.logo} size={18} />{acct.name}</span></td>
                    <td>
                      <span className="so-order">
                        <span className={`so-side ${o.side === "BUY" ? "buy" : "sell"}`}>{o.side}</span>
                        <SymIcon sym={o.symbol} size={18} />
                        <b>{o.symbol}</b>
                        <span className="so-dim">{size(o)}</span>
                      </span>
                    </td>
                    <td><span className="so-when"><IconClock />{when(o)}<span className="so-dim"> · until {o.expiresOn}</span></span></td>
                    <td className="so-dim">{guard(o)} · ±{o.slippagePct}%</td>
                    <td className="so-dim">{exits(o) || "—"}</td>
                    <td>
                      <span className={`status-pill ${PILL[o.status] ?? "dim"}`}>
                        {LIVE_RUN.has(o.status) && <span className="spinner so-spin" />}{LABEL[o.status] ?? o.status}
                      </span>
                      {o.armedBy && o.armedBy !== "user" && <div className="so-dim so-armed-by">armed by Claude</div>}
                      {o.filledQty > 0 && <div className="so-fill">{o.filledQty} @ ${o.avgFillPrice?.toFixed(2)}</div>}
                      {o.lastError && o.status !== "done" && <div className="so-err"><IconWarn />{o.lastError}</div>}
                      {pf && (
                        <div className={`so-pf ${pf.ok ? "ok" : "bad"}`}>
                          {pf.ok ? <IconCheck /> : <IconX />}
                          {pf.ok ? `would send ${pf.qty} @ $${pf.limit} ($${pf.notional?.toLocaleString()})`
                            : (pf.why || pf.reason || (pf.failedChecks ?? []).map((c) => c.detail || c.name).join("; "))}
                        </div>
                      )}
                    </td>
                    <td><span className="so-actions">
                      {!history && <button className="link-btn" disabled={!!busy} title="Dry-run the risk checks at today's quote (no order sent)"
                        onClick={() => act(`pf:${o.id}`, async () => {
                          const r = await api.post<Preflight>(`/api/standing/${o.id}/preflight`);
                          setPreflight((p) => ({ ...p, [o.id]: r }));
                        })}>check</button>}
                      {o.status === "armed" && <button className="link-btn" disabled={!!busy}
                        onClick={() => act(`d:${o.id}`, () => api.post(`/api/standing/${o.id}/disarm`))}>disarm</button>}
                      {OPEN.has(o.status) && <button className="link-btn danger" disabled={!!busy}
                        onClick={() => act(`c:${o.id}`, () => api.post(`/api/standing/${o.id}/cancel`))}>cancel</button>}
                    </span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const armedCount = (orders ?? []).filter((o) => o.status === "armed").length;
  const workingCount = (orders ?? []).filter((o) => LIVE_RUN.has(o.status)).length;
  const realBooks = portfolios.filter((p) => ["live", "paper"].includes(p.kind ?? "") && !(p as { archived?: boolean }).archived);
  const activeDelegation = delegations.find((d) => d.active) ?? null;
  const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const endLabel = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

  const delegationCard = activeDelegation ? (
    <div className="so-switch on so-delegation">
      <span className="status-pill wait">Claude may arm</span>
      <div className="so-switch-text">
        Until <b>{endLabel(activeDelegation.endsAt)}</b> on {activeDelegation.portfolioIds.map((p) => accountOf(p).name).join(", ")}.
        {" "}Buys up to {money(activeDelegation.maxOrderNotional)} each, {money(activeDelegation.committed)} of {money(activeDelegation.maxTotalNotional)} used.
        {" "}You get a push for every order Claude arms.
      </div>
      <button className="danger-btn" disabled={!!busy}
        onClick={() => act("revoke", () => api.post(`/api/standing/delegations/${activeDelegation.id}/revoke`, {}))}>Revoke</button>
    </div>
  ) : delegating ? (
    <div className="panel so-plan so-delegation-form">
      <div className="so-plan-head"><div className="so-plan-title"><b>Let Claude arm orders for a while</b>
        <span className="so-dim">Claude arms your plans, repairs and Scout ideas inside these limits. It can never change the real-money switch, risk caps, the kill switch, cash or accounts.</span></div></div>
      <div className="so-form-grid">
        <label>Accounts</label>
        <div className="so-form-accounts">
          {realBooks.map((p) => (
            <label key={p.id} className="so-check">
              <input type="checkbox" checked={dAccounts.includes(p.id)}
                onChange={(e) => setDAccounts((a) => (e.target.checked ? [...a, p.id] : a.filter((x) => x !== p.id)))} />
              <BrokerIcon name={accountOf(p.id).broker} logoUrl={accountOf(p.id).logo} size={16} /> {p.name}
            </label>
          ))}
        </div>
        <label>For</label>
        <div>
          <select value={dWindow} onChange={(e) => setDWindow(e.target.value)}>
            <option value="today">the rest of today</option>
            <option value="week">until Friday's close</option>
            <option value="7d">7 days</option>
            <option value="date">until a date…</option>
          </select>
          {dWindow === "date" && <input type="date" value={dDate} onChange={(e) => setDDate(e.target.value)} />}
        </div>
        <label>Max per buy</label>
        <input type="number" min={1} value={dPer} onChange={(e) => setDPer(e.target.value)} />
        <label>Max total buys</label>
        <input type="number" min={1} value={dTotal} onChange={(e) => setDTotal(e.target.value)} />
      </div>
      <div className="so-confirm-actions">
        {dConfirm ? (
          <>
            <span className="so-warn-line">Claude will be able to place real-money buys up to {money(Number(dTotal) || 0)} in total. Sure?</span>
            <button className="primary-btn" disabled={!!busy || dAccounts.length === 0} onClick={() => act("delegate", async () => {
              await api.post("/api/standing/delegations", {
                portfolioIds: dAccounts, endsAt: windowEnd(dWindow, dDate), maxOrderNotional: Number(dPer),
                maxTotalNotional: Number(dTotal), confirm: DELEGATE_PHRASE,
              });
              setDelegating(false); setDConfirm(false);
            })}>Yes, delegate</button>
            <button className="ghost-btn" onClick={() => setDConfirm(false)}>Back</button>
          </>
        ) : (
          <>
            <button className="primary-btn" disabled={dAccounts.length === 0 || !(Number(dPer) > 0) || !(Number(dTotal) >= Number(dPer))
              || (dWindow === "date" && !dDate)} onClick={() => setDConfirm(true)}>Delegate</button>
            <button className="ghost-btn" onClick={() => setDelegating(false)}>Cancel</button>
          </>
        )}
      </div>
    </div>
  ) : (
    <div className="so-switch off so-delegation">
      <span className="status-pill dim">you arm</span>
      <div className="so-switch-text">Away for a while? Let Claude arm orders for a set time, accounts and money cap.</div>
      <button className="ghost-btn" onClick={() => { setDelegating(true); setDAccounts(realBooks.map((p) => p.id)); }}>Delegate arming…</button>
    </div>
  );

  return (
    <div className="tips-page">
      <div className="tips-head">
        <h2 className="page-title">Standing orders</h2>
        <span className="so-dim">{plans.open.length} open plan{plans.open.length === 1 ? "" : "s"} · {armedCount} armed · {workingCount} working</span>
      </div>

      <div className={`so-switch ${allowLive ? "on" : "off"}`}>
        <span className={`status-pill ${allowLive ? "bad" : "dim"}`}>{allowLive ? "real money on" : "real money off"}</span>
        <div className="so-switch-text">
          {allowLive
            ? "Armed orders on Webull, Wealthsimple and IBKR live will trade when their trigger fires."
            : "Armed orders on real accounts wait. Turn this on when you want them to trade."}
        </div>
        {confirmLive ? (
          <>
            <button className="primary-btn" disabled={!!busy} onClick={() => act("live", async () => {
              await api.patchSettings({ "execution.standing_orders.allow_live": !allowLive });
              setConfirmLive(false);
            })}>{allowLive ? "Yes, turn off" : "Yes, allow real money"}</button>
            <button className="ghost-btn" onClick={() => setConfirmLive(false)}>Cancel</button>
          </>
        ) : (
          <button className={allowLive ? "ghost-btn" : "danger-btn"} disabled={!!busy} onClick={() => setConfirmLive(true)}>
            {allowLive ? "Turn off" : "Turn on"}
          </button>
        )}
      </div>

      {delegationCard}

      {loadErr && <ErrorState message={`Could not load standing orders: ${loadErr}`} onRetry={load} />}
      {actErr && <ErrorState message={actErr} />}

      {plans.open.length === 0 && !loadErr && (
        <EmptyState title="No open standing orders" hint="Tell Claude your plan — it drafts the orders here for you to arm." />
      )}
      {plans.open.map((p) => renderPlan(p))}

      {plans.closed.length > 0 && (
        <div className="so-history-wrap">
          <button className="link-btn" onClick={() => setShowHistory((v) => !v)}>
            {showHistory ? "Hide" : "Show"} history ({plans.closed.length})
          </button>
          {showHistory && plans.closed.map((p) => renderPlan(p, true))}
        </div>
      )}
    </div>
  );
}
