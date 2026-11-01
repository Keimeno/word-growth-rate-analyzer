import type { UseQueryResult } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiError } from "@/api/fetcher";
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

/** The frame every chart and table sits in: title, subtitle, help, actions. */
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
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-3">
          <div className="min-w-0">
            {title && (
              <h2 className="flex items-center gap-1.5 type-title-sm">
                {title}
                {help && <Help>{help}</Help>}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(flush ? "pt-2" : "p-4 pt-3")}>{children}</div>
    </section>
  );
}

/** A query's data, or its first load, or its error; the last data stays while it refetches
 * (at lower opacity), so nothing jumps. */
export function Loaded<T>({
  query,
  children,
  height = 120,
}: {
  query: UseQueryResult<T, ApiError>;
  children: (data: T) => ReactNode;
  height?: number;
}) {
  if (query.data !== undefined) {
    return (
      <div
        className={cn("transition-opacity", query.isPlaceholderData && "opacity-60")}
        aria-busy={query.isFetching}
      >
        {children(query.data)}
      </div>
    );
  }
  if (query.isError) {
    return (
      <p role="alert" className="px-4 pb-4 text-sm text-status-critical-text">
        Couldn't load this: {query.error.message}
      </p>
    );
  }
  return (
    <div className="px-4 pb-4" aria-busy>
      <Skeleton className="w-full" style={{ height }} />
    </div>
  );
}

/** A section with nothing to show says why and when there will be something. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-4 py-8 text-center">
      <p className="type-title-sm text-ink-secondary">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-prose text-sm text-ink-muted">{children}</p>}
    </div>
  );
}

/** A line of context above the numbers: warm-up, a failing feed. */
export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "good";
  children: ReactNode;
}) {
  return (
    <div
      role={tone === "warning" ? "alert" : "status"}
      className={cn(
        "flex gap-2 rounded-md border px-3 py-2 text-sm",
        tone === "info" && "border-border bg-surface-sunken text-ink-secondary",
        tone === "warning" &&
          "border-status-warning bg-status-warning-wash text-status-warning-text",
        tone === "good" && "border-status-good bg-status-good-wash text-status-good-text",
      )}
    >
      {children}
    </div>
  );
}
