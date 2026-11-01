import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// where `pnpm dev` sends /api: the running stack on 3610, or an API of your own
const api = process.env.UNDERCURRENT_API ?? "http://localhost:3610";

/** .br and .gz next to every text file of the build, served by the API when accepted. */
function precompress(): Plugin {
  const compressible = /\.(js|css|html|svg|json|webmanifest|txt)$/;
  return {
    name: "precompress",
    apply: "build",
    closeBundle() {
      const walk = (dir: string): string[] =>
        readdirSync(dir).flatMap((name) => {
          const path = join(dir, name);
          return statSync(path).isDirectory() ? walk(path) : [path];
        });
      for (const file of walk("dist")) {
        if (!compressible.test(file)) continue;
        const body = readFileSync(file);
        if (body.length < 1024) continue;
        writeFileSync(`${file}.gz`, gzipSync(body, { level: 9 }));
        writeFileSync(
          `${file}.br`,
          brotliCompressSync(body, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }),
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true, quoteStyle: "double" }),
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
    precompress(),
  ],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: { port: 3611, strictPort: true, proxy: { "/api": api } },
  preview: { port: 3611, strictPort: true, proxy: { "/api": api } },
  build: { target: "es2024", sourcemap: true },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "node",
  },
});
