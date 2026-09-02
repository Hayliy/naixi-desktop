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
  // 发布前必须保证 dist 干净，否则历史构建残留的死文件（如旧版含爱发电的 index chunk）
  // 会被 Tauri 一起嵌进 exe，既增大体积又违背"资源干净/防篡改"诉求。
  // 已实测当前环境 vite 内置 emptyOutDir 不再触发 WorkBuddy safe-delete 拦截，
  // 故恢复默认行为：每次 build 前自动清空 dist，从源头杜绝残留累积（无需再手动 rm -rf）。
  build: { emptyOutDir: true },
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
        ws: true, // live2d-stream 等 WebSocket 端点需要代理升级（桌宠/舞台窗口浏览器模式）
      },
    },
  },
}));
