/** ECharts with only what the kit uses, so the bundle carries nothing else. */
import { BarChart, GraphChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  BrushComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  HeatmapChart,
  GraphChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  DataZoomComponent,
  BrushComponent,
  VisualMapComponent,
  AriaComponent,
  CanvasRenderer,
  SVGRenderer,
]);

export { echarts };
export type EChartsOption = echarts.EChartsCoreOption;
