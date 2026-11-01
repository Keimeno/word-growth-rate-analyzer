import { defineConfig, devices } from "@playwright/test";

// The API serves the built page: `pnpm build`, then `uv run undercurrent web` (or the e2e job's
// demo database). E2E_URL points elsewhere.
const baseURL = process.env.E2E_URL ?? "http://localhost:3610";

export default defineConfig({
  testDir: "tests",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
      testIgnore: ["mobile.spec.ts"],
    },
    {
      name: "phone",
      use: { ...devices["iPhone 15"], viewport: { width: 390, height: 844 } },
      // the main flows on a phone; every page's axe check runs on the desktop
      testMatch: ["mobile.spec.ts"],
    },
  ],
});
