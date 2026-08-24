// Ready-made symbol bundles for the validation picker — liquid US names with
// listed options and real 1-minute volume (CBOE chains are US-only, so no .TO/.V).
// Curated by sector / theme; overlap between bundles is fine (the picker dedupes).
export interface SymbolBundle { key: string; label: string; hint: string; symbols: string[] }

export const SYMBOL_BUNDLES: SymbolBundle[] = [
  { key: "b-index", label: "Index & sector ETFs", hint: "the broad tape and its sectors",
    symbols: ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SMH", "XBI", "KRE", "XOP", "GDX", "TLT", "HYG", "GLD", "SLV", "USO", "UVXY", "ARKK", "TQQQ", "SQQQ", "SOXL"] },
  { key: "b-mega", label: "Mega-cap tech", hint: "the Magnificent 7 and friends",
    symbols: ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "NFLX", "ORCL", "CRM", "ADBE", "CSCO", "IBM"] },
  { key: "b-semis", label: "Semiconductors", hint: "chips, equipment, memory",
    symbols: ["NVDA", "AMD", "AVGO", "MU", "INTC", "QCOM", "TSM", "ARM", "MRVL", "AMAT", "LRCX", "KLAC", "ASML", "TXN", "ON", "SMCI", "MCHP", "ADI", "NXPI", "WDC"] },
  { key: "b-software", label: "Software & cloud", hint: "SaaS, security, data",
    symbols: ["CRM", "NOW", "ADBE", "ORCL", "PLTR", "SNOW", "CRWD", "PANW", "ZS", "NET", "DDOG", "MDB", "SHOP", "WDAY", "INTU", "TEAM", "OKTA", "TWLO", "DOCU", "ZM"] },
  { key: "b-fintech", label: "Fintech & crypto", hint: "payments, brokers, crypto proxies",
    symbols: ["COIN", "HOOD", "SOFI", "PYPL", "XYZ", "AFRM", "UPST", "MSTR", "MARA", "RIOT", "CLSK", "BITO", "IBIT", "V", "MA", "AXP"] },
  { key: "b-banks", label: "Banks & financials", hint: "money-center banks, brokers, insurers",
    symbols: ["JPM", "BAC", "GS", "C", "WFC", "MS", "SCHW", "BLK", "BRK-B", "USB", "PNC", "TFC", "COF", "AIG", "MET", "KRE"] },
  { key: "b-energy", label: "Energy & materials", hint: "oil, gas, gold, steel, chemicals",
    symbols: ["XOM", "CVX", "OXY", "COP", "SLB", "HAL", "DVN", "EOG", "MPC", "VLO", "FCX", "NEM", "GOLD", "CLF", "X", "NUE", "AA", "DOW", "LIN"] },
  { key: "b-retail", label: "Retail & consumer", hint: "big box, apparel, restaurants, staples",
    symbols: ["WMT", "COST", "TGT", "HD", "LOW", "AMZN", "NKE", "LULU", "SBUX", "MCD", "CMG", "DG", "DLTR", "KO", "PEP", "PG", "PM", "MO", "EL", "TJX"] },
  { key: "b-health", label: "Healthcare & pharma", hint: "pharma, biotech, devices, insurers",
    symbols: ["LLY", "NVO", "UNH", "JNJ", "PFE", "MRK", "ABBV", "AMGN", "GILD", "MRNA", "BMY", "CVS", "ISRG", "TMO", "ABT", "HIMS", "VRTX", "REGN"] },
  { key: "b-industrial", label: "Industrials & defense", hint: "aerospace, machinery, transport",
    symbols: ["BA", "CAT", "DE", "GE", "HON", "LMT", "RTX", "NOC", "GD", "UPS", "FDX", "UNP", "CSX", "MMM", "ETN", "URI", "WM", "DAL", "UAL", "AAL"] },
  { key: "b-autos", label: "Autos & EV", hint: "makers, suppliers, EV plays",
    symbols: ["TSLA", "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI", "TM", "STLA", "APTV", "QS", "CHPT", "PLUG"] },
  { key: "b-china", label: "China ADRs", hint: "US-listed Chinese names",
    symbols: ["BABA", "PDD", "JD", "BIDU", "NIO", "XPEV", "LI", "BILI", "TCOM", "NTES", "FXI", "KWEB", "YINN"] },
  { key: "b-media", label: "Media & telecom", hint: "streaming, ads, carriers",
    symbols: ["NFLX", "DIS", "WBD", "PARA", "CMCSA", "T", "VZ", "TMUS", "SPOT", "RBLX", "SNAP", "PINS", "TTD", "EA", "TTWO"] },
  { key: "b-travel", label: "Travel & leisure", hint: "airlines, hotels, cruises, gaming",
    symbols: ["UBER", "ABNB", "BKNG", "MAR", "HLT", "CCL", "RCL", "NCLH", "DAL", "UAL", "AAL", "LUV", "LVS", "WYNN", "MGM", "DKNG", "EXPE"] },
  { key: "b-momentum", label: "High-beta movers", hint: "names that move a lot intraday (wide R, wide risk)",
    symbols: ["TSLA", "NVDA", "AMD", "COIN", "MSTR", "PLTR", "SMCI", "ARM", "HOOD", "SOFI", "RIVN", "NIO", "MARA", "RIOT", "AFRM", "UPST", "CVNA", "GME", "AMC", "IONQ", "RKLB", "ASTS", "NU", "SOUN"] },
  { key: "b-steady", label: "Steady large caps", hint: "slow, liquid — good for testing level respect",
    symbols: ["KO", "PEP", "PG", "JNJ", "MCD", "WMT", "HD", "VZ", "T", "IBM", "MMM", "CAT", "HON", "UNP", "XOM", "CVX", "JPM", "BRK-B"] },
];
