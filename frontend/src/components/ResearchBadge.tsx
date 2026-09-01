/** The one way a research (shadow) book identifies itself on shared surfaces
    (POST-SOAK 3.5): blotter rows, position rows, armed plans, proposals.
    Reuse this — never invent another marker. */
export function ResearchBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span className="status-pill dim research-badge"
      title="a research (shadow) book — the per-source track record; not real money">
      🔬{compact ? "" : " research"}
    </span>
  );
}
