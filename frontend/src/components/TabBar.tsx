import { useEffect, useState } from "react";
import { signOut } from "../lib/auth";
import { APP_VERSION } from "../changelog";
import { ChangelogDialog } from "./ChangelogDialog";
import { api } from "../lib/api";
import { useStore, type Page } from "../store";
import { useTechniques } from "../lib/techniques";
import { Sheet } from "./Sheet";
import { ConfirmDialog } from "./Modal";
import {
  IconArmed, IconDashboard, IconJournal, IconLedger, IconOptions, IconPortfolios,
  IconSettings, IconSignals, IconTechnique, IconTrade, IconWatchlist,
} from "./icons";

/** Phone navigation: five thumb-reachable tabs; everything else lives in More. */
const TABS: { key: Page; label: string; icon: React.ReactNode }[] = [
  { key: "armed", label: "Now", icon: <IconArmed /> },
  { key: "trade", label: "Trade", icon: <IconTrade /> },
  { key: "inbox", label: "Tips", icon: <IconSignals /> },
  { key: "portfolios", label: "Portfolio", icon: <IconPortfolios /> },
];

const MORE: { key: Page; label: string; icon: React.ReactNode; sub?: string }[] = [
  { key: "dashboard", label: "Dashboard", icon: <IconDashboard /> },
  { key: "ledger", label: "Ledger", icon: <IconLedger /> },
  { key: "options", label: "Options", icon: <IconOptions /> },
  { key: "watchlists", label: "Watchlists", icon: <IconWatchlist /> },
  { key: "journal", label: "Journal", icon: <IconJournal /> },
  { key: "settings", label: "Settings", icon: <IconSettings /> },
];

export function TabBar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const pending = useStore((s) => s.proposals.length);
  const armed = useStore((s) => s.techniqueArmed);
  const attention = armed.filter((a) => a.needsAttention).length;
  const armedCount = armed.filter((a) => a.status === "armed" || a.status === "paused").length;
  const more = useStore((s) => s.moreOpen);
  const setMore = useStore((s) => s.setMoreOpen);
  const moreActive = MORE.some((m) => m.key === page) || page === "technique" || page === "flow" || page === "team2";
  // installed app icon badge = things that need a human
  useEffect(() => {
    const n = attention + pending;
    const nav = navigator as any;
    try { if (n > 0) nav.setAppBadge?.(n); else nav.clearAppBadge?.(); } catch { /* unsupported */ }
  }, [attention, pending]);

  return (
    <>
      <nav className="tabbar" aria-label="Primary">
        {TABS.map((t) => (
          <button key={t.key} type="button" className={page === t.key ? "active" : ""}
            aria-current={page === t.key ? "page" : undefined}
            onClick={() => { setMore(false); setPage(t.key); }}>
            <span className="tabbar-ic">
              {t.icon}
              {t.key === "armed" && attention > 0 && <span className="tabbar-badge bad">{attention}</span>}
              {t.key === "armed" && attention === 0 && armedCount > 0 && <span className="tabbar-badge">{armedCount}</span>}
              {t.key === "inbox" && pending > 0 && <span className="tabbar-badge">{pending}</span>}
            </span>
            <span className="tabbar-lbl">{t.label}</span>
          </button>
        ))}
        <button type="button" className={moreActive ? "active" : ""} onClick={() => setMore(true)}
          aria-haspopup="dialog" aria-expanded={more}>
          <span className="tabbar-ic"><span className="tabbar-dots" aria-hidden="true">•••</span></span>
          <span className="tabbar-lbl">More</span>
        </button>
      </nav>
      {more && <MoreSheet onClose={() => setMore(false)} />}
    </>
  );
}

