import { useEffect, useState } from "react";
import { api } from "./api";
import type { TechniqueInfo } from "../types";

/** The one technique the app shipped with — also the fallback when the registry
 *  route is unavailable (older server), so the nav never loses its entry. */
export const EM_TECHNIQUE: TechniqueInfo = {
  id: "enhanced_market", label: "EM Options", version: "1", page: "technique",
  tabs: ["validation", "analyse", "chat", "history", "backtest"],
};

let cache: TechniqueInfo[] | null = null;
let inflight: Promise<TechniqueInfo[]> | null = null;

/** Registered techniques (GET /api/techniques), fetched once per page load. */
export function useTechniques(): TechniqueInfo[] {
  const [list, setList] = useState<TechniqueInfo[]>(cache ?? [EM_TECHNIQUE]);
  useEffect(() => {
    if (cache) { setList(cache); return; }
    inflight ??= api.techniques()
      .then((r) => { cache = r.length ? r : [EM_TECHNIQUE]; return cache; })
      .catch(() => [EM_TECHNIQUE]);
    let alive = true;
    inflight.then((r) => { if (alive) setList(r); });
    return () => { alive = false; };
  }, []);
  return list;
}
