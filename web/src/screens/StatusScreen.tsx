import { useState } from "react";
import { ago, dateLabel, eatDay, eatTime, objective, type Status, type StatusService } from "../api";
import { Lamp, Loaded } from "../components";
import { useData, useNow } from "../hooks";

const plural = (n: number | undefined, w: string) => `${n ?? 0} ${w}${(n ?? 0) === 1 ? "" : "s"}`;
const LAMP = { nominal: ["white", "Nominal"], degraded: ["amber", "Degraded"], outage: ["red", "Outage"], nosignal: ["", "No signal"] } as const;
const WORDS = ["None", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
const STALE_MS = 45 * 60_000; // the probe job runs every 15 min; 45 min of silence means it stopped

function DayStrip({ svc }: { svc: StatusService }) {
  const [on, setOn] = useState<number | null>(null);
  const days = svc.days;
  const counts = days.reduce((a, d) => ({ ...a, [d.status]: (a[d.status] ?? 0) + 1 }), {} as Record<string, number>);
  const read = on == null ? `${days.length} days` : `${dateLabel(days[on].date)} · ${days[on].note}`;
  const move = (i: number) => setOn(Math.max(0, Math.min(days.length - 1, i)));
  return (
    <div className="ticks-cell">
      {/* One focusable strip: arrow keys scrub day by day, so 91 bars don't cost 91 tab stops. */}
      <div className="ticks" tabIndex={0} role="group"
        aria-label={`${svc.name}: last ${days.length} days. Use left and right arrows to read each day.`}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") { e.preventDefault(); move((on ?? days.length) - 1); }
          if (e.key === "ArrowRight") { e.preventDefault(); move((on ?? -1) + 1); }
          if (e.key === "Home") move(0);
          if (e.key === "End") move(days.length - 1);
        }}
        onMouseLeave={() => setOn(null)}>
        {days.map((d, i) => (
          <span key={d.date} className={`tick is-${d.status}${on === i ? " is-on" : ""}`} onMouseEnter={() => setOn(i)} aria-hidden="true" />
        ))}
      </div>
      <div className="strip-scale"><span>{days[0] && dateLabel(days[0].date)}</span><span aria-live="polite">{read}</span><span>Today</span></div>
      <p className="sr">{svc.name}: {plural(counts.outage, "outage day")}, {plural(counts.burning, "day")} burning budget, {plural(counts.cold, "day")} with uncounted cold starts{counts.nodata ? `, ${plural(counts.nodata, "day")} before probing began` : ""}, the rest nominal.</p>
    </div>
  );
}

