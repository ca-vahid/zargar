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

/** reject/breakdown triggers are the short side — always expressed with a put. */
const isPut = (kind: string) => kind === "reject" || kind === "breakdown";

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
  const [showAllStopped, setShowAllStopped] = useState(false);
  const [showAllTl, setShowAllTl] = useState(false);
  const toast = useStore((s) => s.toast);
  const armedRef = useStore((s) => s.techniqueArmed);
  const halt = useStore((s) => s.halt);
  const focusId = useStore((s) => s.armedFocusRunId);
  const clearFocus = useStore((s) => s.clearArmedFocus);
  const alerts = useStore((s) => s.alerts);
  useEffect(() => { if (focusId) { setOpenRun(focusId); clearFocus(); } }, [focusId, clearFocus]);
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

      {/* recent alerts (persist beyond the 6s toast) */}
      {alerts.length > 0 && (
        <div className="now-card now-timeline">
          <div className="now-h" style={{ margin: "4px 6px 2px" }}>Alerts</div>
          {alerts.slice(0, 5).map((a, i) => (
            <button type="button" key={i} className={`now-tl ${a.level === "critical" ? "neg" : "warn"}`}
              onClick={() => a.runId && setOpenRun(a.runId)}>
              <span className="now-tl-t">{hhmm(a.ts)}</span>
              <span className="now-tl-ic" aria-hidden="true">⚠</span>
              <span className="now-tl-txt" style={{ gridColumn: "3 / -1", whiteSpace: "normal" }}>{a.text}</span>
            </button>
          ))}
        </div>
      )}

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
              {t.remaining}{t.instrument === "options" ? " contract(s)" : " sh"} of {t.filledQty} left · in at {fmt(t.entry)}
              {" · paid "}{fmt(t.entry * t.filledQty * (t.multiplier ?? (t.instrument === "options" ? 100 : 1)))}
              {" · fired "}{hhmm(t.firedTs)}{t.trimsDone ? ` · ${t.trimsDone} trim(s)` : ""}
            </div>
          </button>
        );
      })}

      {/* before the session: the simplified runway — what tomorrow holds, nearest first */}
      {sum.window === "extended" && sum.watching.length > 0 && sum.inTrade.length === 0 && (() => {
        const puts = sum.watching.filter((w) => isPut(w.nearest.kind)).length;
        return (
          <div className="now-card now-next">
            <div className="now-card-head">
              <span className="now-tag">next session</span>
              <span className="now-next-txt">{sum.watching.length} plan{sum.watching.length === 1 ? "" : "s"} · {sum.watching.length - puts} calls · {puts} puts · closest first below</span>
            </div>
            <div className="now-next-note">Plans fire only in the 9:30–10:30 and 2:45–4:00 ET windows; a gap through a level at the open voids it.</div>
          </div>
        );
      })()}

      {/* armed snapshot: one visual card per plan, closest to firing first */}
      {sum.watching.length > 0 && <div className="now-h">Armed · {sum.watching.length}</div>}
      {sum.watching.map((w) => {
        const n = w.nearest;
        const short = n.direction === "short" || isPut(n.kind);
        const tp1 = n.targets && n.targets.length ? n.targets[0] : null;
        const span = [n.stop, n.entry, ...(tp1 != null ? [tp1] : [])];
        const lo = Math.min(...span), hi = Math.max(...span);
        const posPct = (v: number) => (hi > lo ? Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100)) : 50);
        const px = w.lastPrice;
        const d = n.distancePct;
        const size = w.size?.contracts != null ? `${w.size.contracts} contract${w.size.contracts === 1 ? "" : "s"}`
          : w.size?.qty != null ? `${w.size.qty} sh`
          : w.size?.riskPct != null ? `${w.size.riskPct}% risk` : "";
        const L = short ? { v: tp1, cls: "pos", t: "tp1" } : { v: n.stop, cls: "neg", t: "stop" };
        const R = short ? { v: n.stop, cls: "neg", t: "stop" } : { v: tp1, cls: "pos", t: "tp1" };
        return (
          <button type="button" key={`w-${w.runId}`}
            className={`now-card now-watch ${w.stale ? "stale" : ""} ${w.status === "paused" ? "paused" : ""}`}
            onClick={() => setOpenRun(w.runId)}>
            <div className="now-card-head">
              <span className="now-sym">{w.symbol}</span>
              {w.grade ? <span className={`tq-grade g${w.grade}`}>{w.grade}</span> : null}
              <span className={`now-side ${short ? "put" : "call"}`}>{short ? "put" : "call"}</span>
              {w.triggers > 1 && <span className="now-tag">{w.triggers} trg</span>}
              {w.status === "paused" && <span className="now-tag warn">paused</span>}
              {w.stale && <span className="now-tag bad">stale</span>}
              {size && <span className="now-size">{size}</span>}
              <span className={`now-row-mode ${w.mode === "auto" ? (live ? "neg" : "pos") : ""}`}>{w.mode}</span>
            </div>
            <div className="now-watch-line">
              {n.kind.replace(/_/g, " ")} @ <b>{fmt(n.entry)}</b>
              {px != null && <> · now <b>{fmt(px)}</b></>}
              {d != null && (
                <span className={Math.abs(d) < 0.35 ? "now-close" : "muted"}>
                  {" "}· level {Math.abs(d).toFixed(2)}% {d > 0 ? "above" : "below"}
                </span>
              )}
            </div>
            <div className={`now-meter ${short ? "now-meter--short" : ""}`} aria-hidden="true">
              <span className="now-meter-tick" style={{ left: `${posPct(n.entry)}%` }} />
              {px != null && <span className={`now-meter-dot ${px < lo || px > hi ? "now-meter-dot--out" : ""}`} style={{ left: `${posPct(px)}%` }} />}
            </div>
            <div className="now-meter-lbl">
              <span className={L.cls}>{L.v != null ? `${L.t} ${fmt(L.v)}` : ""}</span>
              <span>entry {fmt(n.entry)}</span>
              <span className={R.cls}>{R.v != null ? `${R.t} ${fmt(R.v)}` : ""}</span>
            </div>
          </button>
        );
      })}

      {/* today's activity — after the snapshot, collapsed to the recent few */}
      {sum.timeline.length > 0 && <div className="now-h">Today's activity</div>}
      {sum.timeline.length > 0 && (
        <div className="now-card now-timeline">
          {sum.timeline.slice(0, showAllTl ? 100 : 8).map((e, i) => (
            <button type="button" key={i} className={`now-tl ${KIND_CLS[e.kind] ?? ""}`} onClick={() => setOpenRun(e.runId)}>
              <span className="now-tl-t">{hhmm(e.ts)}</span>
              <span className="now-tl-ic" aria-hidden="true">{KIND_ICON[e.kind] ?? "·"}</span>
              <span className="now-tl-sym">{e.symbol}</span>
              <span className="now-tl-txt">{e.text || e.kind.replace(/_/g, " ")}</span>
              {e.pnl != null && <span className={`now-tl-pnl ${pnlCls(e.pnl)}`}>{e.pnl > 0 ? "+" : ""}{fmt(e.pnl)}</span>}
            </button>
          ))}
          {sum.timeline.length > 8 && !showAllTl && (
            <button type="button" className="now-btn wide" onClick={() => setShowAllTl(true)}>
              show all {sum.timeline.length} events
            </button>
          )}
        </div>
      )}

      {/* stopped today */}
      {sum.stoppedToday.length > 0 && <div className="now-h">Stopped today · {sum.stoppedToday.length}</div>}
      {(showAllStopped ? sum.stoppedToday : sum.stoppedToday.slice(0, 5)).map((s) => (
        <div key={`st-${s.runId}`} className="now-row now-row--stopped">
          <span className="now-row-sym">{s.symbol}</span>
          <span className="now-row-mid"><span className="now-row-txt">{s.reason}</span></span>
          {s.realizedPnl != null && <span className={`now-row-mode ${pnlCls(s.realizedPnl)}`}>{s.realizedPnl > 0 ? "+" : ""}{fmt(s.realizedPnl)}</span>}
        </div>
      ))}

      {sum.stoppedToday.length > 5 && !showAllStopped && (
        <button type="button" className="now-btn wide" onClick={() => setShowAllStopped(true)}>
          show all {sum.stoppedToday.length} stopped plans
        </button>
      )}

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
