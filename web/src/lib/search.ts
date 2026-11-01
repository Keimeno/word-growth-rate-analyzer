/**
 * Every view's state, per route, as a Zod schema with defaults (WEB-DASHBOARD.md §6.7).
 * Values that don't parse fall back to their default, so old links keep working; defaults
 * are left out of the url (`strip` in each route).
 */
import { z } from "zod";
import { ALL_KINDS, WORD_KINDS } from "./kinds";

const split = (value: unknown): unknown =>
  typeof value === "string"
    ? value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
    : value;

/** A comma separated list, empty when given empty, `fallback` when absent or invalid. */
export function list(fallback: readonly string[]) {
  return z
    .preprocess(split, z.array(z.string()))
    .default([...fallback])
    .catch([...fallback]);
}

/** A comma separated list of some of `allowed`. */
export function listOf<T extends string>(allowed: readonly [T, ...T[]], fallback: readonly T[]) {
  return z
    .preprocess(split, z.array(z.enum(allowed)))
    .default([...fallback])
    .catch([...fallback]);
}

export const flag = z
  .preprocess((value) => value === "1" || value === "true" || value === true, z.boolean())
  .default(false)
  .catch(false);

export function choice<T extends string>(options: readonly [T, ...T[]], fallback: T) {
  return z.enum(options).default(fallback).catch(fallback);
}

const text = (fallback: string) => z.string().default(fallback).catch(fallback);
const optionalText = z.string().optional().catch(undefined);
const number = (fallback: number) =>
  z.coerce.number().int().min(0).default(fallback).catch(fallback);
const optionalNumber = z.coerce.number().int().min(0).optional().catch(undefined);

/** On every page: the scope, a peeked term, time travel. */
export const rootSearch = z.object({
  scope: text("reddit"),
  // a term opened in the side sheet: kind:term
  peek: optionalText,
  as_of: optionalText,
});
export const rootDefaults = { scope: "reddit" };

export const trendingSearch = z.object({
  view: choice(["scored", "quick"], "scored"),
  horizon: choice(["24h", "6h"], "24h"),
  kinds: listOf(ALL_KINDS, WORD_KINDS),
  scopes: list([]),
  subsumed: flag,
  chart: choice(["24h", "3d", "7d", "14d"], "7d"),
  // the quick look
  quick_kinds: listOf(WORD_KINDS, ["word", "phrase"]),
  channels: list([]),
  doc_types: list([]),
  min_mentions: number(10),
  min_authors: number(5),
});
export const trendingDefaults = trendingSearch.parse({});

export const longTermSearch = z.object({
  horizon: choice(["13w", "26w", "52w"], "13w"),
  kinds: listOf(ALL_KINDS, WORD_KINDS),
  scopes: list([]),
  tab: choice(["emerging", "mainstreaming", "fading", "one-off"], "emerging"),
});
export const longTermDefaults = longTermSearch.parse({});

export const intentsSearch = z.object({
  range: choice(["7d", "30d", "90d"], "30d"),
  channels: list([]),
  doc_types: list([]),
  min_authors: number(1),
  min_mentions: number(2),
  comment_kinds: list([]),
  term: text(""),
  rising: choice(["alternative", "complaint", "considering"], "alternative"),
});
export const intentsDefaults = intentsSearch.parse({});

export const spreadSearch = z.object({
  topic: text("all"),
  leaders: list([]),
  range: choice(["14d", "30d", "90d"], "30d"),
});
export const spreadDefaults = spreadSearch.parse({});

export const exploreSearch = z.object({
  terms: list(["ai", "claude", "gpt"]),
  range: choice(["24h", "2d", "7d", "30d", "90d", "26w", "52w"], "2d"),
  bucket: choice(["auto", "hour", "day", "week"], "auto"),
  rate: choice(["pooled", "macro"], "pooled"),
  channels: list([]),
  doc_types: list([]),
  from: optionalNumber,
  to: optionalNumber,
});
export const exploreDefaults = exploreSearch.parse({});

export const collectionSearch = z.object({
  platforms: list([]),
  range: choice(["1h", "6h", "24h", "7d"], "6h"),
});
export const collectionDefaults = collectionSearch.parse({});

/** `kind:term` of the peek, split at the first colon (terms may contain colons). */
export function parsePeek(peek: string | undefined): { kind: string; term: string } | null {
  if (!peek) return null;
  const at = peek.indexOf(":");
  if (at <= 0) return null;
  return { kind: peek.slice(0, at), term: peek.slice(at + 1) };
}
