import { useEffect } from "react";
import { useAnySearch } from "@/lib/navigation";
import { setServerNow } from "@/lib/clock";
import { useMeta } from "./generated/endpoints";

/** Time travel: every request of the page carries the url's `as_of`. */
export function useAsOf(): { as_of?: string } {
  const search = useAnySearch();
  return typeof search.as_of === "string" && search.as_of ? { as_of: search.as_of } : {};
}

/** Scopes, kinds and settings, kept for the whole visit; relative times follow its `now`. */
export function useMetaData() {
  const asOf = useAsOf();
  const meta = useMeta(asOf, { query: { staleTime: 10 * 60_000 } });
  const serverNow = meta.data?.now;
  useEffect(() => setServerNow(serverNow), [serverNow]);
  return meta;
}
