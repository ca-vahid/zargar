import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store";
import { absoluteUrl } from "../../lib/routing";
import { useStickyScroll } from "../../lib/useStickyScroll";
import type { ChatLive, TechniqueRun } from "../../types";
import { Spinner } from "../ui";
import { IconCheck, IconX } from "../icons";
import { Collapse } from "../Collapse";
import { CopyChip } from "../CopyChip";
import { StreamingOutput } from "./StreamingOutput";

const PASS_LABEL: Record<string, string> = {
  context: "1 · Context (higher TF)",
  pattern: "2 · Pattern (mid TF)",
  entry: "3 · Entry (primary TF)",
  critic: "4 · Critic (kill it?)",
  image_entry: "Image analysis",
};

function passLabel(name: string) {
  if (PASS_LABEL[name]) return PASS_LABEL[name];
  if (name.startsWith("entry_retry")) return `3 · Entry retry ${name.replace("entry_retry", "")}`;
  return name;
}

/** Streaming view of an in-flight run: passes, thinking, grounding. */
export function LiveRun({ run }: { run: TechniqueRun }) {
  const live: ChatLive | undefined = useStore((s) => (run.threadId ? s.chatLive[run.threadId] : undefined));
  const [openThink, setOpenThink] = useState(true);
  const thinkRef = useRef<HTMLDivElement>(null);
  const cancel = async () => { try { await fetch(`/api/technique/runs/${run.id}/cancel`, { method: "POST" }); } catch { /* ignore */ } };

  useEffect(() => {
    const el = thinkRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [live?.thinking, live?.text]);

  // Follow the run down the page, but only while the reader is at the bottom.
  useStickyScroll(Boolean(live?.active), [
    live?.thinking?.length, live?.text?.length, live?.passes.length, live?.grounding?.attempt,
  ]);

  const passes = live?.passes ?? [];
  const current = passes.find((p) => p.status === "running");
  return (
    <div className="panel tq-live">
      <div className="panel-head">
        <Spinner /> Analysing {run.symbol} · {run.primaryTf}
        <span className="sub">{run.llm?.model} · effort {run.llm?.effort} · thinking {run.llm?.thinkingDisplay}</span>
        <span className="tq-head-right">
          <CopyChip value={run.id}
            link={absoluteUrl({ page: "technique", techniqueTab: "analyse", runId: run.id })} />
          <button className="link-btn danger" onClick={cancel}>cancel</button>
        </span>
      </div>
      <div className="panel-body">
        {live?.facts && (
          <div className="tq-live-facts muted">
            facts ready · key levels {live.facts.keyLevels?.slice(0, 5).map((l: any) => `${l.price.toFixed(2)}×${l.touches}`).join(", ")}
            {live.facts.volume ? ` · volume ${live.facts.volume.relativeToTimeOfDayAvg}× baseline` : ""}
          </div>
        )}
        <ol className="tq-pass-list">
          {passes.map((p) => (
            <li key={p.name} className={p.status}>
              <span className="tq-pass-dot">{p.status === "done" ? <IconCheck size={10} /> : <Spinner />}</span>
              <span className="tq-pass-name">{passLabel(p.name)}</span>
              {p.status === "done" && <span className="muted">{p.seconds}s · {p.usage?.output} tok</span>}
            </li>
          ))}
          {passes.length === 0 && <li className="running"><Spinner /> preparing bars, levels and chart images…</li>}
        </ol>
        {live?.grounding && (
          <div className={`tq-ground ${live.grounding.passed ? "ok" : "bad"}`}>
            {live.grounding.passed ? <IconCheck size={11} /> : <IconX size={11} />}
            grounding {live.grounding.passed ? "passed" : "failed"} (attempt {live.grounding.attempt})
            {!live.grounding.passed && <span className="muted"> — {live.grounding.checks.filter((c) => !c.passed).map((c) => c.name).join(", ")}</span>}
          </div>
        )}
        {(current || live?.thinking || live?.text) && (
          <div className="tq-stream">
            <div className="tq-stream-head">
              <button className="link-btn" onClick={() => setOpenThink((v) => !v)} aria-expanded={openThink}>
                <span className={`disclosure-chev ${openThink ? "open" : ""}`} aria-hidden="true">
                  <svg width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3l6 5-6 5" /></svg>
                </span> thinking {current ? `(${passLabel(current.name)})` : ""}
              </button>
            </div>
            <Collapse open={openThink}>
              <div className="tq-think" ref={thinkRef}>
                {(current?.thinking || live?.thinking) || <span className="muted">…</span>}
              </div>
            </Collapse>
            {(current?.text || live?.text) && (
              <>
                <div className="tq-stream-head muted">analysis taking shape</div>
                <div className="tq-text-stream">
                  <StreamingOutput text={current?.text || live?.text || ""} streaming />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
