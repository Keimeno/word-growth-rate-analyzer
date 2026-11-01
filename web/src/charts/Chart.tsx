/** Charts in pages: ECharts loads with the first chart a page shows, not with the app
 * (WEB-DASHBOARD.md §4.7), so the first page stays small. */
import { lazy, Suspense } from "react";
import type { ChartProps } from "./EChart";

export type { ChartInstance } from "./EChart";
export { useChartTokens, useReducedMotion } from "./hooks";

const EChart = lazy(() => import("./EChart"));

export function Chart(props: ChartProps) {
  return (
    <Suspense fallback={<div style={{ height: props.height ?? 240 }} aria-busy />}>
      <EChart {...props} />
    </Suspense>
  );
}
