import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import { initClientErrorReporter } from "./lib/clientError";

initClientErrorReporter();

// 全量页面交互自测：**仅开发构建可用，发布包不含该模块**（不随包发放）。
// 用 import.meta.env.DEV 常量折叠 + 动态 import：生产构建里整块是死代码，
// rollup 会把 ./lib/selftest 一并 tree-shake 掉，用户安装后不会再看到 [SELFTEST] 横幅。
if (import.meta.env.DEV) {
  setTimeout(() => {
    import("./lib/selftest")
      .then((m) => m.maybeRunSelfTest())
      .catch(() => {});
  }, 3000);
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
