import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

const backendUrl = process.env.VITE_BACKEND_URL ?? "http://localhost:8006";

export default defineConfig({
  envDir: "..",
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  // The workspace SDK is a file: dep hard-linked from studio/chat-ui/dist.
  // Force re-optimization on every dev start so a rebuilt SDK dist is
  // always picked up (Vite only invalidates on lockfile/version changes).
  optimizeDeps: {
    force: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
  server: {
    proxy: {
      "/auth": { target: backendUrl, changeOrigin: true },
      "/controlled": { target: backendUrl, changeOrigin: true },
      "/awp": { target: backendUrl, changeOrigin: true },
      "/chat": { target: backendUrl, changeOrigin: true },
      "/sessions": { target: backendUrl, changeOrigin: true },
      "/uploads": { target: backendUrl, changeOrigin: true },
      "/downloads": { target: backendUrl, changeOrigin: true },
      "/mcp": { target: backendUrl, changeOrigin: true },
      "/toolhive": { target: backendUrl, changeOrigin: true },
    },
  },
});
