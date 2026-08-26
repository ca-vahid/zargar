import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useViewport } from "../lib/viewport";
import { Sheet } from "./Sheet";

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function Modal({
  title,
  onClose,
  children,
  footer,
  dismissable = true,
  wide = false,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  dismissable?: boolean;
  wide?: boolean;
}) {
  const { isPhone } = useViewport();
  if (isPhone) {
    return (
      <Sheet title={title} onClose={onClose} footer={footer} dismissable={dismissable} full={wide}>
        {children}
      </Sheet>
    );
  }
  return <DesktopModal title={title} onClose={onClose} footer={footer} dismissable={dismissable} wide={wide}>{children}</DesktopModal>;
}

function DesktopModal({
  title, onClose, children, footer, dismissable = true, wide = false,
}: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode;
  dismissable?: boolean; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? node)?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && dismissable) {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab" && node) {
        const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
          .filter((el) => !el.hasAttribute("disabled"));
        if (items.length === 0) return;
        const firstEl = items[0];
        const lastEl = items[items.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      previous?.focus();
    };
  }, [onClose, dismissable]);

  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (dismissable && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={ref}
        tabIndex={-1}
      >
        <div className="modal-head" id={titleId}>{title}</div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel = "Confirm",
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: ReactNode;
  body?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button className="ghost-btn" onClick={onCancel}>Cancel</button>
          <button
            className={danger ? "danger-btn" : "primary-btn"}
            onClick={onConfirm}
            style={danger ? { padding: "7px 14px", fontWeight: 600 } : undefined}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      {body}
    </Modal>
  );
}

export function PromptDialog({
  title,
  label,
  defaultValue = "",
  submitLabel = "OK",
  onSubmit,
  onCancel,
}: {
  title: ReactNode;
  label?: string;
  defaultValue?: string;
  submitLabel?: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(defaultValue);
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button className="ghost-btn" onClick={onCancel}>Cancel</button>
          <button className="primary-btn" onClick={() => onSubmit(value)}>
            {submitLabel}
          </button>
        </>
      }
    >
      <label className="field">
        {label && <span>{label}</span>}
        <input
          type="text"
          value={value}
          autoFocus
          enterKeyHint="done"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSubmit(value); }}
        />
      </label>
    </Modal>
  );
}
