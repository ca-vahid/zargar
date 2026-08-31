// "What's new" — the version chip's popup. Filterable, classified, concise;
// data lives in src/changelog.ts. Modal on desktop, sheet on phones (Modal
// handles that itself).
import { useMemo, useState } from "react";
import { APP_VERSION, CHANGELOG, type ChangeTag } from "../changelog";
import { Modal } from "./Modal";

const TAGS: { key: ChangeTag; label: string; icon: string }[] = [
  { key: "major", label: "Major", icon: "★" },
  { key: "new", label: "New", icon: "✦" },
  { key: "improved", label: "Improved", icon: "↻" },
  { key: "fixed", label: "Fixed", icon: "⚙" },
  { key: "security", label: "Security", icon: "🛡" },
];

export function ChangelogDialog({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [tags, setTags] = useState<Set<ChangeTag>>(new Set());
  const toggle = (t: ChangeTag) =>
    setTags((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  const needle = q.trim().toLowerCase();
  const releases = useMemo(() =>
    CHANGELOG.map((r) => ({
      ...r,
      items: r.items.filter((i) =>
        (tags.size === 0 || tags.has(i.tag)) &&
        (!needle || i.text.toLowerCase().includes(needle) || r.title.toLowerCase().includes(needle)
          || r.version.includes(needle))),
    })).filter((r) => r.items.length > 0),
    [needle, tags]);

  return (
    <Modal title="What's new in Zargar" onClose={onClose} wide>
    <div className="chlog">
      <div className="chlog-sub">Release history &amp; changelog · you're on v{APP_VERSION}</div>
      <input className="chlog-search" type="search" placeholder="Search changelog…"
        value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search changelog" />
      <div className="chlog-tags" role="group" aria-label="Filter by kind">
        {TAGS.map((t) => (
          <button key={t.key} type="button"
            className={`chlog-tag chlog-tag--${t.key} ${tags.has(t.key) ? "on" : ""}`}
            aria-pressed={tags.has(t.key)} onClick={() => toggle(t.key)}>
            <span aria-hidden="true">{t.icon}</span> {t.label}
          </button>
        ))}
      </div>
      <div className="chlog-list">
        {releases.length === 0 && <div className="empty">Nothing matches — clear the search or filters.</div>}
        {releases.map((r, idx) => (
          <section key={r.version} className="chlog-rel">
            <div className="chlog-rel-head">
              <span className="chlog-ver">v{r.version}</span>
              {idx === 0 && r.version === APP_VERSION && <span className="chlog-latest">Latest</span>}
              <b className="chlog-title">{r.title}</b>
              <span className="chlog-date">{new Date(`${r.date}T12:00:00`).toLocaleDateString([], { year: "numeric", month: "long", day: "numeric" })}</span>
            </div>
            {r.items.map((i, j) => (
              <div key={j} className="chlog-item">
                <span className={`chlog-pill chlog-tag--${i.tag}`}>
                  {TAGS.find((t) => t.key === i.tag)?.icon} {TAGS.find((t) => t.key === i.tag)?.label}
                </span>
                <span className="chlog-text">{i.text}</span>
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
    </Modal>
  );
}
