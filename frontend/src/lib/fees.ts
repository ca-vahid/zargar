import type { BrokerageAccount, Settings } from "../types";
import { currencyForSymbol } from "./symbols";

export interface FeeEstimate {
  commission: number;            // in the trade's currency
  commissionNote: string;
  needsFx: boolean;              // symbol currency != account currency
  fxPct: number;                 // broker auto-conversion markup, %
  fxFee: number | null;          // est. conversion cost in trade currency
  fxCoveredByWallet: boolean;    // account holds enough cash in the trade ccy
  walletCash: number | null;     // cash the account holds in the trade currency
}

/** Local, instant fee schedule — editable in Settings, broker-verifiable via
 * the impact endpoint. Sources: webull.ca pricing (C$2.99/order CAD, US$2.99
 * buy / US$3.00 sell US-listed, FX rate+1.5%); Wealthsimple self-directed
 * ($0 commission, ~1.5% FX on USD trades from CAD accounts). */
export function estimateFees(opts: {
  institution: string | null;   // "Webull Canada" | "Wealthsimple Trade" | ...
  account: BrokerageAccount | null; // null for practice/unknown
  accountCurrency: string;
  symbol: string;
  side: "BUY" | "SELL";
  notional: number | null;      // qty * price in the trade's currency
  settings: Settings;
}): FeeEstimate {
  const inst = (opts.institution ?? "").toLowerCase();
  const tradeCcy = currencyForSymbol(opts.symbol);
  const needsFx = tradeCcy !== opts.accountCurrency.toUpperCase();

  let commission = 0;
  let commissionNote = "commission-free equities";
  if (inst.includes("webull")) {
    commission = tradeCcy === "USD" ? (opts.side === "BUY" ? 2.99 : 3.0) : 2.99;
    commissionNote = `Webull flat ${tradeCcy === "USD" ? "US$" : "C$"}${commission.toFixed(2)}/order`;
  } else if (inst.includes("wealthsimple")) {
    commission = 0;
    commissionNote = "Wealthsimple $0 commission";
  } else if (!opts.institution) {
    commission = 0;
    commissionNote = "practice — simulated commission model";
  }

  const fxPct = inst.includes("webull")
    ? Number(opts.settings["fees.webull_fx_pct"] ?? 1.5)
    : inst.includes("wealthsimple")
      ? Number(opts.settings["fees.wealthsimple_fx_pct"] ?? 1.5)
      : Number(opts.settings["fees.default_fx_pct"] ?? 1.5);

  const walletCash = opts.account
    ? (opts.account.cashBalances ?? [])
        .filter((b) => b.currency.toUpperCase() === tradeCcy)
        .reduce((sum, b) => sum + b.cash, 0)
    : null;
  const fxCoveredByWallet =
    needsFx && opts.side === "BUY" && walletCash !== null && opts.notional !== null
      ? walletCash >= opts.notional + commission
      : false;
  const fxFee = needsFx && opts.notional !== null && !fxCoveredByWallet
    ? (opts.notional * fxPct) / 100
    : needsFx ? 0 : null;

  return { commission, commissionNote, needsFx, fxPct, fxFee, fxCoveredByWallet, walletCash };
}
