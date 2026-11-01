/**
 * What "now" is for relative times ("3 h ago"): the browser's clock, unless the server says
 * it's showing another time (a frozen demo database, or `as_of`). Set from /meta.
 */
let reference: number | null = null;

export function now(): number {
  return reference ?? Date.now();
}

/** The server's now; ignored when it's within a few minutes of the browser's. */
export function setServerNow(iso: string | null | undefined): void {
  const server = iso ? Date.parse(iso) : Number.NaN;
  reference = Number.isFinite(server) && Math.abs(server - Date.now()) > 5 * 60_000 ? server : null;
}
