import { useEffect, useMemo, useRef, useState } from "react";
import { cashText } from "../lib/brokerage";
import { fmtCcy } from "../lib/format";
import { useStore } from "../store";
import type { BrokerageAccount, BrokerageProvider, Portfolio } from "../types";
import { BrokerIcon } from "./BrokerIcon";
import { useWorkspace, workspaceOf } from "../lib/workspace";
import { IconChevron } from "./icons";
import { Sheet } from "./Sheet";
import { useViewport } from "../lib/viewport";

export interface AccountOption {
  portfolio: Portfolio;
  account?: BrokerageAccount;
  provider?: BrokerageProvider;
}

function OptionRow({ opt }: { opt: AccountOption }) {
  const { portfolio: p, account, provider } = opt;
  // the seeded IBKR portfolio isn't a usable venue until the gateway connects
  const ibkrPending = !account && p.venue === "ibkr"
    && (p.kind === "live" || p.kind === "paper");
  const available = account
    ? cashText(account)
    : fmtCcy(p.cash, p.baseCurrency ?? "USD");
  return (
    <>
      {provider
        ? <BrokerIcon name={provider.broker} logoUrl={provider.logoUrl} size={18} />
        : <span className="acct-opt-dot" aria-hidden="true" />}
      <span className="acct-opt-main">
        <span className="acct-opt-name">{ibkrPending ? "IBKR" : p.name}</span>
        <span className="acct-opt-cash">
          {ibkrPending ? "not set up yet — account pending" : `available ${available}`}
        </span>
      </span>
      <span className="ccy-chip">{account?.currency ?? p.baseCurrency ?? "USD"}</span>
    </>
  );
}

const PROVIDER_ORDER = ["webull", "wealthsimple"]; // then everything else, IBKR last

function providerRank(opt: AccountOption): number {
  const name = opt.provider?.broker?.toLowerCase() ?? "";
  const idx = PROVIDER_ORDER.findIndex((p) => name.includes(p));
  if (idx >= 0) return idx;
  return opt.portfolio.venue === "ibkr" ? PROVIDER_ORDER.length + 1 : PROVIDER_ORDER.length;
}

/** Rich account picker: broker logo, name, currency, available cash. */
export function AccountSelect({
  options,
  value,
  onChange,
}: {
  options: AccountOption[];
  value: string;
  onChange: (pid: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { isPhone } = useViewport();
  const ws = useWorkspace();
  const scoped = useMemo(() => options.filter((o) => workspaceOf(o.portfolio.kind) === ws), [options, ws]);
  const isPending = (o: AccountOption) => !o.account && o.portfolio.venue === "ibkr"
    && (o.portfolio.kind === "live" || o.portfolio.kind === "paper");
  // keep the parent's selection inside the workspace
  useEffect(() => {
    if (!scoped.length) return;
    if (!scoped.some((o) => o.portfolio.id === value)) {
      const first = scoped.find((o) => !isPending(o)) ?? scoped[0];
      onChange(first.portfolio.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scoped, value]);
  const selected = scoped.find((o) => o.portfolio.id === value) ?? scoped[0] ?? options[0];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = useMemo(() => ({
    real: scoped
      .filter((o) => o.portfolio.kind === "live" || o.portfolio.kind === "paper")
      .sort((a, b) => providerRank(a) - providerRank(b)
        || a.portfolio.name.localeCompare(b.portfolio.name)),
    practice: scoped.filter((o) => o.portfolio.kind === "sim" || o.portfolio.kind === "shadow"),
  }), [scoped]);

  if (!selected) return null;
  const list = (
    <>
      {groups.real.length > 0 && <div className="acct-group">Live accounts</div>}
      {groups.real.map((o) => (
        <button type="button" key={o.portfolio.id} role="option" disabled={isPending(o)}
          aria-selected={o.portfolio.id === value}
          title={isPending(o) ? "IBKR (incl. its paper account) joins the Live workspace when the gateway connects" : undefined}
          className={`acct-opt ${o.portfolio.id === value ? "active" : ""} ${isPending(o) ? "disabled" : ""}`}
          onClick={() => { if (!isPending(o)) { onChange(o.portfolio.id); setOpen(false); } }}>
          <OptionRow opt={o} />
        </button>
      ))}
      {groups.practice.length > 0 && <div className="acct-group">Practice</div>}
      {groups.practice.map((o) => (
        <button type="button" key={o.portfolio.id} role="option"
          aria-selected={o.portfolio.id === value}
          className={`acct-opt ${o.portfolio.id === value ? "active" : ""}`}
          onClick={() => { onChange(o.portfolio.id); setOpen(false); }}>
          <OptionRow opt={o} />
        </button>
      ))}
    </>
  );
  return (
    <div className="acct-select" ref={rootRef}>
      <button type="button" className="acct-btn" onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox" aria-expanded={open}>
        <OptionRow opt={selected} />
        <IconChevron size={11}
          style={{ transform: open ? "rotate(-90deg)" : "rotate(90deg)", flexShrink: 0 }} />
      </button>
      {open && isPhone && (
        <Sheet title="Account" onClose={() => setOpen(false)}>
          <div className="acct-sheet-list" role="listbox" aria-label="Account">{list}</div>
        </Sheet>
      )}
      {open && !isPhone && (
        <div className="acct-pop" role="listbox" aria-label="Account">{list}</div>
      )}
    </div>
  );
}
