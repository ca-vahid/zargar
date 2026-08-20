import type { ReactNode } from "react";
import type { AsyncState } from "../lib/useAsync";
import { IconWarn } from "./icons";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="state-note" role="status" aria-label={label ?? "Loading"}>
      <span className="spinner" />
      {label}
    </span>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-note error" role="alert">
      <IconWarn />
      <span>{message}</span>
      {onRetry && <button className="link-btn" onClick={onRetry}>retry</button>}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
  art = true,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  art?: boolean;
}) {
  return (
    <div className="empty-state">
      {art && <img className="empty-art" src="/art/empty-medallion.png" alt="" aria-hidden="true" />}
      <div className="title">{title}</div>
      {hint && <div className="hint">{hint}</div>}
      {action && <div style={{ marginTop: 8 }}>{action}</div>}
    </div>
  );
}

/** Wraps an async fetch: spinner while loading, error with retry, empty state. */
export function AsyncSection<T>({
  state,
  empty,
  isEmpty,
  children,
}: {
  state: AsyncState<T>;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (state.loading && state.data === undefined) return <Spinner />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return null;
  const emptyCheck = isEmpty
    ? isEmpty(state.data)
    : Array.isArray(state.data) && state.data.length === 0;
  if (emptyCheck && empty) return <>{empty}</>;
  return <>{children(state.data)}</>;
}

const STATUS_PILL: Record<string, string> = {
  FILLED: "ok",
  PARTIALLY_FILLED: "wait",
  SUBMITTED: "wait",
  ACCEPTED: "wait",
  NEW: "wait",
  DRY_RUN: "dim",
  CANCELLED: "dim",
  EXPIRED: "dim",
  REJECTED: "bad",
  REJECTED_RISK: "bad",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`status-pill ${STATUS_PILL[status] ?? "dim"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
