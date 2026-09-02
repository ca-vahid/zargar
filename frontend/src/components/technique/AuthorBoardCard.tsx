import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { MethodNote } from "../../types";
import { Spinner } from "../ui";

/** The author's board for the day (EM ingestion, INGESTION-PLAN.md): the newest
 * note with an extraction — summary, stance, his setups, what OUR pipeline made
 * of each symbol (armed / new plan → Arm / rejected + why), method claims. Polls
 * every 60 s; arming is a human click. EM-only surface. */
export function AuthorBoardCard() {
  const [note, setNote] = useState<MethodNote | null | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  const toast = useStore((s) => s.toast);
  const armed = useStore((s) => s.techniqueArmed);
  const load = useCallback(() => {
    api.techniqueIngestBoard().then((r) => setNote(r.note)).catch(() => setNote(null));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);

  if (note === undefined) return null;
  if (note === null) return null;   // nothing ingested yet — no empty box on the page
  const ex = note.extraction ?? {};
  const bc = note.boardCheck ?? {};
  const rows: any[] = bc.rows ?? [];
  const armedSyms = new Set(armed.filter((a) => a.status === "armed" || a.status === "paused").map((a) => a.symbol));
  const when = note.postedAt ?? note.createdAt;
  const pending = note.status === "pending_transcript";
  const failed = note.status === "failed";

  const arm = async (r: any) => {
    if (!r.runId) return;
    setBusy(r.symbol);
    try { await api.techniqueArm(r.runId); toast("success", `${r.symbol} armed`); load(); }
    catch (e: any) { toast("error", `${r.symbol}: ${e.message}`); }
    finally { setBusy(null); }
  };
  const recheck = async () => {
    setBusy("__check");
    try { const d = await api.techniqueIngestBoardCheck(note.id); setNote(d); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(null); }
  };
  const reextract = async () => {
    setBusy("__extract");
    try { const d = await api.techniqueIngestExtract(note.id); setNote(d); toast("success", "re-read done — running the board check"); const c = await api.techniqueIngestBoardCheck(d.id); setNote(c); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(null); }
  };

  return (
    <div className="panel mb tq-author-board">
      <div className="panel-head">
        Author's board
        <span className="status-pill dim">{note.kind}</span>
        {ex.stance && <span className={`status-pill ${ex.stance === "sit_on_hands" || ex.stance === "cautious" ? "wait" : "ok"}`}>{String(ex.stance).replace(/_/g, " ")}</span>}
        <span className="sub">#{note.channelName || note.channelId} · {note.author} · {when ? fmtDateTime(when) : ""}{note.meta?.durationSeconds ? ` · ${Math.round(note.meta.durationSeconds / 60)} min video` : ""}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {note.transcriptChars || note.text ? (
            <button type="button" className="ghost-btn" onClick={() => setShowText((v) => !v)}>{showText ? "hide" : "read"} {note.transcript ? "transcript" : "post"}</button>
          ) : null}
          {ex.symbols?.length ? <button type="button" className="ghost-btn" disabled={!!busy} onClick={() => void recheck()} title="Re-run our deterministic plan check on his symbols (no LLM)">{busy === "__check" ? <Spinner /> : "re-check board"}</button> : null}
          <button type="button" className="ghost-btn" disabled={!!busy || pending} onClick={() => void reextract()} title="Re-read the material with the model (one call)">{busy === "__extract" ? <Spinner /> : "re-read"}</button>
        </span>
      </div>
      <div className="panel-body">
        {pending && <div className="metric-sub"><Spinner /> video captured — waiting for the transcription worker (scripts\em-ingest.ps1)</div>}
        {failed && <div className="neg">failed: {note.error}</div>}
        {ex.summary && <p style={{ marginTop: 0 }}>{ex.summary}</p>}
        {rows.length > 0 && (
          <table className="tbl" style={{ marginBottom: 8 }}>
            <thead><tr><th>Symbol</th><th>His read</th><th>Our pipeline</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const his = (ex.board ?? []).find((b: string) => b.toUpperCase().startsWith(r.symbol + " ") || b.toUpperCase().startsWith(r.symbol + "|") || b.toUpperCase().startsWith(r.symbol + ":"));
                const isArmed = r.status === "armed" || armedSyms.has(r.symbol);
                return (
                  <tr key={r.symbol}>
                    <td className="sym-cell"><b>{r.symbol}</b></td>
                    <td className="small">{his ? his.replace(/^[A-Z.]+\s*[|:]?\s*/, "") : "—"}</td>
                    <td className="small">
                      {isArmed ? <span className="tq-badge setup">ARMED</span>
                        : r.status === "new" ? <><span className="tq-badge plan">{String(r.kind ?? "").toUpperCase()}</span> grade <b>{r.grade}</b> @ {r.level} · rr {typeof r.rr === "number" ? r.rr.toFixed(1) : r.rr}</>
                        : r.status === "rejected" ? <span className="muted" title={r.reason}>rejected · {String(r.reason ?? "").slice(0, 90)}</span>
                        : <span className="neg">{r.reason ?? r.status}</span>}
                    </td>
                    <td className="nowrap tq-arm-cell">
                      {!isArmed && r.status === "new" && r.runId && (
                        <button className="tq-act next" disabled={!!busy} onClick={() => void arm(r)}>{busy === r.symbol ? "…" : "⚡ arm"}</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {rows.length === 0 && (ex.board?.length ?? 0) > 0 && (
          <ul className="small" style={{ margin: "0 0 8px 16px" }}>{(ex.board ?? []).map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>
        )}
        {((ex.claims?.length ?? 0) > 0 || (ex.vetoes?.length ?? 0) > 0) && (
          <details>
            <summary className="small muted">method claims ({ex.claims?.length ?? 0}) · vetoes ({ex.vetoes?.length ?? 0}) — candidates for TRADING-RULES §3, never auto-applied</summary>
            {(ex.claims?.length ?? 0) > 0 && <ul className="small" style={{ margin: "6px 0 0 16px" }}>{(ex.claims ?? []).map((c: string, i: number) => <li key={`c${i}`}>{c}</li>)}</ul>}
            {(ex.vetoes?.length ?? 0) > 0 && <ul className="small muted" style={{ margin: "6px 0 0 16px" }}>{(ex.vetoes ?? []).map((c: string, i: number) => <li key={`v${i}`}>veto: {c}</li>)}</ul>}
          </details>
        )}
        {showText && (
          <pre className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto", marginTop: 8 }}>{note.transcript || note.text}</pre>
        )}
      </div>
    </div>
  );
}
