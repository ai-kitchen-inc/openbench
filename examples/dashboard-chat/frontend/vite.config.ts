import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

const backendUrl = process.env.VITE_BACKEND_URL ?? "http://localhost:8007";

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
  },
  server: {
    proxy: {
      "/auth": { target: backendUrl, changeOrigin: true },
      "/admin": { target: backendUrl, changeOrigin: true },
      "/db": { target: backendUrl, changeOrigin: true },
      "/dashboard": { target: backendUrl, changeOrigin: true },
      "/awp": { target: backendUrl, changeOrigin: true },
      "/chat": { target: backendUrl, changeOrigin: true },
      "/sessions": { target: backendUrl, changeOrigin: true },
    },
  },
});
