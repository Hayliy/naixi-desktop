// 多角色舞台面板：传输方式 -> 中文徽章（标签 + 配色）
// 抽成纯函数，便于渲染级单元测试（无需浏览器）。

export interface TransportBadge {
  label: string;
  cls: string;
}

export function liveTransportBadge(transport: string): TransportBadge {
  switch (transport) {
    case "local":
      return { label: "内置", cls: "bg-sakura-100 text-sakura-500" };
    case "http":
      return { label: "HTTP", cls: "bg-blue-100 text-blue-500" };
    case "ws":
      return { label: "WS(连出)", cls: "bg-indigo-100 text-indigo-500" };
    case "ws-in":
      return { label: "WS(反向连入)", cls: "bg-purple-100 text-purple-500" };
    default:
      return { label: transport || "未知", cls: "bg-sakura-100 text-sakura-500" };
  }
}
