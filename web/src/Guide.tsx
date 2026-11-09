// First-run guide as a flight director's checklist: numbered CHECK cards that walk the
// room, spotlighting one panel at a time. Opt-in (NN/g: forced tutorials hurt), offered once.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { navigate, parseHash, store } from "./hooks";

type Step = { hash: string; target: string; title: string; body: string };

export const STEPS: Step[] = [
  { hash: "#/", target: "board", title: "The big board", body: "The public status page. One headline, one lamp per app. Lamps are the only colour in the room: white is fine, amber means budget is burning, red means breach." },
  { hash: "#/", target: "strips", title: "91 days, one bar each", body: "Raised amber days burned budget; raised red days hit page level. Hover a bar, or focus the strip and use ← →, to read a day." },
  { hash: "#/", target: "cold", title: "Waking is not down", body: "RepoLens sleeps on a free tier. A slow first answer inside the 50 s wake window is logged as a cold start and never spends budget." },
  { hash: "#/budgets", target: "controls", title: "Replay a real morning", body: "The wall replays 8 November minute by minute, computed by the engine. Hold, Replay and Lamp test are here. Master caution flashes on anything new; press it to acknowledge." },
  { hash: "#/budgets", target: "tank", title: "The budget tank", body: "Each console's tank is what's left of a 28-day error budget. The flow ticks speed up with the burn. The dashed line is the deploy-gate floor." },
  { hash: "#/budgets", target: "meters", title: "Two windows must agree", body: "The 5-minute bar reacts at once; the 1-hour bar is slow. A tier fires only when both pass the line. That is why a two-minute blip never pages." },
  { hash: "#/budgets", target: "strip", title: "Incidents slide in", body: "When a page tier fires, Control Room opens a Resolve ticket, pages Dior and the incident slides in from the edge. Its timeline grows as the replay runs." },
  { hash: "#/budgets", target: "gate", title: "The deploy gate", body: "Below the floor, the GitHub Action fails deploys. To override, lift the cover first, then flip emergency-fix: two moves, so it can't happen by accident." },
  { hash: "#/incidents/RSV-1042", target: "trace", title: "The burn trace", body: "Long and short windows on a log scale. The amber band is when both were over 14.4×. Numbered pins match the loop below." },
  { hash: "#/incidents/RSV-1042", target: "postmortem", title: "A draft, never auto-published", body: "When the incident closes, the timeline becomes a blameless postmortem draft with the root cause left for a human to confirm." },
  { hash: "", target: "guide-key", title: "Reopen any time", body: "This checklist lives behind the Guide key. Press ? anywhere for the help drawer: glossary, keyboard map and how the pipeline works." },
];

const SEEN = "cr.guide.seen";

function waitFor(sel: string, ms = 4000): Promise<Element | null> {
  return new Promise((res) => {
    const t0 = performance.now();
    const tick = () => {
      const el = document.querySelector(sel);
      if (el) return res(el);
      if (performance.now() - t0 > ms) return res(null);
      requestAnimationFrame(tick);
    };
    tick();
  });
}

export function useGuide() {
  const [step, setStep] = useState<number | null>(null);
  const [steps, setSteps] = useState<Step[]>(STEPS);
  const [invite, setInvite] = useState(() => store.get(SEEN) == null);
  const start = useCallback((only?: Step[]) => { store.set(SEEN, "1"); setInvite(false); setSteps(only ?? STEPS); setStep(0); }, []);
  const dismissInvite = useCallback(() => { store.set(SEEN, "1"); setInvite(false); }, []);
  return { step, steps, setStep, start, invite, dismissInvite, close: () => setStep(null) };
}

export function GuideLayer({ g }: { g: ReturnType<typeof useGuide> }) {
  const { step, steps, setStep, close } = g;
  const [rect, setRect] = useState<DOMRect | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const s = step == null ? null : steps[step];

  // Navigate to the step's screen, wait for its target, scroll it under the sticky header.
  useEffect(() => {
    if (!s) return;
    let alive = true;
    if (s.hash && parseHash(location.hash).name !== parseHash(s.hash).name) navigate(s.hash);
    waitFor(`[data-guide="${s.target}"]`).then((el) => {
      if (!alive) return;
      if (!el) { setRect(null); return; }
      const header = (document.querySelector(".overhead") as HTMLElement | null)?.getBoundingClientRect().height ?? 0;
      const sticky = getComputedStyle(document.querySelector(".overhead") ?? document.body).position === "sticky" ? header : 0;
      const top = el.getBoundingClientRect().top + window.scrollY - sticky - 24;
      window.scrollTo({ top: Math.max(0, top), behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      setTimeout(() => alive && setRect(el.getBoundingClientRect()), 350);
    });
    return () => { alive = false; };
  }, [s]);

  // Track the target on scroll and resize.
  useEffect(() => {
    if (!s) return;
    const on = () => { const el = document.querySelector(`[data-guide="${s.target}"]`); setRect(el ? el.getBoundingClientRect() : null); };
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on); };
  }, [s]);

  // Focus into the card; return focus to the opener on close.
  useLayoutEffect(() => {
    if (step != null) {
      if (!opener.current) opener.current = document.activeElement;
      card.current?.querySelector<HTMLElement>("[data-primary]")?.focus();
    } else if (opener.current) {
      (opener.current as HTMLElement).focus?.();
      opener.current = null;
    }
  }, [step]);

  if (!s || step == null) return null;
  const n = steps.length;
  const next = () => (step + 1 < n ? setStep(step + 1) : close());
  const back = () => step > 0 && setStep(step - 1);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); next(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
    else if (e.key === "Tab") {
      const f = card.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (!f || !f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };

  const pad = 8;
  const ring = rect ? { left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 } : null;
  const vw = window.innerWidth, vh = window.innerHeight, cw = Math.min(380, vw - 32);
  let pos: React.CSSProperties = { left: (vw - cw) / 2, top: vh / 2 - 120 };
  if (ring) {
    const below = ring.top + ring.height + 16, above = ring.top - 16 - 260;
    const top = below + 260 < vh ? below : above > 0 ? above : Math.max(16, vh - 300);
    pos = { left: Math.max(16, Math.min(ring.left, vw - cw - 16)), top };
  }

  return (
    <>
      {ring ? <div className="veil-ring" style={ring} aria-hidden="true" /> : <div className="drawer-veil" style={{ zIndex: 60 }} aria-hidden="true" />}
      <div className="gcard on-board" ref={card} role="dialog" aria-modal="false" aria-labelledby="g-title" onKeyDown={onKey} style={pos}>
        <div className="gcard-head">
          <span className="label">Check {step + 1} / {n}</span>
          <button className="xkey" type="button" onClick={close} aria-label="Close guide">×</button>
        </div>
        <div className="gcard-body">
          <h2 id="g-title">{s.title}</h2>
          <p aria-live="polite">{s.body}</p>
          <div className="gprog" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }} aria-hidden="true">
            {steps.map((_, k) => <span key={k} className={k <= step ? "on" : ""} />)}
          </div>
          <div className="gfoot">
            <button className="bkey" type="button" onClick={back} disabled={step === 0}>Back</button>
            <button className="bkey" type="button" data-primary onClick={next}>{step + 1 < n ? "Next" : "Finish"}</button>
          </div>
        </div>
      </div>
    </>
  );
}

