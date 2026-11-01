import { describe, expect, it } from "vitest";
import { endLabels } from "./options";
import { timeTicks } from "./time";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const end = Date.UTC(2026, 10, 1, 12);

// every range the pages offer, hourly and daily buckets
const RANGES: Array<[string, number, boolean]> = [
  ["1h", HOUR, false],
  ["6h", 6 * HOUR, false],
  ["24h", DAY, false],
  ["2d", 2 * DAY, false],
  ["3d", 3 * DAY, false],
  ["7d", 7 * DAY, false],
  ["14d", 14 * DAY, true],
  ["30d", 30 * DAY, true],
  ["90d", 90 * DAY, true],
  ["120d of weeks", 120 * DAY, true],
  ["26w", 26 * 7 * DAY, true],
  ["52w", 52 * 7 * DAY, true],
  ["400d", 400 * DAY, true],
  ["3y", 3 * 365 * DAY, true],
];

describe("timeTicks", () => {
  it.each(RANGES)("%s: a few distinct labels, evenly spaced", (_, span, daily) => {
    const ticks = timeTicks(end - span, end, { daily });
    expect(ticks).not.toBeNull();
    const values = ticks?.values ?? [];
    expect(values.length).toBeGreaterThanOrEqual(2);
    expect(values.length).toBeLessThanOrEqual(8);
    const texts = values.map((value) => ticks?.label(value).text);
    expect(new Set(texts).size).toBe(texts.length);
    // the same step between ticks: exactly, or by calendar months
    const gaps = values.slice(1).map((value, index) => value - (values[index] ?? 0));
    const spread = Math.max(...gaps) - Math.min(...gaps);
    expect(spread).toBeLessThanOrEqual(3 * DAY);
  });

  it("starts weeks on Mondays and months on the 1st", () => {
    const weeks = timeTicks(end - 45 * DAY, end, { daily: true })?.values ?? [];
    for (const value of weeks) expect(new Date(value).getUTCDay()).toBe(1);
    const months = timeTicks(end - 300 * DAY, end, { daily: true })?.values ?? [];
    for (const value of months) expect(new Date(value).getUTCDate()).toBe(1);
  });

  it("never puts hours on daily buckets", () => {
    const ticks = timeTicks(end - 3 * DAY, end, { daily: true });
    for (const value of ticks?.values ?? []) expect(new Date(value).getUTCHours()).toBe(0);
  });

  it("marks a new day among hours", () => {
    const ticks = timeTicks(end - DAY, end);
    const labels = (ticks?.values ?? []).map((value) => ticks?.label(value));
    expect(labels).toContainEqual({ text: "1 Nov", strong: true });
    expect(labels).toContainEqual({ text: "18:00", strong: false });
  });

  it("is nothing for a single instant", () => {
    expect(timeTicks(end, end)).toBeNull();
  });
});

describe("endLabels", () => {
  const series = (name: string, last: number) => ({
    name,
    points: [
      [0, 20],
      [1, last],
    ] as Array<[number, number | null]>,
  });

  it("merges ends that would overlap into one label", () => {
    expect(endLabels([series("Requests", 20), series("Errors", 0), series("Gaps", 0)])).toEqual([
      "Requests",
      "Errors, Gaps",
      null,
    ]);
  });

  it("keeps ends apart that are far enough", () => {
    expect(endLabels([series("a", 20), series("b", 10), series("c", 0)])).toEqual(["a", "b", "c"]);
  });

  it("shortens a long merge", () => {
    expect(
      endLabels([series("comments-1", 5), series("comments-2", 5), series("posts-1", 5)]),
    ).toEqual(["comments-1 +2", null, null]);
  });
});
