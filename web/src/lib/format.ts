/** Numbers, times and statistics as the brand words them (BRAND.md §2): numbers first, with
 * their meaning; below 10, counts stay counts. */
import { now } from "./clock";

const integer = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

type Maybe = number | null | undefined;
const missing = (value: Maybe): value is null | undefined =>
  value === null || value === undefined || Number.isNaN(value);

export function count(value: Maybe): string {
  if (missing(value)) return "–";
  return Math.abs(value) >= 10_000 ? compact.format(value) : integer.format(value);
}

export function decimal(value: Maybe, digits = 1): string {
  if (missing(value)) return "–";
  return value.toLocaleString("en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A rate per 1,000 with as many digits as a small number needs. */
export function perThousand(value: Maybe): string {
  if (missing(value)) return "–";
  if (value === 0) return "0";
  const digits = value >= 10 ? 1 : value >= 1 ? 2 : value >= 0.01 ? 3 : 4;
  return value.toLocaleString("en", { maximumFractionDigits: digits });
}

export function percent(value: Maybe, digits = 0): string {
  if (missing(value)) return "–";
  return `${(100 * value).toFixed(digits)}%`;
}

/** "×12" or "×2.4" times its usual share, "new" when it was barely mentioned before. */
export function times(ratio: Maybe, isNew = false): string {
  if (isNew) return "new";
  if (missing(ratio)) return "–";
  return `×${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}`;
}

export function signedPercent(value: Maybe): string {
  if (missing(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  const size = Math.abs(value);
  return `${sign}${size >= 10 ? Math.round(size) : size.toFixed(1)}%`;
}

/** Hours as "40 min", "14 h" or "2.5 d". */
export function duration(hours: Maybe): string {
  if (missing(hours)) return "–";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${(hours / 24).toFixed(1)} d`;
}

const toTime = (value: string | Date): number =>
  value instanceof Date ? value.getTime() : Date.parse(value);

export function ago(value: string | Date | null | undefined): string {
  if (!value) return "never";
  const seconds = (now() - toTime(value)) / 1000;
  if (seconds < 0) return `in ${duration(-seconds / 3600)}`;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86_400)} d ago`;
}

export function inFuture(value: string | Date): string {
  const hours = (toTime(value) - now()) / 3_600_000;
  return hours >= 0 ? `in ${duration(hours)}` : `${duration(-hours)} ago`;
}

// in UTC, as everything the system computes: days and weeks are UTC days and weeks
const formats = {
  dateTime: new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }),
  date: new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }),
  shortDate: new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }),
  time: new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }),
};
const format =
  (kind: keyof typeof formats) =>
  (value: string | Date | null | undefined): string =>
    value ? formats[kind].format(toTime(value)) : "–";

export const formatDateTime = (value: string | Date | null | undefined): string =>
  value ? `${format("dateTime")(value)} UTC` : "–";
export const formatDate = format("date");
export const formatShortDate = format("shortDate");
export const formatTime = format("time");

export function bytes(value: Maybe): string {
  if (missing(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** exponent).toFixed(exponent ? 1 : 0)} ${units[exponent] ?? "B"}`;
}

export type Strength = { label: string; level: 0 | 1 | 2 | 3 };

/** q-values as words a reader can weigh; the number goes on hover. */
export function confidence(q: Maybe): Strength {
  if (missing(q)) return { label: "–", level: 0 };
  if (q < 0.001) return { label: "very strong", level: 3 };
  if (q < 0.01) return { label: "strong", level: 2 };
  if (q < 0.05) return { label: "moderate", level: 1 };
  return { label: "weak", level: 0 };
}

/** A trend's z as words: 3 is the minimum, alerts start at 10. */
export function strength(z: Maybe): Strength {
  if (missing(z)) return { label: "–", level: 0 };
  if (z >= 10) return { label: "very strong", level: 3 };
  if (z >= 6) return { label: "strong", level: 2 };
  if (z >= 3) return { label: "clear", level: 1 };
  return { label: "weak", level: 0 };
}
