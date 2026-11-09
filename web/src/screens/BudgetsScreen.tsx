import { useEffect, useMemo, useRef, useState } from "react";
import { duration, eatTime, pct, rate, type Frame, type Incident, type Replay, type ServiceRow, type SloRow } from "../api";
import { Lamp, Loaded, type LampColour } from "../components";
import { useData, useReducedMotion } from "../hooks";

const TICK_MS = 250; // one replay minute per tick: 1 s = 4 min
const logPos = (b: number | null) => Math.max(0, Math.min(100, ((Math.log10(Math.max(b ?? 0.1, 0.1)) + 1) / 3) * 100));
const THR = logPos(14.4);
const SHORT: Record<string, string> = { "api-latency": "Latency", "auth-availability": "Sign-in" };

const primary = (s: ServiceRow) => s.slos.find((o) => !o.informational)!;
const secondary = (s: ServiceRow) => s.slos.find((o, i) => i > 0 && o !== primary(s));

function litKeys(f: Frame): string[] {
  const keys: string[] = [];
  for (const s of f.services) for (const o of s.slos) {
    if (o.informational) continue;
    for (const t of o.tiers) if (t.state === "firing") keys.push(`${s.id}/${o.id}/${t.id}`);
    if (o.gate.armed) keys.push(`${s.id}/${o.id}/gate`);
  }
  return keys;
}

export function BudgetsScreen() {
  const load = useData<Replay>("/api/replay");
  return <Loaded load={load} what="the budget wall">{(rp) => <Wall rp={rp} />}</Loaded>;
}

