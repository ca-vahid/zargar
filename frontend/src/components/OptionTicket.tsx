import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { cashText } from "../lib/brokerage";
import { estimateFees } from "../lib/fees";
import { fmtCcy, fmtMoney } from "../lib/format";
import { deriveOptionAction, parseOcc } from "../lib/occ";
import { useAsync } from "../lib/useAsync";
import { watchSymbol } from "../lib/ws";
import { useQuote, useStore, type OrderIntentBody } from "../store";
import type { OptionCapability, OptionImpact, Portfolio } from "../types";
import { AccountSelect, type AccountOption } from "./AccountSelect";
import { ConfirmOrderDialog } from "./ConfirmOrderDialog";
import { EmptyState } from "./ui";

const ACTION_LABEL: Record<string, string> = {
  BUY_TO_OPEN: "buy to open", BUY_TO_CLOSE: "buy to close",
  SELL_TO_OPEN: "sell to open", SELL_TO_CLOSE: "sell to close",
};

/** Single-leg option ticket. Mirrors OrderTicket's account/confirm flow; adds
 * the contract strip (greeks, DTE, spread), derived open/close, per-contract
 * fees, breakeven / max loss, and the broker-side preview that doubles as the
 * SnapTrade options capability probe. */
export function OptionTicket({ contract }: { contract: string | null }) {
  const occ = useMemo(() => parseOcc(contract), [contract]);
  const quote = useQuote(occ?.symbol ?? "");
  const allPortfolios = useStore((s) => s.portfolios);
  const portfolios = useMemo(
    () => allPortfolios.filter((p) => p.kind !== "shadow"), [allPortfolios]);
  const positionsMap = useStore((s) => s.positions);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const settings = useStore((s) => s.settings);
  const brokerages = useStore((s) => s.brokerages);
  const toast = useStore((s) => s.toast);
  const prefill = useStore((s) => s.optionsPrefill);
  const clearPrefill = useStore((s) => s.clearOptionsPrefill);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);

  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState("1");
  const [orderType, setOrderType] = useState("LMT");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [tif, setTif] = useState("DAY");
  const [portfolioId, setPortfolioId] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<OrderIntentBody | null>(null);
  const [riskFails, setRiskFails] = useState<{ name: string; detail: string }[]>([]);
  const [impact, setImpact] = useState<OptionImpact | null>(null);
  const [impactBusy, setImpactBusy] = useState(false);

  // one-shot prefill from navigation (blotter "close", technique "trade this contract")
  useEffect(() => {
    if (!prefill) return;
    if (prefill.side) setSide(prefill.side);
    if (prefill.qty) setQty(String(prefill.qty));
    if (prefill.portfolioId) setPortfolioId(prefill.portfolioId);
    clearPrefill();
  }, [prefill, clearPrefill]);

  useEffect(() => {
    if (occ) { watchSymbol(occ.symbol); }
    setImpact(null); setRiskFails([]);
  }, [occ?.symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  // contract snapshot (greeks, OI, IV) — also makes the backend track the contract
  const snap = useAsync(
    () => (occ ? api.optionsQuote(occ.symbol) : Promise.resolve(null)), [occ?.symbol]);
  useEffect(() => {
    if (!occ) return;
    const t = setInterval(snap.reload, 30_000);
    return () => clearInterval(t);
  }, [occ?.symbol, snap.reload]); // eslint-disable-line react-hooks/exhaustive-deps

  const caps = useAsync(() => api.optionsCapabilities(), []);
  const capByPid = useMemo(() => {
    const m = new Map<string, OptionCapability>();
    for (const c of caps.data?.accounts ?? []) if (c.portfolioId) m.set(c.portfolioId, c);
    return m;
  }, [caps.data]);

  const realPortfolios = useMemo(
    () => portfolios.filter((p) => p.kind === "live" || p.kind === "paper"), [portfolios]);
  const practicePortfolios = useMemo(
    () => portfolios.filter((p) => p.kind === "sim"), [portfolios]);
  const modeDefault = useMemo(() => {
    if (mode === "live") {
      // the options venue first (Webull CA); anything known-unsupported last
      const ranked = [...realPortfolios].sort((a, b) => {
        const ca = capByPid.get(a.id), cb = capByPid.get(b.id);
        const score = (c?: OptionCapability) => c?.supported === true ? 0 : c?.supported === null ? 1 : 2;
        return score(ca) - score(cb) || a.name.localeCompare(b.name);
      });
      return ranked[0]?.id;
    }
    const def = practicePortfolios.find((p) => p.id === defaultPid);
    return (def ?? practicePortfolios[0])?.id;
  }, [mode, realPortfolios, practicePortfolios, capByPid, defaultPid]);
  const pid = portfolioId || modeDefault || portfolios[0]?.id || "";
  const portfolio = portfolios.find((p) => p.id === pid);
  const cap = capByPid.get(pid);

  const { account, provider } = useMemo(() => {
    for (const prov of brokerages?.providers ?? []) {
      const acct = prov.accounts.find((a) => a.portfolioId === pid);
      if (acct) return { account: acct, provider: prov };
    }
    return { account: undefined, provider: undefined };
  }, [brokerages, pid]);
  const readOnlyVenue = provider !== undefined && (provider.type !== "trade" || provider.disabled);
  const venueBlocked = !!account && cap !== undefined && cap.supported === false;
  const venueUnknown = !!account && (cap === undefined || cap.supported === null);

  const accountOptions: AccountOption[] = useMemo(() => {
    const map = new Map<string, { account: any; provider: any }>();
    for (const prov of brokerages?.providers ?? []) {
      for (const acct of prov.accounts) map.set(acct.portfolioId, { account: acct, provider: prov });
    }
    return [...realPortfolios, ...practicePortfolios].map((p) => ({
      portfolio: p, account: map.get(p.id)?.account, provider: map.get(p.id)?.provider,
    }));
  }, [brokerages, realPortfolios, practicePortfolios]);

  const needsLimit = orderType === "LMT" || orderType === "STP_LMT";
  const needsStop = orderType === "STP" || orderType === "STP_LMT";
  const bid = quote?.bid ?? snap.data?.bid ?? 0;
  const ask = quote?.ask ?? snap.data?.ask ?? 0;
  const mid = bid > 0 && ask > 0 ? (bid + ask) / 2 : (quote?.last ?? snap.data?.last ?? 0);
  useEffect(() => {   // default limit at the mid once we know it (user edits win)
    if (needsLimit && !limitPrice && mid > 0) setLimitPrice(mid.toFixed(2));
  }, [mid, needsLimit]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setLimitPrice(""); }, [occ?.symbol]);

  const qtyN = Math.max(0, Math.floor(Number(qty) || 0));
  const price = needsLimit && limitPrice ? parseFloat(limitPrice)
    : side === "BUY" ? (ask || mid) : (bid || mid);
  const premium = price > 0 && qtyN > 0 ? price * 100 * qtyN : null;
  const heldQty = occ ? (positionsMap[`${pid}:${occ.symbol}:OPT`]?.qty ?? 0) : 0;
  const action = deriveOptionAction(side, heldQty);
  const closingTooMany = action.endsWith("_TO_CLOSE") && qtyN > Math.abs(heldQty) + 1e-9;
  const nakedShort = action === "SELL_TO_OPEN";

  const feePerContract = Number(settings["options.fee_per_contract"] ?? 0.99);
  const accountCcy = account?.currency ?? portfolio?.baseCurrency ?? "USD";
  const fees = useMemo(() => estimateFees({
    institution: provider?.broker ?? null, account: account ?? null,
    accountCurrency: accountCcy, symbol: occ?.symbol ?? "", side, notional: premium, settings,
  }), [provider?.broker, account, accountCcy, occ?.symbol, side, premium, settings]);
  const commission = account ? feePerContract * qtyN : 0.99 * qtyN;
  const spreadPct = bid > 0 && ask > 0 ? ((ask - bid) / ((ask + bid) / 2)) * 100 : null;
  const breakeven = occ && price > 0
    ? (occ.right === "C" ? occ.strike + price : occ.strike - price) : null;

  const buildIntent = (): OrderIntentBody => ({
    portfolio_id: pid, symbol: occ!.symbol, sec_type: "OPT", side, qty: qtyN,
    order_type: orderType,
    limit_price: needsLimit && limitPrice ? parseFloat(limitPrice) : null,
    stop_price: needsStop && stopPrice ? parseFloat(stopPrice) : null,
    tif, dry_run: dryRun, bracket: null,
  });

  const handleResult = (order: any) => {
    if (order.status === "REJECTED_RISK" || order.status === "REJECTED") {
      toast("error", `Order rejected: ${order.rejectReason ?? "risk check failed"}`);
      const checks = order?.risk?.checks ?? [];
      setRiskFails(checks.filter((c: any) => !c.passed));
    } else if (order.status === "DRY_RUN") {
      toast("info", `Dry run OK — would ${ACTION_LABEL[order.optionAction] ?? side} ${qtyN} × ${occ?.display}`
        + (order.estimatedPrice ? ` @ ~${fmtMoney(order.estimatedPrice)}` : ""));
    } else {
      toast("success", `${ACTION_LABEL[order.optionAction] ?? side} ${qtyN} × ${occ?.display} submitted`);
    }
  };

  const submit = async () => {
    if (!occ) return;
    setRiskFails([]);
    const intent = buildIntent();
    if (!dryRun && portfolio?.kind === "live") { setConfirming(intent); return; }
    setBusy(true);
    try { handleResult(await api.placeOrder(intent)); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(false); }
  };

  const checkImpact = async () => {
    if (!occ) return;
    setImpactBusy(true);
    try {
      const res = await api.optionsImpact({
        portfolio_id: pid, symbol: occ.symbol, side, qty: qtyN, order_type: orderType,
        limit_price: needsLimit && limitPrice ? parseFloat(limitPrice) : null,
      });
      setImpact(res);
      caps.reload();
    } catch (e: any) {
      toast("error", `broker preview: ${e.message}`);
    } finally {
      setImpactBusy(false);
    }
  };

  if (!occ) {
    return (
      <div className="panel ticket-area">
        <div className="panel-head">Option ticket
          <span className={`status-pill ${mode === "live" ? "bad" : "dim"}`}>{mode}</span></div>
        <div className="panel-body">
          <EmptyState title="Pick a contract" art={false}
            hint="Click a call or put in the ladder to load it here." />
        </div>
      </div>
    );
  }

  const g = snap.data;
  const disabled = busy || !pid || qtyN <= 0 || readOnlyVenue || venueBlocked || closingTooMany
    || nakedShort || (needsLimit && !limitPrice);

  return (
    <div className="panel ticket-area">
      <div className="panel-head">Option ticket
        <span className={`status-pill ${mode === "live" ? "bad" : "dim"}`}>{mode}</span>
      </div>
      <div className="panel-body">
        <div className="opt-contract">
          <div className="opt-contract-name">{occ.display}</div>
          <div className="opt-contract-sub">
            <span className="mono">{occ.symbol}</span>
            <span>· {occ.dte === 0 ? "0DTE" : `${occ.dte}d to expiry`}</span>
            {g?.delayed && <span className="status-pill dim" title="bid/ask + greeks from CBOE's free delayed feed (~15 min); last trades live via Yahoo">delayed</span>}
          </div>
          <div className="opt-greeks">
            <span title="bid × ask (delayed)">bid <b>{fmtMoney(bid)}</b> · ask <b>{fmtMoney(ask)}</b></span>
            {quote && quote.last > 0 && <span>last <b>{fmtMoney(quote.last)}</b></span>}
            <span className={spreadPct != null && spreadPct > Number(settings["risk.max_option_spread_pct"] ?? 10) ? "neg" : ""}
              title="bid/ask spread as % of mid — wide spreads are where premium goes to die (T5.4)">
              spread <b>{spreadPct != null ? `${spreadPct.toFixed(1)}%` : "—"}</b></span>
            <span>Δ <b>{g?.delta != null ? g.delta.toFixed(2) : "—"}</b></span>
            <span>θ <b>{g?.theta != null ? g.theta.toFixed(3) : "—"}</b></span>
            <span>IV <b>{g?.iv != null ? `${(g.iv * 100).toFixed(0)}%` : "—"}</b></span>
            <span>OI <b>{g?.openInterest ?? "—"}</b></span>
            <span>vol <b>{g?.volume ?? "—"}</b></span>
          </div>
        </div>

        <div className="side-toggle">
          <button className={`buy ${side === "BUY" ? "active" : ""}`} onClick={() => setSide("BUY")}>BUY</button>
          <button className={`sell ${side === "SELL" ? "active" : ""}`} onClick={() => setSide("SELL")}>SELL</button>
        </div>
        <div className="metric-sub" style={{ marginBottom: 8 }}>
          {ACTION_LABEL[action]}
          {heldQty !== 0 && <> · you hold <b>{heldQty}</b> in this account</>}
          {nakedShort && <span className="neg"> · naked short options are blocked by the risk gate</span>}
          {closingTooMany && <span className="neg"> · only {Math.abs(heldQty)} to close</span>}
        </div>

        <div className="row2">
          <label className="field">
            <span>Contracts</span>
            <input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
          <label className="field">
            <span>Type</span>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              <option value="LMT">Limit</option>
              <option value="MKT">Market</option>
              <option value="STP">Stop</option>
              <option value="STP_LMT">Stop limit</option>
            </select>
          </label>
        </div>
        {(needsLimit || needsStop) && (
          <div className="row2">
            {needsLimit && (
              <label className="field">
                <span>Limit (per share)</span>
                <input type="number" step="0.01" value={limitPrice}
                  placeholder={mid > 0 ? mid.toFixed(2) : ""}
                  onChange={(e) => setLimitPrice(e.target.value)} />
              </label>
            )}
            {needsStop && (
              <label className="field">
                <span>Stop (per share)</span>
                <input type="number" step="0.01" value={stopPrice}
                  onChange={(e) => setStopPrice(e.target.value)} />
              </label>
            )}
          </div>
        )}
        <label className="field">
          <span>Account</span>
          <AccountSelect options={accountOptions} value={pid} onChange={(id) => setPortfolioId(id)} />
        </label>
        {account && (
          <div className={`opt-venue ${venueBlocked ? "bad" : venueUnknown ? "warn" : "ok"}`}>
            {venueBlocked
              ? `${provider?.broker}: option orders are not supported via SnapTrade (${cap?.detail ?? "code 1156"})`
              : venueUnknown
                ? `${provider?.broker}: options support not yet verified — "preview with broker" below probes it`
                : `${provider?.broker}: options supported${cap?.probed ? " (verified with the broker)" : " (allowlisted)"}`}
          </div>
        )}
        <div className="row2">
          <label className="field">
            <span>Time in force</span>
            <select value={tif} onChange={(e) => setTif(e.target.value)}>
              <option>DAY</option><option>GTC</option>
            </select>
          </label>
          <div className="field">
            <span>Available to trade</span>
            <div className="avail-line">
              {account ? cashText(account)
                : portfolio ? fmtCcy(portfolio.cash, portfolio.baseCurrency ?? "USD") : "—"}
            </div>
          </div>
        </div>

        <label className="switch" style={{ marginBottom: 8 }}>
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          <span className="track" />
          <span>Dry run (validate only, never route)</span>
        </label>

        <div className="fees-block">
          <div className="fee-row">
            <span>{side === "BUY" ? "premium (cost)" : "premium (credit)"}</span>
            <span className="v">{premium !== null ? fmtCcy(premium, "USD") : "—"}
              <span className="muted"> = {price > 0 ? fmtMoney(price) : "—"} × 100 × {qtyN || "?"}</span></span>
          </div>
          <div className="fee-row">
            <span title={account ? `${feePerContract.toFixed(2)} USD per contract (Settings → Options) + regulatory fees` : "practice: simulated per-contract commission"}>
              fees (est.)</span>
            <span className="v">{qtyN > 0 ? fmtCcy(commission, "USD") : "—"}</span>
          </div>
          {side === "BUY" && premium !== null && (
            <div className="fee-row">
              <span title="for a long option the most you can lose is the premium paid (+ fees)">max loss</span>
              <span className="v neg">{fmtCcy(premium + commission, "USD")}</span>
            </div>
          )}
          {breakeven !== null && (
            <div className="fee-row">
              <span title="underlying price at expiry where the trade breaks even (before fees)">breakeven</span>
              <span className="v">{fmtMoney(breakeven)}
                {g?.underlyingSpot ? <span className="muted"> ({((breakeven / g.underlyingSpot - 1) * 100).toFixed(1)}% from {fmtMoney(g.underlyingSpot)})</span> : null}
              </span>
            </div>
          )}
          {fees.needsFx && account && (
            <div className={`fx-note ${fees.fxCoveredByWallet ? "ok" : "warn"}`}>
              {fees.fxCoveredByWallet
                ? <>✓ USD premium from a {accountCcy} account — your USD wallet ({fmtCcy(fees.walletCash ?? 0, "USD")}) covers it.</>
                : <><b>USD premium from a {accountCcy} account.</b> Broker auto-converts at ~{fees.fxPct}%
                  {fees.fxFee !== null && <> (≈ {fmtCcy(fees.fxFee, "USD")})</>}. Keep a USD balance to avoid it.</>}
            </div>
          )}
          {account && !dryRun && (
            <div className="fee-row">
              <button className="link-btn" onClick={checkImpact} disabled={impactBusy || qtyN <= 0}
                title="Asks the broker (via SnapTrade's option impact endpoint) for the exact cash effect and fees — read-only, nothing is placed or reserved. Also verifies this account can trade options.">
                {impactBusy ? "asking broker…" : "preview with broker"}
              </button>
              {impact && (impact.error ? (
                <span className="v neg" title={impact.code ? `SnapTrade code ${impact.code}` : undefined}>
                  {impact.supported === false ? "not supported on this brokerage" : `broker: ${impact.error}`}
                </span>
              ) : (
                <span className="v" title="The broker's own numbers for this exact order">
                  {impact.direction?.toLowerCase()} {fmtCcy(impact.estimatedCashChange ?? 0, "USD")}
                  {" "}· fees {fmtCcy(impact.estimatedFees ?? 0, "USD")}
                </span>
              ))}
            </div>
          )}
          {!quote && !g && <div className="metric-sub">waiting for a contract quote…</div>}
        </div>

        <button className={`submit-btn ${side.toLowerCase()}`} disabled={disabled} onClick={submit}>
          {dryRun ? "VALIDATE " : ""}{ACTION_LABEL[action].toUpperCase()} {qtyN || "?"} × {occ.short}
        </button>
        {readOnlyVenue && (
          <div className="metric-sub" style={{ marginTop: 6 }}>
            {provider?.disabled ? "this brokerage connection is disconnected — re-authorize it first"
              : "read-only connection — upgrade it to trade access to submit orders"}
          </div>
        )}
        {riskFails.length > 0 && (
          <div style={{ marginTop: 10 }}>
            {riskFails.map((c) => (
              <div key={c.name} className="check-item fail" style={{ marginBottom: 4 }}>{c.detail || c.name}</div>
            ))}
          </div>
        )}
      </div>

      {confirming && portfolio && (
        <ConfirmOrderDialog
          intent={confirming}
          portfolio={portfolio as Portfolio}
          account={account}
          provider={provider}
          estCost={premium}
          label={`${ACTION_LABEL[action]} ${qtyN} × ${occ.display}`}
          onSubmitted={(order) => { setConfirming(null); handleResult(order); }}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  );
}
