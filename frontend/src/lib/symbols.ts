const CAD_SUFFIXES = [".TO", ".V", ".NE", ".CN"];

/** Trading currency inferred from the symbol's suffix (mirrors backend fx.py). */
export function currencyForSymbol(symbol: string): string {
  const s = symbol.toUpperCase();
  return CAD_SUFFIXES.some((suf) => s.endsWith(suf)) ? "CAD" : "USD";
}
