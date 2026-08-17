import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useStore } from "../store";
import type { JournalEvent } from "../types";

const GROUPS: Record<string, string[]> = {
  all: [],
  orders: ["OrderIntentCreated", "OrderSubmitted", "OrderAccepted", "OrderFill", "OrderFilled",
    "OrderCancelled", "OrderRejected", "OrderDryRun", "OrderExpired"],
  risk: ["RiskCheckPassed", "RiskCheckFailed", "KillSwitchEngaged", "KillSwitchReleased", "DailyLossHalt"],
  signals: ["ContentReceived", "SignalExtracted", "SignalVerified", "SignalVerificationFailed",
    "ProposalCreated", "ProposalApproved", "ProposalRejected", "ProposalExpired"],
  system: ["SettingChanged", "BrokerConnected", "BrokerDisconnected", "PositionUpdated"],
};

function summarize(e: JournalEvent): string {
  const p = e.payload || {};
  switch (e.type) {
    case "OrderIntentCreated": return `${p.side} ${p.qty} ${p.symbol} ${p.orderType}`;
    case "RiskCheckFailed":
      return (p.checks ?? []).filter((c: any) => !c.passed).map((c: any) => c.detail || c.name).join("; ");
    case "OrderFill": return `filled ${p.qty} @ ${p.price} (comm ${p.commission})`;
    case "OrderRejected": return p.reason ?? "";
    case "KillSwitchEngaged": return p.reason ?? "";
    case "SettingChanged": return `${p.key}: ${JSON.stringify(p.old)} → ${JSON.stringify(p.new)}`;
    case "SignalExtracted": return `${p.ticker} ${p.direction} (${p.confidence})${p.grounded ? "" : " — NOT grounded"}`;
    case "ContentReceived": return `${p.source ?? ""} ${p.subject ?? ""}`;
    case "PositionUpdated": return `${p.symbol} qty ${p.qty} avg ${p.avgCost}`;
    case "ProposalApproved": return `via ${p.via}${p.half ? " (half)" : ""}`;
    default: {
      const str = JSON.stringify(p);
      return str.length > 120 ? str.slice(0, 120) + "…" : str === "{}" ? "" : str;
    }
  }
}

export function JournalPage() {
  const liveEvents = useStore((s) => s.events);
  const [loaded, setLoaded] = useState<JournalEvent[]>([]);
  const [group, setGroup] = useState("all");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    api.get<JournalEvent[]>("/api/events?limit=300").then(setLoaded).catch(() => undefined);
  }, []);

  const merged = useMemo(() => {
    const all = [...liveEvents];
    for (const e of loaded) if (!all.some((x) => x.id === e.id)) all.push(e);
    all.sort((a, b) => b.id - a.id);
    let out = all;
    if (group !== "all") out = out.filter((e) => GROUPS[group].includes(e.type));
    if (typeFilter) out = out.filter((e) =>
      e.type.toLowerCase().includes(typeFilter.toLowerCase()) ||
      summarize(e).toLowerCase().includes(typeFilter.toLowerCase()));
    return out.slice(0, 300);
  }, [liveEvents, loaded, group, typeFilter]);

  return (
    <div>
      <h2 className="page-title">Journal — the append-only audit trail</h2>
      <div className="panel">
        <div className="panel-head">
          <div className="tabs">
            {Object.keys(GROUPS).map((g) => (
              <button key={g} className={group === g ? "active" : ""} onClick={() => setGroup(g)}>
                {g[0].toUpperCase() + g.slice(1)}
              </button>
            ))}
          </div>
          <input type="text" placeholder="filter…" value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            style={{ marginLeft: "auto", width: 180 }} />
        </div>
        <div className="scroll-x">
          {merged.length === 0 ? (
            <div className="empty">No events</div>
          ) : (
            <table className="tbl">
              <thead>
                <tr><th>Time</th><th>Event</th><th>Detail</th><th>Aggregate</th></tr>
              </thead>
              <tbody>
                {merged.map((e) => (
                  <tr key={e.id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(e.ts)}</td>
                    <td>
                      <span className={`status-pill ${
                        e.type.includes("Failed") || e.type.includes("Rejected") || e.type.includes("Halt") ? "bad"
                        : e.type.includes("Filled") || e.type.includes("Verified") || e.type.includes("Approved") ? "ok"
                        : "dim"}`}>
                        {e.type}
                      </span>
                    </td>
                    <td style={{ whiteSpace: "normal", maxWidth: 520 }}>{summarize(e)}</td>
                    <td className="muted">
                      {e.aggregateType && <code className="mono">{e.aggregateType}:{(e.aggregateId ?? "").slice(0, 8)}</code>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
