import { describe, expect, it } from "vitest";
import { exploreSearch, parsePeek, rootSearch, trendingDefaults, trendingSearch } from "./search";
import { parseSearch, stringifySearch } from "./url";

describe("url state", () => {
  it("fills defaults and leaves them out of short links", () => {
    expect(trendingDefaults.horizon).toBe("24h");
    expect(trendingDefaults.kinds).toEqual(["word", "phrase", "domain", "subreddit"]);
    expect(rootSearch.parse({}).scope).toBe("reddit");
  });
  it("reads lists comma separated, and empty as empty", () => {
    const search = trendingSearch.parse(parseSearch("?kinds=word,phrase&scopes="));
    expect(search.kinds).toEqual(["word", "phrase"]);
    expect(search.scopes).toEqual([]);
  });
  it("falls back to the default for values it can't read", () => {
    const search = trendingSearch.parse(parseSearch("?horizon=1h&kinds=word,nonsense&subsumed=1"));
    expect(search.horizon).toBe("24h");
    expect(search.kinds).toEqual(trendingDefaults.kinds);
    expect(search.subsumed).toBe(true);
  });
  it("round-trips through the url", () => {
    const query = stringifySearch({
      terms: ["claude code", "gemini"],
      scope: "r/LocalLLaMA",
      from: 5,
    });
    expect(query).toBe("?terms=claude+code,gemini&scope=r/LocalLLaMA&from=5");
    const back = exploreSearch.parse(parseSearch(query));
    expect(back.terms).toEqual(["claude code", "gemini"]);
    expect(back.from).toBe(5);
  });
  it("splits a peek at its first colon only", () => {
    expect(parsePeek("complaint:complaint: reddit")).toEqual({
      kind: "complaint",
      term: "complaint: reddit",
    });
    expect(parsePeek("nonsense")).toBeNull();
  });
});
