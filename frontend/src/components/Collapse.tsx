import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Height-animated disclosure. Uses the `grid-template-rows: 0fr -> 1fr`
 * technique so content of unknown height animates without measuring, and
 * `content-visibility` keeps collapsed subtrees out of layout.
 *
 * Respects `prefers-reduced-motion` via the stylesheet.
 */
export function Collapse({ open, children, className = "" }: {
  open: boolean;
  children: ReactNode;
  className?: string;
}) {
  // Render children only after the first open so long lists (the rulebook)
  // cost nothing while collapsed, but keep them mounted afterwards so
  // re-opening is instant and scroll position survives.
  const [everOpen, setEverOpen] = useState(open);
  useEffect(() => { if (open) setEverOpen(true); }, [open]);
  return (
    <div className={`collapse ${open ? "open" : ""} ${className}`} aria-hidden={!open}>
      <div className="collapse-inner">{everOpen ? children : null}</div>
    </div>
  );
}

/** A clickable header with a rotating chevron, paired with `Collapse`. */
export function DisclosureHead({ open, onToggle, children, extra, level = "section" }: {
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  extra?: ReactNode;
  level?: "section" | "sub";
}) {
  return (
    <div className={`disclosure-head ${level}`}>
      <button type="button" className="disclosure-btn" onClick={onToggle} aria-expanded={open}>
        <span className={`disclosure-chev ${open ? "open" : ""}`} aria-hidden="true">
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 3l6 5-6 5" />
          </svg>
        </span>
        <span className="disclosure-label">{children}</span>
      </button>
      {extra}
    </div>
  );
}

/** Persist a disclosure's open state across reloads. */
export function useDisclosure(key: string, initial: boolean) {
  const storageKey = `zargar_open_${key}`;
  const [open, setOpen] = useState(() => {
    const v = localStorage.getItem(storageKey);
    return v === null ? initial : v === "1";
  });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    localStorage.setItem(storageKey, open ? "1" : "0");
  }, [open, storageKey]);
  return [open, () => setOpen((v) => !v), setOpen] as const;
}
