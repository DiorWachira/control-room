import { useState } from "react";
import { eatTime, objective, pct, rate, type IncidentDetail } from "../api";
import { Lamp, Loaded } from "../components";
import { useData, useNow } from "../hooks";

const pad = (n: number) => String(n).padStart(2, "0");

export function IncidentScreen({ id }: { id: string }) {
  const load = useData<IncidentDetail>(`/api/incidents/${encodeURIComponent(id)}`);
  return <Loaded load={load} what={`incident ${id}`}>{(inc) => <Detail inc={inc} />}</Loaded>;
}

function Detail({ inc }: { inc: IncidentDetail }) {
  const [sel, setSel] = useState(() => Math.max(0, inc.timeline.findIndex((e) => e.kind === "engine" && e.key)));
  const [reviewed, setReviewed] = useState(false);
  const [mounted] = useState(Date.now());
  const now = useNow();

  // SLA: the engine's "now" plus however long this page has been open.
  const elapsed = Math.floor((now - mounted) / 1000);
  const snapNow = new Date(inc.now).getTime() + elapsed * 1000;
  const left = Math.max(0, Math.floor((new Date(inc.sla.resolve_by).getTime() - snapNow) / 1000));
  const respondedIn = inc.sla.responded_at ? Math.round((new Date(inc.sla.responded_at).getTime() - new Date(inc.opened_at).getTime()) / 1000) : null;

  // Burn trace on a log scale, 0.1x .. 100x.
  const t0 = new Date(inc.trace[0].at).getTime(), t1 = new Date(inc.trace[inc.trace.length - 1].at).getTime();
  const X = (iso: string | number) => (((typeof iso === "number" ? iso : new Date(iso).getTime()) - t0) / (t1 - t0)) * 1000;
  const Y = (b: number | null) => 330 - ((Math.log10(Math.max(b ?? 0.1, 0.1)) + 1) / 3) * 300;
  const line = (k: "h1" | "m5") => inc.trace.map((p) => `${X(p.at).toFixed(1)},${Y(p[k]).toFixed(1)}`).join(" ");
  const fire = inc.timeline.find((e) => e.kind === "engine" && e.text.includes("Fast burn fires"));
  const reset = inc.timeline.find((e) => e.text.includes("Fast burn resets"));
  const pageX = fire ? X(fire.at) : 0, pageW = fire ? (reset ? X(reset.at) : 1000) - pageX : 0;

  let lastX = -100, row = 0;
  const pins = inc.timeline.map((e, k) => {
    const x = X(e.at);
    row = x - lastX < 30 ? row + 1 : 0; lastX = x;
    return { x, y: row * 22, k };
  });
  const s = inc.timeline[sel];
  const near = s && inc.trace.reduce((b, p) => (Math.abs(new Date(p.at).getTime() - new Date(s.at).getTime()) < Math.abs(new Date(b.at).getTime() - new Date(s.at).getTime()) ? p : b), inc.trace[0]);
  const statusColour = inc.status === "resolved" ? "white" : "amber";

  return (
    <div className="wrap" style={{ paddingTop: 30, paddingBottom: 72 }}>
      <div className="head-grid">
        <section className="console" aria-labelledby="inc-h">
          <div className="console-head">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span className="plate">Incident</span><Lamp colour={statusColour}>{inc.status}</Lamp><Lamp>{inc.priority}</Lamp>
              <Lamp>{inc.class === "page" ? "Page tier" : "Ticket tier"}</Lamp>
              {inc.replay && <Lamp>Replay · 8 Nov</Lamp>}
            </div>
            <a className="key" href="#/budgets">← Console wall</a>
          </div>
          <div className="console-body" style={{ padding: "22px 24px 26px" }}>
            <p className="mono muted" style={{ margin: 0 }}>{inc.service_name} · {inc.slo_name} · SLO {objective(inc.objective)} over 28 days</p>
            <h1 id="inc-h" style={{ margin: 0, display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 24px" }}>
              <span className="cond" style={{ fontSize: "clamp(64px, 9vw, 104px)", fontWeight: 700, lineHeight: 0.9 }}>{inc.id}</span>
              <span className="cond" style={{ fontSize: 30, fontWeight: 600, lineHeight: 1.05, textTransform: "uppercase", maxWidth: "20ch" }}>{inc.title}</span>
            </h1>
            <p style={{ margin: "6px 0 0", maxWidth: "68ch", fontSize: 18 }}>
              Opened {eatTime(inc.opened_at)} EAT by Control Room's service token.{" "}
              {inc.status === "monitoring" && inc.quiet_since && `All page tiers clear since ${eatTime(inc.quiet_since)}; it closes itself after 60 quiet minutes.`}
              {inc.status === "resolved" && inc.resolved_at && `Resolved ${eatTime(inc.resolved_at)} EAT.`}
              {inc.status === "firing" && "Still burning."}
            </p>
          </div>
        </section>

        <section className="console" aria-labelledby="sla-h">
          <div className="console-head"><span id="sla-h" className="plate">Resolve SLA clock</span>
            {respondedIn != null ? <Lamp colour="white">Response met · {Math.floor(respondedIn / 60)} m {respondedIn % 60} s</Lamp> : <Lamp colour="amber">Awaiting response</Lamp>}
          </div>
          <div className="console-body">
            <p className="label muted" style={{ margin: 0 }}>Resolution due {eatTime(inc.sla.resolve_by)} EAT · time left</p>
            <div className="drum" role="timer" aria-label={`Resolution due in ${Math.floor(left / 3600)} hours ${Math.floor((left % 3600) / 60)} minutes`}>
              <span>{pad(Math.floor(left / 3600))}<small>Hours</small></span><span>{pad(Math.floor((left % 3600) / 60))}<small>Min</small></span><span>{pad(left % 60)}<small>Sec</small></span>
            </div>
            <dl className="kv"><dt>Assignee</dt><dd>Dior W.</dd><dt>Queue</dt><dd>On-call · portfolio</dd></dl>
          </div>
        </section>
      </div>

      <section className="board on-board" style={{ marginTop: 30 }} aria-labelledby="trace-h" data-guide="trace">
        <div className="board-in">
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
            <h2 id="trace-h" className="h-sec">Burn trace · {eatTime(inc.trace[0].at)} to {eatTime(inc.now)}</h2>
            <p className="mono muted" style={{ margin: 0, fontSize: 14 }}>{s && `#${sel + 1} ${eatTime(s.at, true)} · 1 h ${rate(near?.h1)} · 5 m ${rate(near?.m5)}`}</p>
          </div>
          <svg viewBox="0 0 1000 330" style={{ display: "block", width: "100%", height: "auto", marginTop: 18, overflow: "visible" }} role="img"
            aria-label="Burn rate over time on a log scale, with the 14.4 times page threshold. Numbered pins match the loop entries below.">
            {fire && <rect x={pageX} y="30" width={pageW} height="300" fill="var(--lamp-amber)" opacity=".16" />}
            {fire && <text x={pageX + 8} y="320" fill="var(--board-ink)" fontFamily="Barlow Condensed" fontWeight="600" fontSize="15" letterSpacing="1.5">PAGING · BOTH WINDOWS OVER 14.4×</text>}
            {[1, 10, 100].map((v) => <line key={v} x1="0" y1={Y(v)} x2="1000" y2={Y(v)} stroke="var(--board-rule)" />)}
            <line x1="0" y1={Y(14.4)} x2="1000" y2={Y(14.4)} stroke="var(--lamp-amber)" strokeWidth="2" strokeDasharray="8 5" />
            <text x="4" y={Y(14.4) - 6} fill="var(--board-ink)" fontFamily="Share Tech Mono" fontSize="13">14.4× page threshold</text>
            <text x="4" y={Y(1) - 6} fill="var(--board-mute)" fontFamily="Share Tech Mono" fontSize="12">1×</text>
            <text x="4" y={Y(100) + 16} fill="var(--board-mute)" fontFamily="Share Tech Mono" fontSize="12">100×</text>
            <polyline points={line("m5")} fill="none" stroke="var(--board-mute)" strokeWidth="1.5" strokeLinejoin="round" />
            <polyline points={line("h1")} fill="none" stroke="var(--board-ink)" strokeWidth="3.5" strokeLinejoin="round" />
            {pins.map((p) => {
              const on = p.k === sel;
              return (
                <g key={p.k}>
                  <line x1={p.x} y1="22" x2={p.x} y2="330" stroke="var(--board-ink)" strokeWidth={on ? 2 : 1} strokeDasharray="2 4" opacity={on ? 1 : 0.45} />
                  <rect x={p.x - 13} y={p.y} width="26" height="20" fill={on ? "var(--board-ink)" : "var(--board)"} stroke="var(--board-ink)" strokeWidth="1.5" />
                  <text x={p.x} y={p.y + 15} textAnchor="middle" fill={on ? "var(--board)" : "var(--board-ink)"} fontFamily="Share Tech Mono" fontSize="13">{p.k + 1}</text>
                </g>
              );
            })}
          </svg>
          <div className="mono muted" style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginTop: 4 }}>
            {[0, 0.33, 0.66, 1].map((q) => <span key={q}>{eatTime(new Date(t0 + (t1 - t0) * q).toISOString())}</span>)}
          </div>
          <div className="legend" style={{ marginTop: 10 }}>
            <span><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" stroke="var(--board-ink)" strokeWidth="3.5" /></svg> 1-hour burn (long window)</span>
            <span><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" stroke="var(--board-mute)" strokeWidth="1.5" /></svg> 5-minute burn (short window)</span>
            <span>Select a loop entry to find it on the trace</span>
          </div>
        </div>
      </section>

      <div className="body-grid">
        <section aria-labelledby="loop-h" data-guide="loop">
          <h2 id="loop-h" className="h-sec" style={{ marginBottom: 14 }}>Loop · everything that happened</h2>
          <ol className="loop">
            {inc.timeline.map((e, k) => (
              <li key={k} className={`ev${e.key ? " is-key" : ""}`}>
                <button className="ev-btn" type="button" aria-pressed={sel === k} onClick={() => setSel(k)}>
                  <span className="pin" aria-hidden="true">{k + 1}</span>
                  <span className="mono ev-time" style={{ fontSize: 15 }}>{eatTime(e.at, true)}</span>
                  <span className="ev-text"><span className="src">{e.source}</span>{e.text}</span>
                  {e.meta && <span className="ev-meta">{e.meta}</span>}
                </button>
              </li>
            ))}
          </ol>
        </section>
        <aside style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          <section className="console" aria-labelledby="ctx-h">
            <div className="console-head"><span id="ctx-h" className="plate">At fire · {eatTime(inc.opened_at)}</span></div>
            <div className="console-body">
              <dl className="kv">
                <dt>Error ratio, 1 h</dt><dd>{pct(inc.context.error_ratio["1h"], 2)}</dd>
                <dt>Error ratio, 5 m</dt><dd>{pct(inc.context.error_ratio["5m"])}</dd>
                <dt>Burn, 1 h / 5 m</dt><dd>{rate(inc.context.burn["1h"])} / {rate(inc.context.burn["5m"])}</dd>
                <dt>Budget left then</dt><dd>{pct(inc.context.remaining)}</dd>
                <dt>Budget left now</dt><dd>{pct(inc.remaining_now)}</dd>
              </dl>
            </div>
          </section>
          <section className="console" aria-labelledby="gate-h">
            <div className="console-head"><span id="gate-h" className="plate">Deploy gate</span><Lamp colour={inc.gate.armed ? "amber" : "white"}>{inc.gate.armed ? "Armed" : "Open"}</Lamp></div>
            <div className="console-body">
              <p style={{ margin: 0, fontSize: 15 }}>{inc.gate.armed
                ? `Deploys to ${inc.service_name} stay blocked until the budget is back over ${(inc.gate.floor * 100).toFixed(0)}% or a PR carries the emergency-fix label.`
                : `Budget is above the ${(inc.gate.floor * 100).toFixed(0)}% floor; deploys are open.`}</p>
              <p className="mono muted" style={{ margin: 0, fontSize: 13 }}>GET /budget/{inc.service}</p>
            </div>
          </section>
        </aside>
      </div>

      <section className="console pm" style={{ marginTop: 34 }} aria-labelledby="pm-h" data-guide="postmortem">
        <div className="console-head">
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span className="plate">Postmortem</span><h2 id="pm-h" className="cond" style={{ margin: 0, fontSize: 26, fontWeight: 600, textTransform: "uppercase" }}>Draft for Dior to edit</h2></div>
          <Lamp colour={reviewed ? "white" : ""}>{reviewed ? "Reviewed · not published" : "Draft · not published"}</Lamp>
        </div>
        <div className="console-body" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: "8px 36px", padding: "6px 24px 24px" }}>
          <div>
            <h3>Summary</h3><p>{inc.postmortem.summary}</p>
            <h3>Impact</h3><p>{inc.postmortem.impact}</p>
            <h3>Root cause · to be confirmed</h3><p className="tbc">{inc.postmortem.root_cause}</p>
            {inc.postmortem.refined && (
              <div className="ai-pass">
                <p className="label" style={{ margin: 0 }}>{inc.postmortem.refined.label} · {inc.postmortem.refined.model}</p>
                <h3>Rewritten summary</h3><p>{inc.postmortem.refined.summary}</p>
                <h3>Probable cause</h3><p className="tbc">{inc.postmortem.refined.probable_cause}</p>
                {inc.postmortem.refined.evidence.length > 0 && <ul>{inc.postmortem.refined.evidence.map((e, k) => <li key={k}>{e}</li>)}</ul>}
                {inc.postmortem.refined.follow_ups.length > 0 && <><h3>Suggested follow-ups</h3><ul>{inc.postmortem.refined.follow_ups.map((e, k) => <li key={k}>{e}</li>)}</ul></>}
              </div>
            )}
          </div>
          <div>
            <h3>Action items</h3>
            {inc.postmortem.action_items.map((a, k) => (
              <div className="check" key={k}><input id={`a${k}`} type="checkbox" defaultChecked={a.done} /><label htmlFor={`a${k}`}>{a.text}</label></div>
            ))}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 16 }}>
              <button className="key" type="button" aria-pressed={reviewed} onClick={() => setReviewed(!reviewed)}>{reviewed ? "Reviewed ✓" : "Mark reviewed"}</button>
              <button className="key" type="button" onClick={() => navigator.clipboard?.writeText(inc.postmortem.markdown)}>Copy Markdown</button>
            </div>
            <p className="muted" style={{ margin: "10px 0 0", fontSize: 14 }}>Drafted from {inc.timeline.length} loop entries. Never published automatically.</p>
          </div>
        </div>
      </section>
    </div>
  );
}
