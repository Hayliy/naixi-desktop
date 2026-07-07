import { X, Layers, MessageSquare, Clock, Cpu, Database, Key } from "lucide-react";

interface DetailPanelProps {
  activeKey: string | null;
  messageCount: number;
  tokenEstimate: number;
  modelKey: string;
  onClose: () => void;
}

export default function DetailPanel({ activeKey, messageCount, tokenEstimate, modelKey, onClose }: DetailPanelProps) {
  if (!activeKey) return null;

  const parts = activeKey.split(":");
  const convType = parts[0] === "group" ? "群聊" : parts[0] === "user" ? "私聊" : "其他";
  const convId = parts[1] || activeKey;

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100">
        <span className="text-xs font-semibold text-sakura-500">会话详情</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300 hover:text-sakura-500 transition-colors">
          <X size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 text-xs">
        {/* 基本信息 */}
        <Section title="基本信息">
          <Row icon={<MessageSquare size={12} />} label="类型" value={convType} />
          <Row icon={<Key size={12} />} label="ID" value={convId} />
        </Section>

        {/* 对话统计 */}
        <Section title="对话统计">
          <Row icon={<Clock size={12} />} label="消息数" value={`${messageCount} 条`} />
          <Row icon={<Cpu size={12} />} label="Token 用量" value={tokenEstimate > 1000 ? `${(tokenEstimate / 1000).toFixed(1)}k` : `${tokenEstimate}`} />
        </Section>

        {/* 模型信息 */}
        <Section title="模型">
          <Row icon={<Layers size={12} />} label="当前" value={modelKey} />
        </Section>

        {/* 数据统计 */}
        <Section title="数据">
          <Row icon={<Database size={12} />} label="状态" value={messageCount > 0 ? "活跃" : "空"} />
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-medium text-sakura-400 mb-1.5">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 text-[11px]">
      <span className="text-sakura-300 shrink-0">{icon}</span>
      <span className="text-sakura-400">{label}</span>
      <span className="text-sakura-600 ml-auto truncate max-w-[100px]">{value}</span>
    </div>
  );
}