function Wall({ rp }: { rp: Replay }) {
  const last = rp.frames.length - 1;
  const [i, setI] = useState(0);
  const [held, setHeld] = useState(false);
  const [acked, setAcked] = useState<string[]>(() => litKeys(rp.frames[0]));
  const [test, setTest] = useState(false);
  const [cover, setCover] = useState(false);
  const [override, setOverride] = useState(false);
  const [hoverDay, setHoverDay] = useState<number | null>(null);
  const testTimer = useRef<number>(0);
  const tlRef = useRef<HTMLOListElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (held || i >= last) return;
    const t = window.setTimeout(() => setI((x) => Math.min(last, x + 1)), reduced ? TICK_MS * 2 : TICK_MS);
    return () => window.clearTimeout(t);
  }, [i, held, last, reduced]);
  useEffect(() => () => window.clearTimeout(testTimer.current), []);

  const f = rp.frames[i];
  // Keep the newest loop entry in view as the timeline grows.
  useEffect(() => { const el = tlRef.current; if (el) el.scrollLeft = el.scrollWidth; });
  const at = new Date(f.at).getTime();
  const lit = litKeys(f);
  const unacked = lit.filter((k) => !acked.includes(k));
  const mcLit = unacked.length > 0 && !test;

  const incidents = rp.incidents.filter((x) => x.class === "page" && new Date(x.opened_at).getTime() <= at);
  const inc = incidents[incidents.length - 1];
  const events = (inc?.timeline ?? []).filter((e) => new Date(e.at).getTime() <= at);
  const incFiring = inc ? f.services.some((s) => s.id === inc.service && s.slos.some((o) => o.id === inc.slo && o.tiers.some((t) => t.severity === "page" && t.state === "firing"))) : false;
  const coldNow = (rp.incidents.flatMap((x) => x.timeline ?? [])).some((e) => e.meta === "probe cold_start" && Math.abs(new Date(e.at).getTime() - at) <= 90_000);

  const repo = f.services.find((s) => s.id === "repolens");
  const burning = f.services.find((s) => primary(s).tiers.some((t) => t.severity === "page" && t.state === "firing"));
  const headline = burning ? `${burning.name} burning ${rate(primary(burning).burn["1h"])} budget`
    : inc ? `Alert reset · ${f.services.find((s) => s.id === inc.service)?.name} recovering` : "Three budgets, one burning slowly";

  // ---- big-board chart: 28 days of remaining budget, last point live --------
  const series = f.services.map((s) => {
    const hist = rp.history[s.id] ?? [];
    const vals = hist.map((h, d) => (d === hist.length - 1 ? primary(s).remaining ?? h.remaining : h.remaining));
    const pts = vals.map((v, d) => `${((d / (vals.length - 1)) * 900).toFixed(1)},${(300 - v * 300).toFixed(1)}`).join(" ");
    const isBurning = primary(s).tiers.some((t) => t.severity === "page" && t.state === "firing");
    return { s, vals, pts, isBurning, end: vals[vals.length - 1] };
  });
  const labelYs = series.map((x) => 300 - x.end * 300 + 5).map((y, k, ys) => {
    for (let j = 0; j < k; j++) if (Math.abs(ys[j] - y) < 16) return y + (ys[j] <= y ? 16 : -16);
    return y;
  });
  const days = series[0]?.vals.length ?? 29;
  const dayLabel = (d: number) => { const dt = new Date(new Date(rp.start).getTime() - (days - 1 - d) * 86400_000 + 3 * 3600_000); return `${dt.getUTCDate()} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.getUTCMonth()]}`; };
  const agedOut = series.reduce<{ name: string; points: number; day: number } | null>((best, x) => {
    for (let d = 1; d < x.vals.length - 1; d++) {
      const jump = (x.vals[d] - x.vals[d - 1]) * 100;
      if (jump > 5 && (!best || jump > best.points)) best = { name: x.s.name, points: jump, day: d };
    }
    return best;
  }, null);
  const readout = hoverDay == null ? "Hover the board for a day's reading" : `${dayLabel(hoverDay)} · ` + series.map((x) => `${x.s.name} ${pct(x.vals[hoverDay])}`).join(" · ");

  const lamp = (on: boolean, colour: LampColour, key?: string): { colour: LampColour; flash: boolean } =>
    test ? { colour: "white", flash: false } : { colour: on ? colour : "", flash: !!(on && key && unacked.includes(key)) };

  return (
    <div className="wrap" style={{ paddingTop: 30, paddingBottom: 72 }}>
      <section className="board on-board" aria-labelledby="bb-h">
        <div className="board-in">
          <div className="board-top">
            <div>
              <p className="label muted" style={{ margin: 0 }}>Big board · error budget remaining · 28-day rolling window</p>
              <h1 id="bb-h" className="hero-h" style={{ fontSize: "clamp(40px, 5vw, 60px)" }}>{headline}</h1>
              <p className="muted" style={{ margin: 0, maxWidth: "62ch" }}>
                Replaying Sunday 8 November, {eatTime(rp.start)}–{eatTime(rp.end)} EAT, computed by the engine minute by minute.
                Watch RepoLens's budget drain, the page wait until both windows agree, and the short window reset the alert once the fix lands.
              </p>
            </div>
            <div className="controls" data-guide="controls">
              <button className={`mc${mcLit ? " is-lit" : ""}`} type="button" onClick={() => setAcked(lit)}
                aria-label={mcLit ? `Master caution lit: ${unacked.length} new. Press to acknowledge.` : "Master caution off"}>Master<br />caution</button>
              <button className="bkey" type="button" aria-pressed={held} onClick={() => setHeld((h) => !h)}>{held ? "Resume" : "Hold"}</button>
              <button className="bkey" type="button" onClick={() => { setI(0); setAcked(litKeys(rp.frames[0])); setCover(false); setOverride(false); setHeld(false); }}>Replay</button>
              <button className="bkey" type="button" onClick={() => { window.clearTimeout(testTimer.current); setTest(true); testTimer.current = window.setTimeout(() => setTest(false), 1800); }}>Lamp test</button>
            </div>
          </div>

          <svg className="chart" viewBox="0 0 1000 300" role="img" aria-label={`Error budget remaining over 28 days. ${series.map((x) => `${x.s.name} ${pct(x.end)}`).join(", ")}.`} onMouseLeave={() => setHoverDay(null)}>
            <line x1="0" y1="150" x2="1000" y2="150" stroke="var(--board-rule)" />
            <line x1="0" y1="300" x2="1000" y2="300" stroke="var(--board-mute)" strokeWidth="1.5" />
            <text x="4" y="144" fill="var(--board-mute)" fontFamily="Share Tech Mono" fontSize="12">50%</text>
            {hoverDay != null && <line x1={(hoverDay / (days - 1)) * 900} y1="0" x2={(hoverDay / (days - 1)) * 900} y2="300" stroke="var(--board-ink)" />}
            {series.map((x, k) => (
              <g key={x.s.id}>
                <polyline points={x.pts} fill="none" stroke={x.s.id === "jobbridge" ? "var(--board-mute)" : x.isBurning ? "var(--lamp-amber)" : "var(--board-ink)"}
                  strokeWidth={x.s.id === "repolens" ? 4 : 2} strokeDasharray={x.s.id === "jobbridge" ? "7 4" : undefined} strokeLinejoin="round" />
                <circle cx="900" cy={300 - x.end * 300} r="6" fill={x.isBurning ? "var(--lamp-amber)" : "var(--board-ink)"} stroke="var(--board)" strokeWidth="2" />
                <text className="lbl" x="912" y={labelYs[k]} fill="var(--board-ink)" fontFamily="Barlow Condensed" fontWeight="600" fontSize="15" letterSpacing="1">{x.s.name.toUpperCase()} {pct(x.end)}</text>
              </g>
            ))}
            {Array.from({ length: days }, (_, d) => (
              <rect key={d} x={(d / (days - 1)) * 900 - 16} y="0" width="32" height="300" fill="transparent" onMouseEnter={() => setHoverDay(d)} />
            ))}
          </svg>
          <div className="mono muted" style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginRight: "10%" }}><span>{dayLabel(0)}</span><span>{dayLabel(14)}</span><span>{dayLabel(days - 1)}</span></div>
          <div className="legend" style={{ marginTop: 10 }}>
            <span><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" stroke="var(--board-ink)" strokeWidth="2" /></svg> Resolve</span>
            <span><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" stroke="var(--board-ink)" strokeWidth="4" /></svg> RepoLens (amber while a page tier fires)</span>
            <span><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" stroke="var(--board-mute)" strokeWidth="2" strokeDasharray="7 4" /></svg> JobBridge</span>
          </div>
          <div className="readout">{readout}</div>
          {agedOut && <p className="muted" style={{ margin: "6px 0 0", fontSize: 14, maxWidth: "75ch" }}>Fig. A rolling window forgets: {agedOut.name} regained {agedOut.points.toFixed(0)} points on {dayLabel(agedOut.day)} when an old incident aged out of the 28 days.</p>}
          <label className="label muted" htmlFor="scrub" style={{ display: "block", marginTop: 12 }}>Replay clock · {eatTime(f.at)} EAT</label>
          <input id="scrub" className="scrub" type="range" min={0} max={last} value={i} onChange={(e) => { setHeld(true); setI(Number(e.target.value)); }}
            aria-valuetext={`${eatTime(f.at)} EAT`} />
        </div>
      </section>

      <section className="strip-slot" aria-label="Incident loop" data-guide="strip">
        <p className="sr" aria-live="polite">{inc ? `Incident ${inc.id} open for ${inc.service}.` : ""}</p>
        {inc ? (
          <div className={`istrip on-board${incFiring ? "" : " is-calm"}`} key={inc.id}>
            <div>
              <p className="label muted" style={{ margin: 0 }}>Incident loop · {incFiring ? "firing" : "monitoring"}</p>
              <p className="cond" style={{ margin: "6px 0 2px", fontSize: 40, fontWeight: 700, lineHeight: 1, letterSpacing: ".03em" }}>{inc.id}</p>
              <p style={{ margin: "0 0 12px" }}>{inc.title}</p>
              <a className="bkey" href={`#/incidents/${inc.id}`}>Open incident →</a>
            </div>
            <ol className="tl" aria-label="Incident timeline so far" ref={tlRef}>
              {events.map((e) => (
                <li key={e.at + e.text} className={e.key ? "is-key" : ""}>
                  <span className="mono" style={{ fontSize: 15 }}>{eatTime(e.at)}</span>
                  <span className="label muted" style={{ display: "block", fontSize: 11 }}>{e.source}</span>
                  <span style={{ display: "block", fontSize: 14, lineHeight: 1.35 }}>{e.text}</span>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <div className="quiet"><Lamp>Loop quiet</Lamp><span>No open page-tier incidents. {rp.incidents.some((x: Incident) => x.class === "ticket") ? "A ticket-tier alert is open for JobBridge." : ""}</span></div>
        )}
      </section>

      <section className="wall" aria-label="Service consoles">
        {f.services.map((s) => {
          const o = primary(s);
          const second = secondary(s);
          const fast = o.tiers.find((t) => t.id === "page-1h")!, slow = o.tiers.find((t) => t.id === "page-6h")!, ticket = o.tiers.find((t) => t.id === "ticket-3d")!;
          const fallback = s.id === "repolens" ? s.slos.find((x) => x.id === "examiner-fallback")?.error_ratio["5m"] ?? null : null;
          const breach = (o.remaining ?? 1) <= 0;
          const lamps = [
            { name: "Fast burn", sub: "1h·5m ≥14.4", on: fast.state === "firing", ...lamp(fast.state === "firing", "amber", `${s.id}/${o.id}/page-1h`) },
            { name: "Slow burn", sub: "6h·30m ≥6", on: slow.state === "firing", ...lamp(slow.state === "firing", "amber", `${s.id}/${o.id}/page-6h`) },
            { name: "Ticket", sub: "3d·6h ≥1", on: ticket.state === "firing", ...lamp(ticket.state === "firing", "amber", `${s.id}/${o.id}/ticket-3d`) },
            s.id === "repolens" ? { name: "Waking", sub: "cold start", on: coldNow, ...lamp(coldNow, "white") } : { name: "Probe", sub: "synthetic ok", on: true, ...lamp(true, "white") },
            s.id === "repolens" ? { name: "Fallback", sub: "LLM > 10%", on: (fallback ?? 0) > 0.1, ...lamp((fallback ?? 0) > 0.1, "white") }
              : { name: second ? (SHORT[second.id] ?? second.name.split(" ")[0]) : "Second", sub: "2nd SLO ok", on: !!second && !second.tiers.some((t) => t.state === "firing"), ...lamp(!!second && !second.tiers.some((t) => t.state === "firing"), "white") },
            { name: "Breach", sub: "budget 0", on: breach, ...lamp(breach, "red") },
          ];
          const stateWord = { nominal: "Nominal", ticket: "Ticket", page: "Page", breach: "Breach" }[s.state];
          const stateColour: LampColour = s.state === "breach" ? "red" : s.state === "nominal" ? "white" : "amber";
          return (
            <article className="console" key={s.id} aria-labelledby={`h-${s.id}`} data-guide={s.id === "repolens" ? "console" : undefined}>
              <div className="console-head">
                <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                  <span className="plate">{s.callsign}</span>
                  <h2 id={`h-${s.id}`} className="cond" style={{ margin: 0, fontSize: 26, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em" }}>{s.name}</h2>
                </div>
                <Lamp colour={test ? "white" : stateColour} small>{stateWord}</Lamp>
              </div>
              <div className="riser" role="list" aria-label={`${s.name} annunciator panel`}>
                {lamps.map((l) => (
                  <span role="listitem" key={l.name}><Lamp colour={l.colour} flash={l.flash} sub={l.sub} label={`${l.name} (${l.sub}): ${l.on || test ? "lit" : "off"}`}>{l.name}</Lamp></span>
                ))}
              </div>
              <Desk s={s} o={o} fallback={fallback} second={second} reduced={reduced} />
              <Gate s={s} o={o} test={test} cover={cover} setCover={setCover} override={override} setOverride={setOverride} />
            </article>
          );
        })}
      </section>
      {repo && <p className="mono muted" style={{ margin: "36px 0 0", fontSize: 13 }}>Tiers from the SRE Workbook: page at 14.4× (1 h and 5 min), page at 6× (6 h and 30 min), ticket at 1× (3 d and 6 h). Both windows must exceed the threshold. Burn rate = error ratio ÷ (1 − objective).</p>}
    </div>
  );
}

function Desk({ s, o, fallback, second, reduced }: { s: ServiceRow; o: SloRow; fallback: number | null; second?: SloRow; reduced: boolean }) {
  const rem = Math.max(0, o.remaining ?? 0) * 100;
  const h1 = o.burn["1h"] ?? 0, m5 = o.burn["5m"] ?? 0;
  const fastOrSlow = o.tiers.some((t) => t.severity === "page" && t.state === "firing");
  const fillCls = (o.remaining ?? 1) <= 0 ? "is-red" : fastOrSlow ? "is-amber" : "";
  return (
    <div className="desk" data-guide={s.id === "repolens" ? "tank" : undefined}>
      <div className="gauge" role="meter" aria-label={`${s.name} error budget remaining`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(rem.toFixed(1))} aria-valuetext={pct(o.remaining, 2)}>
        <div className="tank">
          <div className={`fill ${fillCls}`} style={{ height: `${rem}%` }} />
          {h1 >= 1 && !reduced && <div className="flow" style={{ height: `${rem}%`, animationDuration: `${Math.max(0.15, 6 / h1).toFixed(2)}s` }} />}
          <div className="floor" style={{ bottom: `${o.gate.floor * 100}%` }} title="Deploy gate floor" />
        </div>
        <div className="gscale" aria-hidden="true">
          {[100, 75, 50, 25, 0].map((v) => <span key={v} style={{ bottom: `${v}%` }}>{v}</span>)}
          <div className="needle" style={{ bottom: `${rem}%` }} />
        </div>
      </div>
      <div className="readings">
        <div>
          <p className="label muted" style={{ margin: 0 }}>Budget left · {o.name}</p>
          <p className="odo">{pct(o.remaining, 2)}</p>
          <p className="mono muted" style={{ margin: "2px 0 0", fontSize: 13 }}>−{(o.drain_per_min * 100).toFixed(4)}% per min now</p>
        </div>
        <div data-guide={s.id === "repolens" ? "meters" : undefined}>
          {[["1H", h1], ["5M", m5]].map(([lbl, b]) => (
            <div className="meter" key={lbl as string} style={{ marginTop: lbl === "5M" ? 6 : 0 }}>
              <span className="label">{lbl}</span>
              <span className="track"><span className={`bar${(b as number) >= 14.4 ? " is-amber" : ""}`} style={{ width: `${logPos(b as number)}%` }} /><span className="thr" style={{ left: `${THR}%` }} /></span>
              <span className="mono" style={{ textAlign: "right" }}>{rate(b as number)}</span>
            </div>
          ))}
          <div className="mscale" aria-hidden="true"><span style={{ left: "0%" }}>0.1</span><span style={{ left: "33.3%" }}>1</span><span style={{ left: `${THR}%` }}>14.4</span><span style={{ left: "100%" }}>100×</span></div>
        </div>
        <dl className="kv" style={{ fontSize: 14 }}>
          <dt>Runs out in</dt><dd>{duration(o.tte_seconds)}</dd>
          {fallback != null && <><dt>Examiner fallback, 5 m</dt><dd>{pct(fallback)}</dd></>}
          {second && !second.informational && <><dt>{second.name}</dt><dd>{pct(second.remaining)} left</dd></>}
        </dl>
      </div>
    </div>
  );
}

function Gate({ s, o, test, cover, setCover, override, setOverride }: {
  s: ServiceRow; o: SloRow; test: boolean; cover: boolean; setCover: (b: boolean) => void; override: boolean; setOverride: (b: boolean) => void;
}) {
  const guarded = s.id === "repolens" && o.gate.armed;
  const open = !o.gate.armed || (guarded && override);
  const text = open ? (o.gate.armed ? "Override · open" : "Open") : "Armed · blocked";
  const colour: LampColour = test ? "white" : open && !o.gate.armed ? "white" : "amber";
  const ids = useMemo(() => `ovr-${s.id}`, [s.id]);
  return (
    <div className="gate" data-guide={s.id === "repolens" ? "gate" : undefined}>
      <span className="label" style={{ flex: "1 1 100%" }}>Deploy gate · floor {(o.gate.floor * 100).toFixed(0)}%</span>
      <Lamp colour={colour}>{text}</Lamp>
      {guarded && (
        <>
          <button className="cover" type="button" aria-expanded={cover} aria-controls={ids} onClick={() => { setCover(!cover); if (cover) setOverride(false); }}>{cover ? "Close cover" : "Lift cover"}</button>
          <button id={ids} className="toggle" type="button" aria-pressed={override} disabled={!cover} onClick={() => setOverride(!override)}><span className="bat" aria-hidden="true" />Emergency-fix</button>
        </>
      )}
    </div>
  );
}
