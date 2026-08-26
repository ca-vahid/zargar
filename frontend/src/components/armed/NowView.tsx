import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { useStore } from "../../store";
import type { ArmedPlan, ArmedSummary } from "../../types";
import { Sheet } from "../Sheet";
import { ConfirmDialog } from "../Modal";
import { ArmedCard, fmt, pnlCls } from "../technique/ArmedTab";

/* The phone home. Answers, top to bottom: is anything wrong → am I in a trade →
   what fired today → what is still waiting → what died and why → how did today go.
   One column, cards, no tables. Polls the summary endpoint and re-pulls on any
   armed WS patch (debounced), so a fire shows up within seconds. */

const KIND_ICON: Record<string, string> = {
  fired: "⚡", entry_submit: "→", entry_working: "…", entry_rejected: "✗", fire_error: "✗",
  critic_killed: "🛑", critic_error: "⚠", position_open: "●", position_closed: "○",
  exit_submit: "↩", exit_fill: "✓", exit_failed: "‼", exit_retry: "↻", manual_exit: "✋",
  loss_halt: "🛑", paused: "⏸", resumed: "▶", disarmed: "⏹", skipped: "·", premium_stop: "🛑",
  quote_stop: "🛑", proposal: "?", contract_skipped: "·", kill_cap: "🛑", cooldown_skip: "·",
  halt_skip: "·", max_open_skip: "·", stale: "⚠", preopen_check: "☀", entry_fallback: "↪",
  entry_cancelled: "✗", fire_cancelled: "✗", rearmed_after_kill: "▶", option_pick_failed: "⚠",
  armed: "◆", adopted: "◆",
};
const KIND_CLS: Record<string, string> = {
  fired: "pos", position_open: "pos", exit_fill: "pos", resumed: "pos",
  entry_rejected: "neg", fire_error: "neg", critic_killed: "neg", exit_failed: "neg",
  loss_halt: "neg", premium_stop: "neg", quote_stop: "neg", kill_cap: "neg", disarmed: "neg",
  stale: "warn", critic_error: "warn", option_pick_failed: "warn", paused: "warn",
};

