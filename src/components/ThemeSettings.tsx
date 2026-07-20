import { useState, useEffect } from "react";
import { applyTheme, getTheme } from "@/lib/theme";
import { SettingRow, BTN_GHOST } from "./settings/primitives";

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

  const currentName = PRESETS.reduce((a, b) => Math.abs(b.hue - hue) < Math.abs(a.hue - hue) ? b : a, PRESETS[0]).name;

  return (
    <>
      {/* 主题模式 — 分段切换 */}
      <SettingRow label="主题模式" desc="浅色或暗色外观">
        <div className="flex gap-1 bg-sakura-50 border border-sakura-200 rounded-lg p-0.5">
          {(["light", "dark"] as const).map(m => (
            <button key={m} onClick={() => setTheme(m)}
              className={`px-4 py-1 rounded-md text-sm transition-colors ${
                theme === m ? "bg-sakura-500 text-white" : "text-sakura-400 hover:text-sakura-500"
              }`}>
              {m === "light" ? "浅色" : "暗色"}
            </button>
          ))}
        </div>
      </SettingRow>

      {/* 主题色 — 预设色板 */}
      <SettingRow label="主题色" desc="点选预设配色">
        <div className="flex flex-wrap gap-2 justify-end max-w-[220px]">
          {PRESETS.map(p => (
            <button key={p.hue} onClick={() => setHue(p.hue)} title={p.name}
              className={`w-6 h-6 rounded-full border-2 transition-all ${
                hue === p.hue ? "scale-110 border-sakura-500" : "border-transparent hover:scale-105"
              }`}
              style={{
                background: `hsl(${p.hue}, 65%, ${theme === "light" ? "70%" : "35%"})`,
                boxShadow: hue === p.hue ? `0 0 0 2px hsl(${p.hue}, 65%, 55%)` : "none",
              }} />
          ))}
        </div>
      </SettingRow>

      {/* 色相微调 — 滑块 */}
      <SettingRow label="色相微调" desc={`当前：${currentName}（hsl ${hue}°）`}>
        <div className="flex items-center gap-2.5 min-w-[200px]">
          <input type="range" min="0" max="360" value={hue}
            onChange={e => setHue(Number(e.target.value))}
            className="flex-1" style={{ accentColor: `hsl(${hue}, 65%, 55%)` }} />
          <span className="w-6 h-6 rounded-full shrink-0 border"
            style={{ background: `hsl(${hue}, 65%, ${theme === "light" ? "70%" : "35%"})`, borderColor: `hsl(${hue}, 65%, 80%)` }} />
        </div>
      </SettingRow>

      {/* 恢复默认 */}
      <SettingRow label="恢复默认主题" desc="重置为浅色 + 樱粉配色">
        <button onClick={() => { setTheme("light"); setHue(350); }} className={BTN_GHOST}>恢复默认</button>
      </SettingRow>
    </>
  );
}
