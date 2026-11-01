import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/** Every page loads, says what it is, logs no errors and passes axe, in both themes. Runs
 * against any database: the demo one in CI, the live one by hand (E2E_URL). */
const PAGES = [
  ["/trending", "Trending now"],
  ["/trending?view=quick", "Quick look"],
  ["/long-term", "Long-term trends"],
  ["/intents", "Why people switch"],
  ["/spread", "Early warning"],
  ["/explore?terms=ai", "Explore"],
  ["/collection", "Collection"],
] as const;

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(
        (chosen) => localStorage.setItem("undercurrent.theme", chosen),
        theme,
      );
    });

    for (const [path, title] of PAGES) {
      test(`${path} loads and passes axe`, async ({ page }) => {
        const errors = watchErrors(page);
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        // the data has arrived: no skeletons left
        await expect(page.locator("[aria-busy=true]")).toHaveCount(0, { timeout: 15_000 });
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
          .analyze();
        expect(
          results.violations.map(
            (violation) => `${violation.id}: ${violation.nodes[0]?.target.join(" ")}`,
          ),
        ).toEqual([]);
        expect(errors).toEqual([]);
      });
    }
  });
}

test("url state survives a reload", async ({ page }) => {
  await page.goto("/trending");
  await page.getByRole("radio", { name: "Last 6 hours" }).click();
  await expect(page).toHaveURL(/horizon=6h/);
  await page.reload();
  await expect(page.getByRole("radio", { name: "Last 6 hours" })).toHaveAttribute(
    "data-state",
    "on",
  );
});

test("a term opens in the peek, and the peek is a link", async ({ page }) => {
  await page.goto("/explore?terms=ai");
  await page.goto("/trending?peek=word:ai");
  const peek = page.getByRole("dialog");
  await expect(peek.getByRole("heading", { name: "ai" })).toBeVisible();
  await expect(peek.getByText("Share of the conversation")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/peek=/);
});

test("the palette goes to a page", async ({ page }) => {
  await page.goto("/trending");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByPlaceholder("A page, a scope or a term…").fill("collection");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/collection/);
  await expect(page.getByRole("heading", { level: 1, name: "Collection" })).toBeVisible();
});

test("the scope follows from page to page", async ({ page }) => {
  await page.goto("/trending?scope=tech");
  await page.getByRole("link", { name: "Long-term" }).first().click();
  await expect(page).toHaveURL(/\/long-term\?scope=tech/);
});
