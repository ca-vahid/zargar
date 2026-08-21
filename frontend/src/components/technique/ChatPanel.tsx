import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { ChatBlock, ChatLive, ChatMessage, ChatThread } from "../../types";
import { IconX } from "../icons";
import { Spinner } from "../ui";
import { Markdown } from "./Markdown";

// --- helpers -------------------------------------------------------------------

function readFileAsDataUrl(f: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result));
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}

function Thinking({ text, open: initial = false, streaming = false }: { text: string; open?: boolean; streaming?: boolean }) {
  const [open, setOpen] = useState(initial);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (streaming && ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [text, streaming]);
  if (!text) return null;
  return (
    <div className={`chat-think ${streaming ? "streaming" : ""}`}>
      <button className="link-btn" onClick={() => setOpen((v) => !v)}>{open ? "▾" : "▸"} thinking{streaming ? "…" : ""}</button>
      {open && <div className="chat-think-body" ref={ref}>{text}</div>}
    </div>
  );
}

function Collapsible({ label, children, open: initial = false }: { label: string; children: React.ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="chat-collapsible">
      <button className="link-btn" onClick={() => setOpen((v) => !v)}>{open ? "▾" : "▸"} {label}</button>
      {open && <div className="chat-collapsible-body">{children}</div>}
    </div>
  );
}

function ToolCard({ name, input, status, meta, preview }: {
  name: string; input: any; status: "running" | "done"; meta?: any; preview?: string;
}) {
  return (
    <div className={`chat-tool ${status}`}>
      <div className="chat-tool-head">
        {status === "running" ? <Spinner /> : <span className="chat-tool-dot" />}
        <b>{name}</b>
        <span className="muted">{Object.entries(input ?? {}).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("  ")}</span>
        {meta?.seconds !== undefined && <span className="muted" style={{ marginLeft: "auto" }}>{meta.seconds}s</span>}
      </div>
      {meta?.assetId && <img className="chat-img" src={api.assetUrl(meta.assetId)} alt={name} />}
      {preview && !meta?.assetId && <pre className="chat-tool-preview">{preview}</pre>}
    </div>
  );
}

// --- message rendering --------------------------------------------------------------

function Blocks({ blocks, role, meta }: { blocks: ChatBlock[]; role: string; meta: Record<string, any> }) {
  const kind = meta?.kind;
  if (kind === "tool_results") {
    return (
      <div className="chat-tool-results">
        {blocks.map((b, i) => {
          const content = Array.isArray(b.content) ? b.content : [{ type: "text", text: String(b.content ?? "") }];
          const img = content.find((c: any) => c.type === "image_ref");
          const txt = content.filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n");
          return (
            <div key={i} className={`chat-tool done ${b.is_error ? "error" : ""}`}>
              <div className="chat-tool-head"><span className="chat-tool-dot" /><b>{b.meta?.name ?? "tool result"}</b>
                {b.meta?.seconds !== undefined && <span className="muted" style={{ marginLeft: "auto" }}>{b.meta.seconds}s</span>}</div>
              {img && <img className="chat-img" src={api.assetUrl(img.assetId)} alt="tool output" />}
              {txt && <Collapsible label={`result (${txt.length} chars)`}><pre className="chat-tool-preview">{txt.slice(0, 4000)}</pre></Collapsible>}
            </div>
          );
        })}
      </div>
    );
  }
  if (kind === "pipeline_prompt") {
    const imgs = blocks.filter((b) => b.type === "image_ref").length;
    const txt = blocks.filter((b) => b.type === "text").map((b) => b.text).join("\n");
    return (
      <Collapsible label={`pipeline prompt · pass ${meta.pass}${imgs ? ` · ${imgs} chart image${imgs > 1 ? "s" : ""}` : ""}`}>
        <pre className="chat-tool-preview">{txt.slice(0, 6000)}</pre>
      </Collapsible>
    );
  }
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.type) {
          case "text":
            return <Markdown key={i} text={b.text} />;
          case "thinking":
            return <Thinking key={i} text={b.thinking} />;
          case "image_ref":
            return <img key={i} className="chat-img" src={api.assetUrl(b.assetId)} alt="attachment" />;
          case "tool_use":
            return <ToolCard key={i} name={b.name} input={b.input} status="done" />;
          default:
            return null;
        }
      })}
      {kind === "pipeline_response" && meta.parsed && (
        <Collapsible label={`structured output · pass ${meta.pass} · ${meta.seconds}s · ${meta.usage?.output ?? "?"} tok`}>
          <pre className="chat-tool-preview">{JSON.stringify(meta.parsed, null, 1)}</pre>
        </Collapsible>
      )}
    </>
  );
}

