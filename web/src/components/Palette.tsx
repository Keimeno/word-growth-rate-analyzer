import { useNavigate } from "@tanstack/react-router";
import { Compass, Copy, Eye, Layers, Moon } from "lucide-react";
import { useEffect, useState } from "react";
import { useMetaData } from "@/api/hooks";
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
import { searchOf } from "@/lib/navigation";

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
          <CommandItem
            value="action copy link"
            onSelect={() => go(() => void navigator.clipboard.writeText(location.href))}
          >
            <Copy className="size-4" /> Copy link to this view
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
