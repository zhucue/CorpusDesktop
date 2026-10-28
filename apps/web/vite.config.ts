/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Node global; the web tsconfig has no @types/node.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // The API checks Origin on non-GET requests: its PUBLIC_ORIGIN must include http://127.0.0.1:5173 in dev.
    proxy: {
      // VITE_PROXY_TARGET=http://127.0.0.1:8088 points both at the Compose nginx instead.
      "/api": process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000",
      // Agent service (services/agent, PORT 8700 as in deploy/nginx.conf); SSE passes through unbuffered.
      "/agent": process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8700",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\/](echarts|zrender)[\/]/.test(id)) return "echarts";
          if (/[\/](@openuidev|zod)[\/]/.test(id)) return "openui";
          if (/[\/](antd|@ant-design|rc-[^\/]+|@rc-component)[\/]/.test(id)) return "antd";
          if (/[\/](react|react-dom|react-router|@tanstack|scheduler)[\/]/.test(id)) return "react";
          return undefined;
        },
      },
    },
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["test/setup.ts"],
  },
});
