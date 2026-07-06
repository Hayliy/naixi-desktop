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

function darkOverrides(): Record<string, string> {
  return {
    "bg-sakura-50": "#2A2032", "bg-sakura-100": "#352542",
    "bg-sakura-200": "#453050", "bg-sakura-300": "#554070",
    "bg-sakura-400": "#6A5080", "bg-sakura-500": "#8060A0",
    "text-sakura-300": "#A880A8", "text-sakura-400": "#C090C0",
    "text-sakura-500": "#D8A8D8", "text-sakura-600": "#E8C0E8",
    "text-sakura-700": "#F0D0F0",
    "border-sakura-100": "#4A3050", "border-sakura-200": "#5A4070",
    "border-sakura-300": "#6A5090",
    "bg-white": "#22182A", "bg-red-50": "#3A2030",
    "bg-pink-100": "#403050", "bg-pink-500": "#805070",
    "text-pink-500": "#D080B0",
    "purple-50": "#2A2040", "purple-100": "#352550", "purple-500": "#9060C0",
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
  const colors = theme === "dark" ? { ...genPalette(hue), ...darkOverrides() } : genPalette(hue);
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
  localStorage.setItem("naixi_theme", theme);
  localStorage.setItem("naixi_theme_hue", String(hue));
}

export function getTheme(): { theme: ThemeMode; hue: number } {
  const t = (localStorage.getItem("naixi_theme") as ThemeMode) || "light";
  const h = Number(localStorage.getItem("naixi_theme_hue")) || 350;
  return { theme: t, hue: h };
}
