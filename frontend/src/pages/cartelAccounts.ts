import { useMemo } from "react";
import { useStore } from "../store";
import { useWorkspace, useWorkspacePortfolios } from "../lib/workspace";

export function useCartelPortfolios() {
  const workspace = useWorkspace();
  const books = useWorkspacePortfolios();
  const dedicated = useStore(s => String(s.settings["techniques.options_cartel.default_portfolio"] || ""));
  return useMemo(() => books.filter(b => !b.archived &&
    (workspace === "live" || !dedicated || b.id === dedicated)), [books, workspace, dedicated]);
}
