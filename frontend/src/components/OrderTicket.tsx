import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtMoney, fmtUsd } from "../lib/format";
import { useQuote, useStore } from "../store";

export function OrderTicket({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const allPortfolios = useStore((s) => s.portfolios);
  const portfolios = useMemo(
    () => allPortfolios.filter((p) => p.kind !== "shadow"), [allPortfolios]);
  const defaultPid = useStore((s) => s.settings["trading.default_portfolio"]);
  const defaultQty = useStore((s) => Number(s.settings["trading.default_qty"] ?? 10));
  const mode = useStore((s) => s.settings["trading.mode"] ?? "sim");
  const toast = useStore((s) => s.toast);

  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState<string>(String(defaultQty));
  const [orderType, setOrderType] = useState("MKT");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [tif, setTif] = useState("DAY");
  const [portfolioId, setPortfolioId] = useState<string>("");
  const [bracketOn, setBracketOn] = useState(false);
  const [tpPct, setTpPct] = useState("5");
  const [slPct, setSlPct] = useState("2");
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [riskFails, setRiskFails] = useState<{ name: string; detail: string }[]>([]);

  const pid = portfolioId || defaultPid || portfolios[0]?.id || "";
  const needsLimit = orderType === "LMT" || orderType === "STP_LMT";
  const needsStop = orderType === "STP" || orderType === "STP_LMT";

  const estPrice = useMemo(() => {
    if (needsLimit && limitPrice) return parseFloat(limitPrice);
    if (!quote) return null;
    return side === "BUY" ? quote.ask : quote.bid;
  }, [quote, side, needsLimit, limitPrice]);
  const estCost = estPrice !== null && qty ? estPrice * parseFloat(qty || "0") : null;

  const submit = async () => {
    setBusy(true);
    setRiskFails([]);
    try {
      const order = await api.placeOrder({
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
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel ticket-area">
      <div className="panel-head">
        Order ticket <span className="sub">{mode === "dry_run" ? "dry-run mode" : mode}</span>
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
            <span>Portfolio</span>
            <select value={pid} onChange={(e) => setPortfolioId(e.target.value)}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
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
            ? `est. ${side === "BUY" ? "cost" : "proceeds"}: ${estCost ? fmtUsd(estCost) : "—"}`
            : "waiting for quote…"}
        </div>

        <button className={`submit-btn ${side.toLowerCase()}`} disabled={busy || !quote || !pid}
          onClick={submit}>
          {dryRun ? "VALIDATE " : ""}{side} {qty || "?"} {symbol}
        </button>

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
    </div>
  );
}
