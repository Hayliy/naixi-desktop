import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import { initClientErrorReporter } from "./lib/clientError";
import { maybeRunSelfTest } from "./lib/selftest";

initClientErrorReporter();

// 全量页面交互自测：默认不跑，仅当后端 /api/self_test_request 返回 run=true
// （安装目录存在 data/self_test.request 标记文件）时才执行，避免影响正常用户。
setTimeout(() => {
  void maybeRunSelfTest();
}, 3000);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
