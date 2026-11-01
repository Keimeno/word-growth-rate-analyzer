/**
 * Live updates (WEB-DASHBOARD.md §5.3): one EventSource on /api/v1/stream, and which
 * queries each event makes stale. Payloads are checked with Zod, since the generated types
 * don't cover the stream. Without the stream, queries refetch on focus and every 5 minutes.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { z } from "zod";

const STALE: Record<string, string[]> = {
  run: ["/api/v1/trends", "/api/v1/rising", "/api/v1/terms", "/api/v1/intents", "/api/v1/explore"],
  long_term: ["/api/v1/long-term", "/api/v1/terms"],
  edges: [
    "/api/v1/edges",
    "/api/v1/edge",
    "/api/v1/forecasts",
    "/api/v1/events",
    "/api/v1/spread",
    "/api/v1/scopes",
  ],
  alert: ["/api/v1/alerts", "/api/v1/trends", "/api/v1/forecasts"],
  ingest: ["/api/v1/ingestion"],
};

export const sentAlert = z.object({
  kind: z.string(),
  scope: z.string(),
  term: z.string(),
  title: z.string(),
});
export type SentAlert = z.infer<typeof sentAlert>;

/** Listens while `enabled` (not while showing the past). */
export function useLiveUpdates(enabled: boolean, onAlert: (alert: SentAlert) => void): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return undefined;
    const source = new EventSource("/api/v1/stream");
    const stale = (name: string) => () => {
      const prefixes = STALE[name] ?? [];
      void queryClient.invalidateQueries({
        predicate: (query) =>
          prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
      });
    };
    const listeners = Object.keys(STALE).map((name) => [name, stale(name)] as const);
    for (const [name, listener] of listeners) source.addEventListener(name, listener);
    const alert = (event: MessageEvent<string>) => {
      try {
        const parsed = sentAlert.safeParse(JSON.parse(event.data));
        if (parsed.success) onAlert(parsed.data);
      } catch {
        // a payload that isn't JSON: nothing to show
      }
    };
    source.addEventListener("alert", alert);
    return () => {
      for (const [name, listener] of listeners) source.removeEventListener(name, listener);
      source.removeEventListener("alert", alert);
      source.close();
    };
  }, [enabled, onAlert, queryClient]);
}
