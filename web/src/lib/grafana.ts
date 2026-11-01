/** "Pro mode": the same view in Grafana, with the same choices made. */
const DASHBOARDS: Record<string, string> = {
  trending: "undercurrent-trending",
  quick: "undercurrent-rising",
  "long-term": "undercurrent-long-term",
  intents: "undercurrent-intents",
  spread: "undercurrent-early-warning",
  explore: "undercurrent-terms",
  collection: "undercurrent-ingestion",
};

const VARIABLES: Record<string, string> = {
  scope: "group",
  horizon: "horizon",
  terms: "terms",
  bucket: "bucket",
  rate: "rate",
  topic: "topic",
  kinds: "kind",
  platforms: "platform",
  leaders: "leader",
  doc_types: "doc_type",
  channels: "channel",
};

export function grafanaLink(
  base: string,
  page: string,
  params: Record<string, string | readonly string[] | number | boolean | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const variable = VARIABLES[key];
    if (!variable || value === undefined || value === "") continue;
    if (key === "terms") {
      query.append(`var-${variable}`, Array.isArray(value) ? value.join(",") : String(value));
      continue;
    }
    for (const item of Array.isArray(value) ? value : [String(value)]) {
      if (item) query.append(`var-${variable}`, String(item));
    }
  }
  const range = params.range ?? params.chart;
  if (typeof range === "string") {
    query.set("from", `now-${range}`);
    query.set("to", "now");
  }
  return `${base}/d/${DASHBOARDS[page] ?? "undercurrent-trending"}?${query.toString()}`;
}
