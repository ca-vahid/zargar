import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { IconX } from "./icons";

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

let openSheets = 0;

/** Bottom sheet (or full-screen with `full`): the phone replacement for modals,
 * popovers and dropdowns. Locks body scroll, traps focus, closes on Escape and
 * on the OS back gesture (a history entry is pushed while open), and pads its
 * footer for the home indicator. */
export function Sheet({
  title,
  onClose,
  children,
  footer,
  full = false,
  dismissable = true,
  className = "",
}: {
  title?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  full?: boolean;
  dismissable?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // body scroll lock (counted — nested sheets keep it locked)
  useEffect(() => {
    openSheets += 1;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      openSheets -= 1;
      if (openSheets === 0) document.body.style.overflow = prev;
    };
  }, []);

  // Android/iOS back gesture closes the sheet instead of leaving the page
  useEffect(() => {
    let pushed = true;
    try {
      window.history.pushState({ ...(window.history.state ?? {}), zargarSheet: true }, "", window.location.href);
    } catch { pushed = false; }
    const onPop = () => { pushed = false; onCloseRef.current(); };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (pushed && window.history.state?.zargarSheet) window.history.back();
    };
  }, []);

  // focus management + Escape + tab trap
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? node)?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && dismissable) { e.stopPropagation(); onCloseRef.current(); return; }
      if (e.key === "Tab" && node) {
        const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
          .filter((el) => !el.hasAttribute("disabled"));
        if (!items.length) return;
        const firstEl = items[0], lastEl = items[items.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) { e.preventDefault(); lastEl.focus(); }
        else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); firstEl.focus(); }
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); previous?.focus(); };
  }, [dismissable]);

  return createPortal(
    <div className="sheet-overlay"
      onPointerDown={(e) => { if (dismissable && e.target === e.currentTarget) onCloseRef.current(); }}>
      <div className={`sheet ${full ? "sheet--full" : ""} ${className}`} role="dialog" aria-modal="true"
        aria-labelledby={title ? titleId : undefined} ref={ref} tabIndex={-1}>
        {!full && <div className="sheet-handle" aria-hidden="true" />}
        {(title || dismissable) && (
          <div className="sheet-head">
            <div className="sheet-title" id={titleId}>{title}</div>
            {dismissable && (
              <button type="button" className="sheet-close" onClick={() => onCloseRef.current()} aria-label="Close">
                <IconX size={16} />
              </button>
            )}
          </div>
        )}
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
