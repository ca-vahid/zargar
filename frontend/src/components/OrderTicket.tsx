import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtMoney } from "../lib/format";
import { useQuote, useStore, type OrderIntentBody } from "../store";
import { ConfirmOrderDialog } from "./ConfirmOrderDialog";

export function OrderTicket({ symbol }: { symbol: string }) {
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
  const currency = account?.currency ?? portfolio?.baseCurrency ?? "USD";

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

  return (
    <div className="panel ticket-area">
      <div className="panel-head">
        Order ticket
        <span className={`status-pill ${mode === "live" ? "bad" : "dim"}`}>{mode}</span>
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

        <div className="row2">
          <label className="field">
            <span>Account</span>
            <select value={pid} onChange={(e) => setPortfolioId(e.target.value)}>
              {realPortfolios.length > 0 && (
                <optgroup label="Real accounts">
                  {realPortfolios.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.baseCurrency ? ` (${p.baseCurrency})` : ""}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Practice">
                {practicePortfolios.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </optgroup>
            </select>
          </label>
          <label className="field">
            <span>Time in force</span>
            <select value={tif} onChange={(e) => setTif(e.target.value)}>
              <option>DAY</option>
              <option>GTC</option>
              <option>IOC</option>
            </select>
          </label>
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

        <div className="est-line">
          {quote
            ? `est. ${side === "BUY" ? "cost" : "proceeds"}: ${estCost ? fmtCcy(estCost, currency) : "—"}`
            : "waiting for quote…"}
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
