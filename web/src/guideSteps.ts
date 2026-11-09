// The guide's steps. Each targets a [data-guide="…"] element on the screen at `hash`
// (empty hash = whatever screen is open). If a data-guide attribute moves, update it here;
// e2e/guide.spec.ts walks every step and fails if a target is missing.
// No imports on purpose: the e2e tests read this file under Node.
export type Step = { hash: string; target: string; title: string; body: string };

export const STEPS: Step[] = [
  { hash: "#/", target: "nav", title: "Three screens", body: "Status is the live public board for seven of Dior's apps. Budgets is the console wall, replaying a real outage from 8 November. RSV-1042 is that outage's incident. The guide walks you through each one." },
  { hash: "#/", target: "board", title: "The big board", body: "The public status page, fed by real probes every 15 minutes. One headline, one lamp per app. Lamps are the only colour in the room: white is fine, amber means budget is burning, red means breach." },
  { hash: "#/", target: "strips", title: "91 days, one bar each", body: "Raised amber days burned budget; raised red days hit page level; empty slots are days before probing began. Hover a bar, or focus the strip and use ← →, to read a day." },
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
