// The one action Flow offers: make a read a TIP (source: flow-scan) through
// the normal pipeline — both shadow books, dedupe, armable from the Tips page
// or by the morning shadow sweep. Shared by the desk detail and the story.
import { useState } from "react";
import { api } from "../../lib/api";
import { useStore } from "../../store";

export function SendToTipsButton({ symbol, lean }: { symbol: string; lean: string }) {
  const setPage = useStore((s) => s.setPage);
  const toast = useStore((s) => s.toast);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const directional = lean === "bull" || lean === "bear";
  const send = async () => {
    if (sent) { setPage("inbox"); return; }
    // a mixed/none read is refused — but SAY so, never eat the click (a
    // disabled-looking-normal button read as "broken", 2026-08-29)
    if (!directional) {
      toast("error", `${symbol}'s flow is ${lean.toUpperCase()} — calls and puts both heavy, no side to trade. Drill into the story to see both sides.`);
      return;
    }
    setSending(true);
    try {
      const out = await api.flowToTip(symbol);
      setSent(true);
      if (out?.queued) {
        toast("success", `${symbol} ${out.contract ?? ""} sent — the tip desk is appraising it now; Tips → Analyst shows the live run`);
      } else {
        const st = out?.signal?.status ?? "created";
        toast("success", `${symbol} sent to Tips (${String(st).replace("_", " ")}) — arm it there, or the morning sweep arms it in shadow`);
      }
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSending(false);
    }
  };
  return (
    <button className="primary-btn" disabled={sending}
      style={directional ? undefined : { opacity: 0.55 }}
      title={directional
        ? "Make this read a TIP (source: flow-scan): it enters both shadow books, can be armed at a level, and builds flow-scan's own track record — YOU are the judge, Flow is just the evidence"
        : "Two-sided or directionless flow — no side to trade (click for why)"}
      onClick={send}>
      {sending ? "Sending…" : sent ? "View in Tips →" : "Send to Tips"}
    </button>
  );
}
