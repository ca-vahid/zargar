import { defineConfig, mergeConfig } from "vite";
import sharedConfig from "./vite.config";

// Explicit opt-in; shared runtime remains on 8420/5173.
export default mergeConfig(sharedConfig, defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8421", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8421", ws: true },
    },
  },
}));
