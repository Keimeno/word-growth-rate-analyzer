import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// tokens.css and docs/brand/tokens.json were generated together (BRAND.md §7); this keeps
// them from drifting apart silently, and the copies of the brand's icons the same.
const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const json = JSON.parse(
  readFileSync(new URL("../../../docs/brand/tokens.json", import.meta.url), "utf8"),
) as {
  color: {
    primitives?: Array<{ name: string; value: string }>;
    tokens: Array<{ name: string; value: string | { light: string; dark: string } }>;
  };
};

function block(selector: string): Map<string, string> {
  const start = css.indexOf(`\n${selector} {`);
  const body = css.slice(start, css.indexOf("}", start));
  return new Map([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));
}

const primitives = block(":root");
const resolve = (value: string): string =>
  value.replace(/^\{([\w-]+)\}$/, (_, name: string) => primitives.get(name) ?? value).toLowerCase();

describe("tokens.css", () => {
  const light = block(':root,\n[data-theme="light"]');
  const dark = block('[data-theme="dark"]');

  it.each(json.color.tokens.filter((token) => typeof token.value === "object"))(
    "$name matches tokens.json in both themes",
    ({ name, value }) => {
      const themed = value as { light: string; dark: string };
      expect(light.get(name)?.toLowerCase()).toBe(resolve(themed.light));
      expect(dark.get(name)?.toLowerCase()).toBe(resolve(themed.dark));
    },
  );

  it("keeps the brand's data palette", () => {
    const slots = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => light.get(`series-${i}`));
    expect(slots).toEqual([
      "#15a0a1",
      "#b24b0a",
      "#8e65d4",
      "#b07d00",
      "#e267a3",
      "#23851b",
      "#2d72d3",
      "#c24242",
    ]); // prettier-ignore
  });
});

describe("the brand's icons in public/", () => {
  it.each(["favicon.svg", "apple-touch-icon.png", "app-icon-512.png", "notification-icon.png"])(
    "%s is the same as in docs/brand",
    (name) => {
      const copy = readFileSync(new URL(`../../public/${name}`, import.meta.url));
      const original = readFileSync(new URL(`../../../docs/brand/${name}`, import.meta.url));
      expect(copy.equals(original)).toBe(true);
    },
  );
});
