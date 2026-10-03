// W6 (2026-10-03): the Tips method bound to several books. The analyst appraises each tip once; every enabled book
// gets its own proposal, sized by its own budget and caps. An empty list = the single Tips book
// (techniques.tip.default_portfolio). The server validates every save (role vs account kind, one primary, ...).
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import { ConfirmDialog } from "./Modal";

type Binding = {
  portfolioId: string; role: "practice" | "live"; enabled: boolean; primary: boolean; mode: "auto" | "proposal";
  allowLiveAuto?: boolean | null; armAtLevel?: boolean; budgetPerTip?: number | null; maxOpenPositions?: number | null;
  capitalCap?: number | null; riskPct?: number | null;
};

const NUMS: { key: keyof Binding; label: string; hint: string; step?: number }[] = [
  { key: "budgetPerTip", label: "Budget / tip ($)", hint: "caps the source's per-tip budget in this book" },
  { key: "maxOpenPositions", label: "Max open", hint: "open tip positions in this book (blank = the Tips default)" },
  { key: "capitalCap", label: "Capital cap ($)", hint: "cost basis of open tip positions in this book" },
  { key: "riskPct", label: "Risk / tip (%)", hint: "planned loss at the final stop, % of this book's equity", step: 0.1 },
];

export function TipBooksEditor() {
  const saved = useStore((s) => s.settings["techniques.tip.books"]) as Binding[] | undefined;
  const portfolios = useStore((s) => s.portfolios);
  const setSettings = useStore((s) => s.setSettings);
  const toast = useStore((s) => s.toast);
  const [draft, setDraft] = useState<Binding[]>([]);
  const [confirmAck, setConfirmAck] = useState<number | null>(null);
  useEffect(() => { setDraft(Array.isArray(saved) ? saved.map((b) => ({ ...b })) : []); }, [saved]);
  const books = useMemo(() => portfolios.filter((p) => !p.archived && p.kind !== "shadow"), [portfolios]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(Array.isArray(saved) ? saved : []);
  const set = (i: number, patch: Partial<Binding>) =>
    setDraft((d) => d.map((b, j) => (j === i ? { ...b, ...patch } : patch.primary ? { ...b, primary: false } : b)));
  const add = () => {
    const used = new Set(draft.map((b) => b.portfolioId));
    const pf = books.find((p) => !used.has(p.id));
    if (!pf) { toast("info", "every account is already bound"); return; }
    const live = pf.kind === "live" || pf.kind === "paper";
    setDraft((d) => [...d, { portfolioId: pf.id, role: live ? "live" : "practice", enabled: !live, primary: d.length === 0,
      mode: "auto", armAtLevel: !live, allowLiveAuto: live ? false : null }]);
  };
  const save = async () => {
    try {
      const clean = draft.map((b) => Object.fromEntries(Object.entries(b).filter(([, v]) => v !== null && v !== "")));
      setSettings(await api.patchSettings({ "techniques.tip.books": clean }));
      toast("success", clean.length ? `Tips books saved (${clean.length})` : "Tips books cleared - the single Tips book trades");
    } catch (e: any) { toast("error", e.message); }
  };
  return (
    <div className="tip-books">
      {draft.length === 0 && (
        <div className="muted small">No books bound: Tips trades its one Practice book (techniques.tip.default_portfolio).
          Bind a Practice book and a live account to run both at once.</div>)}
      {draft.map((b, i) => {
        const pf = portfolios.find((p) => p.id === b.portfolioId);
        const eligible = books.filter((p) => (b.role === "live" ? p.kind === "live" || p.kind === "paper" : p.kind === "sim"));
        return (
          <div key={i} className={`tip-book-row ${b.enabled ? "" : "off"}`}>
            <div className="tip-book-main">
              <select value={b.role} aria-label="Role"
                onChange={(e) => set(i, { role: e.target.value as Binding["role"], enabled: e.target.value !== "live" && b.enabled,
                  armAtLevel: e.target.value !== "live", allowLiveAuto: e.target.value === "live" ? false : null })}>
                <option value="practice">Practice</option><option value="live">Live</option>
              </select>
              <select value={b.portfolioId} aria-label="Account" onChange={(e) => set(i, { portfolioId: e.target.value })}>
                {!eligible.some((p) => p.id === b.portfolioId) && <option value={b.portfolioId}>{pf?.name ?? b.portfolioId}</option>}
                {eligible.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>)}
              </select>
              <select value={b.mode} aria-label="Mode" onChange={(e) => set(i, { mode: e.target.value as Binding["mode"] })}>
                <option value="auto">auto</option><option value="proposal">cards wait for me</option>
              </select>
              <label className="chk"><input type="checkbox" checked={b.enabled}
                onChange={(e) => set(i, { enabled: e.target.checked })} /> on</label>
              <label className="chk" title="this book's results feed trust, retros and the scorecard (one per idea)">
                <input type="radio" checked={!!b.primary} onChange={() => set(i, { primary: true })} /> primary</label>
              <label className="chk" title="at-level takes arm a waiting plan in this book">
                <input type="checkbox" checked={b.armAtLevel ?? b.role !== "live"}
                  onChange={(e) => set(i, { armAtLevel: e.target.checked })} /> at-level</label>
              {b.role === "live" && (
                <label className="chk" title="this live/paper book may self-approve the analyst's takes (a real account also needs 'Auto mode may trade REAL accounts')">
                  <input type="checkbox" checked={!!b.allowLiveAuto}
                    onChange={(e) => (e.target.checked ? setConfirmAck(i) : set(i, { allowLiveAuto: false }))} /> auto-approve</label>
              )}
              <button type="button" className="ghost-btn" aria-label="Remove book"
                onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>remove</button>
            </div>
            <div className="setting-cells">
              {NUMS.map((n) => (
                <label key={n.key} className="setting-cell" title={n.hint}>
                  <span className="cl">{n.label}</span>
                  <input type="number" step={n.step ?? 1} value={(b[n.key] as number | null | undefined) ?? ""} placeholder="default"
                    onChange={(e) => set(i, { [n.key]: e.target.value === "" ? null : Number(e.target.value) } as Partial<Binding>)} />
                </label>
              ))}
            </div>
          </div>
        );
      })}
      <div className="tip-book-actions">
        <button type="button" className="ghost-btn" onClick={add}>+ bind a book</button>
        <button type="button" className="primary-btn" disabled={!dirty} onClick={() => void save()}>Save books</button>
        {dirty && <button type="button" className="ghost-btn"
          onClick={() => setDraft(Array.isArray(saved) ? saved.map((b) => ({ ...b })) : [])}>discard</button>}
      </div>
      {confirmAck !== null && (
        <ConfirmDialog title="Let this book self-approve?" danger confirmLabel="Allow auto-approve"
          body={<p style={{ margin: 0 }}>The analyst's takes will place orders in {portfolios.find((p) => p.id === draft[confirmAck]?.portfolioId)?.name ?? "this account"} without
            a click, inside this book's budget and caps. Orders still pass the risk gate and need real-order routing on.</p>}
          onConfirm={() => { set(confirmAck, { allowLiveAuto: true }); setConfirmAck(null); }}
          onCancel={() => setConfirmAck(null)} />
      )}
    </div>
  );
}
