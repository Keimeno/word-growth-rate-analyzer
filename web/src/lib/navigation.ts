import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback } from "react";

export type SearchUpdate = Record<string, unknown>;

/**
 * A search updater for `navigate` and `<Link>` that works on whatever route is current.
 * The router types search params per route; these helpers are for components shared by
 * every page (the peek, the palette, term links), so they opt out in this one place.
 */
export function withSearch(updates: SearchUpdate): never {
  const update = (previous: SearchUpdate) => ({ ...previous, ...updates });
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion
  return update as never;
}

/** A search object for a link to another route, typed loosely for the same reason. */
export function searchOf(search: SearchUpdate): never {
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion
  return search as never;
}

/** Changes some of the current page's search params, without a new history entry: filters
 * are part of the view, not steps the back button should walk through. */
export function useSetSearch(): (updates: SearchUpdate) => void {
  const navigate = useNavigate();
  return useCallback(
    (updates: SearchUpdate) => {
      void navigate({
        to: ".",
        search: withSearch(updates),
        replace: true,
        resetScroll: false,
      });
    },
    [navigate],
  );
}

/** The current search params, whatever the route. */
export function useAnySearch(): SearchUpdate {
  return useSearch({ strict: false });
}
