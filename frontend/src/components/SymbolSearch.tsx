import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

export interface SymbolHit {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
}

/** Debounced ticker/company lookup with a keyboard-navigable dropdown.
 * Reused by the TopBar (global lookup) and the sidebar watchlist editor. */
export function SymbolSearch({
  placeholder = "Search stocks…",
  autoFocus = false,
  compact = false,
  onPick,
  onAdd,
  addLabel = "+ watch",
  inputRef,
  value,
  onValueChange,
  inputId,
  inputClassName = "",
}: {
  placeholder?: string;
  autoFocus?: boolean;
  compact?: boolean;
  onPick: (hit: SymbolHit) => void;
  onAdd?: (hit: SymbolHit) => void;
  addLabel?: string;
  inputRef?: React.Ref<HTMLInputElement>;
  /** Controlled mode: the input *is* the field (keeps its text after a pick). */
  value?: string;
  onValueChange?: (v: string) => void;
  inputId?: string;
  inputClassName?: string;
}) {
  const controlled = value !== undefined;
  const [uq, setUq] = useState("");
  const q = controlled ? value : uq;
  const setQ = (v: string) => { if (controlled) onValueChange?.(v); else setUq(v); };
  const [hits, setHits] = useState<SymbolHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const seqRef = useRef(0);
  // In controlled mode the field starts populated (and the parent can set it),
  // so a value change alone must not pop the menu open — only real typing does.
  const typedRef = useRef(false);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 1) {
      setHits([]); setOpen(false); setLoading(false); setFailed(false);
      return;
    }
    setLoading(true);
    const seq = ++seqRef.current;
    const t = setTimeout(async () => {
      try {
        const res = await api.searchSymbols(query);
        if (seq !== seqRef.current) return; // stale response
        setHits(res.results);
        setActive(0);
        if (!controlled || typedRef.current) setOpen(true);
        setFailed(false);
      } catch {
        if (seq !== seqRef.current) return;
        setHits([]); setFailed(true);
        if (!controlled || typedRef.current) setOpen(true);
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const pick = (hit: SymbolHit) => {
    setOpen(false);
    // Controlled mode keeps the chosen symbol in the field; the standalone
    // lookup clears so it is ready for the next search.
    typedRef.current = false;
    setQ(controlled ? hit.symbol : "");
    onPick(hit);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); (e.target as HTMLElement).blur(); return; }
    if (!open || hits.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (hits[active]) pick(hits[active]); }
  };

  return (
    <div className={`sym-search ${compact ? "sym-search--compact" : ""}`} ref={rootRef}>
      <input
        ref={inputRef}
        id={inputId}
        type="text"
        className={`sym-search-input ${inputClassName}`}
        value={q}
        placeholder={placeholder}
        autoFocus={autoFocus}
        spellCheck={false}
        onChange={(e) => { typedRef.current = true; setQ(e.target.value); }}
        onFocus={() => { if (hits.length > 0 && typedRef.current) setOpen(true); }}
        onKeyDown={onKey}
        role="combobox"
        aria-expanded={open}
        aria-label="Search stocks"
      />
      {loading && <span className="sym-search-spin" aria-hidden="true" />}
      {open && (
        <div className="sym-pop" role="listbox">
          {failed && <div className="sym-empty">search unavailable — try again</div>}
          {!failed && hits.length === 0 && !loading && (
            <div className="sym-empty">no matches for “{q.trim()}”</div>
          )}
          {hits.map((h, i) => (
            <div
              key={`${h.symbol}-${i}`}
              role="option"
              aria-selected={i === active}
              className={`sym-opt ${i === active ? "active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(h); }}
            >
              <span className="sym-opt-sym">{h.symbol}</span>
              <span className="sym-opt-name" title={h.name}>{h.name}</span>
              <span className="sym-opt-exch">{h.exchange}</span>
              {onAdd && (
                <button
                  type="button"
                  className="sym-opt-add"
                  title={`Add ${h.symbol} to your watchlist`}
                  onMouseDown={(e) => {
                    e.preventDefault(); e.stopPropagation();
                    setOpen(false); setQ("");
                    onAdd(h);
                  }}
                >
                  {addLabel}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
