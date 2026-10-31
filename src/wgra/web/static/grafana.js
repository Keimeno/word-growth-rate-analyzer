// Links to the same view in Grafana, the pro mode, with the same choices made.
const DASHBOARDS = {
  now: "wgra-trending",
  rising: "wgra-rising",
  "long-term": "wgra-long-term",
  intents: "wgra-intents",
  "early-warning": "wgra-early-warning",
  explore: "wgra-terms",
  health: "wgra-ingestion",
};

const VARIABLES = {
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

export function grafanaLink(config, page, params = {}) {
  const base = config?.grafana_url || "http://localhost:3608";
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const variable = VARIABLES[key];
    if (!variable || value === undefined || value === "") continue;
    for (const item of String(value).split(",")) {
      if (item) query.append(`var-${variable}`, key === "terms" ? value : item);
      if (key === "terms") break;
    }
  }
  if (params.range) {
    query.set("from", `now-${params.range}`);
    query.set("to", "now");
  }
  return `${base}/d/${DASHBOARDS[page] || DASHBOARDS.now}?${query}`;
}
