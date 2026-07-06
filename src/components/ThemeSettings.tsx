import { useState, useEffect } from "react";
import { applyTheme, getTheme } from "@/lib/theme";

type ThemeMode = "light" | "dark";

const PRESETS = [
  { hue: 350, name: "樱粉", light: "sakura" },
  { hue: 240, name: "薰衣草", light: "lavender" },
  { hue: 200, name: "天空蓝", light: "sky" },
  { hue: 150, name: "薄荷绿", light: "mint" },
  { hue: 30,  name: "暖杏", light: "warm" },
  { hue: 330, name: "梅子", light: "plum" },
  { hue: 270, name: "紫罗兰", light: "violet" },
  { hue: 0,   name: "玫瑰红", light: "rose" },
];

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
        {/* 预设色板 */}
        <div className="flex flex-wrap gap-2 mb-2.5">
          {PRESETS.map(p => (
            <button key={p.hue} onClick={() => setHue(p.hue)}
              title={p.name}
              className={`w-7 h-7 rounded-full border-2 transition-all ${
                hue === p.hue ? "scale-110 border-sakura-500 shadow-sm" : "border-transparent hover:scale-105"
              }`}
              style={{
                background: `hsl(${p.hue}, 65%, ${theme === "light" ? "70%" : "35%"})`,
                boxShadow: hue === p.hue ? `0 0 0 2px hsl(${p.hue}, 65%, 55%)` : "none",
              }} />
          ))}
        </div>
        {/* 自定义滑块 */}
        <div className="relative">
          <input type="range" min="0" max="360" value={hue} onChange={e => setHue(Number(e.target.value))}
            className="w-full" style={{ accentColor: `hsl(${hue}, 65%, 55%)` }} />
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="w-5 h-5 rounded-full shrink-0 border" style={{ background: `hsl(${hue}, 65%, ${theme === "light" ? "70%" : "35%"})`, borderColor: `hsl(${hue}, 65%, 80%)` }} />
          <span className="text-[10px] text-sakura-500">
            {PRESETS.reduce((a,b) => Math.abs(b.hue-hue) < Math.abs(a.hue-hue) ? b : a, PRESETS[0]).name}
          </span>
          <span className="text-[10px] text-sakura-300 ml-auto">hsl({hue}&deg;, 65%, ...)</span>
        </div>
      </div>

      <button onClick={() => { setTheme("light"); setHue(350); }}
        className="w-full px-2.5 py-1 rounded-lg text-[10px] border border-sakura-100 text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 transition-colors">
        恢复默认主题
      </button>
    </div>
  );
}
