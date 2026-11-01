/**
 * How search params look in the url: plain `key=value`, lists comma separated
 * (`kinds=word,phrase`), true as `1`, so links stay short and readable
 * (WEB-DASHBOARD.md §6.7). Each route's Zod schema (search.ts) parses the strings back.
 */
export function parseSearch(search: string): Record<string, string> {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const result: Record<string, string> = {};
  for (const [key, value] of params) result[key] = value;
  return result;
}

function text(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (Array.isArray(value)) return value.map(String).join(",");
  if (value === true) return "1";
  if (value === false) return "0";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    const written = text(value);
    if (written !== undefined) params.set(key, written);
  }
  const query = params
    .toString()
    .replaceAll("%2C", ",")
    .replaceAll("%2F", "/")
    .replaceAll("%3A", ":");
  return query ? `?${query}` : "";
}
