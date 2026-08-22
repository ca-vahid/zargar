import { useId, useState, type ReactNode } from "react";

/**
 * A small "?" help bubble. Click (or hover) to reveal a plain-language
 * explanation. Kept deliberately jargon-light — these appear next to trading
 * controls where a wrong assumption costs money.
 */
export function InfoTip({ children, label = "What's this?" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="infotip" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="infotip-btn" aria-label={label} aria-expanded={open}
        aria-describedby={open ? id : undefined} onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}>?</button>
      {open && <span className="infotip-pop" role="tooltip" id={id}>{children}</span>}
    </span>
  );
}
