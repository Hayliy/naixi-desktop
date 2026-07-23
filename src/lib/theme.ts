/* 主题管理：动态 CSS 注入 + 持久化 */
type ThemeMode = "light" | "dark";

function genPalette(h: number): Record<string, string> {
  const s = 65;
  return {
    "bg-sakura-50":  `hsl(${h},${s+10}%,96%)`,
    "bg-sakura-100": `hsl(${h},${s+5}%,92%)`,
    "bg-sakura-200": `hsl(${h},${s}%,84%)`,
    "bg-sakura-300": `hsl(${h},${s}%,72%)`,
    "bg-sakura-400": `hsl(${h},${s}%,60%)`,
    "bg-sakura-500": `hsl(${h},${s+5}%,52%)`,
    "bg-pink-100":   `hsl(${h},${s+10}%,92%)`,
    "bg-pink-500":   `hsl(${h},${s+5}%,55%)`,
    "bg-purple-50":  `hsl(${h+30},50%,96%)`,
    "bg-purple-100": `hsl(${h+30},50%,92%)`,
    "text-sakura-300": `hsl(${h},${s}%,60%)`,
    "text-sakura-400": `hsl(${h},${s}%,52%)`,
    "text-sakura-500": `hsl(${h},${s+5}%,44%)`,
    "text-sakura-600": `hsl(${h},${s+10}%,36%)`,
    "text-sakura-700": `hsl(${h},${s+15}%,28%)`,
    "text-pink-500":   `hsl(${h},${s+5}%,55%)`,
    "text-purple-500": `hsl(${h+30},55%,55%)`,
    "border-sakura-100": `hsl(${h},${s+5}%,88%)`,
    "border-sakura-200": `hsl(${h},${s}%,80%)`,
    "border-sakura-300": `hsl(${h},${s}%,68%)`,
  };
}

function darkPalette(h: number): Record<string, string> {
  const s = 15; // 暗色下饱和度低，纯黑感
  return {
    "bg-sakura-50":  `hsl(${h},${s}%,6%)`,
    "bg-sakura-100": `hsl(${h},${s}%,10%)`,
    "bg-sakura-200": `hsl(${h},${s}%,15%)`,
    "bg-sakura-300": `hsl(${h},${s}%,20%)`,
    "bg-sakura-400": `hsl(${h},${s}%,28%)`,
    "bg-sakura-500": `hsl(${h},${s}%,35%)`,
    "bg-pink-100":   `hsl(${h},25%,12%)`,
    "bg-pink-500":   `hsl(${h},30%,25%)`,
    "bg-purple-50":  `hsl(${h+30},20%,10%)`,
    "bg-purple-100": `hsl(${h+30},20%,14%)`,
    "text-sakura-300": `hsl(${h},20%,55%)`,
    "text-sakura-400": `hsl(${h},20%,65%)`,
    "text-sakura-500": `hsl(${h},25%,75%)`,
    "text-sakura-600": `hsl(${h},25%,85%)`,
    "text-sakura-700": `hsl(${h},30%,92%)`,
    "text-pink-500":   `hsl(${h},40%,65%)`,
    "text-purple-500": `hsl(${h+30},45%,65%)`,
    "border-sakura-100": `hsl(${h},10%,15%)`,
    "border-sakura-200": `hsl(${h},10%,22%)`,
    "border-sakura-300": `hsl(${h},10%,30%)`,
    "bg-white": `hsl(${h},15%,6%)`,
    "bg-red-50": `hsl(0,30%,12%)`,
    "purple-50": `hsl(${h+30},20%,10%)`,
    "purple-100": `hsl(${h+30},20%,14%)`,
    "purple-500": `hsl(${h+30},40%,60%)`,
  };
}

let _styleEl: HTMLStyleElement | null = null;

export function applyTheme(theme: ThemeMode, hue: number) {
  if (!_styleEl) {
    _styleEl = document.getElementById("naixi-theme") as HTMLStyleElement;
    if (!_styleEl) {
      _styleEl = document.createElement("style");
      _styleEl.id = "naixi-theme";
      document.head.appendChild(_styleEl);
    }
  }
  const colors = theme === "dark" ? { ...genPalette(hue), ...darkPalette(hue) } : genPalette(hue);
  const lines: string[] = [];
  for (const [cls, color] of Object.entries(colors)) {
    lines.push(`.${cls}{`);
    if (cls.startsWith("bg-")) lines.push(`background:${color}!important`);
    else if (cls.startsWith("text-")) lines.push(`color:${color}!important`);
    else if (cls.startsWith("border-")) lines.push(`border-color:${color}!important`);
    else if (cls.startsWith("pink-") || cls.startsWith("purple-")) lines.push(`background:${color}!important`);
    lines.push("}");
  }
  if (theme === "dark") {
    lines.push(".bg-gradient-to-br,.bg-gradient-to-r{opacity:0.7}");
  }
  _styleEl.textContent = lines.join("");
  // 同步 Tailwind 的 dark class：light 模式移除（避免系统深色偏好误触发 dark: 变体），dark 模式加上
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
  localStorage.setItem("naixi_theme", theme);
  localStorage.setItem("naixi_theme_hue", String(hue));
}

export function getTheme(): { theme: ThemeMode; hue: number } {
  const t = (localStorage.getItem("naixi_theme") as ThemeMode) || "light";
  const h = Number(localStorage.getItem("naixi_theme_hue")) || 350;
  return { theme: t, hue: h };
}
