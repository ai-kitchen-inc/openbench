import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    proxy: {
      "/awp": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/chat/action": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/chat/upload": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/uploads": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
