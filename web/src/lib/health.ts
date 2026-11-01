/** Is collection healthy? One reading for the Collection page and the sidebar's status. */
import type { Feed, Ingestion } from "@/api/generated/model";
import { now } from "./clock";
import { ago } from "./format";

export type Health = "good" | "warning" | "critical";

export function feedState(feed: Feed): [Health, string] {
  const age = (now() - Date.parse(feed.last_poll)) / 1000;
  if (feed.errors > 0 && feed.errors >= feed.polls / 2) return ["critical", "Failing"];
  if (age > Math.max(300, 4 * (feed.poll_every_s ?? 0))) return ["warning", "Late"];
  if (feed.errors > 0 || feed.gaps > 0) return ["warning", feed.errors > 0 ? "Errors" : "Gaps"];
  return ["good", "OK"];
}

export interface CollectionHealth {
  status: Health;
  /** a few words, for the sidebar */
  short: string;
  /** the sentence, for the Collection page */
  long: string;
}

export function collectionHealth(data: Ingestion): CollectionHealth {
  const lastPollAge = data.last_poll ? (now() - Date.parse(data.last_poll)) / 1000 : null;
  if (lastPollAge === null || lastPollAge > 300) {
    const since = data.last_poll ? ago(data.last_poll).replace(" ago", "") : "a while";
    return {
      status: "warning",
      short: `No requests for ${since}`,
      long: `No requests for ${since}. Is the ingester running? (docker compose ps)`,
    };
  }
  const failing = data.feeds.filter((feed) => feedState(feed)[0] !== "good");
  if (failing.length) {
    const critical = failing.some((feed) => feedState(feed)[0] === "critical");
    return {
      status: critical ? "critical" : "warning",
      short: `${failing.length} feed${failing.length === 1 ? " needs" : "s need"} a look`,
      long: `${failing.length} feed${failing.length === 1 ? " needs" : "s need"} a look: ${failing.map((feed) => feed.feed).join(", ")}.`,
    };
  }
  return {
    status: "good",
    short: "Collecting normally",
    long: "Collecting normally: every feed polled recently, without errors or gaps in the last hour.",
  };
}
