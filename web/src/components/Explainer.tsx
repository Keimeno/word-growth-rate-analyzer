import { Check, X } from "lucide-react";
import { useTermExplain } from "@/api/generated/endpoints";
import type { Explanation } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Dumbbell } from "@/charts/micro";
import { count, decimal, formatDateTime, perThousand, strength, times } from "@/lib/format";
import { pathPart } from "@/lib/links";
import { cn } from "@/lib/utils";
import { AlertBadge, ScopeLink } from "./Entity";
import { Loaded } from "./Panel";

const OUTCOMES: Record<string, string> = {
  sent: "Sent: strong enough for an instant alert, and nothing held it back.",
  failed: "Strong enough for an alert, but sending it failed.",
  capped:
    "Strong enough for an alert, but the day's alerts had been sent (notify.max_alerts_per_day).",
  cooldown:
    "Strong enough for an alert, but it was alerted in the last 72 hours and its score hasn't doubled since.",
  warmup:
    "Strong enough for an alert, but the scope has fewer days of history than alerts wait for.",
  skipped: "Strong enough for an alert, but this scope never alerts (notify.skip_scopes).",
  muted: "Strong enough for an alert, but the run sent no notifications.",
};

const perThousandShare = (share: number) => perThousand(1000 * share);

/** "Why is this trending" (WEB-DASHBOARD.md §7.1, item 2): the shares, the prior's pull, the
 * gates with their values, the alert's outcome and the channels of a group. */
export function Explainer({
  kind,
  term,
  scope,
  horizon,
}: {
  kind: string;
  term: string;
  scope: string;
  horizon: string;
}) {
  const asOf = useAsOf();
  const query = useTermExplain(kind, pathPart(term), { ...asOf, scope, horizon });
  return <Loaded query={query}>{(data) => <Explained data={data} />}</Loaded>;
}

function Explained({ data }: { data: Explanation }) {
  const share = (value: number | null | undefined) => value ?? 0;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ink-secondary">
        In the {data.horizon === "24h" ? "last 24 hours" : "last 6 hours"} up to{" "}
        {formatDateTime(data.detected_at)},{" "}
        <span className="font-medium text-ink">{count(data.mentions)}</span> of {count(data.total)}{" "}
        comments and posts in <ScopeLink scope={data.scope} /> mentioned it, by{" "}
        {count(data.authors)} people:{" "}
        <span className="font-medium text-ink">{times(data.ratio, data.is_new)}</span> its share in
        the {data.reference_days} days before ({count(data.reference_mentions)} of{" "}
        {count(data.reference_total)}).
      </p>
      <div>
        <div className="mb-1 text-xs text-ink-muted">Per 1,000 comments and posts</div>
        <Dumbbell
          before={1000 * share(data.share_before)}
          now={1000 * share(data.share_now)}
          reference={data.platform_share === null ? null : 1000 * data.platform_share}
          format={(value) => perThousand(value)}
        />
        <p className="mt-1 text-xs text-ink-muted">
          The prior blends both sides with the platform's share:{" "}
          {perThousandShare(share(data.share_before))} →{" "}
          {perThousandShare(share(data.share_before_with_prior))} before,{" "}
          {perThousandShare(share(data.share_now))} →{" "}
          {perThousandShare(share(data.share_now_with_prior))} now. Strength: δ{" "}
          {decimal(data.log_odds, 2)} over σ {decimal(data.sigma, 2)} is z {decimal(data.score)},{" "}
          {strength(data.score).label}
          {data.recomputed_score !== null &&
          Math.abs((data.recomputed_score ?? 0) - (data.score ?? 0)) > 0.05
            ? ` (today's settings give ${decimal(data.recomputed_score)})`
            : ""}
          .
        </p>
      </div>
      {data.gates.length > 0 && (
        <div>
          <div className="mb-1 text-xs text-ink-muted">The gates</div>
          <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {data.gates.map((gate) => (
              <li key={gate.name} className="flex items-center gap-2">
                {gate.passed ? (
                  <Check className="size-4 shrink-0 text-status-good-text" aria-label="passed" />
                ) : (
                  <X className="size-4 shrink-0 text-ink-muted" aria-label="not passed" />
                )}
                <span className={cn(!gate.passed && "text-ink-muted")}>
                  {gate.label}:{" "}
                  <span className="tabular-nums">
                    {decimal(gate.value, Number.isInteger(gate.value) ? 0 : 1)}
                  </span>{" "}
                  <span className="text-ink-muted">
                    of {decimal(gate.threshold, Number.isInteger(gate.threshold) ? 0 : 1)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(data.alert || data.subsumed_by) && (
        <div className="flex flex-col gap-1 text-sm">
          {data.alert && (
            <p className="flex flex-wrap items-center gap-2">
              <AlertBadge alert={data.alert} />{" "}
              <span className="text-ink-secondary">{OUTCOMES[data.alert] ?? data.alert}</span>
            </p>
          )}
          {data.subsumed_by && (
            <p className="text-ink-secondary">
              Explained by the phrase “<span className="term">{data.subsumed_by}</span>”: without
              its comments, it wouldn't trend.
            </p>
          )}
        </div>
      )}
      {data.members.length > 0 && (
        <div>
          <div className="mb-1 text-xs text-ink-muted">Its channels in the same run</div>
          <ul className="flex flex-wrap gap-2 text-sm">
            {data.members.map((member) => (
              <li key={member.scope} className="rounded-sm bg-surface-sunken px-2 py-1">
                <ScopeLink scope={member.scope} />{" "}
                <span className="text-ink-muted">{times(member.ratio)}</span>{" "}
                <span className="text-xs text-ink-muted">z {decimal(member.score)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
