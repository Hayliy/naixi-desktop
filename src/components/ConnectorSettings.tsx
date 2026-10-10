import { useState, useEffect, useRef, type ReactNode } from "react";
import { apiGet, apiPost } from "@/lib/api";

/* 各连接器平台的可编辑字段（与后端 connector_manager 配置键对齐） */
const FIELDS: Record<string, { key: string; label: string; secret?: boolean }[]> = {
  napcat: [
    { key: "ws_url", label: "WS 地址（默认 ws://127.0.0.1:3001）" },
    { key: "access_token", label: "Access Token（未配置留空）", secret: true },
    { key: "group_require_at", label: "群聊仅 @ 时回复（true/false）" },
  ],
  feishu: [
    { key: "app_id", label: "App ID" },
    { key: "app_secret", label: "App Secret", secret: true },
  ],
  dingtalk: [
    { key: "client_id", label: "Client ID" },
    { key: "client_secret", label: "Client Secret", secret: true },
  ],
  wecom: [
    { key: "corp_id", label: "Corp ID" },
    { key: "corp_secret", label: "Corp Secret", secret: true },
    { key: "agent_id", label: "Agent ID" },
    { key: "token", label: "Token", secret: true },
    { key: "aes_key", label: "EncodingAESKey", secret: true },
  ],
  wechat: [],
  telegram: [
    { key: "bot_token", label: "Bot Token", secret: true },
    { key: "group_require_at", label: "群聊仅 @ 时回复（true/false）" },
  ],
  discord: [
    { key: "bot_token", label: "Bot Token", secret: true },
  ],
  slack: [
    { key: "bot_token", label: "Bot Token (xoxb-)", secret: true },
    { key: "app_token", label: "App Token (xapp-)", secret: true },
    { key: "group_require_at", label: "群聊仅 @ 时回复（true/false）" },
  ],
  github: [
    { key: "token", label: "Access Token", secret: true },
    { key: "owner", label: "Owner" },
    { key: "repo", label: "Repo" },
  ],
  gitlab: [
    { key: "token", label: "Access Token", secret: true },
    { key: "base_url", label: "Base URL" },
    { key: "project_id", label: "Project ID" },
  ],
  email: [
    { key: "host", label: "IMAP Host" },
    { key: "port", label: "Port" },
    { key: "user", label: "User" },
    { key: "password", label: "Password", secret: true },
  ],
  whatsapp: [
    { key: "verify_token", label: "Verify Token" },
    { key: "phone_number_id", label: "Phone Number ID" },
    { key: "access_token", label: "Access Token", secret: true },
  ],
  generic: [],
};

/* 哪些平台由连接器管理，由 platforms.json 的 managed 字段决定（数据驱动，不在此硬编码） */

type PlatformMeta = {
  id: string;
  name: string;
  platform: string;
  managed?: boolean;
  description?: string;
  connected?: boolean;
  connector_detail?: string;
};

type AdapterCfg = Record<string, any>;

