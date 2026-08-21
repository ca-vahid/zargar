import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { cashText } from "../lib/brokerage";
import { estimateFees } from "../lib/fees";
import { fmtCcy, fmtMoney } from "../lib/format";
import { currencyForSymbol } from "../lib/symbols";
import { useQuote, useStore, type OrderIntentBody } from "../store";
import { AccountSelect, type AccountOption } from "./AccountSelect";
import { ConfirmOrderDialog } from "./ConfirmOrderDialog";
import { IconChevron } from "./icons";

export function OrderTicket({
  symbol,
  collapsed = false,
  onToggleCollapse,
}: {
  symbol: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const quote = useQuote(symbol);
  const allPortfolios = useStore((s) => s.portfolios);
  const portfolios = useMemo(
    () => allPortfolios.filter((p) => p.kind !== "shadow"), [allPortfolios]);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);
  const defaultQty = useStore((s) => Number(s.settings["trading.default_qty"] ?? 10));
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const brokerages = useStore((s) => s.brokerages);
  const toast = useStore((s) => s.toast);

  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState<string>(String(defaultQty));
  const [orderType, setOrderType] = useState("MKT");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [tif, setTif] = useState("DAY");
  const [portfolioId, setPortfolioId] = useState<string>("");
  const ticketPid = useStore((s) => s.ticketPortfolioId);
  const clearTicketPortfolio = useStore((s) => s.clearTicketPortfolio);
  useEffect(() => {
    // one-shot preselect from navigation (e.g. clicking a position row)
    if (ticketPid) {
      setPortfolioId(ticketPid);
      clearTicketPortfolio();
    }
  }, [ticketPid, clearTicketPortfolio]);
  const [bracketOn, setBracketOn] = useState(false);
  const [tpPct, setTpPct] = useState("5");
  const [slPct, setSlPct] = useState("2");
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<OrderIntentBody | null>(null);
  const [riskFails, setRiskFails] = useState<{ name: string; detail: string }[]>([]);

  const realPortfolios = useMemo(
    () => portfolios.filter((p) => p.kind === "live" || p.kind === "paper"), [portfolios]);
  const practicePortfolios = useMemo(
    () => portfolios.filter((p) => p.kind === "sim"), [portfolios]);

  // default account follows the mode: practice mode -> practice portfolio,
  // live mode -> last-used real account (falls back sensibly)
  const modeDefault = useMemo(() => {
    if (mode === "live") {
      const last = localStorage.getItem("zargar_last_real_pid");
      if (last && realPortfolios.some((p) => p.id === last)) return last;
      return realPortfolios[0]?.id;
    }
    const def = practicePortfolios.find((p) => p.id === defaultPid);
    return (def ?? practicePortfolios[0])?.id;
  }, [mode, realPortfolios, practicePortfolios, defaultPid]);

  const pid = portfolioId || modeDefault || defaultPid || portfolios[0]?.id || "";
  const portfolio = portfolios.find((p) => p.id === pid);
  const needsLimit = orderType === "LMT" || orderType === "STP_LMT";
  const needsStop = orderType === "STP" || orderType === "STP_LMT";

  // brokerage account/provider behind this portfolio (SnapTrade venues)
  const { account, provider } = useMemo(() => {
    for (const prov of brokerages?.providers ?? []) {
      const acct = prov.accounts.find((a) => a.portfolioId === pid);
      if (acct) return { account: acct, provider: prov };
    }
    return { account: undefined, provider: undefined };
  }, [brokerages, pid]);
  const readOnlyVenue = provider !== undefined && (provider.type !== "trade" || provider.disabled);

  const estPrice = useMemo(() => {
    if (needsLimit && limitPrice) return parseFloat(limitPrice);
    if (!quote) return null;
    return side === "BUY" ? quote.ask : quote.bid;
  }, [quote, side, needsLimit, limitPrice]);
  const estCost = estPrice !== null && qty ? estPrice * parseFloat(qty || "0") : null;
  const tradeCcy = currencyForSymbol(symbol); // the currency the order settles in
  const accountCcy = account?.currency ?? portfolio?.baseCurrency ?? "USD";
  const settings = useStore((s) => s.settings);
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);

  const fees = useMemo(() => estimateFees({
    institution: provider?.broker ?? null,
    account: account ?? null,
    accountCurrency: accountCcy,
    symbol, side, notional: estCost, settings,
  }), [provider?.broker, account, accountCcy, symbol, side, estCost, settings]);

  const toAccountCcy = (amount: number): number | null => {
    if (tradeCcy === accountCcy) return amount;
    if (!usdCad || usdCad <= 0) return null;
    if (tradeCcy === "USD" && accountCcy === "CAD") return amount * usdCad;
    if (tradeCcy === "CAD" && accountCcy === "USD") return amount / usdCad;
    return null;
  };

  const [impact, setImpact] = useState<{
    estimatedCommission?: number; forexFees?: number;
    remainingCash?: number | null; remainingCashCurrency?: string | null;
    error?: string;
  } | null>(null);
  const [impactBusy, setImpactBusy] = useState(false);
  useEffect(() => setImpact(null), [symbol, side, qty, pid, orderType, limitPrice]);
  const checkImpact = async () => {
    setImpactBusy(true);
    try {
      setImpact(await api.orderImpact({
        portfolio_id: pid, symbol, side, qty: parseFloat(qty),
        order_type: orderType,
        limit_price: needsLimit && limitPrice ? parseFloat(limitPrice) : null,
      }));
    } catch (e: any) {
      toast("error", `impact check: ${e.message}`);
    } finally {
      setImpactBusy(false);
    }
  };

  const accountOptions: AccountOption[] = useMemo(() => {
    const map = new Map<string, { account: any; provider: any }>();
    for (const prov of brokerages?.providers ?? []) {
      for (const acct of prov.accounts) map.set(acct.portfolioId, { account: acct, provider: prov });
    }
    return [...realPortfolios, ...practicePortfolios].map((p) => ({
      portfolio: p,
      account: map.get(p.id)?.account,
      provider: map.get(p.id)?.provider,
    }));
  }, [brokerages, realPortfolios, practicePortfolios]);

  const buildIntent = (): OrderIntentBody => ({
    portfolio_id: pid,
    symbol,
    side,
    qty: parseFloat(qty),
    order_type: orderType,
    limit_price: needsLimit && limitPrice ? parseFloat(limitPrice) : null,
    stop_price: needsStop && stopPrice ? parseFloat(stopPrice) : null,
    tif,
    dry_run: dryRun,
    bracket: bracketOn
      ? { take_profit_pct: parseFloat(tpPct) || null, stop_loss_pct: parseFloat(slPct) || null }
      : null,
  });

  const handleResult = (order: any) => {
    if (portfolio && (portfolio.kind === "live" || portfolio.kind === "paper")
        && !["REJECTED", "REJECTED_RISK"].includes(order.status)) {
      localStorage.setItem("zargar_last_real_pid", portfolio.id);
    }
    if (order.status === "REJECTED_RISK" || order.status === "REJECTED") {
      toast("error", `Order rejected: ${order.rejectReason ?? "risk check failed"}`);
      const checks = order?.risk?.checks ?? [];
      setRiskFails(checks.filter((c: any) => !c.passed));
    } else if (order.status === "DRY_RUN") {
      toast("info",
        `Dry run OK — would ${side} ${qty} ${symbol}` +
        (order.estimatedPrice ? ` @ ~${fmtMoney(order.estimatedPrice)}` : ""));
    } else {
      toast("success", `${side} ${qty} ${symbol} submitted`);
    }
  };

  const submit = async () => {
    setRiskFails([]);
    const intent = buildIntent();
    // Real-money accounts get a confirm dialog with a risk pre-flight;
    // sim/paper/dry-run stay instant.
    if (!dryRun && portfolio?.kind === "live") {
      setConfirming(intent);
      return;
    }
    setBusy(true);
    try {
      handleResult(await api.placeOrder(intent));
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  if (collapsed) {
    return (
      <div className="panel ticket-area ticket-rail">
        <button className="ticket-rail-btn" onClick={onToggleCollapse}
          aria-label="Expand order ticket" title="Expand order ticket">
          <IconChevron size={12} style={{ transform: "rotate(180deg)" }} />
          <span className="ticket-rail-label">Order ticket</span>
        </button>
      </div>
    );
  }

  return (
    <div className="panel ticket-area">
      <div className="panel-head">
        Order ticket
        <span className={`status-pill ${mode === "live" ? "bad" : "dim"}`}>{mode}</span>
        {onToggleCollapse && (
          <button className="icon-btn" style={{ marginLeft: "auto" }}
            onClick={onToggleCollapse} aria-label="Collapse order ticket"
            title="Collapse order ticket">
            <IconChevron size={12} />
          </button>
        )}
      </div>
      <div className="panel-body">
        <div className="side-toggle">
          <button className={`buy ${side === "BUY" ? "active" : ""}`} onClick={() => setSide("BUY")}>
            BUY
          </button>
          <button className={`sell ${side === "SELL" ? "active" : ""}`} onClick={() => setSide("SELL")}>
            SELL
          </button>
        </div>

        <div className="row2">
          <label className="field">
            <span>Quantity</span>
            <input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
          <label className="field">
            <span>Type</span>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              <option value="MKT">Market</option>
              <option value="LMT">Limit</option>
              <option value="STP">Stop</option>
              <option value="STP_LMT">Stop limit</option>
            </select>
          </label>
        </div>

        {(needsLimit || needsStop) && (
          <div className="row2">
            {needsLimit && (
              <label className="field">
                <span>Limit price</span>
                <input type="number" step="0.01" value={limitPrice}
                  placeholder={quote ? fmtMoney(side === "BUY" ? quote.ask : quote.bid) : ""}
                  onChange={(e) => setLimitPrice(e.target.value)} />
              </label>
            )}
            {needsStop && (
              <label className="field">
                <span>Stop price</span>
                <input type="number" step="0.01" value={stopPrice}
                  onChange={(e) => setStopPrice(e.target.value)} />
              </label>
            )}
          </div>
        )}

        <label className="field">
          <span>Account</span>
          <AccountSelect options={accountOptions} value={pid}
            onChange={(id) => setPortfolioId(id)} />
        </label>
        <div className="row2">
          <label className="field">
            <span>Time in force</span>
            <select value={tif} onChange={(e) => setTif(e.target.value)}>
              <option>DAY</option>
              <option>GTC</option>
              <option>IOC</option>
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
          <input type="checkbox" checked={bracketOn} onChange={(e) => setBracketOn(e.target.checked)} />
          <span className="track" />
          <span>Bracket (take-profit + stop-loss)</span>
        </label>
        {bracketOn && (
          <div className="row2">
            <label className="field">
              <span>Take profit %</span>
              <input type="number" step="0.5" value={tpPct} onChange={(e) => setTpPct(e.target.value)} />
            </label>
            <label className="field">
              <span>Stop loss %</span>
              <input type="number" step="0.5" value={slPct} onChange={(e) => setSlPct(e.target.value)} />
            </label>
          </div>
        )}

        <label className="switch" style={{ marginBottom: 8 }}>
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          <span className="track" />
          <span>Dry run (validate only, never route)</span>
        </label>

        <div className="fees-block">
          <div className="fee-row">
            <span>est. {side === "BUY" ? "cost" : "proceeds"}</span>
            <span className="v">{estCost ? fmtCcy(estCost, tradeCcy) : "—"}</span>
          </div>
          <div className="fee-row">
            <span title={fees.commissionNote}>commission (est.)</span>
            <span className="v">
              {fees.commission > 0 ? fmtCcy(fees.commission, tradeCcy) : "$0"}
            </span>
          </div>
          {fees.needsFx && (
            <div className={`fx-note ${fees.fxCoveredByWallet ? "ok" : "warn"}`}>
              {fees.fxCoveredByWallet ? (
                <>✓ {tradeCcy} trade from a {accountCcy} account — your {tradeCcy} wallet
                  ({fmtCcy(fees.walletCash ?? 0, tradeCcy)}) covers it, no conversion needed.</>
              ) : (
                <>
                  <b>{tradeCcy} trade from a {accountCcy} account.</b>{" "}
                  {fees.walletCash !== null && fees.walletCash > 0.004 && (
                    <>Wallet has {fmtCcy(fees.walletCash, tradeCcy)} — not enough. </>
                  )}
                  Broker auto-converts at ~{fees.fxPct}%
                  {fees.fxFee !== null && estCost !== null && (
                    <> (≈ {fmtCcy(fees.fxFee, tradeCcy)}
                    {toAccountCcy(estCost + fees.commission + fees.fxFee) !== null &&
                      <>; total ≈ {fmtCcy(toAccountCcy(estCost + fees.commission + fees.fxFee)!, accountCcy)}</>}
                    )</>
                  )}.
                  {" "}Cheaper options: pre-convert in the broker app at a moment you
                  choose, or keep a {tradeCcy} cash balance for {tradeCcy} trades.
                </>
              )}
            </div>
          )}
          {account && !dryRun && (
            <div className="fee-row">
              <button className="link-btn" onClick={checkImpact} disabled={impactBusy}
                title="Asks the broker (via SnapTrade) for the exact commission and FX fees — read-only, nothing is reserved">
                {impactBusy ? "checking with broker…" : "verify exact fees with broker"}
              </button>
              {impact && (impact.error ? (
                /rate limit/i.test(impact.error) ? (
                  <span className="v muted"
                    title="The brokerage throttles third-party checks (Wealthsimple especially) — this is on their side, not yours.">
                    broker busy — retry in a minute
                  </span>
                ) : (
                  <span className="v neg" title="The broker's own verdict on this order">
                    broker: {impact.error}
                  </span>
                )
              ) : (
                <span className="v"
                  title="The broker's own live numbers — computed against their real-time wallet, so they can differ slightly from the synced balances shown above.">
                  fees {fmtCcy(impact.estimatedCommission ?? 0, tradeCcy)}
                  {(impact.forexFees ?? 0) > 0 && <> · FX {fmtCcy(impact.forexFees!, tradeCcy)}</>}
                  {impact.remainingCash != null && (
                    <> · cash after {fmtCcy(impact.remainingCash,
                      impact.remainingCashCurrency ?? accountCcy)}</>
                  )}
                </span>
              ))}
            </div>
          )}
          {!quote && <div className="metric-sub">waiting for quote…</div>}
        </div>

        <button className={`submit-btn ${side.toLowerCase()}`}
          disabled={busy || !quote || !pid || readOnlyVenue}
          onClick={submit}>
          {dryRun ? "VALIDATE " : ""}{side} {qty || "?"} {symbol}
        </button>
        {readOnlyVenue && (
          <div className="metric-sub" style={{ marginTop: 6 }}>
            {provider?.disabled
              ? "this brokerage connection is disconnected — re-authorize it first"
              : "read-only connection — upgrade it to trade access to submit orders"}
          </div>
        )}

        {riskFails.length > 0 && (
          <div style={{ marginTop: 10 }}>
            {riskFails.map((c) => (
              <div key={c.name} className="check-item fail" style={{ marginBottom: 4 }}>
                {c.detail || c.name}
              </div>
            ))}
          </div>
        )}
      </div>

      {confirming && portfolio && (
        <ConfirmOrderDialog
          intent={confirming}
          portfolio={portfolio}
          account={account}
          provider={provider}
          estCost={estCost}
          onSubmitted={(order) => { setConfirming(null); handleResult(order); }}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  );
}