export function StatusScreen() {
  const load = useData<Status>("/api/status");
  const now = useNow(30_000);
  return (
    <Loaded load={load} what="the status board">
      {(st) => {
        const nominal = st.services.filter((s) => s.state === "nominal").length;
        const n = st.services.length;
        const headline = nominal === n ? `All ${(WORDS[n] ?? String(n)).toLowerCase()} systems nominal` : `${WORDS[nominal] ?? nominal} of ${(WORDS[n] ?? String(n)).toLowerCase()} systems nominal`;
        const live = st.mode === "probes";
        const stale = live && now - new Date(st.at).getTime() > STALE_MS;
        const quiet = st.services.filter((s) => s.state === "nosignal").map((s) => s.name);
        const active = st.active[0];
        const svcName = (id: string) => st.services.find((s) => s.id === id)?.name ?? id;
        return (
          <>
            <section className="wrap" style={{ paddingTop: 36, paddingBottom: 20 }} aria-labelledby="board-h">
              <div className="board on-board">
                <div className="board-in">
                  <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 16 }}>
                    <p className="label muted" style={{ margin: 0 }}>Big board · public status · {st.mode === "replay" ? "replay of 8 Nov" : live ? `live probes every ${st.interval ?? "15m"}${st.since ? ` since ${eatDay(st.since)}` : ""}` : "refreshed every 60 s"}</p>
                    <p className="mono muted" style={{ margin: 0, fontSize: 14 }}>As of {eatDay(st.at)} {eatTime(st.at)} EAT</p>
                  </div>
                  {stale && (
                    <p className="signal-lost" role="status"><span className="label">Signal lost</span> The last reading is from {ago(st.at, now)}. The probe job may be delayed; these lamps show the last known state.</p>
                  )}
                  <h1 id="board-h" className="hero-h" data-guide="board">{headline}</h1>
                  <p className="muted" style={{ margin: "0 0 26px", maxWidth: "62ch", fontSize: 18 }}>
                    {active ? `${svcName(active.service)} is degraded since ${eatTime(active.opened_at)} EAT. ${active.status === "monitoring" ? "The burn has stopped and we are watching it." : "A fix is in progress."}`
                      : quiet.length ? `No probe has reached ${quiet.join(", ")} for 45 minutes. Everything else is inside its error budget.`
                      : "Every objective is inside its error budget."}
                  </p>
                  <div role="list" data-guide="strips">
                    {st.services.map((s) => {
                      const [colour, word] = LAMP[s.state];
                      return (
                        <div className="svc" role="listitem" key={s.id}>
                          <span className="svc-lamp"><Lamp colour={colour}>{word}</Lamp></span>
                          <div>
                            <p className="cond" style={{ margin: 0, fontWeight: 600, fontSize: 28, letterSpacing: ".04em", textTransform: "uppercase", lineHeight: 1 }}>{s.name}</p>
                            <p className="muted" style={{ margin: "4px 0 0", fontSize: 14 }}>{s.description}</p>
                            {live && s.url && (
                              <p className="mono muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
                                <a className="svc-link" href={s.url} target="_blank" rel="noopener noreferrer">{new URL(s.url).host}<span className="sr"> (opens in a new tab)</span> ↗</a>
                                {s.last_probe && <> · probed {ago(s.last_probe, now)}</>}
                              </p>
                            )}
                          </div>
                          <DayStrip svc={s} />
                          <div style={{ textAlign: "right" }}>
                            <p className="mono" style={{ margin: 0, fontSize: 26, lineHeight: 1 }}>{s.uptime_90d == null ? "—" : `${(s.uptime_90d * 100).toFixed(2)}%`}</p>
                            <p className="label muted" style={{ margin: "4px 0 0", fontSize: 11 }}>90-day SLI</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="legend" style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--board-rule)" }}>
                    <span><span className="sw" />Nominal day</span>
                    <span><span className="sw is-burning" />Budget burning (raised)</span>
                    <span><span className="sw is-outage" />Page-level burn (raised, outlined)</span>
                    <span><span className="sw is-cold" />Cold starts only, not counted</span>
                    {live && <span><span className="sw is-nodata" />No probes yet</span>}
                  </div>
                </div>
              </div>
            </section>

            <section className="wrap" style={{ paddingBlock: 28 }} aria-label="Consoles">
              <div className="row3">
                <article className="console">
                  <div className="console-head"><span className="plate">Now</span>{active ? <Lamp colour="amber" small>{active.status}</Lamp> : <Lamp colour="white" small>Quiet</Lamp>}</div>
                  <div className="console-body">
                    {active ? (
                      <>
                        <p className="mono muted" style={{ margin: 0, fontSize: 14 }}>{active.id} · opened {eatTime(active.opened_at)} EAT · {active.priority}</p>
                        <h2 className="cond" style={{ margin: 0, fontSize: 30, lineHeight: 1.05, fontWeight: 600, textTransform: "uppercase" }}>{active.title}</h2>
                        {active.last && <p style={{ margin: 0 }}>Last update {eatTime(active.last.at)}: {active.last.text}</p>}
                        <div style={{ marginTop: "auto" }}><a className="key" href={`#/incidents/${active.id}`}>Open incident log →</a></div>
                      </>
                    ) : (
                      <>
                        <p style={{ margin: 0 }}>No incidents open. The loop is quiet.</p>
                        {st.mode !== "replay" && <p className="muted" style={{ margin: 0, fontSize: 15 }}>To see the loop at work, open the 8 November replay: a real page from first failed probe to postmortem.</p>}
                        {st.mode !== "replay" && <div style={{ marginTop: "auto" }}><a className="key" href="#/incidents/RSV-1042">Open the RSV-1042 replay →</a></div>}
                      </>
                    )}
                  </div>
                </article>
                <article className="console">
                  <div className="console-head"><span className="plate">Measured</span><span className="label muted">28-day objectives</span></div>
                  <div className="console-body">
                    <dl className="kv">
                      {st.services.flatMap((s) => s.objectives.map((o) => (
                        <div key={s.id + o.name} style={{ display: "contents" }}><dt>{s.name} · {o.name.toLowerCase()}</dt><dd>{objective(o.objective)}</dd></div>
                      )))}
                    </dl>
                    <p className="muted" style={{ margin: 0, fontSize: 14 }}>Each objective leaves an error budget. Alerts fire only when it burns fast on both a long and a short window, so a two-minute blip never pages anyone.</p>
                    <div style={{ marginTop: "auto" }}><a className="key" href="#/budgets">See the budget wall →</a></div>
                  </div>
                </article>
                <article className="console" data-guide="cold">
                  <div className="console-head"><span className="plate">Cold starts</span><Lamp small>Waking</Lamp></div>
                  <div className="console-body">
                    <p style={{ margin: 0 }}>RepoLens runs on a free hosting tier that sleeps after 15 quiet minutes. The first scan after a nap can take up to 50 seconds.</p>
                    <p style={{ margin: 0 }}>If it answers inside that wake window the probe logs <span className="mono">cold_start</span>, the lamp reads WAKING and nothing is counted. Past 50 seconds it counts as a failure.</p>
                  </div>
                </article>
              </div>
            </section>

            <section className="wrap" style={{ paddingBlock: "36px 64px" }} aria-labelledby="hist-h">
              <div className="sec-title"><span className="sec-num">04</span><h2 id="hist-h" className="h-sec">Incident history</h2></div>
              {st.history.length === 0 && (
                <p className="muted" style={{ margin: "0 0 8px" }}>
                  No page-level incidents{st.since ? ` since probing began on ${eatDay(st.since)}` : ""}. The <a href="#/incidents/RSV-1042">8 November replay</a> shows what one looks like.
                </p>
              )}
              <ol className="log">
                {st.history.map((h) => (
                  <li key={h.id}>
                    <span className="mono" style={{ fontSize: 14 }}>{eatDay(h.start)} · {eatTime(h.start)}{h.end ? `–${eatTime(h.end)}` : "–"}</span>
                    <span className="label">{svcName(h.service)}</span>
                    <span className="log-desc">{h.detail ? <strong style={{ fontWeight: 600 }}>{h.title}</strong> : <a href={`#/incidents/${h.id}`} style={{ fontWeight: 600 }}>{h.title}</a>}{h.detail && ` — ${h.detail}`}</span>
                    <span style={{ justifySelf: "end" }}><Lamp small colour={h.status === "resolved" ? "" : "amber"}>{h.status}</Lamp></span>
                  </li>
                ))}
              </ol>
            </section>
          </>
        );
      }}
    </Loaded>
  );
}
