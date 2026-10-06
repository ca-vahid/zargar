import { useCallback } from "react";

import { api } from "./api";
import { fmtCcy } from "./format";
import { makeRate } from "./liveEquity";
import { useStore } from "../store";

/** The ONE currency every money total on the Portfolios page and the top-bar real-money chip is shown in
 *  (`ui.display_currency`, 2026-10-05: accounts in CAD and USD side by side read as a confusing switch).
 *  Per-share prices stay in the stock's own trading currency; native cash per currency stays visible. */
export type DisplayCcy = "CAD" | "USD";

export function useDisplayCurrency(): [DisplayCcy, (c: DisplayCcy) => void] {
  const raw = useStore((s) => s.settings["ui.display_currency"]);
  const ccy: DisplayCcy = String(raw ?? "CAD").toUpperCase() === "USD" ? "USD" : "CAD";
  const set = useCallback((c: DisplayCcy) => {
    const st = useStore.getState();
    st.setSettings({ ...st.settings, "ui.display_currency": c });
    api.patchSettings({ "ui.display_currency": c }).catch((e) => st.toast("error", e.message));
  }, []);
  return [ccy, set];
}

/** amount in `from` -> the display currency; null when the USD/CAD rate is not known yet (never a silent 1:1). */
export function useToDisplay(): (amount: number, from: string | null | undefined) => number | null {
  const [ccy] = useDisplayCurrency();
  const usdCad = useStore((s) => s.quotes["USDCAD=X"]?.last);
  return useCallback((amount: number, from: string | null | undefined) => {
    const r = makeRate(usdCad)((from || "USD").toUpperCase(), ccy);
    return r == null ? null : amount * r;
  }, [usdCad, ccy]);
}

/** Format in the display currency; without a rate, fall back to the native amount (labelled by its own currency). */
export function useFmtDisplay(): (amount: number, from: string | null | undefined) => string {
  const [ccy] = useDisplayCurrency();
  const to = useToDisplay();
  return useCallback((amount: number, from: string | null | undefined) => {
    const v = to(amount, from);
    return v == null ? fmtCcy(amount, (from || "USD").toUpperCase()) : fmtCcy(v, ccy);
  }, [to, ccy]);
}
