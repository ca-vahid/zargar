import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

/** Standing orders (2026-11-14): the user's own order plans. Claude drafts them from what the user asked
 *  for; the user reviews here and arms a whole plan with ONE click. Real-money books also need the
 *  "allow real-money standing orders" switch, which only the user turns on. The app then executes:
 *  trigger -> limit off the live quote -> RiskGate -> venue, re-pricing an unfilled limit inside the
 *  user's cap, and hands a filled buy its take-profit / stop-loss. */

type SO = {
  id: string; planId: string | null; planName: string | null; planArmConfirm: string | null;
  portfolioId: string; symbol: string; side: "BUY" | "SELL"; qty: number | null; budget: number | null;
  trigger: string; notBefore: string | null; expiresOn: string; maxPrice: number | null; minPrice: number | null;
  slippagePct: number; takeProfitPct: number | null; stopLossPct: number | null; status: string;
  note: string | null; lastError: string | null; filledQty: number; avgFillPrice: number | null;
  attempts: { n: number; qty: number; limit: number; status?: string }[]; armConfirm: string; positionId: string | null;
};

const OPEN = new Set(["draft", "armed", "placing", "working"]);

export function StandingPage() {
  const portfolios = useStore((s) => s.portfolios);
  const [orders, setOrders] = useState<SO[]>([]);
  const [allowLive, setAllowLive] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<Record<string, any>>({});

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ orders: SO[]; allowLive: boolean }>("/api/standing");
      setOrders(r.orders);
      setAllowLive(r.allowLive);
    } catch (e) { setErr(String((e as Error).message)); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const name = (pid: string) => portfolios.find((p) => p.id === pid)?.name ?? pid.slice(0, 8);
  const plans = useMemo(() => {
    const m = new Map<string, SO[]>();
    for (const o of orders) {
      const k = o.planId ?? `single:${o.id}`;
      m.set(k, [...(m.get(k) ?? []), o]);
    }
    return [...m.entries()];
  }, [orders]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setErr(null);
    try { await fn(); await load(); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(null);
  };

  const sizeText = (o: SO) => o.qty ? `${o.qty} sh` : `up to $${o.budget?.toLocaleString()}`;
  const triggerText = (o: SO) => o.trigger === "listing" ? "when it lists" : o.trigger === "at" ? `from ${o.notBefore} ET` : "at the next open market";
  const exitsText = (o: SO) => [o.takeProfitPct && `TP +${o.takeProfitPct}%`, o.stopLossPct && `SL -${o.stopLossPct}%`].filter(Boolean).join(" · ");

  return (
    <div>
      <h2 className="page-title">Standing orders</h2>
      <div className="panel">
        <div className="panel-head">Real-money switch</div>
        <div className="panel-body">
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={allowLive} disabled={busy === "live"}
              onChange={(e) => {
                const on = e.target.checked;
                if (on && !window.confirm("Allow ARMED standing orders to trade your real Wealthsimple / Webull / IBKR accounts?")) return;
                act("live", () => api.patchSettings({ "execution.standing_orders.allow_live": on }));
              }} />
            Allow armed standing orders to trade real accounts
          </label>
          <div className="sub">Off = armed orders on real accounts wait. Only you turn this on.</div>
        </div>
      </div>
      {err && <div className="state-note error">{err}</div>}
      {plans.length === 0 && <div className="state-note">No standing orders yet - tell Claude your plan.</div>}
      {plans.map(([key, rows]) => {
        const first = rows[0];
        const drafts = rows.filter((r) => r.status === "draft");
        const isPlan = !!first.planId;
        return (
          <div className="panel" key={key}>
            <div className="panel-head">{isPlan ? first.planName : `${first.side} ${first.symbol}`}
              <span className="sub"> {rows.filter((r) => OPEN.has(r.status)).length} open · {rows.length} total</span></div>
            <div className="panel-body">
              <table className="data-table">
                <thead><tr><th>Account</th><th>Order</th><th>Trigger</th><th>Limits</th><th>Exits</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={o.id}>
                      <td>{name(o.portfolioId)}</td>
                      <td>{o.side} {o.symbol} {sizeText(o)}</td>
                      <td>{triggerText(o)} · until {o.expiresOn}</td>
                      <td>{o.side === "BUY" ? (o.maxPrice ? `max $${o.maxPrice}` : "no cap") : (o.minPrice ? `min $${o.minPrice}` : "no floor")} · slip {o.slippagePct}%</td>
                      <td>{exitsText(o) || "-"}</td>
                      <td title={o.lastError ?? ""}>
                        <b>{o.status}</b>{o.filledQty > 0 && ` · ${o.filledQty} @ ${o.avgFillPrice?.toFixed(2)}`}
                        {o.lastError && <div className="sub">{o.lastError}</div>}
                        {preflight[o.id] && <div className="sub">preflight: {preflight[o.id].ok ? `OK ${preflight[o.id].qty} @ ${preflight[o.id].limit}` : (preflight[o.id].why || preflight[o.id].reason || JSON.stringify(preflight[o.id].failedChecks))}</div>}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="link-btn" disabled={!!busy} onClick={() => act(`pf:${o.id}`, async () => {
                          const r = await api.post<any>(`/api/standing/${o.id}/preflight`);
                          setPreflight((p) => ({ ...p, [o.id]: r }));
                        })}>preflight</button>
                        {o.status === "armed" && <button className="link-btn" disabled={!!busy}
                          onClick={() => act(`d:${o.id}`, () => api.post(`/api/standing/${o.id}/disarm`))}>disarm</button>}
                        {OPEN.has(o.status) && <button className="link-btn" disabled={!!busy}
                          onClick={() => act(`c:${o.id}`, () => api.post(`/api/standing/${o.id}/cancel`))}>cancel</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {drafts.length > 0 && (confirming === key ? (
                <div className="state-note">
                  Arm {drafts.length} order{drafts.length > 1 ? "s" : ""}? The app will place them on their triggers.
                  <button className="btn btn-primary" disabled={!!busy} style={{ marginLeft: 8 }}
                    onClick={() => act(`arm:${key}`, async () => {
                      if (isPlan) await api.post(`/api/standing/plan/${first.planId}/arm`, { confirm: first.planArmConfirm });
                      else await api.post(`/api/standing/${first.id}/arm`, { confirm: first.armConfirm });
                      setConfirming(null);
                    })}>Confirm arm</button>
                  <button className="link-btn" onClick={() => setConfirming(null)}>cancel</button>
                </div>
              ) : (
                <button className="btn btn-primary" disabled={!!busy} onClick={() => setConfirming(key)}>
                  {isPlan ? "Arm plan" : "Arm"}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
