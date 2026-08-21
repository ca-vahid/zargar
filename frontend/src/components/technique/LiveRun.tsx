import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store";
import type { ChatLive, TechniqueRun } from "../../types";
import { Spinner } from "../ui";
import { IconCheck, IconX } from "../icons";

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

  const passes = live?.passes ?? [];
  const current = passes.find((p) => p.status === "running");
  return (
    <div className="panel tq-live">
      <div className="panel-head">
        <Spinner /> Analysing {run.symbol} · {run.primaryTf}
        <span className="sub">{run.llm?.model} · effort {run.llm?.effort} · thinking {run.llm?.thinkingDisplay}</span>
        <button className="link-btn danger" style={{ marginLeft: "auto" }} onClick={cancel}>cancel</button>
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
              <button className="link-btn" onClick={() => setOpenThink((v) => !v)}>
                {openThink ? "▾" : "▸"} thinking {current ? `(${passLabel(current.name)})` : ""}
              </button>
            </div>
            {openThink && (
              <div className="tq-think" ref={thinkRef}>
                {(current?.thinking || live?.thinking) || <span className="muted">…</span>}
              </div>
            )}
            {(current?.text || live?.text) && (
              <>
                <div className="tq-stream-head muted">structured output (streaming)</div>
                <pre className="tq-text-stream">{current?.text || live?.text}</pre>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
