import { useNavigate } from "@tanstack/react-router";
import {
  Bookmark,
  BookmarkPlus,
  Compass,
  Copy,
  Eye,
  Hash,
  History,
  Keyboard,
  Layers,
  Moon,
  Pin,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getViewsQueryKey,
  saveView,
  usePins,
  useSearch as useTermSearch,
  useViews,
} from "@/api/generated/endpoints";
import { useAsOf, useMetaData } from "@/api/hooks";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { setTheme, useTheme } from "@/lib/theme";
import { PAGES } from "./AppShell";
import { searchOf, withSearch } from "@/lib/navigation";

/** ⌘K or `/`: pages, scopes and actions, and any typed term (WEB-DASHBOARD.md §6.6). Terms
 * from the catalog come with phase 3. */
export function Palette() {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const navigate = useNavigate();
  const meta = useMetaData();
  const theme = useTheme();

  useEffect(() => {
    const show = () => setOpen(true);
    const key = (event: KeyboardEvent) => {
      const typing =
        event.target instanceof HTMLElement &&
        event.target.closest("input, textarea, [contenteditable=true]");
      if (
        (event.key === "k" && (event.metaKey || event.ctrlKey)) ||
        (event.key === "/" && !typing)
      ) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    window.addEventListener("undercurrent:palette", show);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("undercurrent:palette", show);
      window.removeEventListener("keydown", key);
    };
  }, []);

  const go = (action: () => void) => {
    setOpen(false);
    setTyped("");
    action();
  };
  const term = typed.trim().toLowerCase().replace(/\s+/g, " ");
  const asOf = useAsOf();
  const queryClient = useQueryClient();
  const pins = usePins(undefined, { query: { enabled: open } });
  const views = useViews(undefined, { query: { enabled: open } });
  const save = useMutation({
    mutationFn: (name: string) => saveView({ name, url: location.pathname + location.search }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: getViewsQueryKey() }),
  });
  // "2026-10-01" or "2026-10-01 14:00": the dashboard as it was then
  const when = typed.trim().match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?$/);
  const hits = useTermSearch(
    { ...asOf, q: term },
    { query: { enabled: term.length >= 2, staleTime: 60_000 } },
  );

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title="Search"
      description="Pages, scopes and terms"
    >
      <CommandInput
        placeholder="A page, a scope or a term…"
        value={typed}
        onValueChange={setTyped}
      />
      <CommandList>
        <CommandEmpty>Nothing matches.</CommandEmpty>
        {term.length >= 2 && (hits.data ?? []).length > 0 && (
          <CommandGroup heading="Terms">
            {(hits.data ?? []).map((hit) => (
              <CommandItem
                key={`${hit.kind}:${hit.term}`}
                value={`term ${hit.term} ${hit.kind}`}
                onSelect={() =>
                  go(
                    () =>
                      void navigate({
                        to: "/t/$kind/$",
                        params: { kind: hit.kind, _splat: hit.term },
                      }),
                  )
                }
              >
                <Hash className="size-4" /> <span className="term">{hit.term}</span>
                <CommandShortcut>{hit.kind}</CommandShortcut>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {when && (
          <CommandGroup heading="Time travel">
            <CommandItem
              value={`as of ${typed}`}
              onSelect={() =>
                go(
                  () =>
                    void navigate({
                      to: ".",
                      search: withSearch({ as_of: `${when[1]}T${when[2] ?? "12:00"}Z` }),
                    }),
                )
              }
            >
              <History className="size-4" /> Show the dashboard as of {when[1]} {when[2] ?? "12:00"}{" "}
              UTC
            </CommandItem>
          </CommandGroup>
        )}
        {(pins.data ?? []).length > 0 && (
          <CommandGroup heading="Pinned">
            {(pins.data ?? []).map((pin) => (
              <CommandItem
                key={`${pin.kind}:${pin.term}`}
                value={`pinned ${pin.term}`}
                onSelect={() =>
                  go(
                    () =>
                      void navigate({
                        to: "/t/$kind/$",
                        params: { kind: pin.kind, _splat: pin.term },
                      }),
                  )
                }
              >
                <Pin className="size-4" /> <span className="term">{pin.term}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {(views.data ?? []).length > 0 && (
          <CommandGroup heading="Saved views">
            {(views.data ?? []).map((view) => (
              <CommandItem
                key={view.name}
                value={`view ${view.name}`}
                onSelect={() => go(() => void navigate({ href: view.url }))}
              >
                <Bookmark className="size-4" /> {view.name}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        <CommandGroup heading="Pages">
          {PAGES.map((page) => (
            <CommandItem
              key={page.to}
              value={`page ${page.label}`}
              onSelect={() => go(() => void navigate({ to: page.to }))}
            >
              <page.icon className="size-4" /> {page.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Scopes">
          {(meta.data?.scopes ?? []).map((scope) => (
            <CommandItem
              key={scope.name}
              value={`scope ${scope.name}`}
              onSelect={() =>
                go(
                  () =>
                    void navigate({
                      to: ".",
                      search: ((previous: Record<string, unknown>) => ({
                        ...previous,
                        scope: scope.name,
                      })) as never,
                    }),
                )
              }
            >
              <Layers className="size-4" /> {scope.name}
              <CommandShortcut>{scope.type}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Actions">
          <CommandItem
            value="action toggle dark mode"
            onSelect={() => go(() => setTheme(theme === "dark" ? "light" : "dark"))}
          >
            <Moon className="size-4" /> {theme === "dark" ? "Light mode" : "Dark mode"}
          </CommandItem>
          {typed.trim() && !when && (
            <CommandItem
              value={`action save view ${typed}`}
              onSelect={() => go(() => save.mutate(typed.trim()))}
            >
              <BookmarkPlus className="size-4" /> Save this view as “{typed.trim()}”
            </CommandItem>
          )}
          <CommandItem
            value="action keyboard shortcuts help"
            onSelect={() => go(() => window.dispatchEvent(new Event("undercurrent:shortcuts")))}
          >
            <Keyboard className="size-4" /> Keyboard shortcuts
          </CommandItem>
          <CommandItem
            value="action copy link"
            onSelect={() => go(() => void navigator.clipboard.writeText(location.href))}
          >
            <Copy className="size-4" /> Copy link to this view
          </CommandItem>
        </CommandGroup>
        {term && (
          <CommandGroup heading="Term">
            <CommandItem
              value={`explore ${term}`}
              onSelect={() =>
                go(() => void navigate({ to: "/explore", search: searchOf({ terms: [term] }) }))
              }
            >
              <Compass className="size-4" /> Explore{" "}
              <span className="term font-medium">{term}</span>
            </CommandItem>
            <CommandItem
              value={`peek ${term}`}
              onSelect={() =>
                go(
                  () =>
                    void navigate({
                      to: ".",
                      search: ((previous: Record<string, unknown>) => ({
                        ...previous,
                        peek: `word:${term}`,
                      })) as never,
                    }),
                )
              }
            >
              <Eye className="size-4" /> Peek at <span className="term font-medium">{term}</span>
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
