import type { ReactNode } from "react";
import { buildPath } from "../lib/routing";

/** Normal navigation stays in the app; modified clicks can open a new browser tab. */
export function CartelRunLink({id, onOpen, disabled, children}: {
  id: string; onOpen: (id: string) => void; disabled?: boolean; children: ReactNode;
}) {
  return <a className="link-btn" href={buildPath({page:"options_cartel", cartelRunId:id})}
    aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined} onClick={e => {
      if (disabled) { e.preventDefault(); return; }
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault(); onOpen(id);
    }}>{children}</a>;
}
