import { useEffect } from "react";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { Toasts } from "./components/Toasts";
import { TradePage } from "./pages/TradePage";
import { InboxPage } from "./pages/InboxPage";
import { PortfoliosPage } from "./pages/PortfoliosPage";
import { JournalPage } from "./pages/JournalPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useStore } from "./store";

export default function App() {
  const page = useStore((s) => s.page);
  const halt = useStore((s) => s.halt);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "dark");
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
      {halt.engaged && (
        <div className="halt-banner">
          KILL SWITCH ENGAGED — {halt.reason || "all order submission blocked"}
        </div>
      )}
      <div className="main">
        <Sidebar />
        <div className="content">
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
