import { Cpu, Loader } from "lucide-react";

export default function AgentStatus({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-sakura-50 to-pink-50 border-b border-sakura-100 text-xs text-sakura-500">
      <Loader size={12} className="animate-spin" />
      <Cpu size={12} />
      <span>Agent 运行中</span>
    </div>
  );
}
