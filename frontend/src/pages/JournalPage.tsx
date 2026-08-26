import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useStore } from "../store";
import { useViewport } from "../lib/viewport";
import type { JournalEvent } from "../types";

const GROUPS: Record<string, string[]> = {
  all: [],
  orders: ["OrderIntentCreated", "OrderSubmitted", "OrderAccepted", "OrderFill", "OrderFilled",
    "OrderCancelled", "OrderRejected", "OrderDryRun", "OrderExpired"],
  risk: ["RiskCheckPassed", "RiskCheckFailed", "KillSwitchEngaged", "KillSwitchReleased",
    "DailyLossHalt", "DailyDriftWarning"],
  signals: ["ContentReceived", "SignalExtracted", "SignalVerified", "SignalVerificationFailed",
    "ProposalCreated", "ProposalApproved", "ProposalRejected", "ProposalExpired"],
  broker: ["BrokerConnected", "BrokerDisconnected", "BrokerSync", "BrokerSyncMismatch",
    "PositionReconciled", "BrokerOrderLinked", "BrokerSubmitUnknown", "BrokerageAccountLinked"],
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
  const requestedGroup = useStore((s) => s.journalGroup);
  const clearJournalGroup = useStore((s) => s.clearJournalGroup);
  const loadedState = useAsync(
    () => api.get<JournalEvent[]>("/api/events?limit=300"), []);
  const loaded = loadedState.data ?? [];
  const [group, setGroup] = useState(
    requestedGroup && requestedGroup in GROUPS ? requestedGroup : "all");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    if (requestedGroup) {
      if (requestedGroup in GROUPS) setGroup(requestedGroup);
      clearJournalGroup();
    }
  }, [requestedGroup, clearJournalGroup]);

  const { isPhone } = useViewport();
  const [shown, setShown] = useState(50);
  const merged = useMemo(() => {
    const all = [...liveEvents];
    for (const e of loaded) if (!all.some((x) => x.id === e.id)) all.push(e);
    all.sort((a, b) => b.id - a.id);
    let out = all;
    if (group !== "all") out = out.filter((e) => GROUPS[group].includes(e.type));
    if (typeFilter) out = out.filter((e) =>
      e.type.toLowerCase().includes(typeFilter.toLowerCase()) ||
      (e.aggregateId ?? "").toLowerCase().startsWith(typeFilter.toLowerCase()) ||
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
          <input type="text" placeholder="filter…" value={typeFilter} className="journal-filter"
            onChange={(e) => setTypeFilter(e.target.value)}
            style={{ marginLeft: "auto", width: 180 }} />
        </div>
        <div className="scroll-x">
          {loadedState.loading && merged.length === 0 ? (
            <Spinner />
          ) : loadedState.error && merged.length === 0 ? (
            <ErrorState message={loadedState.error} onRetry={loadedState.reload} />
          ) : merged.length === 0 ? (
            <EmptyState title="No events yet"
              hint="Every decision the engine makes lands here." />
          ) : isPhone ? (
            <div className="jr-list">
              {merged.slice(0, shown).map((e) => (
                <div key={e.id} className="jr-row">
                  <div className="jr-head">
                    <span className={`status-pill ${
                      e.type.includes("Failed") || e.type.includes("Rejected") || e.type.includes("Halt") ? "bad"
                      : e.type.includes("Filled") || e.type.includes("Verified") || e.type.includes("Approved") ? "ok"
                      : "dim"}`}>{e.type}</span>
                    <span className="jr-time">{fmtDateTime(e.ts)}</span>
                  </div>
                  <div className="jr-detail">{summarize(e)}</div>
                  {e.aggregateType && (
                    <button className="link-btn jr-agg" onClick={() => setTypeFilter((e.aggregateId ?? "").slice(0, 8))}>
                      <code className="mono">{e.aggregateType}:{(e.aggregateId ?? "").slice(0, 8)}</code>
                    </button>
                  )}
                </div>
              ))}
              {merged.length > shown && (
                <button type="button" className="ghost-btn jr-more" onClick={() => setShown((n) => n + 50)}>
                  show more ({merged.length - shown} left)
                </button>
              )}
            </div>
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
                      {e.aggregateType && (
                        <button className="link-btn" title="Filter to this aggregate"
                          onClick={() => setTypeFilter((e.aggregateId ?? "").slice(0, 8))}>
                          <code className="mono">{e.aggregateType}:{(e.aggregateId ?? "").slice(0, 8)}</code>
                        </button>
                      )}
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