function hhmm(ts: number | null | undefined): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
}
function ago(ms: number): string {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m}m ago` : `${Math.round(m / 60)}h ago`;
}
const WINDOW_LABEL: Record<string, string> = {
  prime_open: "opening window · firing", prime_close: "closing window · firing",
  midday: "mid-day · watch only", extended: "market closed", pre: "pre-market",
};

export function NowView() {
  const [sum, setSum] = useState<ArmedSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [stopAll, setStopAll] = useState<null | "stop" | "flatten">(null);
  const [sellNow, setSellNow] = useState<{ runId: string; symbol: string } | null>(null);
  const toast = useStore((s) => s.toast);
  const armedRef = useStore((s) => s.techniqueArmed);
  const halt = useStore((s) => s.halt);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(async () => {
    try { setSum(await api.techniqueArmedSummary()); setErr(null); }
    catch (e: any) { setErr(e.message); }
  }, []);
  useEffect(() => { void refresh(); const id = setInterval(refresh, 20_000); return () => clearInterval(id); }, [refresh]);
  // any armed WS patch → re-pull (debounced) so fires / exits land within seconds
  const deb = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (deb.current) clearTimeout(deb.current);
    deb.current = setTimeout(() => { void refresh(); }, 1500);
    return () => { if (deb.current) clearTimeout(deb.current); };
  }, [armedRef, halt.engaged, refresh]);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 15_000); return () => clearInterval(id); }, []);
  void tick;

  const doStopAll = async (flatten: boolean) => {
    setStopAll(null);
    try { const r = await api.techniqueStopAll(flatten); toast("info", `Disarmed ${r.disarmed} plan(s)`); void refresh(); }
    catch (e: any) { toast("error", e.message); }
  };
  const doSellNow = async (runId: string) => {
    setSellNow(null);
    try { await api.techniqueArmedExit(runId, null); toast("info", "market exit sent"); void refresh(); }
    catch (e: any) { toast("error", e.message); }
  };

  if (!sum) {
    return <div className="now-empty">{err ? `couldn't load: ${err}` : "loading…"}</div>;
  }
  const c = sum.counts;
  const live = sum.workspace === "live";
  const nothing = !sum.attention.length && !sum.inTrade.length && !sum.watching.length
    && !sum.timeline.length && !sum.stoppedToday.length;

  return (
    <div className="now">
      {/* status strip */}
      <button type="button" className={`now-strip ${live ? "live" : ""} ${sum.haltEngaged ? "halted" : ""}`}
        onClick={() => setStopAll("stop")} aria-label="Fleet actions">
        <span className="now-strip-ws">{live ? "LIVE" : "PRACTICE"}</span>
        <span className="now-strip-txt">
          {c.armed + c.paused} armed · {c.inTrade} in trade{c.attention ? ` · ${c.attention} need attention` : ""}
          {c.paused ? ` · ${c.paused} paused` : ""}
        </span>
        <span className={`now-strip-halt ${sum.haltEngaged ? "on" : ""}`}>
          {sum.haltEngaged ? "KILL SWITCH ON" : WINDOW_LABEL[sum.window] ?? sum.window}
        </span>
        <span className="now-strip-age">{ago(sum.asOf)}</span>
      </button>

      {/* needs attention */}
      {sum.attention.map((a) => (
        <div key={`att-${a.runId}`} className="now-card now-card--attn">
          <div className="now-card-head">
            <span className="now-sym">{a.symbol}</span>
            <span className="now-tag bad">needs attention</span>
            <span className="now-acct">{a.account}</span>
          </div>
          <ul className="now-reasons">{a.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          <div className="now-actions">
            {a.hasPosition && (
              <button type="button" className="now-btn danger" onClick={() => setSellNow({ runId: a.runId, symbol: a.symbol })}>
                Sell now (market)
              </button>
            )}
            <button type="button" className="now-btn" onClick={() => setOpenRun(a.runId)}>Open plan</button>
          </div>
        </div>
      ))}

      {/* in trade */}
      {sum.inTrade.length > 0 && <div className="now-h">In trade</div>}
      {sum.inTrade.map((t) => {
        const up = (t.unrealizedPnl ?? 0) >= 0;
        const lo = Math.min(t.stop, t.entry), hi = Math.max(t.nextTarget ?? t.entry, t.entry);
        const px = t.lastPrice ?? t.entry;
        const pct = hi > lo ? Math.min(100, Math.max(0, ((px - lo) / (hi - lo)) * 100)) : 50;
        return (
          <button type="button" key={`tr-${t.runId}-${t.triggerId}`} className="now-card now-card--trade"
            onClick={() => setOpenRun(t.runId)}>
            <div className="now-card-head">
              <span className="now-sym">{t.symbol}</span>
              <span className={`now-tag ${t.direction === "short" ? "neg" : "pos"}`}>{t.kind}{t.direction === "short" ? " ↓" : ""}</span>
              <span className="now-acct">{t.instrument === "options" && t.contract?.symbol ? t.contract.symbol : `${t.remaining} sh`}</span>
            </div>
            <div className={`now-big ${up ? "pos" : "neg"}`}>
              {up ? "+" : "−"}{fmt(Math.abs(t.unrealizedPnl ?? 0))}
              <small>{t.unrealizedR != null ? ` ${t.unrealizedR >= 0 ? "+" : ""}${t.unrealizedR.toFixed(2)}R` : ""} unrealized</small>
            </div>
            <div className="now-meter" aria-hidden="true">
              <span className="now-meter-fill" style={{ width: `${pct}%` }} />
              <span className="now-meter-dot" style={{ left: `${pct}%` }} />
            </div>
            <div className="now-meter-lbl">
              <span className="neg">stop {fmt(t.stop)}</span>
              <span>now {fmt(px)}</span>
              <span className="pos">{t.nextTarget != null ? `target ${fmt(t.nextTarget)}` : "runner"}</span>
            </div>
            <div className="now-sub">
              {t.remaining}{t.instrument === "options" ? " contract(s)" : ""} left · in at {fmt(t.entry)} · fired {hhmm(t.firedTs)}
              {t.trimsDone ? ` · ${t.trimsDone} trim(s)` : ""}
            </div>
          </button>
        );
      })}

      {/* fired today */}
      {sum.timeline.length > 0 && <div className="now-h">Today</div>}
      {sum.timeline.length > 0 && (
        <div className="now-card now-timeline">
          {sum.timeline.slice(0, 40).map((e, i) => (
            <button type="button" key={i} className={`now-tl ${KIND_CLS[e.kind] ?? ""}`} onClick={() => setOpenRun(e.runId)}>
              <span className="now-tl-t">{hhmm(e.ts)}</span>
              <span className="now-tl-ic" aria-hidden="true">{KIND_ICON[e.kind] ?? "·"}</span>
              <span className="now-tl-sym">{e.symbol}</span>
              <span className="now-tl-txt">{e.text || e.kind.replace(/_/g, " ")}</span>
              {e.pnl != null && <span className={`now-tl-pnl ${pnlCls(e.pnl)}`}>{e.pnl > 0 ? "+" : ""}{fmt(e.pnl)}</span>}
            </button>
          ))}
        </div>
      )}

      {/* watching */}
      {sum.watching.length > 0 && <div className="now-h">Watching · {sum.watching.length}</div>}
      {sum.watching.map((w) => {
        const d = w.nearest.distancePct;
        const far = d == null ? 100 : Math.min(100, Math.abs(d) / 3 * 100);
        return (
          <button type="button" key={`w-${w.runId}`} className={`now-row ${w.stale ? "stale" : ""} ${w.status === "paused" ? "paused" : ""}`}
            onClick={() => setOpenRun(w.runId)}>
            <span className="now-row-sym">{w.symbol}{w.grade ? <span className={`tq-grade g${w.grade}`}>{w.grade}</span> : null}</span>
            <span className="now-row-mid">
              <span className="now-dist" aria-hidden="true"><span style={{ width: `${100 - far}%` }} /></span>
              <span className="now-row-txt">
                {w.nearest.kind} {fmt(w.nearest.entry)}{d != null ? ` · ${Math.abs(d).toFixed(2)}% ${d > 0 ? "above" : "below"}` : ""}
                {w.status === "paused" ? " · paused" : ""}{w.stale ? " · STALE" : ""}
              </span>
            </span>
            <span className={`now-row-mode ${w.mode === "auto" ? (live ? "neg" : "pos") : ""}`}>{w.mode}</span>
          </button>
        );
      })}

      {/* stopped today */}
      {sum.stoppedToday.length > 0 && <div className="now-h">Stopped today</div>}
      {sum.stoppedToday.map((s) => (
        <div key={`st-${s.runId}`} className="now-row now-row--stopped">
          <span className="now-row-sym">{s.symbol}</span>
          <span className="now-row-mid"><span className="now-row-txt">{s.reason}</span></span>
          {s.realizedPnl != null && <span className={`now-row-mode ${pnlCls(s.realizedPnl)}`}>{s.realizedPnl > 0 ? "+" : ""}{fmt(s.realizedPnl)}</span>}
        </div>
      ))}

      {/* today P&L */}
      <div className="now-card now-pnl">
        <div className="now-pnl-row">
          <span><small>realized</small><b className={pnlCls(sum.pnl.realized)}>{sum.pnl.realized > 0 ? "+" : ""}{fmt(sum.pnl.realized)}</b></span>
          <span><small>unrealized</small><b className={pnlCls(sum.pnl.unrealized)}>{sum.pnl.unrealized > 0 ? "+" : ""}{fmt(sum.pnl.unrealized)}</b></span>
          <span><small>loss limit</small><b>{sum.pnl.lossLimit > 0 ? fmt(sum.pnl.lossLimit, 0) : "off"}</b></span>
        </div>
        {sum.pnl.lossLimit > 0 && (
          <div className="now-limit" aria-label={`${sum.pnl.lossLimitUsedPct ?? 0}% of the loss limit used`}>
            <span style={{ width: `${Math.min(100, sum.pnl.lossLimitUsedPct ?? 0)}%` }} className={(sum.pnl.lossLimitUsedPct ?? 0) > 70 ? "hot" : ""} />
          </div>
        )}
      </div>

      {nothing && (
        <div className="now-empty">
          Nothing armed in the {live ? "LIVE" : "practice"} workspace. Arm plans from Techniques → EM Options (desktop is best for that),
          and they'll show up here with what they're waiting for.
        </div>
      )}

      {/* plan sheet */}
      {openRun && <PlanSheet runId={openRun} onClose={() => setOpenRun(null)} onChanged={refresh} />}

      {/* fleet actions */}
      {stopAll && (
        <FleetSheet
          counts={c} onClose={() => setStopAll(null)}
          onStop={() => void doStopAll(false)} onFlatten={() => void doStopAll(true)} live={live} />
      )}
      {sellNow && (
        <ConfirmDialog
          title={`Sell ${sellNow.symbol} now?`}
          danger
          confirmLabel="Sell at market"
          body={<p style={{ margin: 0 }}>Sends a market exit for every open position of this plan{live ? " on your real account" : " (practice)"}. This can't be undone.</p>}
          onConfirm={() => void doSellNow(sellNow.runId)}
          onCancel={() => setSellNow(null)}
        />
      )}
    </div>
  );
}

function PlanSheet({ runId, onClose, onChanged }: { runId: string; onClose: () => void; onChanged: () => void }) {
  const [plan, setPlan] = useState<ArmedPlan | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api.techniqueArmedDetail(runId).then((p) => { setPlan(p); setErr(null); })
      .catch((e) => setErr(e.message));
  }, [runId]);
  useEffect(() => { load(); const id = setInterval(load, 15_000); return () => clearInterval(id); }, [load]);
  return (
    <Sheet title={plan ? `${plan.symbol} · ${plan.config.mode}` : "Plan"} onClose={onClose} full className="now-plan-sheet">
      {err && <div className="state-note error">{err}</div>}
      {!plan && !err && <div className="state-note">loading…</div>}
      {plan && (
        <>
          <div className="now-plan-summary">{plan.summary}</div>
          <ArmedCard a={plan} onChanged={() => { load(); onChanged(); }} />
        </>
      )}
    </Sheet>
  );
}

function FleetSheet({ counts, live, onClose, onStop, onFlatten }: {
  counts: ArmedSummary["counts"]; live: boolean; onClose: () => void; onStop: () => void; onFlatten: () => void;
}) {
  const [typed, setTyped] = useState("");
  const armed = counts.armed + counts.paused;
  return (
    <Sheet title="Fleet actions" onClose={onClose}>
      <p className="now-fleet-p">
        {armed} plan(s) armed · {counts.inTrade} in trade{live ? " · LIVE workspace — real money" : " · practice"}.
      </p>
      <button type="button" className="now-btn wide" disabled={!armed} onClick={onStop}>
        Stop all — disarm every plan, keep open positions
      </button>
      <div className="now-fleet-flatten">
        <label className="field">
          <span>Type FLATTEN to sell every open position at market and disarm all</span>
          <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoCapitalize="characters" autoComplete="off" />
        </label>
        <button type="button" className="now-btn danger wide" disabled={typed.trim().toUpperCase() !== "FLATTEN" || !counts.inTrade}
          onClick={onFlatten}>
          Flatten &amp; stop all
        </button>
      </div>
    </Sheet>
  );
}
