import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    proxy: {
      "/chat/ws": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
      "/chat/stream": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
