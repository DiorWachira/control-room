// Typed client for the Control Room engine API.

export type TierState = "inactive" | "pending" | "cooling" | "firing";

export interface TierRow {
  id: string; name: string; severity: "page" | "ticket"; threshold: number;
  long: string; short: string; long_rate: number | null; short_rate: number | null; state: TierState;
}
export interface SloRow {
  id: string; name: string; objective: number; informational: boolean;
  remaining: number | null; error_ratio: Record<string, number | null>; burn: Record<string, number | null>;
  tte_seconds: number | null; drain_per_min: number; gate: { floor: number; armed: boolean }; tiers: TierRow[];
}
export interface ServiceRow {
  id: string; name: string; callsign: string; description: string;
  state: "nominal" | "ticket" | "page" | "breach"; slos: SloRow[];
}
export interface Frame { at: string; services: ServiceRow[] }

export interface TimelineEvent { at: string; source: string; text: string; meta: string; key: boolean; kind: string }
export interface Incident {
  id: string; service: string; slo: string; class: "page" | "ticket"; title: string; priority: string;
  status: "firing" | "monitoring" | "resolved"; opened_at: string; resolved_at: string | null; quiet_since: string | null;
  firing: string[]; sla: { respond_by: string; resolve_by: string; responded_at: string | null };
  timeline?: TimelineEvent[]; context?: { remaining: number | null; burn: Record<string, number | null>; error_ratio: Record<string, number | null> };
}
export interface Replay {
  start: string; end: string; step_s: number; frames: Frame[];
  history: Record<string, { at: string; remaining: number }[]>; incidents: Incident[];
}
export interface Day { date: string; status: "nominal" | "burning" | "outage" | "cold" | "nodata"; burn: number; note: string }
export interface StatusService {
  id: string; name: string; description: string; state: "nominal" | "degraded" | "outage" | "nosignal";
  uptime_90d: number | null; days: Day[]; objectives: { name: string; objective: number }[];
  last_probe?: string | null; url?: string | null;
}
export interface Status {
  mode: "replay" | "probes" | "live"; at: string; services: StatusService[]; since?: string | null; interval?: string;
  active: (Incident & { last: TimelineEvent | null })[];
  history: { id: string; service: string; title: string; start: string; end: string | null; status: string; detail: string }[];
}
export interface IncidentDetail extends Incident {
  service_name: string; slo_name: string; objective: number; now: string; remaining_now: number | null;
  gate: { floor: number; armed: boolean }; trace: { at: string; h1: number | null; m5: number | null }[];
  timeline: TimelineEvent[];
  context: NonNullable<Incident["context"]>;
  replay?: boolean;
  postmortem: {
    summary: string; impact: string; root_cause: string; timeline: string[]; action_items: { text: string; done: boolean }[]; markdown: string; published: boolean;
    refined?: { summary: string; probable_cause: string; evidence: string[]; follow_ups: string[]; model: string; label: string };
  };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// The public demo (GitHub Pages) has no engine: `VITE_STATIC=1` builds read the replay that
// `python -m controlroom.export` froze into dist/api/*.json at build time.
export const STATIC = import.meta.env?.VITE_STATIC === "1";
export const apiUrl = (path: string) =>
  STATIC ? `${import.meta.env.BASE_URL}${path.replace(/^\//, "").split("?")[0]}.json` : path;

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(apiUrl(path), { signal, headers: { Accept: "application/json" } });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

// ---- formatting -------------------------------------------------------------
const EAT_OFFSET = 3 * 3600 * 1000;
const pad = (n: number) => String(n).padStart(2, "0");

export function eatTime(iso: string, seconds = false): string {
  const d = new Date(new Date(iso).getTime() + EAT_OFFSET);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}${seconds ? ":" + pad(d.getUTCSeconds()) : ""}`;
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function eatDay(iso: string): string {
  const d = new Date(new Date(iso).getTime() + EAT_OFFSET);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}
export function dateLabel(isoDate: string): string {
  const [, m, d] = isoDate.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
}
export const pct = (x: number | null | undefined, dp = 1) => (x == null ? "—" : `${(x * 100).toFixed(dp)}%`);
export const rate = (x: number | null | undefined) => (x == null ? "—" : x >= 10 ? `${x.toFixed(1)}×` : `${x.toFixed(2)}×`);
export function duration(seconds: number | null): string {
  if (seconds == null) return "outlasts window";
  // Whole minutes first: (h % 1) * 60 on a float turned 10 h 38 m into "10 h 37 m".
  const mins = Math.floor(seconds / 60), h = Math.floor(mins / 60);
  if (h >= 48) return `${Math.floor(h / 24)} d ${h % 24} h`;
  return `${h} h ${pad(mins % 60)} m`;
}
export const objective = (o: number) => `${+(o * 100).toFixed(2)}%`;
/** "4 min ago", "3 h ago", "2 d ago" from two instants. */
export function ago(iso: string, nowMs: number): string {
  const m = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.floor(m / 60)} h ago`;
  return `${Math.floor(m / 1440)} d ago`;
}
