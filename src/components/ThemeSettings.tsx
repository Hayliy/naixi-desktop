import { useState, useEffect } from "react";
import { applyTheme, getTheme } from "@/lib/theme";

type ThemeMode = "light" | "dark";

const HUE_NAMES: Record<number, string> = {
  0: "玫瑰红", 15: "珊瑚橙", 30: "暖杏", 45: "琥珀",
  60: "柠檬黄", 120: "薄荷绿", 180: "天蓝", 210: "雾蓝",
  240: "薰衣草", 270: "紫罗兰", 300: "粉紫", 330: "梅子",
};

export default function ThemeSettings() {
  const [theme, setTheme] = useState<ThemeMode>(() => getTheme().theme);
  const [hue, setHue] = useState(() => getTheme().hue);

  useEffect(() => { applyTheme(theme, hue); }, [theme, hue]);

  return (
    <div className="space-y-3 text-xs">
      <div>
        <p className="text-[10px] text-sakura-400 mb-1.5">主题模式</p>
        <div className="flex gap-1.5">
          {(["light", "dark"] as const).map(m => (
            <button key={m} onClick={() => setTheme(m)}
              className={`flex-1 px-3 py-1.5 rounded-lg text-[11px] border transition-colors ${
                theme === m ? "bg-sakura-200 text-sakura-600 border-sakura-300" : "bg-sakura-50 text-sakura-400 border-sakura-100 hover:bg-sakura-100"
              }`}>
              {m === "light" ? "浅色" : "暗色"}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-[10px] text-sakura-400 mb-1.5">主题色</p>
        <input type="range" min="0" max="360" value={hue} onChange={e => setHue(Number(e.target.value))}
          className="w-full" style={{ accentColor: `hsl(${hue}, 65%, 55%)` }} />
        <div className="flex items-center gap-2 mt-1">
          <span className="w-5 h-5 rounded-full shrink-0 border" style={{ background: `hsl(${hue}, 65%, 70%)`, borderColor: `hsl(${hue}, 65%, 80%)` }} />
          <span className="text-[10px] text-sakura-500">
            {[0,15,30,45,60,120,180,210,240,270,300,330].reduce((a,b) => Math.abs(b-hue) < Math.abs(a-hue) ? b : a)}
            {Object.entries(HUE_NAMES).find(([k]) => Math.abs(+k - hue) < 8)?.[1] || "自定义"}
          </span>
          <span className="text-[10px] text-sakura-300 ml-auto">{theme === "light" ? "浅色" : "暗色"}</span>
        </div>
      </div>
    </div>
  );
}
