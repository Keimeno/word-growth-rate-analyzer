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

/** A headline number with its unit and what it's compared with. */
export function StatTile({ label, value, unit, hint, help, pressed, onClick }: StatProps) {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-xs text-ink-muted">
        <span className="truncate">{label}</span>
        {help && <Help>{help}</Help>}
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-xl leading-7 font-medium tabular-nums">{value}</span>
        {unit && <span className="text-xs text-ink-muted">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 text-xs text-ink-muted">{hint}</div>}
    </>
  );
  const classes = cn(
    "min-w-0 rounded-md border border-border bg-surface px-4 py-3 text-left",
    pressed && "border-primary bg-primary-wash",
  );
  return onClick ? (
    <button
      type="button"
      className={cn(classes, "hover:bg-surface-hover")}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {body}
    </button>
  ) : (
    <div className={classes}>{body}</div>
  );
}

export function KpiRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-[repeat(auto-fit,minmax(170px,1fr))]",
        className,
      )}
    >
      {children}
    </div>
  );
}
