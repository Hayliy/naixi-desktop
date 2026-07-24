import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  clearScreen: false,
  // 不自动清空 dist：vite 默认 build 会 rmSync 清空 outDir，触发 WorkBuddy safe-delete
  // shim 拦截并改走回收站导致构建中止。关闭后 shim 不再被触发，不再需要 rm -rf 绕过。
  // 代价：dist 可能残留旧文件；发布前手动清理一次即可（开发构建因资源带 hash 影响极小）。
  build: { emptyOutDir: false },
  server: {
    port: 1420,
    strictPort: true,
    host: host || "127.0.0.1",
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:9845",
        changeOrigin: true,
      },
    },
  },
}));
