import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tsConfigPaths from "vite-tsconfig-paths";

// Separate from vite.config.ts (which drives dev/build and needs the
// TanStack Router codegen plugin) -- routeTree.gen.ts is already generated
// on disk, so tests just need JSX/TS transform + the "@/" path alias.
export default defineConfig({
  plugins: [react(), tsConfigPaths()],
  test: {
    environment: "jsdom",
    globals: false,
    // Round 41: real auth needs real localStorage (token persistence).
    // jsdom's Storage implementation requires a real http(s) origin --
    // without this, window.localStorage is undefined under jsdom's default
    // "about:blank"-ish environment, which is exactly what broke every
    // test in this round until this was added.
    environmentOptions: {
      jsdom: { url: "http://localhost:3000" },
    },
  },
});