function MessageRow({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user" && m.meta?.kind !== "tool_results";
  const kind = m.meta?.kind;
  const cls = kind === "run_summary" ? "summary" : kind?.startsWith("pipeline") ? "pipeline" : m.meta?.error ? "error" : "";
  return (
    <div className={`chat-msg ${isUser ? "user" : "assistant"} ${cls}`}>
      <div className="chat-msg-meta">
        {isUser ? "you" : kind === "run_summary" ? "pipeline result" : kind?.startsWith("pipeline") ? `pipeline · ${m.meta.pass}` : kind === "tool_results" ? "tools" : "claude"}
        {m.createdAt && <span> · {fmtDateTime(m.createdAt)}</span>}
        {m.meta?.usage && <span> · {m.meta.usage.output} tok{m.meta.usage.cacheRead ? ` · ${m.meta.usage.cacheRead} cached` : ""}</span>}
      </div>
      <div className="chat-msg-body"><Blocks blocks={m.blocks} role={m.role} meta={m.meta ?? {}} /></div>
    </div>
  );
}

function LiveTurn({ live }: { live: ChatLive }) {
  if (!live.active && !live.thinking && !live.text && live.tools.length === 0) return null;
  return (
    <div className="chat-msg assistant live">
      <div className="chat-msg-meta">claude {live.active && <Spinner />}{live.pass ? ` · pass ${live.pass}` : ""}</div>
      <div className="chat-msg-body">
        {live.tools.map((t) => <ToolCard key={t.id} name={t.name} input={t.input} status={t.status} meta={t.meta} preview={t.preview} />)}
        <Thinking text={live.thinking} open streaming />
        {live.text && <Markdown text={live.text} />}
        {live.error && <div className="neg">{live.error}</div>}
      </div>
    </div>
  );
}

// --- thread list ---------------------------------------------------------------------

function ThreadList({ activeId, onPick }: { activeId: string | null; onPick: (id: string) => void }) {
  const threads = useStore((s) => s.chatThreads);
  const setThreads = useStore((s) => s.setChatThreads);
  const toast = useStore((s) => s.toast);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [kind, setKind] = useState<"all" | "run" | "chat">("all");

  useEffect(() => { api.chatThreads().then(setThreads).catch((e) => toast("error", e.message)); }, [setThreads, toast]);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api.chatSearch(q).then(setHits).catch(() => setHits([])), 250);
    return () => clearTimeout(t);
  }, [q]);

  const visible = useMemo(() => threads.filter((t) => kind === "all" || t.kind === kind), [threads, kind]);

  const create = async () => {
    try {
      const t = await api.chatCreate({ title: "" });
      onPick(t.id);
    } catch (e: any) { toast("error", e.message); }
  };

  return (
    <div className="chat-threads">
      <div className="chat-threads-head">
        <button className="primary-btn" onClick={create}>+ New chat</button>
        <div className="tabs small">
          {(["all", "run", "chat"] as const).map((k) => (
            <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>{k === "run" ? "runs" : k === "chat" ? "chats" : "all"}</button>
          ))}
        </div>
      </div>
      <input className="chat-search" placeholder="Search all messages…" value={q} onChange={(e) => setQ(e.target.value)} />
      {hits && (
        <div className="chat-hits">
          {hits.length === 0 && <div className="muted">no matches</div>}
          {hits.map((h) => (
            <button key={h.messageId} className="chat-hit" onClick={() => { onPick(h.threadId); setQ(""); }}>
              <span className="muted">{h.role} · {h.createdAt ? fmtDateTime(h.createdAt) : ""}</span>
              <span>…{h.snippet}…</span>
            </button>
          ))}
        </div>
      )}
      <div className="chat-thread-list">
        {visible.map((t) => (
          <button key={t.id} className={`chat-thread-row ${t.id === activeId ? "active" : ""}`} onClick={() => onPick(t.id)}>
            <span className={`chat-thread-kind ${t.kind}`}>{t.kind === "run" ? "run" : "chat"}</span>
            <span className="chat-thread-title">{t.title || "(untitled)"}</span>
            <span className="muted">{t.messageCount ?? ""}{t.updatedAt ? ` · ${fmtDateTime(t.updatedAt)}` : ""}</span>
          </button>
        ))}
        {visible.length === 0 && <div className="empty">No threads yet — run an analysis or start a chat.</div>}
      </div>
    </div>
  );
}

// --- main panel ---------------------------------------------------------------------