export function Invite({ g }: { g: ReturnType<typeof useGuide> }) {
  if (!g.invite || g.step != null) return null;
  return (
    <div className="invite on-board" role="region" aria-label="Guide invitation">
      <p className="label" style={{ margin: 0, color: "var(--board-mute)" }}>First time in the room?</p>
      <p style={{ margin: "6px 0 12px" }}>Take the 11-step walk through the consoles. About two minutes.</p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button className="bkey" type="button" onClick={() => g.start()}>Start</button>
        <button className="bkey" type="button" onClick={g.dismissInvite}>Not now</button>
      </div>
    </div>
  );
}

export function HelpDrawer({ open, onClose, g }: { open: boolean; onClose: () => void; g: ReturnType<typeof useGuide> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) ref.current?.querySelector<HTMLElement>("button")?.focus(); }, [open]);
  if (!open) return null;
  const here = parseHash(location.hash).name;
  const screenSteps = STEPS.filter((s) => s.hash && parseHash(s.hash).name === here);
  return (
    <>
      <div className="drawer-veil" onClick={onClose} aria-hidden="true" />
      <div className="drawer" ref={ref} role="dialog" aria-modal="true" aria-labelledby="help-h" onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <h2 id="help-h">Flight manual</h2>
          <button className="key" type="button" onClick={onClose} aria-label="Close help">×</button>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
          <button className="key" type="button" onClick={() => { onClose(); g.start(); }}>Full tour</button>
          <button className="key" type="button" disabled={!screenSteps.length} onClick={() => { onClose(); g.start(screenSteps); }}>Tour this screen</button>
        </div>
        <h3>How it works</h3>
        <ol className="pipe">
          <li>Probes and OpenTelemetry count good and bad events in Resolve, RepoLens and JobBridge.</li>
          <li>Prometheus stores them; the engine asks it for error ratios over six windows every minute.</li>
          <li>Burn rate = error ratio ÷ (1 − objective). A tier fires when its long and short windows both pass the threshold.</li>
          <li>A firing tier opens one Resolve ticket with the SLA clock running, and pages Dior on Telegram.</li>
          <li>Everything lands on the incident's timeline; when it closes, the timeline becomes a postmortem draft.</li>
          <li>GitHub Actions ask /budget/&#123;service&#125; before deploying and fail under the floor.</li>
        </ol>
        <h3>Glossary</h3>
        <dl>
          <dt>SLI</dt><dd>Good events ÷ valid events, e.g. scans that finished ÷ scans started.</dd>
          <dt>SLO</dt><dd>The target for an SLI over 28 days, e.g. 99.5%.</dd>
          <dt>Error budget</dt><dd>The failures the SLO allows: 0.5% of scans at 99.5%.</dd>
          <dt>Burn rate</dt><dd>How fast the budget is being spent. 1× empties it in exactly 28 days; 14.4× in under two.</dd>
          <dt>Fast / slow burn</dt><dd>Page tiers: 14.4× over 1 h and 5 m, or 6× over 6 h and 30 m.</dd>
          <dt>Ticket tier</dt><dd>1× over 3 days and 6 hours. Opens a low-priority ticket, never pages.</dd>
          <dt>Cold start</dt><dd>A sleeping app waking up inside its wake window. Logged, never counted.</dd>
          <dt>Deploy gate</dt><dd>Budget floor below which deploys fail unless the PR is labelled emergency-fix.</dd>
        </dl>
        <h3>Keys</h3>
        <dl className="keys">
          <dt><kbd>?</kbd></dt><dd>Open this manual</dd>
          <dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Previous / next guide step; read days on a strip</dd>
          <dt><kbd>Esc</kbd></dt><dd>Close the guide or this manual</dd>
        </dl>
      </div>
    </>
  );
}
