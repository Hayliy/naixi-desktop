import { Check, Loader, X, Search, FileImage, FileCode, FileText, Globe, Cpu, Wrench } from "lucide-react";

interface ToolEvent {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  state: "loading" | "done" | "error";
  content?: string;
}

export default function ToolExecutionPanel({ events }: { events: ToolEvent[] }) {
  if (events.length === 0) return null;

  const toolIcon = (name: string) => {
    if (name.includes("search") || name.includes("web")) return <Search size={11} />;
    if (name.includes("image")) return <FileImage size={11} />;
    if (name.includes("code") || name.includes("interpreter")) return <FileCode size={11} />;
    if (name.includes("file") || name.includes("doc") || name.includes("read")) return <FileText size={11} />;
    if (name.includes("translate") || name.includes("weather")) return <Globe size={11} />;
    return <Wrench size={11} />;
  };

  const stateColor = (state: string) => {
    if (state === "loading") return "border-sakura-200 bg-sakura-50";
    if (state === "done") return "border-green-100 bg-green-50";
    return "border-red-100 bg-red-50";
  };

  const stateIcon = (state: string) => {
    if (state === "loading") return <Loader size={10} className="animate-spin text-sakura-500" />;
    if (state === "done") return <Check size={10} className="text-green-600" />;
    return <X size={10} className="text-red-500" />;
  };

  return (
    <div className="space-y-1 my-2">
      <p className="text-[10px] text-sakura-400 font-medium px-1">工具调用</p>
      <div className="space-y-1">
        {events.map((ev) => (
          <div key={ev.id} className={`px-2.5 py-1.5 rounded-lg border ${stateColor(ev.state)} text-[11px]`}>
            <div className="flex items-center gap-1.5">
              {stateIcon(ev.state)}
              <span className="font-medium text-sakura-600 truncate">{ev.name}</span>
              {ev.state === "loading" && <span className="text-sakura-400 ml-auto text-[10px]">运行中...</span>}
            </div>
            {ev.state === "done" && ev.content && (
              <p className="mt-1 text-[10px] text-sakura-500 line-clamp-2 break-all">{ev.content.slice(0, 120)}</p>
            )}
            {ev.state === "error" && (
              <p className="mt-1 text-[10px] text-red-500">{ev.content?.slice(0, 80) || "执行出错"}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
