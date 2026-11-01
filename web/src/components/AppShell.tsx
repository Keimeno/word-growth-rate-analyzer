import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  ArrowUpRight,
  Bell,
  ChevronRight,
  Compass,
  History,
  Keyboard,
  Menu,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Repeat,
  Search,
  Sun,
  TrendingUp,
  Waves,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useIngestion } from "@/api/generated/endpoints";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDateTime } from "@/lib/format";
import { grafanaLink } from "@/lib/grafana";
import { collectionHealth, type Health } from "@/lib/health";
import { KIND_LABELS } from "@/lib/kinds";
import { useAnySearch, withSearch } from "@/lib/navigation";
import { setTheme, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { BrandSymbol, Lockup } from "./Logo";
import { usePinned } from "./Personal";

export const PAGES = [
  {
    to: "/trending",
    label: "Trending",
    short: "Trending",
    icon: TrendingUp,
    grafana: "trending",
    section: "Monitor",
  },
  {
    to: "/alerts",
    label: "Alerts",
    short: "Alerts",
    icon: Bell,
    grafana: "trending",
    section: "Monitor",
  },
  {
    to: "/pinned",
    label: "Pinned",
    short: "Pinned",
    icon: Pin,
    grafana: "trending",
    section: "Monitor",
  },
  {
    to: "/long-term",
    label: "Long-term",
    short: "Long-term",
    icon: Waves,
    grafana: "long-term",
    section: "Analyze",
  },
  {
    to: "/intents",
    label: "Why people switch",
    short: "Switches",
    icon: Repeat,
    grafana: "intents",
    section: "Analyze",
  },
  {
    to: "/spread",
    label: "Early warning",
    short: "Spread",
    icon: Network,
    grafana: "spread",
    section: "Analyze",
  },
  {
    to: "/explore",
    label: "Explore",
    short: "Explore",
    icon: Compass,
    grafana: "explore",
    section: "Analyze",
  },
  {
    to: "/collection",
    label: "Collection",
    short: "Collection",
    icon: Activity,
    grafana: "collection",
    section: "System",
  },
] as const;

type Page = (typeof PAGES)[number];
const SECTIONS = ["Monitor", "Analyze", "System"] as const;

/** Entity pages light up the page they belong to. */
const PARENT: Array<[prefix: string, page: Page["to"]]> = [
  ["/p/", "/intents"],
  ["/e/", "/spread"],
  ["/edge", "/spread"],
];

function pageOf(path: string): Page | undefined {
  const parent = PARENT.find(([prefix]) => path.startsWith(prefix))?.[1];
  return PAGES.find((page) => (parent ? page.to === parent : path.startsWith(page.to)));
}

export function openPalette(): void {
  window.dispatchEvent(new Event("undercurrent:palette"));
}

const COLLAPSED = "undercurrent.sidebar";

/** The sidebar collapsed to its icons or not: the reader's choice, kept in this browser. */
function useCollapsed(): [boolean, (value: boolean) => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED) === "collapsed";
    } catch {
      return false;
    }
  });
  const set = (value: boolean) => {
    setCollapsed(value);
    try {
      localStorage.setItem(COLLAPSED, value ? "collapsed" : "expanded");
    } catch {
      // private mode: the choice lasts for this page
    }
  };
  useEffect(() => {
    const toggle = () => setCollapsed((value) => !value);
    window.addEventListener("undercurrent:sidebar", toggle);
    return () => window.removeEventListener("undercurrent:sidebar", toggle);
  }, []);
  return [collapsed, set];
}

/** The app's frame (BRAND.md §8): a sidebar of pages in three sections with the system's
 * status at its foot, a top bar with where you are, search and time travel, and on phones
 * a bottom bar with the main pages. */
