import { useEffect, useState } from "react";
import { MarkLamps, NotFound } from "./components";
import { GuideLayer, HelpDrawer, Invite, useGuide } from "./Guide";
import { store, useNow, useRoute } from "./hooks";
import { BudgetsScreen } from "./screens/BudgetsScreen";
import { IncidentScreen } from "./screens/IncidentScreen";
import { StatusScreen } from "./screens/StatusScreen";

const pad = (n: number) => String(n).padStart(2, "0");
function clock(ms: number, offsetH: number) {
  const d = new Date(ms + offsetH * 3600_000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

export function App() {
  const route = useRoute();
  const now = useNow();
  const g = useGuide();
  const [help, setHelp] = useState(false);
  const [down, setDown] = useState(() => document.documentElement.dataset.lights === "down");

  useEffect(() => {
    document.documentElement.dataset.lights = down ? "down" : "up";
    store.set("cr.lights", down ? "down" : "up");
  }, [down]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "?") { e.preventDefault(); setHelp(true); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  useEffect(() => {
    const titles = { status: "Status", budgets: "Budget wall", incident: route.name === "incident" ? route.id : "", missing: "Loss of signal" };
    document.title = `${titles[route.name]} · Control Room`;
  }, [route]);

  const current = (name: string) => (route.name === name ? "page" : undefined);

  return (
    <>
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      <header className="overhead on-board">
        <div className="wrap overhead-in">
          <a className="mark" href="#/"><MarkLamps />Control Room</a>
          <nav className="nav" aria-label="Screens" data-guide="nav">
            <a href="#/" aria-current={current("status")}>Status</a>
            <a href="#/budgets" aria-current={current("budgets")}>Budgets</a>
            <a href="#/incidents/RSV-1042" aria-current={current("incident")}>RSV-1042</a>
          </nav>
          <div className="overhead-right">
            <div className="clock"><span className="label">Nairobi · EAT</span><span className="mono">{clock(now, 3)}</span></div>
            <button className="okey" type="button" aria-pressed={down} onClick={() => setDown(!down)}><span className="knob" aria-hidden="true" /><span className="long">House lights</span><span className="short-l">Lights</span> {down ? "down" : "up"}</button>
            <button className="okey" type="button" data-guide="guide-key" onClick={() => setHelp(true)}>Guide <kbd>?</kbd></button>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} style={{ outline: "none" }}>
        {route.name === "status" && <StatusScreen />}
        {route.name === "budgets" && <BudgetsScreen />}
        {route.name === "incident" && <IncidentScreen key={route.id} id={route.id} />}
        {route.name === "missing" && <NotFound path={route.path} />}
      </main>
      <footer className="wrap mono muted" style={{ fontSize: 13, paddingBottom: 40 }}>
        Control Room · built and on call: Dior Wachira, Nairobi · engine replay of Sun 8 Nov 2026 until live telemetry is wired
      </footer>
      <Invite g={g} />
      <GuideLayer g={g} />
      <HelpDrawer open={help} onClose={() => setHelp(false)} g={g} />
    </>
  );
}