function MoreSheet({ onClose }: { onClose: () => void }) {
  const techniques = useTechniques();
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const connected = useStore((s) => s.connected);
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const toast = useStore((s) => s.toast);
  const chgDollar = useStore((s) => s.chgDollar);
  const toggleChgMode = useStore((s) => s.toggleChgMode);
  const authUser = useStore((s) => s.auth.user);
  const [confirmLive, setConfirmLive] = useState(false);
  const [changelog, setChangelog] = useState(false);
  const go = (p: Page) => { setPage(p); onClose(); };
  const setMode = async (value: string) => {
    try { await api.patchSettings({ "trading.mode": value }); toast("info", `Workspace: ${value}`); }
    catch (e: any) { toast("error", e.message); }
  };
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    useStore.getState().setSettings({ ...useStore.getState().settings, "ui.theme": next });
    api.patchSettings({ "ui.theme": next }).catch((e) => toast("error", e.message));
  };

  return (
    <Sheet title="More" onClose={onClose}>
      <div className="more-grid">
        {MORE.map((m) => (
          <button key={m.key} type="button" className={`more-item ${page === m.key ? "active" : ""}`}
            onClick={() => go(m.key)}>
            {m.icon}<span>{m.label}</span>
          </button>
        ))}
      </div>
      <div className="more-group">
        <div className="more-group-title"><IconTechnique /> Techniques</div>
        {techniques.map((t) => (
          <button type="button" key={`technique-${t.id}`} className={`more-item more-item--sub ${page === t.page ? "active" : ""}`}
            onClick={() => go(t.page as Page)}>
            <span className="nav-sub-dot" aria-hidden="true" /><span>{t.label}</span>
          </button>
        ))}
      </div>
      <div className="more-rows">
        <div className="more-row">
          <span>Workspace</span>
          <div className="seg" role="group" aria-label="Workspace">
            <button type="button" className={mode !== "live" ? "on" : ""} onClick={() => void setMode("practice")}>Practice</button>
            <button type="button" className={mode === "live" ? "on live" : ""}
              onClick={() => { if (mode !== "live") setConfirmLive(true); }}>LIVE</button>
          </div>
        </div>
        <div className="more-row">
          <span>Theme</span>
          <button type="button" className="ghost-btn" onClick={toggleTheme}>
            {theme === "dark" ? "☀ Light" : "🌙 Dark"}
          </button>
        </div>
        <div className="more-row">
          <span>Day change shows</span>
          <div className="seg" role="group" aria-label="Day change unit">
            <button type="button" className={!chgDollar ? "on" : ""} onClick={() => { if (chgDollar) toggleChgMode(); }}>%</button>
            <button type="button" className={chgDollar ? "on" : ""} onClick={() => { if (!chgDollar) toggleChgMode(); }}>$</button>
          </div>
        </div>
        {authUser && authUser.provider !== "open" && (
          <div className="more-row">
            <span className="muted small" style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              {authUser.picture && <img src={authUser.picture} alt="" width={24} height={24} style={{ borderRadius: "50%" }} referrerPolicy="no-referrer" />}
              <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{authUser.email}</span>
            </span>
            <button type="button" className="ghost-btn" onClick={() => void signOut()}>Sign out</button>
          </div>
        )}
        <div className="more-row">
          <span>Connection</span>
          <span className={`status-pill ${connected ? "ok" : "bad"}`}>{connected ? "live" : "offline"}</span>
        </div>
        <div className="more-row">
          <span>Version</span>
          <button type="button" className="ghost-btn" onClick={() => setChangelog(true)}>v{APP_VERSION} · what's new</button>
        </div>
      </div>
      {changelog && <ChangelogDialog onClose={() => setChangelog(false)} />}
      {confirmLive && (
        <ConfirmDialog
          title="Switch to LIVE?"
          danger
          confirmLabel="Go live"
          body={<p style={{ margin: 0 }}>Real orders will route to your brokerage accounts. Every order still passes the risk gate and asks for confirmation.</p>}
          onConfirm={() => { setConfirmLive(false); void setMode("live"); }}
          onCancel={() => setConfirmLive(false)}
        />
      )}
    </Sheet>
  );
}
