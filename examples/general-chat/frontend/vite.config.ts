import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

const backendUrl = process.env.VITE_BACKEND_URL ?? "http://localhost:8005";

export default defineConfig({
  envDir: "..",
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
  server: {
    proxy: {
      "/awp": { target: backendUrl, changeOrigin: true },
      "/chat/action": { target: backendUrl, changeOrigin: true },
      "/chat/upload": { target: backendUrl, changeOrigin: true },
      "/chat/sources": { target: backendUrl, changeOrigin: true },
      "/sessions": { target: backendUrl, changeOrigin: true },
      "/uploads": { target: backendUrl, changeOrigin: true },
      "/downloads": { target: backendUrl, changeOrigin: true },
      "/image-search": { target: backendUrl, changeOrigin: true },
      "/persona": { target: backendUrl, changeOrigin: true },
      "/skills": { target: backendUrl, changeOrigin: true },
      "/mcp/tools": { target: backendUrl, changeOrigin: true },
      "/mcp/catalogs": { target: backendUrl, changeOrigin: true },
      "/toolhive": { target: backendUrl, changeOrigin: true },
    },
  },
});
