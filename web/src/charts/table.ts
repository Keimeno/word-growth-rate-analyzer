/** A chart's numbers as a table, from the same option the chart draws: the table view and
 * the CSV export of every chart (WEB-DASHBOARD.md §4.4). */
import type { EChartsOption } from "./echarts";

export interface ChartTable {
  columns: string[];
  rows: Array<Array<string | number | null>>;
}

const time = (value: unknown) =>
  typeof value === "number" && value > 10 ** 11
    ? new Date(value).toISOString().replace(".000Z", "Z")
    : (value as string | number | null);

export function tableOf(option: EChartsOption): ChartTable {
  const series = (option.series ?? []) as Array<Record<string, unknown>>;
  const axis = (key: "xAxis" | "yAxis") => (option[key] as { data?: string[] } | undefined)?.data;
  const first = series[0];
  if (first?.type === "sankey") {
    const links = (first.links ?? []) as Array<{ source: string; target: string; value: number }>;
    return {
      columns: ["from", "to", "value"],
      rows: links.map((link) => [
        link.source.replace(/^from: /, ""),
        link.target.replace(/^to: /, ""),
        link.value,
      ]),
    };
  }
  if (first?.type === "graph") {
    const links = (first.links ?? []) as Array<{
      source: string;
      target: string;
      tooltip?: string;
    }>;
    return { columns: ["from", "to"], rows: links.map((link) => [link.source, link.target]) };
  }
  if (first?.type === "heatmap") {
    const x = axis("xAxis");
    const y = axis("yAxis");
    const cells = (first.data ?? []) as Array<[number | string, number | string, number | null]>;
    return {
      columns: x && y ? ["row", "column", "value"] : ["day", "value"],
      rows: cells.map((cell) =>
        x && y
          ? [y[Number(cell[1])] ?? cell[1], x[Number(cell[0])] ?? cell[0], cell[2]]
          : [cell[0], cell[1]],
      ),
    };
  }
  const rows: ChartTable["rows"] = [];
  for (const one of series) {
    const name = one.name;
    if (typeof name !== "string" || !name) continue;
    for (const point of (one.data ?? []) as Array<unknown>) {
      if (Array.isArray(point))
        rows.push([name, time(point[0]), (point[1] as number | null) ?? null]);
    }
  }
  return { columns: ["series", "x", "value"], rows };
}

export function csv(table: ChartTable): string {
  const cell = (value: string | number | null) => {
    const text = value === null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return [table.columns, ...table.rows].map((row) => row.map(cell).join(",")).join("\n");
}

export function download(name: string, content: string | Blob, type = "text/plain"): void {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
