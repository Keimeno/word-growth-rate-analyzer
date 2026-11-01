# web/: notes for agents

The dashboard's page: React 19 and TypeScript 7, built by Vite 8, styled with Tailwind v4 and
shadcn/ui, routed by TanStack Router, data through TanStack Query, charts through our own kit
on Apache ECharts 6. The plan is [docs/WEB-DASHBOARD.md](../docs/WEB-DASHBOARD.md), the
look [docs/BRAND.md](../docs/BRAND.md). The data comes from the Python API in
`src/undercurrent/web/` (FastAPI), the only server.

## Commands

Node 26 and pnpm 12 (`.nvmrc`, `packageManager`); run them in `web/`.

| Command        | What                                                                          |
| -------------- | ----------------------------------------------------------------------------- |
| `pnpm install` | dependencies, exactly as in `pnpm-lock.yaml`                                  |
| `pnpm dev`     | Vite on 3611 with hot reload, `/api` proxied to 3610 (or `UNDERCURRENT_API`)  |
| `pnpm check`   | types (`tsc`), lint (Oxlint, type-aware), format (Biome), unit tests (Vitest) |
| `pnpm format`  | formats everything                                                            |
| `pnpm e2e`     | Playwright against a running API (see `playwright.config.ts`)                 |
| `pnpm gen:api` | regenerates `src/api/generated/` from `src/api/openapi.json`                  |
| `pnpm build`   | the page in `dist/`, with `.br` and `.gz` next to each file                   |

## Rules

- `src/api/generated/` is generated, never edited. A change to the API's data is a change
  to a Pydantic model in `src/undercurrent/web/models.py`, then
  `uv run undercurrent web openapi > web/src/api/openapi.json` and `pnpm gen:api`. CI fails
  when they disagree.
- Add a shadcn/ui component with the CLI (`pnpm dlx shadcn@4.23.0 add <name>`), then edit
  it like our own code; `pnpm dlx shadcn@4.23.0 docs <name>` answers for the version in use.
- Every view's state lives in its route's search schema (Zod, `src/lib/search.ts`). Nothing
  that changes what's shown lives only in component state; hovers may.
- Charts go through the kit in `src/charts/`; no chart library is imported anywhere else
  (Oxlint refuses it). Colours come from tokens (`bg-surface`, `text-ink-muted`,
  `var(--series-3)`), never hex values in components.
- Series colours follow the entity: assign slots in order of first appearance and keep them
  through filters (`src/lib/colors.ts`).
- Every number carries its unit, comparison and people; below 10, counts stay counts. Copy
  is sentence case, plain, no emoji or exclamation marks (BRAND.md §2).
- Empty states say why they're empty and when data will come.
- Every new endpoint comes with a model, a test on the schema in `tests/test_web.py`, an
  entry in `bench/web.py` and its cost written next to it.
- Dependencies are pinned and only installed three days after release
  (`pnpm-workspace.yaml`). Add one only when it earns its place.
