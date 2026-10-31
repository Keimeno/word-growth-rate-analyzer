// Routing, data fetching and formatting, shared by every page.
import { useEffect, useRef, useState } from "./vendor/preact-htm.js";

// --- Routing: #/page?key=value, so every view is a link -------------------------------

export function readRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [page, query = ""] = hash.split("?");
  return { page: page || "now", params: Object.fromEntries(new URLSearchParams(query)) };
}

function routeHash(page, params) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
  ).toString();
  return `#/${page}${query ? `?${query}` : ""}`;
}

export function useRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const changed = () => setRoute(readRoute());
    addEventListener("hashchange", changed);
    return () => removeEventListener("hashchange", changed);
  }, []);
  return route;
}

/** Changes the current page's parameters without a new history entry. */
export function setParams(updates) {
  const { page, params } = readRoute();
  history.replaceState(null, "", routeHash(page, { ...params, ...updates }));
  dispatchEvent(new HashChangeEvent("hashchange"));
}

export function href(page, params = {}) {
  return routeHash(page, params);
}

/** A list parameter: comma separated in the url. `fallback` when it's absent. */
export function listParam(params, name, fallback = []) {
  if (!(name in params)) return fallback;
  return params[name] ? params[name].split(",") : [];
}

// --- Data -----------------------------------------------------------------------------

export async function api(name, params = {}, signal) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    query.set(key, Array.isArray(value) ? value.join(",") : String(value));
  }
  const response = await fetch(`/api/${name}?${query}`, { signal });
  const body = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

/**
 * Fetches an endpoint whenever its parameters change, and every `refresh` ms while the
 * page is visible. Keeps the previous data while refetching, so nothing jumps.
 */
export function useApi(name, params, { refresh = 0, skip = false } = {}) {
  const key = JSON.stringify([name, params]);
  const [state, setState] = useState({ data: null, error: null, loading: !skip });
  const [tick, setTick] = useState(0);
  const latest = useRef(key);
  latest.current = key;

  useEffect(() => {
    if (skip) return;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true }));
    api(name, params, controller.signal)
      .then((data) => latest.current === key && setState({ data, error: null, loading: false }))
      .catch((error) => {
        if (error.name !== "AbortError" && latest.current === key) {
          setState((previous) => ({ data: previous.data, error, loading: false }));
        }
      });
    return () => controller.abort();
  }, [key, tick, skip]);

  useEffect(() => {
    if (!refresh) return;
    const timer = setInterval(() => document.visibilityState === "visible" && setTick((t) => t + 1), refresh);
    return () => clearInterval(timer);
  }, [refresh]);

  return state;
}

export function usePersistent(name, fallback) {
  const [value, setValue] = useState(() => {
    try {
      const saved = localStorage.getItem(name);
      return saved === null ? fallback : JSON.parse(saved);
    } catch (_) {
      return fallback;
    }
  });
  const update = (next) => {
    setValue(next);
    try {
      localStorage.setItem(name, JSON.stringify(next));
    } catch (_) {}
  };
  return [value, update];
}

// --- Formatting -----------------------------------------------------------------------

const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function count(value) {
  if (value === null || value === undefined) return "–";
  return Math.abs(value) >= 10000 ? compact.format(value) : integer.format(value);
}

export function decimal(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** A rate per 1,000 with as many digits as a small number needs. */
export function perThousand(value) {
  if (value === null || value === undefined) return "–";
  if (value === 0) return "0";
  const digits = value >= 10 ? 1 : value >= 1 ? 2 : value >= 0.01 ? 3 : 4;
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function percent(value, digits = 0) {
  if (value === null || value === undefined) return "–";
  return `${(100 * value).toFixed(digits)}%`;
}

export function times(ratio, isNew) {
  if (isNew) return "new";
  if (ratio === null || ratio === undefined) return "–";
  return `×${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}`;
}

export function signedPercent(value) {
  if (value === null || value === undefined) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value) >= 10 ? Math.round(Math.abs(value)) : Math.abs(value).toFixed(1)}%`;
}

export function toDate(value) {
  return value instanceof Date ? value : new Date(value);
}

export function ago(value) {
  if (!value) return "never";
  const seconds = (Date.now() - toDate(value).getTime()) / 1000;
  if (seconds < 0) return `in ${duration(-seconds / 3600)}`;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function inFuture(value) {
  const hours = (toDate(value).getTime() - Date.now()) / 3600000;
  return hours >= 0 ? `in ${duration(hours)}` : `${duration(-hours)} ago`;
}

/** Hours as "40 min", "14 h" or "2.5 d". */
export function duration(hours) {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "–";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${(hours / 24).toFixed(1)} d`;
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
});
const dateFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const shortDate = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

export const formatDateTime = (value) => (value ? dateTimeFormat.format(toDate(value)) : "–");
export const formatDate = (value) => (value ? dateFormat.format(toDate(value)) : "–");
export const formatShortDate = (value) => (value ? shortDate.format(toDate(value)) : "–");
export const formatTime = (value) => (value ? timeFormat.format(toDate(value)) : "–");

export function bytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** exponent).toFixed(exponent ? 1 : 0)} ${units[exponent]}`;
}

/** q-values as words a reader can weigh, with the number for those who want it. */
export function confidence(q) {
  if (q === null || q === undefined) return { label: "–", tone: "" };
  if (q < 0.001) return { label: "very strong", tone: "good" };
  if (q < 0.01) return { label: "strong", tone: "good" };
  if (q < 0.05) return { label: "moderate", tone: "" };
  return { label: "weak", tone: "warn" };
}

// what an intent's term is about, and its kind ("complaint: reddit" -> reddit, complaint)
export function intentKind(term) {
  const at = term.indexOf(": ");
  return at > 0 ? term.slice(0, at) : term.includes(" → ") ? "switch" : null;
}

export function intentEntity(term) {
  const at = term.indexOf(": ");
  return at > 0 ? term.slice(at + 2) : term;
}

export const KIND_LABELS = {
  word: "Words",
  phrase: "Phrases",
  domain: "Links",
  subreddit: "Subreddits",
  switch: "Switches",
  considering: "Considering",
  alternative: "Alternatives",
  complaint: "Complaints",
  need: "Needs",
};

export const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"].map((name) => `var(${name})`);
