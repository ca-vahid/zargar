import type { ReactNode } from "react";
import { useDisclosure } from "../Collapse";

/** Persisted open/closed state for a rail; the parent applies `rail-closed` to its grid. */
export function useRail(storageKey: string) {
  const [open, toggle] = useDisclosure(storageKey, true);
  return { open, toggle, gridClass: `tq-grid ${open ? "" : "rail-closed"}` };
}

/**
 * The right-hand rail of the Technique page, collapsible from its left edge.
 * The grid column animates (CSS `grid-template-columns` transition) while the
 * rail's inner content keeps a fixed width, so text does not reflow mid-way;
 * the handle stays visible in both states so there is always a way back.
 */
export function RailShell({ open, onToggle, label, children }: {
  open: boolean; onToggle: () => void; label: string; children: ReactNode;
}) {
  return (
    <aside className={`tq-rail-shell ${open ? "open" : "closed"}`} aria-label={label}>
      <button type="button" className="tq-rail-handle" onClick={onToggle}
        title={open ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`} aria-expanded={open}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {open ? <path d="M6 3l5 5-5 5" /> : <path d="M10 3L5 8l5 5" />}
        </svg>
        {!open && <span className="tq-rail-handle-label">{label}</span>}
      </button>
      <div className="tq-rail-body" aria-hidden={!open}>
        <div className="tq-rail">{children}</div>
      </div>
    </aside>
  );
}
