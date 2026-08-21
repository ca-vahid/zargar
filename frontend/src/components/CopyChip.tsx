import { useEffect, useRef, useState } from "react";
import { copyText } from "../lib/routing";

/**
 * A short identifier you can click to copy. Shows the truncated form (a run's
 * first 8 hex chars is plenty to quote in conversation) but copies the full
 * value, or a link when one is given.
 */
export function CopyChip({
  value,
  label,
  title,
  link,
  short = 8,
}: {
  value: string;
  label?: string;
  title?: string;
  /** When present, a second button copies this instead (a shareable URL). */
  link?: string;
  short?: number;
}) {
  const [copied, setCopied] = useState<"" | "id" | "link">("");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const doCopy = async (text: string, which: "id" | "link") => {
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(which);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(""), 1400);
  };

  const display = label ?? `#${value.slice(0, short)}`;
  return (
    <span className="copy-chip-group">
      <button type="button" className={`copy-chip ${copied === "id" ? "done" : ""}`}
        title={title ?? `${value} — click to copy`}
        onClick={(e) => { e.stopPropagation(); doCopy(value, "id"); }}>
        <span className="copy-chip-text">{copied === "id" ? "copied" : display}</span>
      </button>
      {link && (
        <button type="button" className={`copy-chip copy-chip--link ${copied === "link" ? "done" : ""}`}
          title={`${link} — click to copy link`}
          onClick={(e) => { e.stopPropagation(); doCopy(link, "link"); }}>
          {copied === "link" ? "copied" : "link"}
        </button>
      )}
    </span>
  );
}
