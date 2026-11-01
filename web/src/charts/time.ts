/**
 * Ticks for time axes, chosen by the kit instead of ECharts: one step for the whole axis
 * (15 minutes to years, weeks from Monday, months from the 1st), so labels are evenly
 * spaced and never two of a kind side by side, then the plainest format in which every
 * label is distinct. All in UTC, like the tooltips.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
/** Monday 5 January 1970, 00:00 UTC: weeks are counted from a Monday */
const MONDAY = 4 * DAY;

type Unit = "minute" | "hour" | "day" | "week" | "month" | "year";
interface Step {
  unit: Unit;
  size: number;
  /** about how long, to pick the step */
  ms: number;
}

const STEPS: Step[] = [
  ...[15, 30].map((size): Step => ({ unit: "minute", size, ms: size * MINUTE })),
  ...[1, 2, 3, 6, 12].map((size): Step => ({ unit: "hour", size, ms: size * HOUR })),
  ...[1, 2].map((size): Step => ({ unit: "day", size, ms: size * DAY })),
  ...[1, 2].map((size): Step => ({ unit: "week", size, ms: size * 7 * DAY })),
  ...[1, 2, 3, 6].map((size): Step => ({ unit: "month", size, ms: size * 30.44 * DAY })),
  ...[1, 2, 5, 10].map((size): Step => ({ unit: "year", size, ms: size * 365.25 * DAY })),
];

export interface TimeTicks {
  values: number[];
  /** the label of a tick; `strong` marks a boundary (a new day, a new year) */
  label: (value: number) => { text: string; strong: boolean };
}

const pad = (value: number) => String(value).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const hhmm = (d: Date) => `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
const dayMonth = (d: Date) => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
const midnight = (d: Date) => d.getUTCHours() === 0 && d.getUTCMinutes() === 0;

type Format = (d: Date, previous: Date | undefined) => { text: string; strong: boolean };

/** From plainest to most specific, per unit; the first with distinct labels wins. */
const FORMATS: Record<"subday" | "day" | "month" | "year", Format[]> = {
  subday: [
    (d) => (midnight(d) ? { text: dayMonth(d), strong: true } : { text: hhmm(d), strong: false }),
    (d) =>
      midnight(d)
        ? { text: dayMonth(d), strong: true }
        : { text: `${DAYS[d.getUTCDay()]} ${hhmm(d)}`, strong: false },
    (d) => ({ text: `${dayMonth(d)} ${hhmm(d)}`, strong: midnight(d) }),
  ],
  day: [
    (d, previous) =>
      previous && previous.getUTCFullYear() !== d.getUTCFullYear()
        ? { text: `${dayMonth(d)} ${d.getUTCFullYear()}`, strong: true }
        : { text: dayMonth(d), strong: false },
    (d) => ({ text: `${dayMonth(d)} ${d.getUTCFullYear()}`, strong: false }),
  ],
  month: [
    (d) =>
      d.getUTCMonth() === 0
        ? { text: String(d.getUTCFullYear()), strong: true }
        : { text: MONTHS[d.getUTCMonth()] ?? "", strong: false },
    (d) => ({ text: `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`, strong: false }),
  ],
  year: [(d) => ({ text: String(d.getUTCFullYear()), strong: false })],
};

function generate(step: Step, min: number, max: number): number[] {
  const values: number[] = [];
  if (step.unit === "month" || step.unit === "year") {
    const months = step.unit === "year" ? 12 * step.size : step.size;
    const from = new Date(min);
    // the first month start at or after min whose index is a multiple of the step
    let index = from.getUTCFullYear() * 12 + from.getUTCMonth();
    if (Date.UTC(Math.floor(index / 12), index % 12) < min) index += 1;
    index = Math.ceil(index / months) * months;
    for (; ; index += months) {
      const value = Date.UTC(Math.floor(index / 12), index % 12);
      if (value > max) break;
      values.push(value);
    }
    return values;
  }
  const size = step.unit === "week" ? step.size * 7 * DAY : step.ms;
  const origin = step.unit === "week" ? MONDAY : 0;
  for (let value = Math.ceil((min - origin) / size) * size + origin; value <= max; value += size)
    values.push(value);
  return values;
}

/**
 * About `target` ticks between `min` and `max`, none within 3% of either edge (a label
 * there is cut off or crowds the axis); `daily` buckets never get hours.
 */
export function timeTicks(
  min: number,
  max: number,
  { target = 7, daily = false }: { target?: number; daily?: boolean } = {},
): TimeTicks | null {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
  const span = max - min;
  const candidates = STEPS.filter(
    (step) => !daily || (step.unit !== "minute" && step.unit !== "hour"),
  );
  const step = candidates.find((candidate) => span / candidate.ms <= target) ?? candidates.at(-1);
  if (!step) return null;
  const margin = 0.03 * span;
  const values = generate(step, min, max).filter(
    (value) => value >= min + margin && value <= max - margin,
  );
  const kind =
    step.unit === "minute" || step.unit === "hour"
      ? "subday"
      : step.unit === "day" || step.unit === "week"
        ? "day"
        : step.unit;
  const formats = FORMATS[kind];
  const apply = (format: Format) =>
    values.map((value, index) => {
      const before = values[index - 1];
      return format(new Date(value), before === undefined ? undefined : new Date(before));
    });
  let labels = apply(formats[0] as Format);
  for (const format of formats.slice(1)) {
    if (new Set(labels.map((label) => label.text)).size === labels.length) break;
    labels = apply(format);
  }
  const byValue = new Map(values.map((value, index) => [value, labels[index]]));
  return {
    values,
    label: (value) => byValue.get(value) ?? { text: "", strong: false },
  };
}
