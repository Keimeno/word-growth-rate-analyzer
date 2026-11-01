import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

const GO: Record<string, [string, string]> = {
  t: ["/trending", "Trending"],
  l: ["/long-term", "Long-term"],
  s: ["/intents", "Why people switch"],
  e: ["/spread", "Early warning"],
  x: ["/explore", "Explore"],
  c: ["/collection", "Collection"],
  a: ["/alerts", "Alerts"],
  p: ["/pinned", "Pinned"],
};

const KEYS: Array<[string, string]> = [
  ["⌘K or /", "Search pages, scopes and terms; save a view; time travel"],
  ["?", "These shortcuts"],
  ...Object.entries(GO).map(([key, [, label]]): [string, string] => [`g ${key}`, `Go to ${label}`]),
  ["[", "Collapse or expand the sidebar"],
  ["t", "On a focused chart: its table, or the chart again"],
  ["Esc", "Close the peek, a dialog or the palette"],
];

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  Boolean(target.closest("input, textarea, select, [contenteditable=true]"));

/** `?` for help, `g` then a letter to go to a page. */
export function Shortcuts() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    let leader = 0;
    const key = (event: KeyboardEvent) => {
      if (typing(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "?") {
        event.preventDefault();
        setOpen(true);
      } else if (event.key === "[") {
        window.dispatchEvent(new Event("undercurrent:sidebar"));
      } else if (event.key === "g") {
        leader = Date.now();
      } else if (Date.now() - leader < 1200 && GO[event.key]) {
        leader = 0;
        void navigate({ to: GO[event.key]?.[0] ?? "/trending" });
      }
    };
    const show = () => setOpen(true);
    window.addEventListener("keydown", key);
    window.addEventListener("undercurrent:shortcuts", show);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("undercurrent:shortcuts", show);
    };
  }, [navigate]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Everywhere but in a text field.</DialogDescription>
        </DialogHeader>
        <dl className="-mx-6 border-t border-border text-[13px]">
          {KEYS.map(([keys, what]) => (
            <div
              key={keys}
              className="flex flex-row-reverse items-center justify-between gap-4 border-b border-border px-6 py-2 last:border-b-0"
            >
              <dt className="flex shrink-0 gap-1">
                {keys.split(" ").map((part) =>
                  part === "or" ? (
                    <span key={part} className="text-xs text-ink-muted">
                      or
                    </span>
                  ) : (
                    <kbd
                      key={part}
                      className="min-w-5 rounded-xs border border-border border-b-control-border bg-surface-sunken px-1.5 py-px text-center font-sans text-[11px] leading-4 font-medium text-ink-secondary"
                    >
                      {part}
                    </kbd>
                  ),
                )}
              </dt>
              <dd className="text-ink-secondary">{what}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
