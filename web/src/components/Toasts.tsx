import { Link } from "@tanstack/react-router";
import { Bell, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { type SentAlert, useLiveUpdates } from "@/api/stream";
import { intentKind } from "@/lib/kinds";
import { useAnySearch } from "@/lib/navigation";

interface Toast extends SentAlert {
  id: number;
}

/** A new alert while the page is open: a toast that opens the term page. */
export function Toasts() {
  const search = useAnySearch();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((alert: SentAlert) => {
    setToasts((current) => [...current.slice(-2), { ...alert, id: Date.now() + Math.random() }]);
  }, []);
  useLiveUpdates(typeof search.as_of !== "string", add);
  useEffect(() => {
    if (!toasts.length) return undefined;
    const timer = setTimeout(() => setToasts((current) => current.slice(1)), 15_000);
    return () => clearTimeout(timer);
  }, [toasts]);
  return (
    <div
      aria-live="polite"
      className="fixed right-4 bottom-20 z-50 flex w-80 flex-col gap-2 md:bottom-4"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className="flex items-start gap-3 rounded-md border border-border bg-surface-raised p-3 text-sm shadow-[var(--elevation-popover)]"
        >
          <Bell className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="text-xs text-ink-muted">
              {toast.kind === "forecast" ? "Forecast alert" : "Alert"} · {toast.scope}
            </div>
            <Link
              to="/t/$kind/$"
              params={{
                kind: intentKind(toast.term) ?? (toast.term.includes(" ") ? "phrase" : "word"),
                _splat: toast.term,
              }}
              search={{ scope: toast.scope } as never}
              className="term font-medium hover:text-primary hover:underline"
            >
              {toast.term}
            </Link>
          </div>
          <button
            type="button"
            aria-label="Dismiss"
            className="text-ink-muted hover:text-ink"
            onClick={() => setToasts((current) => current.filter((other) => other.id !== toast.id))}
          >
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
