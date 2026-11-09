import type { ReactNode } from "react";
import type { Load } from "./hooks";

export type LampColour = "" | "white" | "amber" | "red";

export function Lamp({ colour = "", flash, small, children, sub, label }: {
  colour?: LampColour; flash?: boolean; small?: boolean; children: ReactNode; sub?: string; label?: string;
}) {
  const cls = ["lamp", colour && `is-${colour}`, flash && "is-flash", small && "sm"].filter(Boolean).join(" ");
  return (
    <span className={cls} aria-label={label}>
      {children}
      {sub && <small>{sub}</small>}
    </span>
  );
}

export function MarkLamps() {
  return (
    <span className="mark-lamps" aria-hidden="true">
      <span className="on" /><span /><span /><span /><span /><span />
    </span>
  );
}

export function WarmUp({ what }: { what: string }) {
  return (
    <div className="warmup wrap" role="status" aria-live="polite">
      <div>
        <div className="warm-lamps" aria-hidden="true"><span /><span /><span /><span /><span /><span /></div>
        <p className="label">Warming up the consoles</p>
        <p className="muted" style={{ margin: 0 }}>Loading {what} from the engine…</p>
      </div>
    </div>
  );
}

export function Fault({ error, retry, what }: { error: Error; retry?: () => void; what: string }) {
  return (
    <div className="warmup wrap" role="alert">
      <div className="console" style={{ maxWidth: 560, textAlign: "left" }}>
        <div className="console-head"><span className="plate">Link lost</span><Lamp colour="red">Fault</Lamp></div>
        <div className="console-body">
          <p style={{ margin: 0 }}>Control Room could not load {what}. The engine may be asleep or unreachable.</p>
          <p className="mono muted" style={{ margin: 0, fontSize: 14 }}>{error.message}</p>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Start it with <span className="mono">uvicorn controlroom.api:app --port 8000</span> from <span className="mono">engine/</span>.</p>
          {retry && <div><button className="key" type="button" onClick={retry}>Try the link again</button></div>}
        </div>
      </div>
    </div>
  );
}

export function NotFound({ path }: { path: string }) {
  return (
    <div className="warmup wrap">
      <div className="board on-board" style={{ maxWidth: 640, width: "100%", textAlign: "left" }}>
        <div className="board-in">
          <p className="label muted" style={{ margin: 0 }}>No console at this position</p>
          <h1 className="hero-h">404 · Loss of signal</h1>
          <p className="muted mono" style={{ marginTop: 0 }}>{path}</p>
          <a className="bkey" href="#/">Back to the big board</a>
        </div>
      </div>
    </div>
  );
}

export function Loaded<T>({ load, what, children }: { load: Load<T>; what: string; children: (data: T) => ReactNode }) {
  if (load.state === "loading") return <WarmUp what={what} />;
  if (load.state === "error") return <Fault error={load.error} retry={load.retry} what={what} />;
  return <>{children(load.data)}</>;
}
