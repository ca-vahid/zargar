import { Fragment, useMemo, type ReactNode } from "react";

/** Tiny dependency-free markdown: headings, bold/italic/code, lists, tables,
 *  fenced code, paragraphs. Enough for model answers; not a full parser. */
export function Markdown({ text }: { text: string }) {
  const nodes = useMemo(() => render(text || ""), [text]);
  return <div className="md">{nodes}</div>;
}

function inline(s: string, key: number): ReactNode {
  // split on **bold**, `code`, *italic*
  const parts: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) parts.push(<Fragment key={`${key}-${i++}`}>{s.slice(last, m.index)}</Fragment>);
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<b key={`${key}-${i++}`}>{tok.slice(2, -2)}</b>);
    else if (tok.startsWith("`")) parts.push(<code key={`${key}-${i++}`}>{tok.slice(1, -1)}</code>);
    else parts.push(<i key={`${key}-${i++}`}>{tok.slice(1, -1)}</i>);
    last = m.index + tok.length;
  }
  if (last < s.length) parts.push(<Fragment key={`${key}-${i++}`}>{s.slice(last)}</Fragment>);
  return parts;
}

function render(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push(<pre key={k++}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = h[1].length;
      const content = inline(h[2], k);
      out.push(lvl <= 2 ? <h4 key={k++}>{content}</h4> : <h5 key={k++}>{content}</h5>);
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      out.push(
        <div className="md-table-wrap" key={k++}>
          <table className="md-table">
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => ri === 0
                  ? <th key={ci}>{inline(c, k * 100 + ci)}</th>
                  : <td key={ci}>{inline(c, k * 100 + ci)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*([-*•]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\./.test(line);
      while (i < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+\.)\s+/, ""));
        i++;
      }
      const els = items.map((it, ii) => <li key={ii}>{inline(it, k * 100 + ii)}</li>);
      out.push(ordered ? <ol key={k++}>{els}</ol> : <ul key={k++}>{els}</ul>);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const buf: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\||\s*([-*•]|\d+\.)\s)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    out.push(<p key={k++}>{inline(buf.join(" "), k)}</p>);
  }
  return out;
}
