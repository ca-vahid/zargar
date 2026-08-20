import { useEffect, useState } from "react";
import { useStore } from "../store";

const MIN_SHOW_MS = 1400;
const MAX_SHOW_MS = 4000;

/** Golden splash on first load of the session — fades once the app is live. */
export function Splash() {
  const connected = useStore((s) => s.connected);
  const [phase, setPhase] = useState<"show" | "fade" | "gone">(() =>
    sessionStorage.getItem("zargar_splashed") ? "gone" : "show");
  const [bornAt] = useState(() => Date.now());

  useEffect(() => {
    if (phase !== "show") return;
    const ready = connected;
    const elapsed = Date.now() - bornAt;
    const wait = ready ? Math.max(0, MIN_SHOW_MS - elapsed) : MAX_SHOW_MS - elapsed;
    const t = setTimeout(() => {
      sessionStorage.setItem("zargar_splashed", "1");
      setPhase("fade");
      setTimeout(() => setPhase("gone"), 650);
    }, Math.max(0, wait));
    return () => clearTimeout(t);
  }, [phase, connected, bornAt]);

  if (phase === "gone") return null;
  return (
    <div className={`splash ${phase === "fade" ? "splash--fade" : ""}`} aria-hidden="true">
      <img className="splash-art" src="/art/splash-1600.webp" alt="" />
      <div className="splash-center">
        <img className="splash-logo" src="/art/logo-mark.png" alt="" />
        <div className="splash-word">Zar<em>gar</em></div>
        <div className="splash-tag">the goldsmith of your portfolio</div>
      </div>
    </div>
  );
}
