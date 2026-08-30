import { useState } from "react";

/** Real stock logo (parqet CDN — the same source EM's Validation tab uses),
 *  falling back to a lettermark for unlisted/unknown symbols. Pass the
 *  UNDERLYING for option contracts. */
export function SymIcon({ sym, size = 22 }: { sym: string; size?: number }) {
  const [err, setErr] = useState(false);
  const s = (sym || "").toUpperCase().replace(/[^A-Z.\-]/g, "");
  if (!s || err) {
    return (
      <span className="sym-avatar" aria-hidden
        style={{ width: size, height: size, fontSize: Math.max(7, Math.round(size * 0.32)) }}>
        {s.slice(0, 4) || "?"}
      </span>
    );
  }
  return (
    <img className="sym-logo" alt="" aria-hidden loading="lazy"
      width={size} height={size}
      src={`https://assets.parqet.com/logos/symbol/${s}?format=png&size=${size > 24 ? 64 : 32}`}
      onError={() => setErr(true)} />
  );
}
