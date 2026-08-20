import { useState } from "react";

/** Deterministic tint per broker name so lettermarks stay recognizable. */
function hue(name: string): number {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/** Broker logo from SnapTrade's CDN with a lettermark fallback. */
export function BrokerIcon({
  name,
  logoUrl,
  size = 20,
}: {
  name: string;
  logoUrl?: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  if (logoUrl && !failed) {
    return (
      <img
        src={logoUrl}
        alt=""
        aria-hidden="true"
        width={size}
        height={size}
        style={{ borderRadius: 5, objectFit: "cover", flexShrink: 0 }}
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: 5,
        flexShrink: 0,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.45,
        fontWeight: 700,
        color: "var(--text-1)",
        background: `oklch(0.55 0.11 ${hue(name)} / 0.35)`,
      }}
    >
      {initials || "?"}
    </span>
  );
}
