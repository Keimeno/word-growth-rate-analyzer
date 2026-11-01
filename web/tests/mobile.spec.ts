import { expect, test } from "@playwright/test";

test.describe("on a phone", () => {
  test.skip(({ isMobile }) => !isMobile, "phone layout only");

  test("navigates with the bottom bar and never scrolls sideways", async ({ page }) => {
    await page.goto("/trending");
    const bottom = page.getByRole("navigation", { name: "Pages" }).last();
    await expect(bottom).toBeVisible();
    await bottom.getByRole("link", { name: "Spread" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Early warning" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