export function ChatPanel() {
  const activeId = useStore((s) => s.chatActiveThreadId);
  const setActive = useStore((s) => s.setChatActive);
  const messagesMap = useStore((s) => s.chatMessages);
  const liveMap = useStore((s) => s.chatLive);
  const threads = useStore((s) => s.chatThreads);
  const setThread = useStore((s) => s.setChatThread);
  const toast = useStore((s) => s.toast);
  const [text, setText] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const messages = activeId ? messagesMap[activeId] : undefined;
  const live = activeId ? liveMap[activeId] : undefined;
  const thread = useMemo(() => threads.find((t) => t.id === activeId) ?? null, [threads, activeId]);

  // load the thread's messages when it becomes active (or was never loaded)
  useEffect(() => {
    if (!activeId || messagesMap[activeId]) return;
    setLoading(true);
    api.chatThread(activeId).then((t: ChatThread) => setThread(t)).catch((e) => toast("error", e.message))
      .finally(() => setLoading(false));
  }, [activeId, messagesMap, setThread, toast]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ block: "end" }); },
    [messages?.length, live?.text, live?.thinking, live?.tools.length]);

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => f.type.startsWith("image/"));
    const urls = await Promise.all(list.map(readFileAsDataUrl));
    setImages((prev) => [...prev, ...urls].slice(0, 6));
  }, []);

  const onPaste = (e: ClipboardEvent) => {
    const files: File[] = [];
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) { e.preventDefault(); addFiles(files); }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); };

  const send = async () => {
    if (!activeId || (!text.trim() && images.length === 0)) return;
    setSending(true);
    try {
      await api.chatSend(activeId, { text, images });
      setText("");
      setImages([]);
      taRef.current?.focus();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSending(false);
    }
  };
  const cancel = async () => { if (activeId) await api.chatCancel(activeId).catch(() => undefined); };
  const saveTitle = async () => {
    if (!activeId) return;
    setEditingTitle(false);
    if (titleDraft.trim() && titleDraft !== thread?.title) {
      const t = await api.chatPatch(activeId, { title: titleDraft.trim() }).catch((e) => { toast("error", e.message); return null; });
      if (t) setThread({ ...t, messages: messages });
    }
  };
  const archive = async () => {
    if (!activeId) return;
    await api.chatPatch(activeId, { archived: true }).catch((e) => toast("error", e.message));
    setActive(null);
    api.chatThreads().then(useStore.getState().setChatThreads);
  };

  const busy = Boolean(live?.active) || sending;

  return (
    <div className="chat-layout">
      <ThreadList activeId={activeId} onPick={(id) => setActive(id)} />
      <div className="chat-main" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
        {!activeId && (
          <div className="empty chat-empty">
            <div>Pick a thread, or start a new chat.</div>
            <div className="muted">Every pipeline run has its own thread with the full transcript — open one from History or a result card and keep asking.</div>
          </div>
        )}
        {activeId && (
          <>
            <div className="chat-head">
              {editingTitle ? (
                <input autoFocus value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={saveTitle} onKeyDown={(e) => e.key === "Enter" && saveTitle()} />
              ) : (
                <button className="chat-title" onClick={() => { setTitleDraft(thread?.title ?? ""); setEditingTitle(true); }}
                  title="click to rename">{thread?.title || "(untitled)"}</button>
              )}
              <span className="muted">{thread?.kind === "run" ? "pipeline run thread" : "chat"}{thread?.symbol ? ` · ${thread.symbol}` : ""}</span>
              {thread?.runId && <button className="link-btn" onClick={() => useStore.getState().openTechniqueRun(thread.runId!)}>view run</button>}
              <button className="link-btn" style={{ marginLeft: "auto" }} onClick={archive}>archive</button>
            </div>
            <div className="chat-scroll">
              {loading && <Spinner label="loading thread…" />}
              {(messages ?? []).map((m) => <MessageRow key={m.id} m={m} />)}
              {live && <LiveTurn live={live} />}
              <div ref={bottomRef} />
            </div>
            <div className="chat-composer">
              {images.length > 0 && (
                <div className="chat-attach">
                  {images.map((u, i) => (
                    <span key={i} className="chat-attach-item">
                      <img src={u} alt="" />
                      <button onClick={() => setImages((p) => p.filter((_, j) => j !== i))} aria-label="remove"><IconX size={10} /></button>
                    </span>
                  ))}
                </div>
              )}
              <textarea ref={taRef} rows={3} value={text} placeholder="Ask about this chart, the levels, a rule… Paste or drop a screenshot to analyse it. Enter to send, Shift+Enter for a new line."
                onChange={(e) => setText(e.target.value)} onPaste={onPaste}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy) send(); } }} />
              <div className="chat-composer-actions">
                <label className="link-btn">
                  attach image
                  <input type="file" accept="image/*" multiple style={{ display: "none" }} onChange={(e) => e.target.files && addFiles(e.target.files)} />
                </label>
                <span className="muted">{busy ? "claude is working…" : ""}</span>
                {live?.active && <button className="link-btn danger" onClick={cancel}>stop</button>}
                <button className="primary-btn" disabled={busy || (!text.trim() && images.length === 0)} onClick={send}>
                  {sending ? "Sending…" : "Send"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
