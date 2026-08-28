// The Flow page (docs/techniques/flow/UI-PLAN.md): Reads desk (Option A + C's
// evidence) with the Symbol Story drill-in, and the Morning Brief tab.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BriefTab } from "../components/flow/BriefTab";
import { DayStrip } from "../components/flow/DayStrip";
import { EvidenceBadges, ReadsTable, ScoreCell } from "../components/flow/ReadsTable";
import { ReadDetail } from "../components/flow/ReadDetail";
import { SymbolStory } from "../components/flow/SymbolStory";
import { fmtOcc, fmtPrem, topFlag } from "../components/flow/lib";
import { Sheet } from "../components/Sheet";
import { EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useStore } from "../store";
import { useViewport } from "../lib/viewport";
import type { FlowBrief, FlowDaySummary, FlowReadItem, FlowStory } from "../types";

type Tab = "reads" | "brief";

export function FlowPage() {
  const toast = useStore((s) => s.toast);
  const quotes = useStore((s) => s.quotes);
  const [tab, setTab] = useState<Tab>("reads");
  const [days, setDays] = useState<FlowDaySummary[]>([]);
  const [day, setDay] = useState<string | null>(null);
  const [reads, setReads] = useState<FlowReadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [story, setStory] = useState<FlowStory | null>(null);
  const [storyOpen, setStoryOpen] = useState(false);
  const [brief, setBrief] = useState<FlowBrief | null>(null);
  const [scanning, setScanning] = useState(false);
  const pickedOnce = useRef(false);
  const { isPhone } = useViewport();
  const [sheetOpen, setSheetOpen] = useState(false);

  // hand-off from elsewhere (the Tips page's flow chip): honor it once
  const focusSym = useStore((s) => s.flowFocusSymbol);
  const setFlowFocus = useStore((s) => s.setFlowFocus);
  useEffect(() => {
    if (!focusSym) return;
    setSelected(focusSym);
    pickedOnce.current = true;
    if (isPhone) setSheetOpen(true);
    setFlowFocus(null);
  }, [focusSym, setFlowFocus, isPhone]);

  const refreshDays = useCallback(async () => {
    try {
      const d = await api.flowDays(8);
      setDays(d);
      setDay((cur) => cur ?? (d.length ? d[0].day : null));
    } catch { /* engine warming up */ }
  }, []);
  useEffect(() => { refreshDays(); }, [refreshDays]);

  useEffect(() => {
    if (!day) { setLoading(false); return; }
    let dead = false;
    setLoading(true);
    api.flowReads(day).then((r) => {
      if (dead) return;
      setReads(r);
      setLoading(false);
      if (!pickedOnce.current && r.length) {
        pickedOnce.current = true;
        const best = r.slice().sort((a, b) => b.score - a.score)[0];
        setSelected(best.symbol);
      }
    }).catch(() => !dead && setLoading(false));
    return () => { dead = true; };
  }, [day]);

  // the selected symbol's story feeds the detail sparkline AND the drill-in
  useEffect(() => {
    if (!selected) { setStory(null); return; }
    let dead = false;
    api.flowSymbol(selected).then((s) => !dead && setStory(s)).catch(() => !dead && setStory(null));
    return () => { dead = true; };
  }, [selected, day]);

  useEffect(() => {
    if (tab !== "brief") return;
    let dead = false;
    api.flowBrief(day ?? undefined).then((b) => !dead && setBrief(b)).catch(() => undefined);
    return () => { dead = true; };
  }, [tab, day]);

  // keyboard: walk the flagged reads like the Armed page
  const flagged = useMemo(() => reads.filter((r) => r.score > 0).sort((a, b) => b.score - a.score || a.symbol.localeCompare(b.symbol)), [reads]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || flagged.length < 2) return;
      const i = Math.max(0, flagged.findIndex((r) => r.symbol === selected));
      setSelected(flagged[(i + (e.key === "ArrowRight" ? 1 : flagged.length - 1)) % flagged.length].symbol);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [flagged, selected]);

  const scanNow = async () => {
    setScanning(true);
    try {
      const out = await api.flowScan();
      toast("success", `Scanned ${out.scanned} symbols — ${out.flagged} flagged`);
      pickedOnce.current = false;
      setDay(null);
      await refreshDays();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setScanning(false);
    }
  };

  const daySummary = days.find((d) => d.day === day) ?? null;
  const selectedRead = reads.find((r) => r.symbol === selected) ?? null;
  const lastOf = (sym: string) => {
    const q = quotes[sym];
    if (q && q.last > 0) return q.last;
    const r = reads.find((x) => x.symbol === sym);   // scan-time spot as the fallback
    return r?.spot && r.spot > 0 ? r.spot : undefined;
  };
  const quoteMap = useMemo(() => Object.fromEntries(reads.map((r) => [r.symbol, lastOf(r.symbol)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [reads, quotes]);

  return (
    <div className="flow-page">
      <div className="flow-head">
        <h2 className="page-title">Flow</h2>
        <span className="muted flow-head-sub">daily unusual-options-activity scan · context, never orders</span>
        <span style={{ flex: 1 }} />
        <div className="tabs" role="tablist">
          {days.slice(0, isPhone ? 3 : 5).map((d) => (
            <button key={d.day} role="tab" aria-selected={d.day === day} className={d.day === day ? "active" : ""}
              onClick={() => { setDay(d.day); pickedOnce.current = false; }}>
              {d.day.slice(5)}
            </button>
          ))}
        </div>
        <div className="tabs" role="tablist" style={{ marginLeft: 10 }}>
          <button role="tab" aria-selected={tab === "reads"} className={tab === "reads" ? "active" : ""} onClick={() => setTab("reads")}>Reads</button>
          <button role="tab" aria-selected={tab === "brief"} className={tab === "brief" ? "active" : ""} onClick={() => setTab("brief")}>Brief</button>
        </div>
        <button className="ghost-btn" disabled={scanning} onClick={scanNow}>{scanning ? "Scanning…" : "Scan now"}</button>
      </div>

      {tab === "brief" ? (
        <BriefTab brief={brief} onScanNow={scanNow} scanning={scanning} />
      ) : loading && reads.length === 0 ? (
        <Spinner />
      ) : days.length === 0 ? (
        <EmptyState title="No scans yet"
          hint="The nightly scan runs at 16:45 ET after the chain snapshots — or run one now with the button above." />
      ) : isPhone ? (
        <>
          <DayStrip d={daySummary} />
          <div className="bl-cards">
            {flagged.map((r) => {
              const f = topFlag(r);
              return (
                <button key={r.symbol} type="button" className="bl-card"
                  onClick={() => { setSelected(r.symbol); setStoryOpen(false); setSheetOpen(true); }}>
                  <span className="bl-card-l">
                    <span className="bl-card-sym">{r.symbol} <ScoreCell score={r.score} lean={r.lean} /></span>
                    <span className="bl-card-sub">
                      {f ? `${fmtOcc(f.contract)} · ${fmtPrem(f.premium)} · V/OI ${f.volOi.toFixed(1)}` : "no flags"}
                    </span>
                    <span className="bl-card-sub"><EvidenceBadges r={r} compact /></span>
                  </span>
                </button>
              );
            })}
            {flagged.length === 0 && <EmptyState title="Nothing flagged" hint="Only routine options activity this day." />}
          </div>
          {sheetOpen && selectedRead && (
            <Sheet title={storyOpen ? `${selectedRead.symbol} — the story` : `${selectedRead.symbol} flow read`}
              onClose={() => { setSheetOpen(false); setStoryOpen(false); }} full>
              {storyOpen && story
                ? <SymbolStory story={story} onBack={() => setStoryOpen(false)} />
                : <ReadDetail read={selectedRead} story={story} last={lastOf(selectedRead.symbol)}
                    onStory={() => setStoryOpen(true)} />}
            </Sheet>
          )}
        </>
      ) : storyOpen && story ? (
        <SymbolStory story={story} onBack={() => setStoryOpen(false)} />
      ) : (
        <>
          <DayStrip d={daySummary} />
          <div className="flow-split">
            <ReadsTable reads={reads} selected={selected} quotes={quoteMap}
              onSelect={(sym) => setSelected(sym)}
              onStory={(sym) => { setSelected(sym); setStoryOpen(true); }} />
            {selectedRead
              ? <ReadDetail read={selectedRead} story={story} last={lastOf(selectedRead.symbol)}
                  onStory={() => setStoryOpen(true)} />
              : <div className="panel flow-detail"><div className="empty">Select a read</div></div>}
          </div>
        </>
      )}
    </div>
  );
}
