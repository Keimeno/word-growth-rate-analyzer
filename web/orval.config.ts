import { defineConfig } from "orval";

// The page's types, fetch functions and TanStack Query hooks, from the API's schema
// (src/api/openapi.json, exported by `uv run undercurrent web openapi`). `pnpm gen:api` writes
// src/api/generated/, which is never edited by hand.
export default defineConfig({
  api: {
    input: { target: "./src/api/openapi.json" },
    output: {
      mode: "tags-split",
      target: "./src/api/generated/endpoints",
      schemas: "./src/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: { path: "./src/api/fetcher.ts", name: "apiFetch" },
        fetch: { includeHttpResponseReturnType: false },
        query: { useQuery: true, signal: true, shouldExportKeys: true },
      },
    },
  },
  schemas: {
    input: { target: "./src/api/openapi.json" },
    output: {
      mode: "tags-split",
      target: "./src/api/generated/zod",
      client: "zod",
      fileExtension: ".zod.ts",
    },
  },
});
