import { useState, useEffect } from "react";
import { X, Plus, Trash2, Check, ChevronDown, ChevronUp, Pencil, Zap, Link, Loader2 } from "lucide-react";
import { useToast } from "@/components/Toast";
import { apiGet, apiPost } from "@/lib/api";

export default function ConnectionPanel({ onClose }: { onClose: () => void }) {
  const { notify } = useToast();
  const [servers, setServers] = useState<Record<string, { command: string; args: string[]; env: Record<string, string> }>>({});
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");

  const loadServers = async () => {
    try {
      const res = await apiGet<{ servers: any }>("/api/mcp/servers");
      setServers(res.servers || {});
    } catch {}
    setLoading(false);
  };

  useEffect(() => { loadServers(); }, []);

  const handleAdd = async () => {
    if (!name.trim() || !command.trim()) return;
    const updated = { ...servers };
    if (editingKey && editingKey !== name.trim()) {
      delete updated[editingKey];
    }
    updated[name.trim()] = {
      command: command.trim(),
      args: args.split(" ").filter(Boolean),
      env: {},
    };
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setServers(updated);
      setShowForm(false);
      setEditingKey(null);
      setName(""); setCommand(""); setArgs("");
    } catch {}
  };

  const handleEdit = (key: string) => {
    const srv = servers[key];
    if (!srv) return;
    setEditingKey(key);
    setName(key);
    setCommand(srv.command);
    setArgs(srv.args?.join(" ") || "");
    setShowForm(true);
  };

  const handleDelete = async (key: string) => {
    const updated = { ...servers };
    delete updated[key];
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setServers(updated);
    } catch {}
  };

  const handleConnect = async () => {
    try {
      const res = await apiPost<{ ok: boolean; tool_count: number }>("/api/mcp/connect", {});
      if (res.ok) notify(`MCP 连接成功，当前共 ${res.tool_count} 个工具`, "success");
    } catch {}
  };

  const handleTestSingle = async (key: string) => {
    try {
      const res = await apiPost<{ ok: boolean; error?: string; tools?: string[] }>("/api/mcp/test", { name: key });
      if (res.ok) {
        notify(`✅ ${key} 连接成功！工具: ${(res.tools || []).join(", ")}`, "success");
      } else {
        notify(`❌ ${key} 连接失败: ${res.error || "未知错误"}`, "error");
      }
    } catch (e) {
      notify(`❌ ${key} 测试异常: ${String(e)}`, "error");
    }
  };

  const mcpKeys = Object.keys(servers);

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500 flex items-center gap-1">
          <Zap size={13} /> 外部连接
          <span className="text-sakura-300 font-normal">({mcpKeys.length})</span>
        </span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {/* 连接按钮 */}
        {mcpKeys.length > 0 && (
          <button onClick={handleConnect}
            className="w-full px-3 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-teal-400 to-teal-500 text-white hover:shadow-md transition-shadow">
            连接 MCP 服务器
          </button>
        )}

        {/* 添加按钮 */}
        {!showForm && !editingKey && (
          <button onClick={() => setShowForm(true)}
            className="flex items-center gap-1 w-full px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
            <Plus size={10} /> 添加外部连接
          </button>
        )}

        {/* 添加/编辑表单 */}
        {(showForm || editingKey) && (
          <div className="bg-white border border-sakura-200 rounded-lg p-2.5 space-y-1.5 text-xs">
            <p className="text-[10px] font-semibold text-sakura-500">{editingKey ? "编辑" : "添加"}外部连接</p>
            <input value={name} onChange={e => setName(e.target.value)}
              placeholder="名称（如: fetch）" className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] outline-none" />
            <input value={command} onChange={e => setCommand(e.target.value)}
              placeholder="启动命令（如: uvx）" className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] font-mono outline-none" />
            <input value={args} onChange={e => setArgs(e.target.value)}
              placeholder="参数如: mcp-server-fetch（空格分隔）" className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] font-mono outline-none" />
            <div className="flex items-center gap-1 pt-0.5">
              <button onClick={() => { setShowForm(false); setEditingKey(null); setName(""); setCommand(""); setArgs(""); }}
                className="px-3 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleAdd} disabled={!name.trim() || !command.trim()}
                className="flex items-center gap-1 px-3 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-50">
                <Check size={10} /> {editingKey ? "保存" : "添加"}
              </button>
            </div>
          </div>
        )}

        {/* 服务器列表 */}
        <div className="max-h-[300px] overflow-y-auto space-y-1 pr-0.5">
          {mcpKeys.map(key => (
            <div key={key}>
              <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-sakura-50 border border-sakura-100">
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium text-sakura-600 truncate">{key}</p>
                  <p className="text-[10px] text-sakura-400 truncate font-mono">{servers[key].command} {servers[key].args?.join(" ")}</p>
                </div>
                <button onClick={() => handleTestSingle(key)}
                  className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors shrink-0" title="测试连接">
                  <Zap size={11} />
                </button>
                <button onClick={() => handleEdit(key)}
                  className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500 transition-colors shrink-0" title="编辑">
                  <Pencil size={11} />
                </button>
                <button onClick={() => handleDelete(key)}
                  className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors shrink-0">
                  <Trash2 size={11} />
                </button>
              </div>
              {editingKey === key && (
                <div className="bg-white border border-sakura-100 rounded-lg px-2.5 py-2 space-y-2 text-xs mt-1">
                  <p className="text-[11px] font-semibold text-sakura-500">编辑 MCP 服务器</p>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">名称</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]"
                      value={name} onChange={e => setName(e.target.value)} />
                  </div>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">启动命令</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                      value={command} onChange={e => setCommand(e.target.value)} />
                  </div>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">参数（空格分隔）</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                      value={args} onChange={e => setArgs(e.target.value)} />
                  </div>
                  <div className="flex justify-end gap-2 pt-1">
                    <button onClick={() => { setShowForm(false); setEditingKey(null); setName(""); setCommand(""); setArgs(""); }}
                      className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
                    <button onClick={handleAdd} disabled={!name.trim() || !command.trim()}
                      className="flex items-center gap-1 px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40">
                      <Check size={11} /> 保存
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
