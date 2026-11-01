import type { UseQueryResult } from "@tanstack/react-query";
import { CircleCheck, CircleHelp, CircleX, Info, RotateCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiError } from "@/api/fetcher";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** A help icon with its text on hover and focus. */
export function Help({
  children,
  label = "What this means",
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-full text-ink-muted hover:text-ink"
        >
          <CircleHelp className="size-3.5" strokeWidth={1.75} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-80 text-xs leading-4">{children}</TooltipContent>
    </Tooltip>
  );
}

interface PanelProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  help?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** content to the edges: tables */
  flush?: boolean;
  className?: string;
  id?: string;
}

/** The frame every chart and table sits in: a header with the title, what's measured (unit,
 * bucket, window) and the panel's controls over a hairline, then the content. */
export function Panel({
  title,
  subtitle,
  help,
  actions,
  children,
  flush,
  className,
  id,
}: PanelProps) {
  return (
    <section
      id={id}
      className={cn("min-w-0 rounded-md border border-border bg-surface", className)}
      aria-label={typeof title === "string" ? title : undefined}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
          <div className="min-h-7 min-w-0 flex-1 basis-60 self-center">
            {title && (
              <h2 className="flex items-center gap-1 text-sm leading-5 font-semibold text-ink">
                {title}
                {help && <Help>{help}</Help>}
              </h2>
            )}
            {subtitle && <p className="text-xs leading-4 text-ink-muted">{subtitle}</p>}
          </div>
          {actions && (
            <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">{actions}</div>
          )}
        </header>
      )}
      <div className={cn(!flush && "p-4")} data-padded={flush ? undefined : ""}>
        {children}
      </div>
    </section>
  );
}

/** A query's data, or its first load in the shape of what's coming, or its error with a
 * retry; the last data stays while it refetches (at lower opacity), so nothing jumps. */
export function Loaded<T>({
  query,
  children,
  height = 120,
  shape,
}: {
  query: UseQueryResult<T, ApiError>;
  children: (data: T) => ReactNode;
  height?: number;
  /** what's loading: rows of a table, or a block (a chart, a list) */
  shape?: "table" | "block";
}) {
  if (query.data !== undefined) {
    return (
      <div
        className={cn("transition-opacity duration-160", query.isPlaceholderData && "opacity-60")}
        aria-busy={query.isFetching}
      >
        {children(query.data)}
      </div>
    );
  }
  if (query.isError) {
    return (
      <div role="alert" className="flex items-start gap-3 p-4 in-data-padded:p-0">
        <CircleX className="mt-0.5 size-4 shrink-0 text-status-critical-text" aria-hidden />
        <div className="min-w-0 flex-1 text-[13px]">
          <p className="font-medium text-ink">Couldn't load this</p>
          <p className="mt-0.5 text-ink-muted">{query.error.message}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
          <RotateCw /> Retry
        </Button>
      </div>
    );
  }
  if (shape === "table") {
    const rows = Math.max(3, Math.min(10, Math.round(height / 40)));
    return (
      <div aria-busy>
        <div className="h-8 border-b border-border bg-surface-sunken" />
        {Array.from({ length: rows }, (_, index) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: placeholder rows, in order
            key={index}
            className="flex h-10 items-center gap-6 border-b border-border px-4 last:border-b-0"
          >
            <Skeleton className="h-3 w-40" />
            <Skeleton className="ml-auto h-3 w-12" />
            <Skeleton className="h-3 w-16" />
            <Skeleton className="hidden h-3 w-24 sm:block" />
          </div>
        ))}
      </div>
    );
  }
  return (
    // in a padded panel the skeleton fills the content box; in a flush one it keeps an inset
    <div className="p-4 in-data-padded:p-0" aria-busy>
      <Skeleton className="w-full" style={{ height }} />
    </div>
  );
}

/** A section with nothing to show says why and when there will be something. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <p className="text-sm font-semibold text-ink-secondary">{title}</p>
      {children && (
        <p className="mt-1 max-w-md text-[13px] leading-[18px] text-ink-muted">{children}</p>
      )}
    </div>
  );
}

const NOTICE = {
  info: {
    icon: Info,
    className: "border-border bg-surface text-ink-secondary",
    iconClass: "text-ink-muted",
  },
  warning: {
    icon: TriangleAlert,
    className: "border-status-warning/50 bg-status-warning-wash text-status-warning-text",
    iconClass: "text-status-warning-text",
  },
  good: {
    icon: CircleCheck,
    className: "border-status-good/40 bg-status-good-wash text-status-good-text",
    iconClass: "text-status-good-text",
  },
} as const;

/** A line of context above the numbers: warm-up, a failing feed. Always with its icon. */
export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "good";
  children: ReactNode;
}) {
  const { icon: Icon, className, iconClass } = NOTICE[tone];
  return (
    <div
      role={tone === "warning" ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-md border px-3 py-2 text-[13px] leading-[18px]",
        className,
      )}
    >
      <Icon className={cn("mt-px size-4 shrink-0", iconClass)} strokeWidth={1.75} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
