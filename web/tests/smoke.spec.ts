import { expect, test } from "@playwright/test";

test("the page loads with the brand", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Undercurrent");
});
