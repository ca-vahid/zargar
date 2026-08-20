import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtCcy, fmtMoney } from "../lib/format";
import type { OrderIntentBody } from "../store";
import type { BrokerageAccount, BrokerageProvider, Portfolio } from "../types";
import { IconWarn } from "./icons";
import { Modal } from "./Modal";
import { Spinner } from "./ui";

interface RiskCheck { name: string; passed: boolean; detail: string }

/** Pre-flights the order as a dry run, shows the risk verdict, then submits. */
export function ConfirmOrderDialog({
  intent,
  portfolio,
  account,
  provider,
  estCost,
  onSubmitted,
  onCancel,
}: {
  intent: OrderIntentBody;
  portfolio: Portfolio;
  account?: BrokerageAccount;
  provider?: BrokerageProvider;
  estCost: number | null;
  onSubmitted: (order: any) => void;
  onCancel: () => void;
}) {
  const [checks, setChecks] = useState<RiskCheck[] | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [preflightRejected, setPreflightRejected] = useState(false);
  const [estimated, setEstimated] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // one pre-flight per dialog
    ran.current = true;
    api.placeOrder({ ...intent, dry_run: true }).then(
      (order) => {
        setChecks(order?.risk?.checks ?? []);
        setEstimated(order?.estimatedPrice ?? null);
        setPreflightRejected(order.status === "REJECTED_RISK" || order.status === "REJECTED");
      },
      (err) => setPreflightError(err instanceof Error ? err.message : String(err)),
    );
  }, [intent]);

  const confirm = async () => {
    setSubmitting(true);
    try {
      const order = await api.placeOrder(intent);
      onSubmitted(order);
    } catch (err: any) {
      setPreflightError(err.message);
      setSubmitting(false);
    }
  };

  const currency = account?.currency ?? portfolio.baseCurrency ?? "USD";
  const failed = (checks ?? []).filter((c) => !c.passed);
  const checking = checks === null && !preflightError;
  const sideClass = intent.side === "BUY" ? "buy" : "sell";
  const cost = estCost ?? (estimated !== null ? estimated * intent.qty : null);

  return (
    <Modal
      title="Confirm real-money order"
      onClose={onCancel}
      footer={
        <>
          <button className="ghost-btn" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            className={`submit-btn ${sideClass}`}
            style={{ width: "auto", padding: "8px 18px" }}
            disabled={checking || preflightRejected || submitting}
            onClick={confirm}
          >
            {submitting ? "Submitting…" : `${intent.side} ${intent.qty} ${intent.symbol}`}
          </button>
        </>
      }
    >
      <div className="confirm-headline">
        {intent.side} {intent.qty} {intent.symbol} · {intent.order_type}
        {intent.limit_price ? ` @ ${fmtMoney(intent.limit_price)}` : ""} · {intent.tif ?? "DAY"}
      </div>
      <div className="confirm-line">
        <span className="k">Account</span>
        <span>
          {portfolio.name} <span className="ccy-chip">{currency}</span>
          {provider && (
            <span className={`status-pill ${provider.type === "trade" ? "ok" : "bad"}`}
              style={{ marginLeft: 6 }}>
              {provider.disabled ? "disconnected" : provider.type}
            </span>
          )}
        </span>
      </div>
      <div className="confirm-line">
        <span className="k">Est. {intent.side === "BUY" ? "cost" : "proceeds"}</span>
        <span className="v">{cost !== null ? fmtCcy(cost, currency) : "—"}</span>
      </div>
      <div style={{ marginTop: 10 }}>
        {checking && <Spinner label="running risk checks…" />}
        {preflightError && (
          <div className="state-note" style={{ justifyContent: "flex-start", padding: "6px 0" }}>
            <IconWarn />
            <span>pre-flight unavailable ({preflightError}) — the server re-checks on submit</span>
          </div>
        )}
        {checks !== null && (
          <div className="check-grid">
            {checks.map((c) => (
              <span key={c.name} className={`check-item ${c.passed ? "ok" : "fail"}`}
                title={c.detail || c.name}>
                {c.passed ? c.name : c.detail || c.name}
              </span>
            ))}
          </div>
        )}
        {preflightRejected && failed.length > 0 && (
          <div className="state-note error" style={{ padding: "6px 0" }}>
            <IconWarn />
            <span>risk gate would reject this order — fix the checks above</span>
          </div>
        )}
      </div>
      <div className="metric-sub" style={{ marginTop: 8 }}>
        Prices can move between this check and the submit — the server re-runs
        every risk check on the real order.
      </div>
    </Modal>
  );
}