export default function ConnectorSettings() {
  const [platforms, setPlatforms] = useState<PlatformMeta[]>([]);
  const [config, setConfig] = useState<{ adapters: Record<string, AdapterCfg> }>({ adapters: {} });
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const qrTimer = useRef<number | null>(null);

  // 拉取完整配置：只在初次加载与保存成功后调用（轮询不能用，否则会覆盖用户未保存的编辑）
  const loadConfig = async () => {
    try {
      const cfg = await apiGet<any>("/api/connector/config");
      setConfig({ adapters: (cfg.config && cfg.config.adapters) || {} });
      setRunning(!!cfg.running);
      return true;
    } catch (e: any) {
      const msg = e?.message || String(e);
      if (/API 404/.test(msg)) {
        setMsg({
          ok: false,
          text: "后端未加载连接器接口（404）：前端已更新但后端是旧进程。请重启后端 / 重新编译桌面端，然后刷新本页。",
        });
      } else {
        setMsg({ ok: false, text: "加载失败：" + msg });
      }
      return false;
    }
  };

  // 状态轮询：只更新平台连接状态与运行标志，绝不覆盖 config（避免把用户正在编辑的表单弹回去）
  const loadStatus = async () => {
    try {
      const [cfg, plats] = await Promise.all([
        apiGet<any>("/api/connector/config"),
        apiGet<any>("/api/desktop/platforms"),
      ]);
      setRunning(!!cfg.running);
      setPlatforms(plats.platforms || []);
    } catch {
      // 轮询失败静默（初次加载的错误已由 loadConfig 提示）
    }
  };

  useEffect(() => {
    loadConfig();
    loadStatus();
    // 轮询状态（连接/断开后实时反映）
    const t = window.setInterval(loadStatus, 3000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 微信二维码轮询（端点直接返回 PNG，浏览器按图片地址加载，带时间戳防缓存）
  useEffect(() => {
    const wechat = config.adapters?.wechat;
    const needQr = running && wechat?.enabled && !platforms.find((p) => p.id === "wechat")?.connected;
    if (needQr) {
      if (qrTimer.current == null) {
        const imgTick = () => setQrUrl("/api/connector/qr?t=" + Date.now());
        imgTick();
        qrTimer.current = window.setInterval(imgTick, 2000);
      }
    } else {
      if (qrTimer.current != null) {
        window.clearInterval(qrTimer.current);
        qrTimer.current = null;
      }
      setQrUrl(null);
    }
    return () => {
      if (qrTimer.current != null) window.clearInterval(qrTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, config.adapters?.wechat, platforms]);

  const getAdapter = (id: string): AdapterCfg =>
    config.adapters?.[id] || { enabled: false };

  const setField = (id: string, key: string, value: string) => {
    setConfig((prev) => {
      const adapters = { ...(prev.adapters || {}) };
      const a = { ...(adapters[id] || { enabled: false }) };
      a[key] = value;
      adapters[id] = a;
      return { adapters };
    });
  };
  const setEnabled = (id: string, enabled: boolean) => {
    setConfig((prev) => {
      const adapters = { ...(prev.adapters || {}) };
      const a = { ...(adapters[id] || {}) };
      a.enabled = enabled;
      adapters[id] = a;
      return { adapters };
    });
  };

  const save = async (alsoStart: boolean) => {
    setBusy(true);
    setMsg(null);
    try {
      // 只提交连接器托管的平台（platforms.json 中 managed===true），避免误改其它
      const payload: any = { adapters: {} };
      for (const p of platforms) {
        if (p.managed === true) payload.adapters[p.id] = getAdapter(p.id);
      }
      await apiPost("/api/connector/config", payload);
      if (alsoStart) {
        try {
          await apiPost("/api/connector/start", {});
          setMsg({ ok: true, text: "已保存并启动连接器" });
        } catch (e: any) {
          setMsg({ ok: false, text: "已保存，但启动失败：" + (e?.message || e) });
        }
      } else {
        setMsg({ ok: true, text: "已保存" });
      }
      await loadConfig();
    } catch (e: any) {
      setMsg({ ok: false, text: "保存失败：" + (e?.message || e) });
    }
    setBusy(false);
  };

  const stop = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await apiPost("/api/connector/stop", {});
      setMsg({ ok: true, text: "已断开连接器" });
      await loadStatus();
    } catch (e: any) {
      setMsg({ ok: false, text: "断开失败：" + (e?.message || e) });
    }
    setBusy(false);
  };

  const statusBadge = (p: PlatformMeta) => {
    const a = getAdapter(p.id);
    if (p.connected) return <Badge cls="bg-green-100 text-green-600">已连接</Badge>;
    if (a?.enabled && running) return <Badge cls="bg-amber-100 text-amber-600">连接中…</Badge>;
    if (a?.enabled && !running) return <Badge cls="bg-gray-100 text-gray-400">已停用</Badge>;
    return <Badge cls="bg-gray-100 text-gray-400">未启用</Badge>;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-sakura-600">连接到消息平台</p>
        <span className={`text-[11px] px-2 py-0.5 rounded-full ${running ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-400"}`}>
          {running ? "连接器运行中" : "连接器未运行"}
        </span>
      </div>

      {msg && (
        <div className={`text-xs px-3 py-2 rounded-lg ${msg.ok ? "bg-green-50 text-green-600" : "bg-red-50 text-red-500"}`}>
          {msg.text}
        </div>
      )}

      <div className="space-y-3 max-h-[58vh] overflow-y-auto pr-1">
        {platforms.map((p) => {
          const isConn = p.managed === true;
          const a = getAdapter(p.id);
          if (!isConn) {
            // 非连接器管理：诚实标注
            const label =
              p.id === "napcat" ? "本机检测（自动）" : "暂未接入连接器（规划中）";
            const cls = p.id === "napcat" ? "bg-green-50 text-green-600" : "bg-gray-100 text-gray-400";
            return (
              <div key={p.id} className="border border-gray-200 rounded-xl px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-700">{p.name}</span>
                  <span className="text-gray-400 text-[11px]">({p.platform})</span>
                  <span className={`ml-auto text-[11px] px-2 py-0.5 rounded-full ${cls}`}>{label}</span>
                </div>
                {p.connector_detail && <p className="text-[11px] mt-1 text-sakura-400">{p.connector_detail}</p>}
              </div>
            );
          }
          const fields = FIELDS[p.id] || [];
          return (
            <div key={p.id} className="border border-gray-200 rounded-xl overflow-hidden">
              <div className="px-4 py-3 flex items-center gap-2">
                <span className="text-xs font-medium text-gray-700">{p.name}</span>
                <span className="text-gray-400 text-[11px]">({p.platform})</span>
                <span className="ml-auto">{statusBadge(p)}</span>
              </div>
              <div className="px-4 pb-4 border-t border-gray-100 bg-gray-50/40">
                {p.description && <p className="text-[11px] text-gray-500 my-2">{p.description}</p>}
                {p.connector_detail && <p className="text-[11px] mb-2 text-sakura-400">{p.connector_detail}</p>}

                <label className="flex items-center gap-2 mt-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={!!a?.enabled}
                    onChange={(e) => setEnabled(p.id, e.target.checked)}
                    className="accent-sakura-500"
                  />
                  <span className="text-xs text-gray-600">启用 {p.name} 连接器</span>
                </label>

                {!!a?.enabled && (
                  <div className="mt-3 space-y-2">
                    {fields.map((f) => (
                      <div key={f.key}>
                        <label className="block text-[11px] text-gray-500 mb-0.5">{f.label}</label>
                        <input
                          value={a?.[f.key] ?? ""}
                          onChange={(e) => setField(p.id, f.key, e.target.value)}
                          type={f.secret ? "password" : "text"}
                          autoComplete="off"
                          placeholder={f.secret ? "填写后保存" : ""}
                          className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300 font-mono"
                        />
                      </div>
                    ))}

                    {p.id === "wechat" && qrUrl && (
                      <div className="mt-2 p-2 bg-white border border-gray-200 rounded-lg inline-block">
                        <p className="text-[11px] text-gray-500 mb-1">微信扫码登录（约 5 分钟有效）：</p>
                        <img src={qrUrl} alt="wechat qr" className="w-40 h-40 object-contain" />
                      </div>
                    )}
                    {p.id === "wechat" && (
                      <p className="text-[11px] text-gray-400">启用后自动生成二维码，用微信扫码即可；登录态会保存，重启无需再扫。</p>
                    )}

                    <div className="flex items-center gap-2 pt-1">
                      <button
                        onClick={() => save(true)}
                        disabled={busy}
                        className="px-3 py-1.5 bg-sakura-500 text-white rounded-lg text-xs hover:bg-sakura-600 disabled:opacity-50 transition-colors">
                        {busy ? "处理中…" : "保存并连接"}
                      </button>
                      <button
                        onClick={() => save(false)}
                        disabled={busy}
                        className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200 disabled:opacity-50 transition-colors">
                        仅保存
                      </button>
                      {running && (
                        <button
                          onClick={stop}
                          disabled={busy}
                          className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200 disabled:opacity-50 transition-colors">
                          断开
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Badge({ cls, children }: { cls: string; children: ReactNode }) {
  return <span className={`text-[11px] px-2 py-0.5 rounded-full ${cls} shrink-0`}>{children}</span>;
}
