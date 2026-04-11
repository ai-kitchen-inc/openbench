import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5174,
    proxy: {
      "/awp": { target: "http://localhost:8004", changeOrigin: true },
      "/chat/action": { target: "http://localhost:8004", changeOrigin: true },
      "/persona": { target: "http://localhost:8004", changeOrigin: true },
    },
  },
});
