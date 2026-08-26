import { Sheet } from "../Sheet";
import type { ChartSession, ChartType, ChartView, Indicator } from "../StockChart";

export interface RangeDef { key: string; label: string; tfs: string[]; def: string }

/** Phone chart settings: everything the desktop toolbar shows in one row,
 * with the *reasons* for disabled choices written out instead of tooltips. */
export function ChartSettingsSheet({
  onClose, chartType, setChartType, tf, setTf, rangeDef, tfs, indicators, toggleIndicator,
  indicatorDefs, view, setView, session, setSession, hasArmed,
}: {
  onClose: () => void;
  chartType: ChartType; setChartType: (t: ChartType) => void;
  tf: string; setTf: (t: string) => void; rangeDef: RangeDef; tfs: string[];
  indicators: Indicator[]; toggleIndicator: (k: Indicator) => void;
  indicatorDefs: { key: Indicator; label: string }[];
  view: ChartView; setView: (v: ChartView) => void;
  session: ChartSession; setSession: (s: ChartSession) => void;
  hasArmed: boolean;
}) {
  return (
    <Sheet title="Chart settings" onClose={onClose}>
      <div className="cs-group">
        <div className="cs-label">Style</div>
        <div className="seg cs-seg" role="group" aria-label="Chart style">
          {(["candlestick", "line"] as ChartType[]).map((t) => (
            <button key={t} type="button" className={chartType === t ? "on" : ""} onClick={() => setChartType(t)}>
              {t === "candlestick" ? "Candles" : "Line"}
            </button>
          ))}
        </div>
      </div>
      <div className="cs-group">
        <div className="cs-label">Bars <small>for the {rangeDef.label} range</small></div>
        <div className="cs-chips">
          {tfs.map((t) => {
            const ok = rangeDef.tfs.includes(t);
            return (
              <button key={t} type="button" className={`chip-btn ${tf === t ? "active" : ""}`} disabled={!ok}
                onClick={() => setTf(t)}>{t}</button>
            );
          })}
        </div>
        {tfs.some((t) => !rangeDef.tfs.includes(t)) && (
          <div className="cs-hint">Greyed bars aren't available for {rangeDef.label} — Yahoo only keeps 1-minute history ~7 days, 5/15-minute ~60 days, hourly ~2 years.</div>
        )}
      </div>
      <div className="cs-group">
        <div className="cs-label">Indicators</div>
        <div className="cs-chips">
          {indicatorDefs.map((i) => (
            <button key={i.key} type="button" className={`chip-btn ${indicators.includes(i.key) ? "active" : ""}`}
              onClick={() => toggleIndicator(i.key)}>{i.label}</button>
          ))}
        </div>
        {chartType === "line" && <div className="cs-hint">Indicators draw on candles only.</div>}
      </div>
      <div className="cs-group">
        <div className="cs-label">View</div>
        <div className="seg cs-seg" role="group" aria-label="Chart view">
          {(["candles", "zones", "panes"] as ChartView[]).map((v) => (
            <button key={v} type="button" className={view === v ? "on" : ""} disabled={v === "zones" && !hasArmed}
              onClick={() => setView(v)}>{v}</button>
          ))}
        </div>
        <div className="cs-hint">
          <b>candles</b> hollow candles with level labels · <b>zones</b> the armed plan's risk/reward bands{hasArmed ? "" : " (needs an armed plan on this symbol)"} · <b>panes</b> adds a P&L-vs-avg-cost pane when you hold a position.
        </div>
      </div>
      <div className="cs-group">
        <div className="cs-label">Session</div>
        <div className="seg cs-seg" role="group" aria-label="Session">
          <button type="button" className={session === "eth" ? "on" : ""} onClick={() => setSession("eth")}>Extended</button>
          <button type="button" className={session === "rth" ? "on" : ""} onClick={() => setSession("rth")}>Regular</button>
        </div>
        <div className="cs-hint">Extended shows pre-market and after-hours shaded; Regular is 9:30–16:00 ET only.</div>
      </div>
    </Sheet>
  );
}
