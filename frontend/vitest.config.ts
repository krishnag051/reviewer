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
  },
});
