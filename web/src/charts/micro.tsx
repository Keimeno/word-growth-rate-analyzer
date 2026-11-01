/** Charts too small for ECharts: inside table cells and stat tiles, as SVG or HTML. A table
 * of 200 rows with an ECharts instance each would be 200 canvases. */
import { cn } from "@/lib/utils";

interface SparklineProps {
  values: ReadonlyArray<number | null> | undefined;
  color?: string | undefined;
  width?: number;
  height?: number;
  label: string;
}

/** A line of values with the last point marked; no axes. */
export function Sparkline({
  values,
  color = "var(--series-1)",
  width = 96,
  height = 24,
  label,
}: SparklineProps) {
  const points = (values ?? []).map((value) => value ?? 0);
  if (points.length < 2) return <span className="text-ink-muted">–</span>;
  const max = Math.max(...points, 0) || 1;
  const step = width / (points.length - 1);
  const y = (value: number) => height - 2 - (value / max) * (height - 4);
  const path = points
    .map(
      (value, index) => `${index ? "L" : "M"}${(index * step).toFixed(1)},${y(value).toFixed(1)}`,
    )
    .join("");
  const last = points.at(-1) ?? 0;
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      className="block overflow-visible"
    >
      <path
        d={`${path}L${width},${height}L0,${height}Z`}
        fill={color}
        opacity={0.12}
        stroke="none"
      />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={width} cy={y(last)} r={2} fill={color} />
    </svg>
  );
}

/** A value as a bar against a maximum, with its label beside it. */
export function Meter({
  value,
  max,
  children,
  className,
}: {
  value: number | null | undefined;
  max: number;
  children?: React.ReactNode;
  className?: string;
}) {
  const share = Math.max(0, Math.min(1, (value ?? 0) / (max || 1)));
  return (
    <span className={cn("inline-flex items-center gap-2 tabular-nums", className)}>
      <span className="relative h-1.5 w-14 overflow-hidden rounded-full bg-surface-sunken">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-seq-500"
          style={{ width: `${share * 100}%` }}
        />
      </span>
      {children}
    </span>
  );
}

/** Two shares of one whole side by side: this way against the other way. */
export function SplitBar({ left, right, label }: { left: number; right: number; label: string }) {
  const total = left + right || 1;
  return (
    <span
      className="flex h-2 w-24 overflow-hidden rounded-sm bg-surface-sunken"
      role="img"
      aria-label={label}
    >
      <span className="h-full bg-series-1" style={{ width: `${(100 * left) / total}%` }} />
      {right > 0 && (
        <span className="h-full bg-series-2" style={{ width: `${(100 * right) / total}%` }} />
      )}
    </span>
  );
}

/** Rows of labels with horizontal bars, values at the end: where it's discussed, top flows. */
export function BarList({
  rows,
  format = (value) => value.toLocaleString("en"),
  onSelect,
  selected,
}: {
  rows: ReadonlyArray<{ key: string; label: React.ReactNode; value: number; note?: string }>;
  format?: (value: number) => string;
  onSelect?: (key: string) => void;
  selected?: string | undefined;
}) {
  const max = Math.max(...rows.map((row) => row.value), 0) || 1;
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((row) => {
        const content = (
          <>
            <span
              aria-hidden
              className={cn(
                "absolute inset-y-0.5 left-0 rounded-sm",
                selected === row.key ? "bg-seq-300" : "bg-primary-wash",
              )}
              style={{ width: `${(100 * row.value) / max}%` }}
            />
            <span className="relative min-w-0 truncate">{row.label}</span>
            <span className="relative ml-auto shrink-0 tabular-nums text-ink-secondary">
              {format(row.value)}
              {row.note && <span className="ml-1 text-xs text-ink-muted">{row.note}</span>}
            </span>
          </>
        );
        return (
          <li key={row.key}>
            {onSelect ? (
              <button
                type="button"
                aria-pressed={selected === row.key}
                className="relative flex h-7 w-full items-center gap-2 rounded-sm px-2 text-left text-sm hover:bg-surface-hover"
                onClick={() => onSelect(row.key)}
              >
                {content}
              </button>
            ) : (
              <div className="relative flex h-7 items-center gap-2 px-2 text-sm">{content}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