export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useCollapsed();
  const [drawer, setDrawer] = useState(false);

  return (
    <div className="flex min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-160 ease-standard md:flex",
          collapsed ? "w-(--sidebar-width-collapsed)" : "w-(--sidebar-width)",
        )}
      >
        <SidebarBody collapsed={collapsed} onCollapse={() => setCollapsed(!collapsed)} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col pb-16 md:pb-0">
        <TopBar onMenu={() => setDrawer(true)} />
        <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 md:px-6 md:py-6">
          {children}
        </main>
      </div>
      <Sheet open={drawer} onOpenChange={setDrawer}>
        <SheetContent side="left" className="w-(--sidebar-width) gap-0 p-0 sm:max-w-none">
          <SheetTitle className="sr-only">Pages</SheetTitle>
          <SheetDescription className="sr-only">Every page of Undercurrent</SheetDescription>
          <SidebarBody collapsed={false} onNavigate={() => setDrawer(false)} />
        </SheetContent>
      </Sheet>
      <BottomBar onMore={() => setDrawer(true)} />
    </div>
  );
}

function SidebarBody({
  collapsed,
  onCollapse,
  onNavigate,
}: {
  collapsed: boolean;
  onCollapse?: () => void;
  /** in the phone's drawer: a followed link closes it */
  onNavigate?: () => void;
}) {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const current = pageOf(path);
  const pinned = usePinned().size;
  return (
    <>
      <div
        className={cn(
          "flex h-12 shrink-0 items-center border-b border-border",
          collapsed ? "justify-center" : "px-4",
        )}
      >
        <Link
          to="/trending"
          className="flex items-center rounded-sm"
          aria-label="Undercurrent, home"
          onClick={onNavigate}
        >
          {collapsed ? <BrandSymbol /> : <Lockup className="h-[15px]" />}
        </Link>
      </div>
      <nav
        aria-label={onCollapse ? "Pages" : "All pages"}
        className={cn("flex-1 overflow-y-auto py-3", collapsed ? "px-2" : "px-3")}
      >
        {SECTIONS.map((section) => (
          <div key={section} className="mb-4 last:mb-0">
            {collapsed ? (
              <div aria-hidden className="mx-2 mb-2 h-px bg-border first:hidden" />
            ) : (
              <h2 className="mb-1 px-2 type-overline text-ink-muted">{section}</h2>
            )}
            <ul className="flex flex-col gap-px">
              {PAGES.filter((page) => page.section === section).map((page) => (
                <li key={page.to}>
                  <NavItem
                    page={page}
                    active={current?.to === page.to}
                    collapsed={collapsed}
                    count={page.to === "/pinned" && pinned ? pinned : undefined}
                    onNavigate={onNavigate}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div
        className={cn(
          "flex shrink-0 flex-col gap-1 border-t border-border py-2",
          collapsed ? "px-2" : "px-3",
        )}
      >
        <SystemStatus collapsed={collapsed} onNavigate={onNavigate} />
        <SidebarActions collapsed={collapsed} onCollapse={onCollapse} />
      </div>
    </>
  );
}

function NavItem({
  page,
  active,
  collapsed,
  count,
  onNavigate,
}: {
  page: Page;
  active: boolean;
  collapsed: boolean;
  count?: number | undefined;
  onNavigate?: (() => void) | undefined;
}) {
  const link = (
    <Link
      to={page.to}
      activeOptions={{ includeSearch: false }}
      aria-label={collapsed ? page.label : undefined}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "relative flex h-8 items-center gap-2.5 rounded-sm text-[13px] font-medium text-ink-secondary transition-colors duration-100 hover:bg-surface-hover hover:text-ink",
        collapsed ? "justify-center" : "px-2",
        active && "bg-primary-wash text-primary-ink hover:bg-primary-wash hover:text-primary-ink",
      )}
    >
      <page.icon
        className={cn("size-4 shrink-0", active ? "text-primary-ink" : "text-ink-muted")}
        strokeWidth={1.75}
        aria-hidden
      />
      {!collapsed && <span className="truncate">{page.label}</span>}
      {!collapsed && count !== undefined && (
        <span className="ml-auto rounded-xs bg-surface-sunken px-1.5 text-[11px] leading-4 text-ink-muted tabular-nums">
          {count}
        </span>
      )}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{page.label}</TooltipContent>
    </Tooltip>
  );
}

const HEALTH_DOT: Record<Health, string> = {
  good: "bg-status-good",
  warning: "bg-status-warning",
  critical: "bg-status-critical",
};

/** Collection's health, as on the Collection page: a dot and a few words. */
function SystemStatus({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: (() => void) | undefined;
}) {
  const asOf = useAsOf();
  // the Collection page's default query, so the two share one request
  const ingestion = useIngestion({ ...asOf, platforms: [], range: "6h" });
  const health = ingestion.data ? collectionHealth(ingestion.data) : undefined;
  const dot = (
    <span
      aria-hidden
      className={cn(
        "size-2 shrink-0 rounded-full",
        health ? HEALTH_DOT[health.status] : "bg-ink-disabled",
      )}
    />
  );
  const words = health?.short ?? (ingestion.isError ? "Status unknown" : "Checking collection");
  const link = (
    <Link
      to="/collection"
      aria-label={collapsed ? `Collection: ${words}` : undefined}
      onClick={onNavigate}
      className={cn(
        "flex h-8 items-center gap-2.5 rounded-sm text-xs text-ink-secondary hover:bg-surface-hover hover:text-ink",
        collapsed ? "justify-center" : "px-2",
      )}
    >
      <span className="flex size-4 items-center justify-center">{dot}</span>
      {!collapsed && <span className="truncate">{words}</span>}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{words}</TooltipContent>
    </Tooltip>
  );
}

function SidebarActions({
  collapsed,
  onCollapse,
}: {
  collapsed: boolean;
  onCollapse?: (() => void) | undefined;
}) {
  const theme = useTheme();
  const grafana = useProModeLink();
  const icon =
    "flex size-8 shrink-0 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-hover hover:text-ink [&_svg]:size-4";
  const tip = (label: string, control: ReactNode) => (
    <Tooltip key={label}>
      <TooltipTrigger asChild>{control}</TooltipTrigger>
      <TooltipContent side={collapsed ? "right" : "top"}>{label}</TooltipContent>
    </Tooltip>
  );
  const themeLabel = theme === "dark" ? "Light theme" : "Dark theme";
  return (
    <div className={cn("flex items-center gap-0.5", collapsed && "flex-col")}>
      {tip(
        themeLabel,
        <button
          type="button"
          className={icon}
          aria-label={themeLabel}
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>,
      )}
      {tip(
        "Keyboard shortcuts",
        <button
          type="button"
          className={icon}
          aria-label="Keyboard shortcuts"
          onClick={() => window.dispatchEvent(new Event("undercurrent:shortcuts"))}
        >
          <Keyboard />
        </button>,
      )}
      {grafana &&
        (collapsed ? (
          tip(
            "Pro mode, in Grafana",
            <a
              href={grafana}
              target="_blank"
              rel="noreferrer"
              className={icon}
              aria-label="Pro mode"
            >
              <ArrowUpRight />
            </a>,
          )
        ) : (
          <a
            href={grafana}
            target="_blank"
            rel="noreferrer"
            title="This view in Grafana"
            className="flex h-8 items-center gap-1 rounded-sm px-2 text-xs font-medium text-ink-secondary hover:bg-surface-hover hover:text-ink"
          >
            Pro mode
            <ArrowUpRight className="size-3.5 text-ink-muted" />
          </a>
        ))}
      {onCollapse &&
        tip(
          collapsed ? "Expand sidebar  [" : "Collapse sidebar  [",
          <button
            type="button"
            className={cn(icon, !collapsed && "ml-auto")}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={onCollapse}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </button>,
        )}
    </div>
  );
}

/** The same view in Grafana, with the same choices made. */
function useProModeLink(): string | undefined {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const search = useAnySearch();
  const meta = useMetaData();
  const page = pageOf(path);
  if (!meta.data) return undefined;
  return grafanaLink(
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
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const search = useAnySearch();
  const meta = useMetaData();
  const asOf = typeof search.as_of === "string" && search.as_of ? search.as_of : undefined;
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface">
      <div className="flex h-12 items-center gap-3 px-4 md:px-6">
        <Button
          variant="ghost"
          size="icon-sm"
          className="-ml-1.5 md:hidden"
          aria-label="Open pages"
          onClick={onMenu}
        >
          <Menu />
        </Button>
        <Link to="/trending" className="md:hidden" aria-label="Undercurrent, home">
          <BrandSymbol />
        </Link>
        <Breadcrumbs />
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={openPalette}
            aria-label="Search pages, scopes and terms"
            className="flex h-8 items-center gap-2 rounded-sm border border-control-border bg-surface-sunken px-2.5 text-[13px] text-ink-muted transition-colors duration-100 hover:border-border-strong hover:text-ink-secondary sm:w-56 lg:w-72"
          >
            <Search className="size-3.5 shrink-0" aria-hidden />
            <span className="hidden truncate sm:inline">Search terms, scopes, pages</span>
            <kbd className="ml-auto hidden rounded-xs border border-border bg-surface px-1 font-sans text-[11px] leading-4 text-ink-muted sm:inline">
              ⌘K
            </kbd>
          </button>
          <AsOfControl asOf={asOf} />
        </div>
      </div>
      {asOf && (
        <div className="flex items-center justify-center gap-2 border-t border-status-warning/40 bg-status-warning-wash px-4 py-1 text-xs text-status-warning-text">
          <History className="size-3.5 shrink-0" aria-hidden />
          <span>
            Showing the dashboard as of {formatDateTime(meta.data?.now ?? asOf)}.{" "}
            <Link
              to="."
              search={withSearch({ as_of: undefined })}
              className="font-medium underline"
            >
              Back to now
            </Link>
          </span>
        </div>
      )}
    </header>
  );
}

interface Crumb {
  label: string;
  to?: string;
  term?: boolean;
}

function decode(part: string | undefined): string {
  try {
    return decodeURIComponent(part ?? "");
  } catch {
    return part ?? "";
  }
}

/** Where you are: the section and page, or an entity and what it belongs to. */
function crumbsOf(path: string): Crumb[] {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "t") {
    const kind = parts[1] ?? "word";
    return [
      { label: "Terms" },
      { label: (KIND_LABELS[kind] ?? kind).replace(/s$/, "") },
      { label: decode(parts.slice(2).join("/")), term: true },
    ];
  }
  if (parts[0] === "s") return [{ label: "Scopes" }, { label: decode(parts.slice(1).join("/")) }];
  if (parts[0] === "p")
    return [
      { label: "Why people switch", to: "/intents" },
      { label: "Products" },
      { label: decode(parts.slice(1).join("/")) },
    ];
  if (parts[0] === "e")
    return [
      { label: "Early warning", to: "/spread" },
      { label: "Stories" },
      { label: decode(parts.slice(3).join("/")), term: true },
    ];
  if (parts[0] === "edge") return [{ label: "Early warning", to: "/spread" }, { label: "Pairs" }];
  const page = pageOf(path);
  return page ? [{ label: page.section }, { label: page.label }] : [];
}

function Breadcrumbs() {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const crumbs = crumbsOf(path);
  if (!crumbs.length) return null;
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 md:block">
      <ol className="flex min-w-0 items-center gap-1.5 text-[13px]">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li
              key={`${index}-${crumb.label}`}
              className={cn("flex min-w-0 items-center gap-1.5", !last && "shrink-0")}
            >
              {index > 0 && (
                <ChevronRight className="size-3.5 shrink-0 text-ink-disabled" aria-hidden />
              )}
              {crumb.to ? (
                <Link to={crumb.to} className="text-ink-muted hover:text-ink">
                  {crumb.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? "page" : undefined}
                  className={cn(
                    "truncate",
                    last ? "font-medium text-ink" : "text-ink-muted",
                    crumb.term && "term",
                  )}
                >
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Live, or the dashboard as of a time in the past (time travel), set here or in the
 * palette; every request of every page carries it. */
function AsOfControl({ asOf }: { asOf: string | undefined }) {
  const navigate = useNavigate();
  const meta = useMetaData();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const go = (as_of: string | undefined) => {
    setOpen(false);
    void navigate({ to: ".", search: withSearch({ as_of }) });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value) go(`${value}Z`);
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        // start from what's shown: the time travelled to, or now
        if (next) setValue((asOf ?? meta.data?.now ?? new Date().toISOString()).slice(0, 16));
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "gap-2 px-2.5",
            asOf &&
              "border-status-warning/60 bg-status-warning-wash text-status-warning-text hover:bg-status-warning-wash",
          )}
          aria-label={asOf ? `Time travel: as of ${formatDateTime(asOf)}` : "Time travel: live"}
        >
          {asOf ? (
            <History className="size-3.5" />
          ) : (
            <span aria-hidden className="size-2 rounded-full bg-status-good" />
          )}
          <span className="hidden sm:inline">{asOf ? formatDateTime(asOf) : "Live"}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <form onSubmit={submit}>
          <div className="border-b border-border px-4 py-3">
            <p className="type-title-sm">Time travel</p>
            <p className="mt-0.5 text-xs text-ink-muted">
              Every page as it was at a moment in the past: what had been collected and found by
              then. Times are UTC.
            </p>
          </div>
          <div className="flex flex-col gap-1.5 px-4 py-3">
            <label htmlFor="as-of" className="text-xs font-medium text-ink-secondary">
              Show the dashboard as of
            </label>
            <input
              id="as-of"
              type="datetime-local"
              step={900}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              className="h-8 rounded-sm border border-border-strong bg-surface px-2 text-[13px] tabular-nums text-ink"
            />
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border bg-surface-sunken px-4 py-2.5">
            {asOf ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => go(undefined)}>
                Back to live
              </Button>
            ) : (
              <span className="text-xs text-ink-muted">Now: live</span>
            )}
            <Button type="submit" size="sm" disabled={!value}>
              Show
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/** On phones: the main pages and everything else in the drawer. */
function BottomBar({ onMore }: { onMore: () => void }) {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const current = pageOf(path);
  const main = ["/trending", "/long-term", "/intents", "/spread"]
    .map((to) => PAGES.find((page) => page.to === to))
    .filter((page): page is Page => page !== undefined);
  return (
    <nav
      aria-label="Pages"
      className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {main.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ includeSearch: false }}
          className={cn(
            "flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-ink-muted",
            current?.to === item.to && "text-primary-ink",
          )}
        >
          <item.icon className="size-5" strokeWidth={1.75} aria-hidden />
          {item.short}
        </Link>
      ))}
      <button
        type="button"
        onClick={onMore}
        className="flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-ink-muted"
      >
        <Menu className="size-5" strokeWidth={1.75} aria-hidden />
        More
      </button>
    </nav>
  );
}

/** A page's header: an eyebrow for entity pages, the title, the one sentence that says
 * what it is, and the page's actions on the right. */
export function PageHeader({
  title,
  eyebrow,
  children,
  actions,
  titleClassName,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  titleClassName?: string;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-[22rem]">
        {eyebrow && <p className="mb-1 type-overline text-ink-muted">{eyebrow}</p>}
        <h1 className={cn("break-words text-ink", titleClassName ?? "type-title-lg")}>{title}</h1>
        {children && (
          <p className="mt-1 max-w-3xl text-[13px] leading-[18px] text-ink-muted">{children}</p>
        )}
      </div>
      {actions && (
        <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </header>
  );
}

/** The one row of filters under a page's header: a toolbar of labelled controls. */
export function Filters({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-border bg-surface px-3 py-2">
      {children}
    </div>
  );
}
