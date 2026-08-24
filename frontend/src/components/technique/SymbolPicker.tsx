import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { Modal } from "../Modal";

export interface SymbolSet { key: string; label: string; hint: string; symbols: string[]; collapsed?: boolean; group?: string }

/**
 * Multi-select symbol picker: quick sets (the book's universe, holdings, watchlists,
 * recently swept) + live search. Returns the selection on Apply; nothing is sent
 * until then.
 */
export function SymbolPicker({ initial, sets, onClose, onApply }: {
  initial: string[]; sets: SymbolSet[]; onClose: () => void; onApply: (symbols: string[]) => void;
}) {
  const [sel, setSel] = useState<string[]>(initial);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ symbol: string; name: string; exchange: string; type: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    let alive = true;
    setSearching(true);
    const t = setTimeout(() => {
      api.searchSymbols(term).then((r) => { if (alive) setHits(r.results.slice(0, 12)); })
        .catch(() => undefined).finally(() => { if (alive) setSearching(false); });
    }, 180);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  const has = (s: string) => sel.includes(s);
  const add = (s: string) => { const u = s.trim().toUpperCase(); if (u && !has(u)) setSel((v) => [...v, u]); };
  const remove = (s: string) => setSel((v) => v.filter((x) => x !== s));
  const toggle = (s: string) => (has(s) ? remove(s) : add(s));
  const addSet = (syms: string[]) => setSel((v) => [...v, ...syms.filter((s) => !v.includes(s))]);
  const removeSet = (syms: string[]) => setSel((v) => v.filter((s) => !syms.includes(s)));
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const first = hits[0]?.symbol ?? q;
      if (first) { add(first); setQ(""); }
    } else if (e.key === "Backspace" && !q && sel.length) { remove(sel[sel.length - 1]); }
  };
  const visibleSets = useMemo(() => sets.filter((s) => s.symbols.length), [sets]);
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  let lastGroup: string | undefined;

  return (
    <Modal wide title={<>Choose symbols <span className="muted">· {sel.length} selected</span></>} onClose={onClose}
      footer={<>
        <button className="link-btn" onClick={() => setSel([])} disabled={!sel.length}>clear all</button>
        <span style={{ flex: 1 }} />
        <button className="secondary-btn" onClick={onClose}>Cancel</button>
        <button className="primary-btn" disabled={!sel.length} onClick={() => onApply(sel)}>Use {sel.length} symbol{sel.length === 1 ? "" : "s"}</button>
      </>}>
      <div className="tq-picker">
        <div className="tq-picker-selected">
          {sel.length === 0 && <span className="muted">nothing selected yet — pick a set below or search</span>}
          {sel.map((s) => (
            <button key={s} type="button" className="tq-sym-chip on" onClick={() => remove(s)} title="remove">{s} <span aria-hidden="true">×</span></button>
          ))}
        </div>
        <div className="tq-picker-search">
          <input ref={inputRef} className="sym-search-input" placeholder="search ticker or company… (Enter adds the first hit)"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} />
          {(hits.length > 0 || searching) && (
            <div className="tq-picker-hits">
              {searching && hits.length === 0 && <div className="muted small">searching…</div>}
              {hits.map((h) => (
                <button key={h.symbol} type="button" className={`tq-picker-hit ${has(h.symbol) ? "on" : ""}`} onClick={() => { toggle(h.symbol); }}>
                  <b>{h.symbol}</b><span>{h.name}</span><small className="muted">{h.exchange}{h.type ? ` · ${h.type}` : ""}</small>
                  <span className="tq-picker-hit-mark">{has(h.symbol) ? "✓" : "+"}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {visibleSets.map((set) => {
          const allIn = set.symbols.every(has);
          const nIn = set.symbols.filter(has).length;
          const isOpen = set.collapsed ? !!opened[set.key] : true;
          const groupHead = set.group && set.group !== lastGroup ? set.group : null;
          lastGroup = set.group;
          return (
            <div key={set.key}>
              {groupHead && <div className="tq-picker-group">{groupHead}</div>}
              <div className={`tq-picker-set ${set.collapsed ? "compact" : ""}`}>
                <div className="tq-picker-set-head">
                  {set.collapsed
                    ? <button type="button" className="tq-picker-set-toggle" onClick={() => setOpened((o) => ({ ...o, [set.key]: !isOpen }))} aria-expanded={isOpen}>
                        <span className="tq-picker-caret">{isOpen ? "▾" : "▸"}</span> <b>{set.label}</b> <span className="muted">· {set.hint} · {set.symbols.length}{nIn ? ` (${nIn} in)` : ""}</span>
                      </button>
                    : <><b>{set.label}</b> <span className="muted">· {set.hint}</span></>}
                  <button type="button" className={`tq-picker-addall ${allIn ? "on" : ""}`} onClick={() => (allIn ? removeSet(set.symbols) : addSet(set.symbols))}>
                    {allIn ? "✓ added · remove" : `+ add all ${set.symbols.length}`}
                  </button>
                </div>
                {isOpen && (
                  <div className="tq-picker-chips">
                    {set.symbols.map((s) => (
                      <button key={s} type="button" className={`tq-sym-chip ${has(s) ? "on" : ""}`} onClick={() => toggle(s)}>{s}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
