import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  // Read .env from examples/lci-mini/ (parent) so backend + frontend
  // share a single source of truth — VITE_* go to the browser, the
  // rest go to uvicorn.
  envDir: "..",
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    // Firebase signInWithPopup opens accounts.google.com in a popup and
    // polls window.closed to detect user cancellation. Vite's default
    // COOP is "same-origin" which blocks that poll (harmless warnings,
    // but noisy). Loosen it to allow popup interop in dev.
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
    },
    proxy: {
      "/awp": { target: "http://localhost:8004", changeOrigin: true },
      "/chat/action": { target: "http://localhost:8004", changeOrigin: true },
      "/chat/upload": { target: "http://localhost:8004", changeOrigin: true },
      "/sessions": { target: "http://localhost:8004", changeOrigin: true },
      "/uploads": { target: "http://localhost:8004", changeOrigin: true },
      "/downloads": { target: "http://localhost:8004", changeOrigin: true },
      "/persona": { target: "http://localhost:8004", changeOrigin: true },
      "/skills": { target: "http://localhost:8004", changeOrigin: true },
      "/auth": { target: "http://localhost:8004", changeOrigin: true },
    },
  },
});
