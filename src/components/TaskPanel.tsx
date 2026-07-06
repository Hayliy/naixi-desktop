import { useState, useEffect } from "react";
import { apiGet } from "@/lib/api";
import { X, CheckCircle2, Circle, Loader2 } from "lucide-react";

interface TaskStep {
  desc: string;
  status: string;
}

interface TaskItem {
  id: string;
  description: string;
  status: string;
  current_step: number;
  total_steps: number;
  steps: TaskStep[];
}

export default function TaskPanel({ onClose }: { onClose: () => void }) {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const res = await apiGet<{ tasks: TaskItem[] }>("/api/tasks");
      setTasks(res.tasks || []);
    } catch {
      setTasks([]);
    }
    setLoading(false);
  };

  useEffect(() => { fetchTasks(); }, []);
  useEffect(() => {
    const iv = setInterval(fetchTasks, 3000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500">任务进度</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
          <X size={13} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2 text-xs">
        {loading && tasks.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-sakura-300">
            <Loader2 size={14} className="animate-spin mr-1" /> 加载中...
          </div>
        ) : tasks.length === 0 ? (
          <p className="text-sakura-300 text-center py-8">暂无进行中的任务</p>
        ) : (
          tasks.map(task => (
            <div key={task.id} className="bg-sakura-50 rounded-lg p-3 border border-sakura-100">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-medium text-sakura-600 truncate max-w-[10rem]">{task.description}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  task.status === "done" ? "bg-green-100 text-green-600" :
                  task.status === "failed" ? "bg-red-100 text-red-600" :
                  "bg-sakura-100 text-sakura-500"
                }`}>
                  {task.status === "done" ? "完成" : task.status === "failed" ? "失败" : `${task.current_step+1}/${task.total_steps}`}
                </span>
              </div>
              {task.steps.length > 0 && (
                <div className="space-y-1 mt-2">
                  {task.steps.map((step, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      {step.status === "done" ? <CheckCircle2 size={10} className="text-green-500 shrink-0" />
                        : step.status === "running" ? <Loader2 size={10} className="text-sakura-400 animate-spin shrink-0" />
                        : <Circle size={10} className="text-sakura-300 shrink-0" />}
                      <span className="text-[10px] text-sakura-500 truncate">{step.desc}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
