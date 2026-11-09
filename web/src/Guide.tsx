// First-run guide as a flight director's checklist: numbered CHECK bubbles that walk the
// room, spotlighting one panel at a time and pointing at it with a caret. Opt-in (NN/g:
// forced tutorials hurt), offered once. Placement: below, above, right, left of the panel,
// else inside it; on phones the bubble docks to the screen edge away from the panel.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { STEPS, type Step } from "./guideSteps";
import { navigate, parseHash, store } from "./hooks";

export { STEPS };


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
  const [cardSize, setCardSize] = useState({ w: 380, h: 280 });

  // Measure the bubble so placement uses its real height (copy length varies per step).
  useLayoutEffect(() => {
    const el = card.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    if (Math.abs(w - cardSize.w) > 1 || Math.abs(h - cardSize.h) > 1) setCardSize({ w, h });
  });

  // Navigate to the step's screen, wait for its target, scroll it under the sticky header.
  useEffect(() => {
    if (!s) return;
    let alive = true;
    if (s.hash && parseHash(location.hash).name !== parseHash(s.hash).name) navigate(s.hash);
    waitFor(`[data-guide="${s.target}"]`).then((el) => {
      if (!alive) return;
      if (!el) { setRect(null); return; }
      const top = el.getBoundingClientRect().top + window.scrollY - stickyHeight() - 24;
      window.scrollTo({ top: Math.max(0, top), behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      // Overlapping smooth scrolls (fast Next presses) can land off target: once settled,
      // nudge the panel back to just under the header, then spotlight it.
      setTimeout(() => {
        if (!alive) return;
        const off = el.getBoundingClientRect().top - stickyHeight() - 24;
        const room = document.documentElement.scrollHeight - innerHeight - window.scrollY;
        if (Math.abs(off) > 4 && (off < 0 ? window.scrollY > 0 : room > 0)) window.scrollBy({ top: off, behavior: "auto" });
        setRect(el.getBoundingClientRect());
      }, 450);
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

  const { ring, pos, side, caret } = place(rect, cardSize);
  return (
    <>
      {ring ? <div className="veil-ring" style={ring} aria-hidden="true" /> : <div className="drawer-veil" style={{ zIndex: 60 }} aria-hidden="true" />}
      <div className={`gcard on-board side-${side}`} ref={card} role="dialog" aria-modal="false" aria-labelledby="g-title"
        onKeyDown={onKey} style={{ ...pos, ["--caret" as string]: `${caret}px` }} data-testid="guide-bubble">
        {(side === "below" || side === "above" || side === "right" || side === "left") && <span className="gcaret" aria-hidden="true" />}
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

type Side = "below" | "above" | "right" | "left" | "inside" | "dock" | "none";
const GAP = 18, EDGE = 16, PAD = 8;

// Where the bubble goes, given the target's rect and the bubble's measured size.
export function place(rect: DOMRect | null, size: { w: number; h: number }) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const top0 = stickyHeight();
  const w = size.w, h = size.h;
  if (!rect) return { ring: null, pos: { left: (vw - w) / 2, top: Math.max(EDGE, (vh - h) / 2) } as React.CSSProperties, side: "none" as Side, caret: 0 };
  const ring = { left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 };
  const r = { l: ring.left, t: ring.top, rt: ring.left + ring.width, b: ring.top + ring.height };
  const cx = (Math.max(r.l, 0) + Math.min(r.rt, vw)) / 2;
  const cy = (Math.max(r.t, top0) + Math.min(r.b, vh)) / 2;
  const clampX = (x: number) => Math.max(EDGE, Math.min(x, vw - w - EDGE));
  const clampY = (y: number) => Math.max(top0 + EDGE, Math.min(y, vh - h - EDGE));

  if (vw <= 560) {
    // Phones: dock to whichever edge is away from the panel, full width, no caret.
    const dockTop = cy > vh / 2;
    return { ring, pos: dockTop ? { left: EDGE, right: EDGE, top: top0 + EDGE } : { left: EDGE, right: EDGE, bottom: EDGE }, side: "dock" as Side, caret: 0 };
  }
  if (r.b + GAP + h <= vh - EDGE && r.b > 0) {
    const left = clampX(cx - w / 2);
    return { ring, pos: { left, top: r.b + GAP }, side: "below" as Side, caret: Math.max(20, Math.min(cx - left, w - 20)) };
  }
  if (r.t - GAP - h >= top0 + EDGE && r.t <= vh) {
    const left = clampX(cx - w / 2);
    return { ring, pos: { left, top: r.t - GAP - h }, side: "above" as Side, caret: Math.max(20, Math.min(cx - left, w - 20)) };
  }
  if (r.rt + GAP + w <= vw - EDGE) {
    const top = clampY(cy - h / 2);
    return { ring, pos: { left: r.rt + GAP, top }, side: "right" as Side, caret: Math.max(20, Math.min(cy - top, h - 20)) };
  }
  if (r.l - GAP - w >= EDGE) {
    const top = clampY(cy - h / 2);
    return { ring, pos: { left: r.l - GAP - w, top }, side: "left" as Side, caret: Math.max(20, Math.min(cy - top, h - 20)) };
  }
  // The panel fills the screen: sit inside its visible part, bottom right.
  return { ring, pos: { left: clampX(Math.min(r.rt, vw) - w - 24), top: clampY(Math.min(r.b, vh) - h - 24) }, side: "inside" as Side, caret: 0 };
}

function stickyHeight(): number {
  const el = document.querySelector<HTMLElement>(".overhead");
  if (!el || getComputedStyle(el).position !== "sticky") return 0;
  return el.getBoundingClientRect().bottom;
}

export function Invite({ g }: { g: ReturnType<typeof useGuide> }) {
  if (!g.invite || g.step != null) return null;
  return (
    <div className="invite on-board" role="region" aria-label="Guide invitation" data-testid="guide-invite">
      <p className="label" style={{ margin: 0, color: "var(--board-mute)" }}>First time in the room?</p>
      <p style={{ margin: "6px 0 12px" }}>Take the {STEPS.length}-step walk through the screens and consoles. About two minutes.</p>
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
