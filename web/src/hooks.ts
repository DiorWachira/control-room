import { useCallback, useEffect, useState } from "react";
import { get } from "./api";

export type Route = { name: "status" } | { name: "budgets" } | { name: "incident"; id: string } | { name: "missing"; path: string };

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  if (path === "/" || path === "") return { name: "status" };
  if (path === "/budgets") return { name: "budgets" };
  const m = path.match(/^\/incidents\/([A-Za-z0-9-]+)$/);
  if (m) return { name: "incident", id: m[1] };
  return { name: "missing", path };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(location.hash));
  useEffect(() => {
    const on = () => { setRoute(parseHash(location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function navigate(hash: string) {
  if (location.hash !== hash) location.hash = hash;
}

export type Load<T> = { state: "loading" } | { state: "error"; error: Error; retry: () => void } | { state: "ready"; data: T };

export function useData<T>(path: string): Load<T> {
  const [res, setRes] = useState<Load<T>>({ state: "loading" });
  const [n, setN] = useState(0);
  const retry = useCallback(() => setN((x) => x + 1), []);
  useEffect(() => {
    const ac = new AbortController();
    setRes({ state: "loading" });
    get<T>(path, ac.signal)
      .then((data) => setRes({ state: "ready", data }))
      .catch((error) => { if (!ac.signal.aborted) setRes({ state: "error", error, retry }); });
    return () => ac.abort();
  }, [path, n, retry]);
  return res;
}

export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

export function useReducedMotion(): boolean {
  const q = "(prefers-reduced-motion: reduce)";
  const [r, setR] = useState(() => matchMedia(q).matches);
  useEffect(() => {
    const m = matchMedia(q);
    const on = () => setR(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return r;
}

export const store = {
  get(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
