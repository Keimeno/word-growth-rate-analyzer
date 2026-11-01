import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  Link,
  Outlet,
  retainSearchParams,
  stripSearchParams,
} from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/Panel";
import { Palette } from "@/components/Palette";
import { Peek } from "@/components/Peek";
import { TooltipProvider } from "@/components/ui/tooltip";
import { rootDefaults, rootSearch } from "@/lib/search";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  validateSearch: rootSearch,
  search: {
    // the scope and time travel follow from page to page; defaults stay out of the url
    // (the outer middleware sees the inner one's result, so stripping comes first)
    middlewares: [stripSearchParams(rootDefaults), retainSearchParams(["scope", "as_of"])],
  },
  component: Root,
  notFoundComponent: () => (
    <EmptyState title="No such page">
      <Link to="/trending" className="text-primary underline">
        Go to Trending
      </Link>
    </EmptyState>
  ),
});

function Root() {
  return (
    <TooltipProvider delayDuration={200}>
      <AppShell>
        <Outlet />
      </AppShell>
      <Peek />
      <Palette />
    </TooltipProvider>
  );
}
