import { useEffect } from "react";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { Toasts } from "./components/Toasts";
import { DashboardPage } from "./pages/DashboardPage";
import { TradePage } from "./pages/TradePage";
import { InboxPage } from "./pages/InboxPage";
import { PortfoliosPage } from "./pages/PortfoliosPage";
import { JournalPage } from "./pages/JournalPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useStore } from "./store";

export default function App() {
  const page = useStore((s) => s.page);
  const halt = useStore((s) => s.halt);
  const driftWarnings = useStore((s) => s.driftWarnings);
  const openJournal = useStore((s) => s.openJournal);
  const dismissDrift = useStore((s) => s.dismissDrift);
  const setPage = useStore((s) => s.setPage);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const accent = useStore((s) => s.settings["ui.accent"] ?? "#5b8cff");
  const density = useStore((s) => s.settings["ui.density"] ?? "comfortable");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.density = density;
    document.documentElement.style.setProperty("--accent", accent);
  }, [theme, accent, density]);

  return (
    <div className="app">
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
      <div className="main">
        <Sidebar />
        <div className="content">
          {page === "dashboard" && <DashboardPage />}
          {page === "trade" && <TradePage />}
          {page === "inbox" && <InboxPage />}
          {page === "portfolios" && <PortfoliosPage />}
          {page === "journal" && <JournalPage />}
          {page === "settings" && <SettingsPage />}
        </div>
      </div>
      <Toasts />
    </div>
  );
}
