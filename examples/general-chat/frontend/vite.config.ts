import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  envDir: "..",
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    proxy: {
      "/awp": { target: "http://localhost:8005", changeOrigin: true },
      "/chat/action": { target: "http://localhost:8005", changeOrigin: true },
      "/chat/upload": { target: "http://localhost:8005", changeOrigin: true },
      "/chat/sources": { target: "http://localhost:8005", changeOrigin: true },
      "/sessions": { target: "http://localhost:8005", changeOrigin: true },
      "/uploads": { target: "http://localhost:8005", changeOrigin: true },
      "/downloads": { target: "http://localhost:8005", changeOrigin: true },
      "/persona": { target: "http://localhost:8005", changeOrigin: true },
      "/skills": { target: "http://localhost:8005", changeOrigin: true },
    },
  },
});
