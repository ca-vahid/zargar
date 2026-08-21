/**
 * Parse JSON that is still streaming in.
 *
 * A structured model pass emits one JSON document token by token, so every
 * intermediate state is a truncated document. To show it as fields rather than
 * raw text we repair the truncation: find the last point where a value had just
 * completed, cut there, and close whatever containers are still open.
 *
 * Cutting blindly at the end does not work — the tail is usually mid-string or
 * mid-key — so this records candidate cut points during a single scan (with the
 * bracket stack at each one) and walks backwards through them until a candidate
 * parses. In practice the first or second candidate succeeds.
 */

const MAX_BACKTRACK = 40;
/** Only the tail of a candidate can contain a trailing comma or dangling key,
 *  so the end-anchored cleanup regexes run over this many chars, not the lot. */
const TRIM_WINDOW = 256;

interface Cut {
  /** index one past the completed value */
  end: number;
  /** closers needed at that point, outermost last — e.g. `]}` */
  closers: string;
}

export function parsePartialJson(raw: string): any | null {
  const text = raw.trim();
  if (!text || (text[0] !== "{" && text[0] !== "[")) return null;
  try {
    return JSON.parse(text);
  } catch {
    /* truncated — repair below */
  }

  const cuts: Cut[] = [];
  const stack: string[] = [];
  let inStr = false;
  let esc = false;
  let literal = false; // inside a number / true / false / null

  const closersFor = () => {
    let out = "";
    for (let i = stack.length - 1; i >= 0; i--) out += stack[i] === "{" ? "}" : "]";
    return out;
  };
  const mark = (end: number) => {
    if (stack.length > 0) cuts.push({ end, closers: closersFor() });
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') {
        inStr = false;
        mark(i + 1); // a string ended here (value or key — retry sorts it out)
      }
      continue;
    }

    if (literal && (ch === "," || ch === "}" || ch === "]" || /\s/.test(ch))) {
      literal = false;
      mark(i); // the literal ended just before this delimiter
    }

    if (ch === '"') {
      inStr = true;
    } else if (ch === "{" || ch === "[") {
      stack.push(ch);
    } else if (ch === "}" || ch === "]") {
      stack.pop();
      mark(i + 1); // a container closed here
    } else if (!literal && /[-\d tfn]/.test(ch) && !/\s/.test(ch)) {
      literal = true; // start of a number / true / false / null
    }
  }
  // NOTE: a numeric literal still open at end-of-buffer is deliberately NOT
  // marked. `{"entry_price":1` is valid JSON on its own, so marking it would
  // return 1 for a value that is really 145.67 — and unlike truncated prose, a
  // truncated number looks settled. Leaving it unmarked hides the field until a
  // delimiter proves it finished.

  // Candidates are generated lazily and tried in order, most complete first:
  // building all 40 up front cost a full-length slice plus two full-buffer
  // regex scans each, on every streamed delta (O(n^2) on the render path).
  function* candidates(): Generator<string> {
    // If the stream stopped inside a string, close it and show the partial
    // prose — the common streaming case, not an edge case.
    if (inStr) {
      // A trailing lone backslash would escape the quote we are about to add.
      yield `${esc ? text.slice(0, -1) : text}"${closersFor()}`;
    }
    for (let k = cuts.length - 1, n = 0; k >= 0 && n < MAX_BACKTRACK; k--, n++) {
      const cut = cuts[k];
      const head = text.slice(0, cut.end);
      // Trim only the tail: these patterns are all end-anchored, so scanning
      // the whole buffer for them is wasted work on every delta.
      const from = Math.max(0, head.length - TRIM_WINDOW);
      const tail = head
        .slice(from)
        .replace(/,\s*$/, "")
        // A dangling `"key":` with no value cannot be closed — drop the pair.
        .replace(/,?\s*"[^"]*"\s*:\s*$/, "");
      yield head.slice(0, from) + tail + cut.closers;
    }
  }

  for (const candidate of candidates()) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      /* try the next, less complete, repair */
    }
  }
  return null;
}

/** Decode escapes that would otherwise show through raw (—, \n, \" …). */
export function decodeEscapes(s: string): string {
  return s
    .replace(/\\u([0-9a-fA-F]{4})/g, (_m, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "  ")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}
