/** OCC option symbology (mirrors backend zargar/options/occ.py).
 * Canonical form is the unpadded OCC symbol, e.g. F260828C00014500. */

export interface OccInfo {
  symbol: string;        // canonical, unpadded
  underlying: string;
  expiry: string;        // ISO date
  right: "C" | "P";
  optionType: "call" | "put";
  strike: number;
  dte: number;           // days to expiry vs today (local date)
  display: string;       // "F 28 Aug 26 14.5 C"
  short: string;         // "F 14.5C 8/28"
}

const RE = /^([A-Z]{1,6})(\d{6})([CP])(\d{8})$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtStrike(strike: number): string {
  return Number.isInteger(strike) ? String(strike) : String(Number(strike.toFixed(3)));
}

export function parseOcc(symbol: string | null | undefined): OccInfo | null {
  if (!symbol) return null;
  const s = symbol.trim().toUpperCase().replace(/\s+/g, "");
  const m = RE.exec(s);
  if (!m) return null;
  const yy = Number(m[2].slice(0, 2)), mm = Number(m[2].slice(2, 4)), dd = Number(m[2].slice(4, 6));
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return null;
  const right = m[3] as "C" | "P";
  const strike = Number(m[4]) / 1000;
  const expiryDate = new Date(2000 + yy, mm - 1, dd);
  if (expiryDate.getMonth() !== mm - 1) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dte = Math.round((expiryDate.getTime() - today.getTime()) / 86_400_000);
  const expiry = `${2000 + yy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  return {
    symbol: s,
    underlying: m[1],
    expiry,
    right,
    optionType: right === "C" ? "call" : "put",
    strike,
    dte,
    display: `${m[1]} ${dd} ${MONTHS[mm - 1]} ${String(yy).padStart(2, "0")} ${fmtStrike(strike)} ${right}`,
    short: `${m[1]} ${fmtStrike(strike)}${right} ${mm}/${dd}`,
  };
}

export function isOcc(symbol: string | null | undefined): boolean {
  return parseOcc(symbol) !== null;
}

/** Human label for any symbol: OCC contracts read as "F 28 Aug 26 14.5 C", stocks as-is. */
export function symbolLabel(symbol: string): string {
  return parseOcc(symbol)?.display ?? symbol;
}

export function symbolShort(symbol: string): string {
  return parseOcc(symbol)?.short ?? symbol;
}

/** Position-keyed qty lookup helper for the derived open/close action. */
export function deriveOptionAction(side: "BUY" | "SELL", positionQty: number): string {
  if (side === "BUY") return positionQty < -1e-9 ? "BUY_TO_CLOSE" : "BUY_TO_OPEN";
  return positionQty > 1e-9 ? "SELL_TO_CLOSE" : "SELL_TO_OPEN";
}
