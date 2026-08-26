import { useEffect, useState } from "react";
import { Splash } from "./components/Splash";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { Toasts } from "./components/Toasts";
import { DashboardPage } from "./pages/DashboardPage";
import { TradePage } from "./pages/TradePage";
import { InboxPage } from "./pages/InboxPage";
import { PortfoliosPage } from "./pages/PortfoliosPage";
import { JournalPage } from "./pages/JournalPage";
import { ArmedPage } from "./pages/ArmedPage";
import { WatchlistsPage } from "./pages/WatchlistsPage";
import { api } from "./lib/api";
import { SettingsPage } from "./pages/SettingsPage";
import { TechniquePage } from "./pages/TechniquePage";
import { OptionsPage } from "./pages/OptionsPage";
import { useStore } from "./store";
import { buildPath, onRouteChange, parseLocation, syncUrl } from "./lib/routing";
import { clientKind, useViewport } from "./lib/viewport";
import { TabBar } from "./components/TabBar";

export default function App() {
  // armed fleet powers the sidebar badge and the dashboard widget on every page
  useEffect(() => {
    api.techniqueArmed(clientKind() === "phone").then((a) => useStore.getState().setTechniqueArmed(a)).catch(() => undefined);
  }, []);
  const page = useStore((s) => s.page);
  const techniqueTab = useStore((s) => s.techniqueTab);
  const techniqueRunId = useStore((s) => s.techniqueFocusRunId);
  const chatThreadId = useStore((s) => s.chatActiveThreadId);
  const optionsUnderlying = useStore((s) => s.optionsUnderlying);
  const optionsExpiry = useStore((s) => s.optionsExpiry);
  const optionsContract = useStore((s) => s.optionsContract);
  const applyRoute = useStore((s) => s.applyRoute);

  // URL is the source of truth on load and on back/forward; state drives it after.
  useEffect(() => {
    applyRoute(parseLocation());
    return onRouteChange(applyRoute);
  }, [applyRoute]);

  useEffect(() => {
    const next = { page, techniqueTab, runId: techniqueRunId, threadId: chatThreadId,
      optionsUnderlying, optionsExpiry, optionsContract };
    // pushState only when the destination really changes, so back/forward walks
    // the places the user visited rather than every incidental state write.
    syncUrl(next, buildPath(next) !== window.location.pathname);
  }, [page, techniqueTab, techniqueRunId, chatThreadId, optionsUnderlying, optionsExpiry, optionsContract]);
  const halt = useStore((s) => s.halt);
  const driftWarnings = useStore((s) => s.driftWarnings);
  const openJournal = useStore((s) => s.openJournal);
  const dismissDrift = useStore((s) => s.dismissDrift);
  const setPage = useStore((s) => s.setPage);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const accent = useStore((s) => s.settings["ui.accent"] ?? "#5b8cff");
  const density = useStore((s) => s.settings["ui.density"] ?? "comfortable");
  const mode = useStore((s) => s.settings["trading.mode"] ?? "practice");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.density = density;
    document.documentElement.dataset.mode = mode;
    document.documentElement.style.setProperty("--accent", accent);
  }, [theme, accent, density, mode]);

  const { isPhone, isTablet } = useViewport();
  const [sideCollapsed, setSideCollapsed] = useState(() => {
    const stored = localStorage.getItem("zargar_side_collapsed");
    if (stored !== null) return stored === "1";
    return window.matchMedia("(max-width: 1023px)").matches; // tablets start on the icon rail
  });
  void isTablet;
  return (
    <div className={`app ${isPhone ? "app--phone" : ""}`}>
      <Splash />
      <TopBar />
      <div className="banners">
        {halt.engaged && (
          <div className="halt-banner" role="alert">
            <span>KILL SWITCH ENGAGED — {halt.reason || "all order submission blocked"}</span>
            <button className="link-btn" onClick={() => openJournal("risk")}>
              view in journal
            </button>
          </div>
        )}
        {driftWarnings.map((d) => (
          <div key={d.portfolioId} className="drift-banner" role="status">
            <span>
              {d.name} {d.lossPct.toFixed(2)}% today — market drift, no zargar trades;
              trading is NOT halted
            </span>
            <button className="link-btn" onClick={() => setPage("portfolios")}>details</button>
            <button className="link-btn" onClick={() => dismissDrift(d.portfolioId)}
              aria-label={`Dismiss ${d.name} drift warning`}>
              dismiss
            </button>
          </div>
        ))}
      </div>
      <div className={`main ${sideCollapsed ? "side-collapsed" : ""}`}>
        {!isPhone && (
          <Sidebar collapsed={sideCollapsed} onToggleCollapse={() => { const next = !sideCollapsed; localStorage.setItem("zargar_side_collapsed", next ? "1" : "0"); setSideCollapsed(next); }} />
        )}
        <div className="content">
          {page === "dashboard" && <DashboardPage />}
          {page === "trade" && <TradePage />}
          {page === "options" && <OptionsPage />}
          {page === "inbox" && <InboxPage />}
          {page === "portfolios" && <PortfoliosPage />}
          {page === "journal" && <JournalPage />}
          {page === "settings" && <SettingsPage />}
          {page === "technique" && <TechniquePage />}
          {page === "armed" && <ArmedPage />}
          {page === "watchlists" && <WatchlistsPage />}
        </div>
      </div>
      <Toasts />
      {isPhone && <TabBar />}
    </div>
  );
}
