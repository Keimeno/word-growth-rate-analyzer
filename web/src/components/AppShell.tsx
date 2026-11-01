import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Compass,
  Moon,
  Network,
  Pin,
  Repeat,
  Search,
  Sun,
  TrendingUp,
  Waves,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMetaData } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { grafanaLink } from "@/lib/grafana";
import { useAnySearch } from "@/lib/navigation";
import { setTheme, useTheme } from "@/lib/theme";
import { BrandSymbol, Lockup } from "./Logo";

export const PAGES = [
  { to: "/trending", label: "Trending", short: "Trending", icon: TrendingUp, grafana: "trending" },
  { to: "/long-term", label: "Long-term", short: "Long-term", icon: Waves, grafana: "long-term" },
  {
    to: "/intents",
    label: "Why people switch",
    short: "Switches",
    icon: Repeat,
    grafana: "intents",
  },
  { to: "/spread", label: "Early warning", short: "Spread", icon: Network, grafana: "spread" },
  { to: "/explore", label: "Explore", short: "Explore", icon: Compass, grafana: "explore" },
  { to: "/alerts", label: "Alerts", short: "Alerts", icon: Bell, grafana: "trending" },
  { to: "/pinned", label: "Pinned", short: "Pinned", icon: Pin, grafana: "trending" },
  {
    to: "/collection",
    label: "Collection",
    short: "Collection",
    icon: Activity,
    grafana: "collection",
  },
] as const;

export function openPalette(): void {
  window.dispatchEvent(new Event("undercurrent:palette"));
}

/** The app bar (lockup, pages as text tabs, search, theme, Pro mode) and, on phones, a
 * bottom bar with the main pages and the palette (BRAND.md §8, WEB-DASHBOARD.md §8.5). */
export function AppShell({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const search = useAnySearch();
  const meta = useMetaData();
  const theme = useTheme();
  const page = PAGES.find((candidate) => path.startsWith(candidate.to));
  const grafana = meta.data
    ? grafanaLink(
        meta.data.grafana_url,
        page?.grafana === "trending" && search.view === "quick"
          ? "quick"
          : (page?.grafana ?? "trending"),
        Object.fromEntries(
          Object.entries(search).filter(
            (entry): entry is [string, string | string[]] =>
              typeof entry[1] === "string" || Array.isArray(entry[1]),
          ),
        ),
      )
    : undefined;

  return (
    <div className="min-h-dvh bg-bg pb-16 md:pb-0">
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-border bg-surface">
        <div className="mx-auto flex h-12 max-w-[1440px] items-center gap-4 px-4 md:px-6">
          <Link
            to="/trending"
            className="flex shrink-0 items-center"
            aria-label="Undercurrent, home"
          >
            <Lockup className="hidden h-[18px] min-[900px]:block" />
            <BrandSymbol className="min-[900px]:hidden" />
          </Link>
          <nav
            aria-label="Pages"
            className="hidden min-w-0 flex-1 items-center gap-0.5 overflow-x-auto md:flex"
          >
            {PAGES.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                activeOptions={{ includeSearch: false }}
                className="rounded-sm px-2.5 py-1.5 text-sm font-medium whitespace-nowrap text-ink-secondary hover:bg-surface-hover hover:text-ink data-[status=active]:bg-primary-wash data-[status=active]:text-primary-ink"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-2 bg-surface text-ink-secondary dark:bg-surface"
              onClick={openPalette}
              aria-label="Search pages and scopes"
            >
              <Search className="size-3.5" />
              <span className="hidden lg:inline">Search</span>
              <kbd className="hidden rounded-xs border border-border px-1 text-[11px] lg:inline">
                ⌘K
              </kbd>
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={theme === "dark" ? "Switch to light" : "Switch to dark"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
            {grafana && (
              <Button
                variant="ghost"
                size="sm"
                asChild
                className="hidden h-8 text-ink-secondary sm:inline-flex"
              >
                <a href={grafana} target="_blank" rel="noreferrer">
                  Pro mode
                  <ArrowUpRight className="size-3.5" />
                </a>
              </Button>
            )}
          </div>
        </div>
        {typeof search.as_of === "string" && search.as_of && (
          <div className="border-t border-border bg-status-warning-wash px-4 py-1 text-center text-xs text-status-warning-text">
            Showing the dashboard as of {formatDateTime(meta.data?.now ?? search.as_of)}.{" "}
            <Link
              to="."
              search={
                ((previous: Record<string, unknown>) => ({
                  ...previous,
                  as_of: undefined,
                })) as never
              }
              className="underline"
            >
              Back to now
            </Link>
          </div>
        )}
      </header>
      <main id="main" className="mx-auto max-w-[1440px] px-4 py-5 md:px-6 md:py-6">
        {children}
      </main>
      <nav
        aria-label="Pages"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {PAGES.slice(0, 4).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            activeOptions={{ includeSearch: false }}
            className="flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-ink-muted data-[status=active]:text-primary-ink"
          >
            <item.icon className="size-5" strokeWidth={1.75} aria-hidden />
            {item.short}
          </Link>
        ))}
        <button
          type="button"
          onClick={openPalette}
          className="flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-ink-muted"
        >
          <Search className="size-5" strokeWidth={1.75} aria-hidden />
          More
        </button>
      </nav>
    </div>
  );
}

/** A page's title and the one sentence that says what it is. */
export function PageHeader({
  title,
  children,
  actions,
}: {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="type-title-lg">{title}</h1>
        {children && <p className="mt-1 max-w-3xl text-sm text-ink-secondary">{children}</p>}
      </div>
      {actions}
    </div>
  );
}

/** The one row of filters under a page's header. */
export function Filters({ children }: { children: ReactNode }) {
  return <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">{children}</div>;
}
