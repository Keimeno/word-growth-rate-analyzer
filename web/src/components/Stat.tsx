import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Help } from "./Panel";

interface StatProps {
  label: string;
  value: ReactNode;
  unit?: ReactNode;
  hint?: ReactNode;
  help?: ReactNode;
  pressed?: boolean;
  onClick?: () => void;
}

/** A headline number with its unit and what it's compared with: one cell of a KpiRow. */
export function StatTile({ label, value, unit, hint, help, pressed, onClick }: StatProps) {
  const figure = (
    <>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5">
        <span
          className={cn(
            "tabular-nums text-ink",
            // a date or a sentence as the value: a size that fits a cell
            typeof value === "string" && value.length > 10
              ? "text-lg leading-7 font-medium tracking-[-0.01em]"
              : "type-figure-md",
          )}
        >
          {value}
        </span>
        {unit && <span className="text-xs text-ink-muted">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-xs leading-4 text-ink-muted">{hint}</div>}
    </>
  );
  return (
    <div
      className={cn(
        "relative min-w-0 flex-1 basis-44 border-r border-b border-border bg-surface px-4 py-3 text-left",
        onClick && "hover:bg-surface-hover",
        pressed && "bg-primary-wash shadow-[inset_0_2px_0_var(--primary)] hover:bg-primary-wash",
      )}
    >
      {/* labels wrap rather than lose their end; on phones every label keeps two lines, so the
          values of a row stay level */}
      <div className="relative z-10 flex items-start gap-1 text-xs leading-4 font-medium text-ink-muted max-sm:min-h-9">
        <span className="py-0.5 text-pretty">{label}</span>
        {help && (
          <span className="-my-0.5 shrink-0">
            <Help>{help}</Help>
          </span>
        )}
      </div>
      {onClick ? (
        <button
          type="button"
          aria-pressed={pressed}
          aria-label={`${label}: show its comments`}
          className="block w-full rounded-sm text-left after:absolute after:inset-0"
          onClick={onClick}
        >
          {figure}
        </button>
      ) : (
        figure
      )}
    </div>
  );
}

/** The headline numbers of a page as one strip, cells divided by hairlines; it wraps
 * without holes, the last row's cells sharing its width. */
export function KpiRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-md border border-border bg-surface", className)}>
      <div className="-mr-px -mb-px flex flex-wrap">{children}</div>
    </div>
  );
}
