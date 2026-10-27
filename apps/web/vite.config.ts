/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // The API checks Origin on non-GET requests: its PUBLIC_ORIGIN must include http://127.0.0.1:5173 in dev.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router", "@tanstack/react-query"],
          antd: ["antd", "@ant-design/icons"],
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
