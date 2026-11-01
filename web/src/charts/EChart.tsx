import { Download, Table2 } from "lucide-react";
import { type ComponentProps, type ReactNode, useEffect, useRef, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { type EChartsOption, echarts } from "./echarts";
import { csv, download, tableOf } from "./table";
import { registerUndercurrentTheme } from "./theme";

export type ChartInstance = ReturnType<typeof echarts.init>;

export interface ChartProps {
  option: EChartsOption;
  height?: number;
  /** what the chart shows, for screen readers; the table view has the numbers */
  label: string;
  className?: string;
  /** crosshairs and tooltips linked across the charts of a group */
  group?: string;
  onReady?: (chart: ChartInstance) => void;
  onBrush?: (from: number, to: number) => void;
}

/** An ECharts instance: init on mount, setOption on change, resize with its box, re-themed
 * in place when the page's theme changes. Charts only come through the kit. */
export default function EChart({
  option,
  height = 240,
  label,
  className,
  group,
  onReady,
  onBrush,
}: ChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const instance = useRef<ChartInstance | null>(null);
  const theme = useTheme();

  useEffect(() => {
    const element = box.current;
    if (!element) return undefined;
    const chart = echarts.init(element, registerUndercurrentTheme(echarts), { renderer: "canvas" });
    instance.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    chart.setTheme(registerUndercurrentTheme(echarts));
  }, [theme]);

  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    chart.setOption(option, { notMerge: true, lazyUpdate: true });
    onReady?.(chart);
  }, [option, onReady]);

  useEffect(() => {
    const chart = instance.current;
    if (!chart || !group) return;
    chart.group = group;
    echarts.connect(group);
  }, [group]);

  useEffect(() => {
    const chart = instance.current;
    if (!chart || !onBrush) return undefined;
    chart.dispatchAction({
      type: "takeGlobalCursor",
      key: "brush",
      brushOption: { brushType: "lineX", brushMode: "single" },
    });
    const ended = (event: unknown) => {
      const areas = (event as { areas?: Array<{ coordRange?: [number, number] }> }).areas;
      const range = areas?.[0]?.coordRange;
      if (range) onBrush(Math.round(range[0]), Math.round(range[1]));
      chart.dispatchAction({ type: "brush", areas: [] });
    };
    chart.on("brushEnd", ended);
    return () => {
      chart.off("brushEnd", ended);
    };
  }, [onBrush, option]);

  const [asTable, setAsTable] = useState(false);
  const name =
    label
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase() || "chart";
  return (
    // focusable, so `t` switches between the chart and its table (WEB-DASHBOARD.md §4.6)
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      className={cn("group relative w-full rounded-sm", className)}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={`${label}. Press t for its table.`}
      onKeyDown={(event) => {
        if (event.key === "t" && event.target === event.currentTarget) setAsTable(!asTable);
      }}
    >
      <div className="absolute top-0 right-0 z-10 flex overflow-hidden rounded-sm border border-border bg-surface-raised opacity-0 shadow-popover transition-opacity duration-100 group-focus-within:opacity-100 group-hover:opacity-100 has-[[data-state=open]]:opacity-100">
        <ToolButton
          label={asTable ? "Show the chart" : "Show as a table"}
          pressed={asTable}
          onClick={() => setAsTable(!asTable)}
        >
          <Table2 />
        </ToolButton>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <ToolButton label="Download">
              <Download />
            </ToolButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel className="type-overline text-ink-muted">Download</DropdownMenuLabel>
            <DropdownMenuItem
              onSelect={() => download(`${name}.csv`, csv(tableOf(option)), "text/csv")}
            >
              Data as CSV
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => exportPng(instance.current, name)}>
              Image as PNG
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => exportSvg(option, box.current?.clientWidth ?? 800, height, name)}
            >
              Image as SVG
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {asTable && <ChartTableView option={option} label={label} height={height} />}
      <div
        ref={box}
        role="img"
        aria-label={label}
        className={cn("w-full", asTable && "hidden")}
        style={{ height }}
      />
    </div>
  );
}

function ToolButton({
  label,
  pressed,
  children,
  ...props
}: {
  label: string;
  pressed?: boolean;
  children: ReactNode;
} & Omit<ComponentProps<"button">, "children">) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className="flex size-7 items-center justify-center text-ink-muted not-first:border-l not-first:border-border hover:bg-surface-hover hover:text-ink aria-pressed:bg-primary-wash aria-pressed:text-primary-ink [&_svg]:size-3.5"
      {...props}
    >
      {children}
    </button>
  );
}

function exportPng(chart: ChartInstance | null, name: string): void {
  const surface = getComputedStyle(document.documentElement).getPropertyValue("--surface");
  const url = chart?.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: surface });
  if (url)
    void fetch(url)
      .then((response) => response.blob())
      .then((blob) => download(`${name}.png`, blob));
}

/** SVG from ECharts' own SVG renderer, the same option and theme. */
function exportSvg(option: EChartsOption, width: number, height: number, name: string): void {
  const svg = echarts.init(null, registerUndercurrentTheme(echarts), {
    renderer: "svg",
    ssr: true,
    width,
    height,
  });
  svg.setOption({ ...option, animation: false });
  download(`${name}.svg`, svg.renderToSVGString(), "image/svg+xml");
  svg.dispose();
}

function ChartTableView({
  option,
  label,
  height,
}: {
  option: EChartsOption;
  label: string;
  height: number;
}) {
  const table = tableOf(option);
  return (
    <div className="overflow-auto" style={{ maxHeight: Math.max(height, 240) }}>
      <table className="w-full text-xs" aria-label={`${label}, as a table`}>
        <thead className="sticky top-0">
          <tr className="border-b border-border bg-surface-sunken">
            {table.columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="h-7 px-2 text-left type-overline whitespace-nowrap text-ink-muted"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.slice(0, 2000).map((row, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows of one table, in order
            <tr key={index} className="border-b border-border last:border-b-0">
              {row.map((cell, column) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: cells of one row, in order
                <td key={column} className="h-7 px-2 tabular-nums text-ink-secondary">
                  {typeof cell === "number"
                    ? cell.toLocaleString("en", { maximumFractionDigits: 3 })
                    : (cell ?? "–")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
