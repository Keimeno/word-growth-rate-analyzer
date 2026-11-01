import { useEffect, useRef } from "react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { type EChartsOption, echarts } from "./echarts";
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

  return (
    <div
      ref={box}
      role="img"
      aria-label={label}
      className={cn("w-full", className)}
      style={{ height }}
    />
  );
}
