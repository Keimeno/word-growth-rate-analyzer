import { Link } from "@tanstack/react-router";
import { CircleAlert, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { Strength } from "@/lib/format";
import { KIND_LABELS } from "@/lib/kinds";
import { cn } from "@/lib/utils";

/** A term, as everywhere: in mono as the detector stores it, opening its peek. */
export function TermLink({
  term,
  kind,
  label,
  color,
}: {
  term: string;
  kind: string;
  label?: string;
  color?: string | undefined;
}) {
  return (
    <Link
      to="."
      search={
        ((previous: Record<string, unknown>) => ({ ...previous, peek: `${kind}:${term}` })) as never
      }
      resetScroll={false}
      className="inline-flex max-w-full items-center gap-1.5 rounded-sm font-medium text-ink hover:text-primary hover:underline"
      onClick={(event) => event.stopPropagation()}
    >
      {color && (
        <span
          aria-hidden
          className="h-0.5 w-2.5 shrink-0 rounded-full"
          style={{ background: color }}
        />
      )}
      <span className="term truncate">{label ?? term}</span>
    </Link>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  if (kind === "word") return null;
  const label = (KIND_LABELS[kind] ?? kind).replace(/s$/, "").toLowerCase();
  return (
    <span className="ml-1.5 rounded-xs bg-surface-sunken px-1 py-px text-[11px] text-ink-muted">
      {label}
    </span>
  );
}

/** A strength as a word with three steps of seq-700 (BRAND.md §8, the trend row). */
export function StrengthWord({ value, title }: { value: Strength; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span aria-hidden className="flex gap-0.5">
        {[1, 2, 3].map((step) => (
          <span
            key={step}
            className={cn(
              "h-2.5 w-1 rounded-xs",
              step <= value.level ? "bg-seq-700" : "bg-seq-100",
            )}
          />
        ))}
      </span>
      <span className="text-ink-secondary">{value.label}</span>
    </span>
  );
}

const STATUS = {
  good: { icon: CircleCheck, className: "bg-status-good-wash text-status-good-text" },
  warning: { icon: TriangleAlert, className: "bg-status-warning-wash text-status-warning-text" },
  serious: { icon: CircleAlert, className: "bg-status-serious-wash text-status-serious-text" },
  critical: { icon: CircleX, className: "bg-status-critical-wash text-status-critical-text" },
} as const;

/** The system's state, always with an icon and a word (BRAND.md §5.4). */
export function StatusBadge({
  status,
  children,
}: {
  status: keyof typeof STATUS | "neutral";
  children: ReactNode;
}) {
  if (status === "neutral") {
    return (
      <Badge variant="outline" className="font-normal text-ink-secondary">
        {children}
      </Badge>
    );
  }
  const { icon: Icon, className } = STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <Icon className="size-3" strokeWidth={2} aria-hidden />
      {children}
    </span>
  );
}

const ALERTS: Record<string, [keyof typeof STATUS | "neutral", string]> = {
  sent: ["good", "Sent"],
  failed: ["critical", "Failed"],
  capped: ["warning", "Daily limit"],
  cooldown: ["neutral", "Cooldown"],
  warmup: ["neutral", "Warming up"],
  skipped: ["neutral", "Skipped"],
  muted: ["neutral", "Muted"],
};

export const ALERT_HELP =
  "What happened to the trends strong enough for an instant alert: sent, failed, daily limit reached (at most 5 a day), cooldown (alerted in the last 72 hours), warming up (less than 3 days of history), skipped (the scope never alerts), muted (a run without notifications).";

export function AlertBadge({ alert }: { alert: string }) {
  if (!alert) return null;
  const [status, label] = ALERTS[alert] ?? ["neutral", alert];
  return <StatusBadge status={status}>{label}</StatusBadge>;
}
