/**
 * 全量页面交互自测（1.0.1 起）
 *
 * 由来：用户报「点桌宠没反应」时，问题其实在日志里躺着，只是没人翻 —— 说明靠人肉点界面
 * 一定会漏。本模块让应用**自己把每个页面走一遍、把能点的都点一遍**，并把结论落盘。
 *
 * 两种模式（由后端 `GET /api/self_test_request` 下发，默认 safe）：
 *   · safe —— 只点安全元素（刷新 / 详情 / 展开 / 标签页 / 取消 …），可用于用户自查；
 *   · full —— **除「会中断自测本身」的动作外全部点击**，包括弹窗内的确认/删除/清空/启动，
 *             并填写空输入框、遍历下拉选项。仅限一次性测试环境（虚拟机可回滚）。
 *
 * 触发方式（默认关闭，不影响正常用户）：安装目录下存在 `data/self_test.request` 时执行。
 *   空文件           -> safe 模式
 *   {"mode":"full"}  -> 全量模式
 * 标记文件由后端**一次性消费**（下发即删除），不会每次启动都重跑。
 *
 * 为什么不用 CDP：实测 release 包设 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port
 * 端口根本不监听，外部拿不到 WebView 控制通道，故改由「数据文件 + 后端端点」下发指令。
 *
 * 报告为**增量上报**：每页跑完立即 POST 一次，即使后续页面把应用点崩，也能拿到已跑部分。
 *
 * ⚠ 自测期间会临时接管 confirm/alert/prompt/window.open，原因见 installGuards()。
 */

import { API_BASE } from "./api";

export type SelfTestMode = "safe" | "full";

export interface SelfAction {
  label: string;
  kind: string;
  scope: "page" | "dialog";
  note?: string;
}

export interface SelfTestStep {
  page: string;
  label: string;
  ok: boolean;
  ms: number;
  clickables: number;
  actions: SelfAction[];
  skipped: string[];
  errors: string[];
  suspicious: string[];
}

export interface SelfTestReport {
  startedAt: string;
  finishedAt: string;
  version: string;
  mode: SelfTestMode;
  done: boolean;
  steps: SelfTestStep[];
  totalErrors: number;
  failedPages: string[];
}

const NAV_LABELS: { key: string; label: string }[] = [
  { key: "dashboard", label: "仪表盘" },
  { key: "chat", label: "对话" },
  { key: "workflow", label: "工作流" },
  { key: "scheduler", label: "自动化" },
  { key: "knowledge", label: "知识库" },
  { key: "tools", label: "工具" },
  { key: "memory", label: "记忆" },
  { key: "connection", label: "连接" },
  { key: "ops", label: "运维" },
  { key: "live", label: "直播" },
  { key: "logs", label: "日志" },
  { key: "settings", label: "设置" },
];

/**
 * 无论哪种模式都不点：点了会**终止自测本身**或弹 JS 关不掉的系统原生框。
 * 这不是「怕搞坏数据」——测试环境数据可以随便破坏（VM 可回滚）；
 * 排除的只是"会把测试自己弄死"的动作。
 */
const NEVER =
  /(卸载|退出应用|退出程序|退出奶昔|退出软件|重启应用|重启程序|重启电脑|关机|注销登录|删除账号|选择文件|浏览文件|打开文件夹|打开目录|打开所在|另存为|导出到文件)/;

const DANGER =
  /(删除|移除|清空|重置|恢复默认|发布|导入|上传|下载|发送|执行|运行|停止|启动|关闭服务|断开|退出|注销|安装|更新|保存|同意|授权|支付|赞助|同步)/;

const SAFE = /(刷新|重试|详情|查看|展开|收起|更多|上一页|下一页|标签|切换|取消|关闭|返回|折叠|确定|帮助|说明|复制)/;

/** 外链 / 锚点：点了会把 WebView 带走或开系统浏览器，对功能自测无价值且破坏后续遍历 */
const SKIP_HREF = /^(https?:|mailto:|tel:|javascript:|#)/i;

const BUDGET_SAFE = 12;
const BUDGET_FULL = 60;
/**
 * 单次动作后的最长等待。**不能设大**：仪表盘有每秒刷新的实时图表/CPU 曲线，DOM 几乎一直在变，
 * MutationObserver 的"静默"判定永远达不到，于是每个动作都会等满这个上限。
 * 真机实测设 5200ms 时 120 个动作 × 12 页要跑数小时（后台看不到进度、报告迟迟不落盘）。
 * 2200ms 下总时长约 20 分钟，且对"点击是否生效"的判定依然够用。
 */
const SETTLE_MAX_MS = 2200;
const QUIET_MS = 250;

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

function textOf(el: Element): string {
  return (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
}

function isVisible(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 1 && r.height > 1;
}

function findByText(root: ParentNode, text: string): HTMLElement | null {
  const cands = Array.from(
    root.querySelectorAll<HTMLElement>('button, [role="button"], a, [class*="cursor-pointer"]'),
  );
  for (const el of cands) {
    const t = textOf(el);
    if (t === text || t.startsWith(text)) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return el;
    }
  }
  return null;
}

/** 内容区：优先 <main>；退路只在**非侧栏**的可滚动容器里挑面积最大的，避免误把左侧导航当内容区 */
function mainArea(): HTMLElement {
  const m = document.querySelector<HTMLElement>("main");
  if (m) return m;
  const cands = Array.from(
    document.querySelectorAll<HTMLElement>('[class*="overflow-y-auto"], [class*="overflow-auto"]'),
  ).filter((el) => !el.closest("aside, nav"));
  let best: HTMLElement | null = null;
  let bestArea = 0;
  for (const el of cands) {
    const r = el.getBoundingClientRect();
    const a = r.width * r.height;
    if (a > bestArea) {
      bestArea = a;
      best = el;
    }
  }
  return best || document.body;
}

/**
 * 找左侧导航项。必须在 aside/nav 内找 —— 「连接」「日志」「设置」这类词在正文里到处都是，
 * 直接在 document 里找会点到别的东西，把整轮自测带偏。
 */
function findNavItem(label: string): HTMLElement | null {
  const scope =
    document.querySelector("aside") || document.querySelector("nav") || document.body;
  return findByText(scope, label) || findByText(document, label);
}

function visibleDialog(): HTMLElement | null {
  const cands = Array.from(
    document.querySelectorAll<HTMLElement>(
      '[role="dialog"], [role="alertdialog"], [class*="fixed inset-0"], [class*="z-[5"], [class*="z-50"]',
    ),
  );
  for (const el of cands) {
    if (isVisible(el)) return el;
  }
  return null;
}

async function waitStable(minMs = 500, quietMs = QUIET_MS, maxMs = SETTLE_MAX_MS): Promise<void> {
  const t0 = performance.now();
  await sleep(minMs);
  await new Promise<void>((resolve) => {
    let timer: number | undefined;
    const obs = new MutationObserver(() => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(done, quietMs);
    });
    const done = () => {
      obs.disconnect();
      if (timer) window.clearTimeout(timer);
      resolve();
    };
    obs.observe(document.body, { childList: true, subtree: true, attributes: true });
    timer = window.setTimeout(done, quietMs);
    window.setTimeout(() => {
      if (performance.now() - t0 > maxMs) done();
    }, maxMs);
  });
}

/**
 * 自测期间的安全阀。两条都是会**让自测当场死掉**的硬伤，不是洁癖：
 *  1. 前端有两处原生 `confirm()`（删对话、清痕迹）—— WebView2 里原生 confirm 是同步阻塞的，
 *     一弹出来 JS 就停在那，整轮自测永远跑不完，且外部无法点它。
 *  2. `window.open` 会开新窗口/系统浏览器，把测试界面顶掉。
 */
function installGuards() {
  const orig = {
    confirm: window.confirm,
    alert: window.alert,
    prompt: window.prompt,
    open: window.open,
  };
  window.confirm = () => true; // 自测模式下"确认"一切（VM 可回滚）
  window.alert = () => undefined;
  window.prompt = (() => "selftest") as typeof window.prompt;
  window.open = (() => null) as typeof window.open;
  return {
    restore() {
      window.confirm = orig.confirm;
      window.alert = orig.alert;
      window.prompt = orig.prompt;
      window.open = orig.open;
    },
  };
}

function installErrorHooks() {
  const errors: string[] = [];
  const origError = console.error;
  const origWarn = console.warn;
  console.error = (...args: unknown[]) => {
    errors.push("console.error: " + args.map((a) => String(a)).join(" ").slice(0, 300));
    origError.apply(console, args as unknown[]);
  };
  console.warn = (...args: unknown[]) => {
    const s = args.map((a) => String(a)).join(" ");
    if (/error|failed|失败|异常/i.test(s)) errors.push("console.warn: " + s.slice(0, 300));
    origWarn.apply(console, args as unknown[]);
  };
  const onErr = (e: ErrorEvent) => errors.push("window.onerror: " + String(e.message).slice(0, 300));
  const onRej = (e: PromiseRejectionEvent) =>
    errors.push("unhandledrejection: " + String(e.reason).slice(0, 300));
  window.addEventListener("error", onErr);
  window.addEventListener("unhandledrejection", onRej);
  return {
    errors,
    restore() {
      console.error = origError;
      console.warn = origWarn;
      window.removeEventListener("error", onErr);
      window.removeEventListener("unhandledrejection", onRej);
    },
  };
}

/** 元素指纹：优先用 collectClickables 打的编号（能区分列表里重复出现的同名按钮） */
function sigOf(el: HTMLElement): string {
  const k = el.getAttribute("data-st-key");
  if (k) return k;
  return el.tagName.toLowerCase() + "|" + textOf(el) + "|" + String(el.className || "").slice(0, 40);
}

function isFileTrigger(el: HTMLElement): boolean {
  if (el instanceof HTMLInputElement && el.type === "file") return true;
  const label = el.closest("label");
  if (label && label.querySelector("input[type='file']")) return true;
  return false;
}

function isExternalLink(el: HTMLElement): boolean {
  if (!(el instanceof HTMLAnchorElement)) return false;
  return SKIP_HREF.test(el.getAttribute("href") || "");
}

/**
 * 收集可点元素。
 * 排除三类「点了会让自测自己死掉」的东西：文件选择（弹系统框，JS 关不掉）、外链锚点、
 * 以及包着 file input 的 label。它们会被记进 skipped，报告里能看到「为什么没测」。
 */
function collectClickables(
  scope: HTMLElement,
  mode: SelfTestMode,
  skippedOut: string[] = [],
): HTMLElement[] {
  const sel = [
    "button",
    "[role='button']",
    "[role='tab']",
    "[role='switch']",
    "a[href]",
    "select",
    "input[type='checkbox']",
    "input[type='radio']",
  ].join(",");
  const out: HTMLElement[] = [];
  for (const el of Array.from(scope.querySelectorAll<HTMLElement>(sel))) {
    if (el.hasAttribute("disabled")) continue;
    if (el.getAttribute("aria-disabled") === "true") continue;
    if (!isVisible(el)) continue;
    if (isFileTrigger(el)) {
      skippedOut.push("(文件选择) " + (textOf(el) || el.getAttribute("type") || "input"));
      continue;
    }
    if (isExternalLink(el)) {
      skippedOut.push("(外链) " + (textOf(el) || el.getAttribute("href") || "a"));
      continue;
    }
    out.push(el);
  }
  if (mode === "full") {
    for (const el of Array.from(scope.querySelectorAll<HTMLElement>('[class*="cursor-pointer"]'))) {
      if (!isVisible(el)) continue;
      if (el.querySelector("button, a, [role='button'], select, input")) continue;
      if (!textOf(el)) continue;
      if (isFileTrigger(el)) continue;
      out.push(el);
    }
  }
  // 编号：同 tag+同文本按出现次序编号，否则列表里 10 个「删除」只会点到第一个
  const seen = new Map<string, number>();
  for (const el of out) {
    const base = el.tagName.toLowerCase() + "|" + textOf(el);
    const n = seen.get(base) || 0;
    seen.set(base, n + 1);
    el.setAttribute("data-st-key", base + "#" + n);
  }
  return out;
}

function appAlive(): boolean {
  const root = document.getElementById("root");
  return !!root && root.childElementCount > 0;
}

async function fillEmptyInputs(scope: HTMLElement): Promise<number> {
  let n = 0;
  const fields = Array.from(
    scope.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"),
  );
  for (const f of fields) {
    const type = (f.getAttribute("type") || "text").toLowerCase();
    if (["checkbox", "radio", "file", "submit", "button", "image", "range", "color"].includes(type)) continue;
    if (!isVisible(f) || f.disabled || f.readOnly) continue;
    if (f.value && f.value.length > 0) continue;
    try {
      const proto = f instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(proto.prototype, "value")?.set;
      setter?.call(f, "selftest");
      f.dispatchEvent(new Event("input", { bubbles: true }));
      f.dispatchEvent(new Event("change", { bubbles: true }));
      n++;
    } catch {
      /* 单字段失败忽略 */
    }
  }
  return n;
}

interface PageCtx {
  step: SelfTestStep;
  errors: string[];
  clicked: Set<string>;
  mode: SelfTestMode;
}

async function performAction(el: HTMLElement, ctx: PageCtx, scope: "page" | "dialog"): Promise<void> {
  const label = textOf(el);
  const kind = el.tagName === "SELECT" ? "select" : el.getAttribute("type") || el.tagName.toLowerCase();
  const errBefore = ctx.errors.length;
  const act: SelfAction = { label, kind, scope };

  try {
    if (el instanceof HTMLSelectElement) {
      const n = Math.min(el.options.length, 5);
      for (let i = 0; i < n; i++) {
        el.selectedIndex = i;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(320);
      }
      act.note = `遍历 ${n} 个选项`;
    } else {
      el.click();
      await waitStable();
    }
  } catch (e) {
    act.note = "点击抛错: " + String(e).slice(0, 140);
    ctx.step.errors.push(`点击「${label}」抛错: ${String(e).slice(0, 200)}`);
  }

  if (!appAlive()) {
    act.note = (act.note ? act.note + "；" : "") + "应用根节点被清空（前端崩溃）";
    ctx.step.suspicious.push(`动作「${label}」后应用根节点为空 —— 疑似前端崩溃`);
  }
  if (ctx.errors.length > errBefore) {
    const fresh = ctx.errors.slice(errBefore).slice(0, 2).join(" / ");
    act.note = (act.note ? act.note + "；" : "") + "产生错误: " + fresh.slice(0, 160);
  }
  ctx.step.actions.push(act);
}

/** 处理弹窗。返回值 = 是否「值得再来一轮」——没做成任何动作就必须返回 false，否则死循环空转。 */
async function drainDialog(ctx: PageCtx): Promise<boolean> {
  const dlg = visibleDialog();
  if (!dlg) return false;
  const cands = collectClickables(dlg, ctx.mode, ctx.step.skipped);
  let acted = false;
  for (const el of cands) {
    const s = "D|" + sigOf(el);
    if (ctx.clicked.has(s)) continue;
    const t = textOf(el);
    if (!t) {
      ctx.clicked.add(s);
      continue;
    }
    if (NEVER.test(t)) {
      ctx.step.skipped.push("[弹窗] " + t);
      ctx.clicked.add(s);
      continue;
    }
    if (ctx.mode === "safe" && (!SAFE.test(t) || DANGER.test(t))) {
      if (DANGER.test(t)) ctx.step.skipped.push("[弹窗] " + t);
      ctx.clicked.add(s);
      continue;
    }
    ctx.clicked.add(s);
    await performAction(el, ctx, "dialog");
    acted = true;
    if (!visibleDialog()) return false; // 弹窗已关，回到页面
  }
  return acted && !!visibleDialog();
}

async function testOnePage(
  key: string,
  label: string,
  mode: SelfTestMode,
  sink: string[],
): Promise<SelfTestStep> {
  const t0 = performance.now();
  const before = sink.length;
  const step: SelfTestStep = {
    page: key,
    label,
    ok: true,
    ms: 0,
    clickables: 0,
    actions: [],
    skipped: [],
    errors: [],
    suspicious: [],
  };
  const ctx: PageCtx = { step, errors: sink, clicked: new Set<string>(), mode };

  const nav = findNavItem(label);
  if (!nav) {
    step.ok = false;
    step.errors.push(`找不到导航项「${label}」`);
    step.ms = Math.round(performance.now() - t0);
    return step;
  }
  const areaBefore = mainArea();
  const beforeTxt = (areaBefore.innerText || "").trim();
  nav.click();
  await waitStable(1300);
  const areaAfter = mainArea();
  const afterTxt = (areaAfter.innerText || "").trim();
  if (beforeTxt.length > 50 && beforeTxt === afterTxt) {
    // ★ 必须自解释。上一轮有 9 个页面报这条，当时只能靠"各页点到的控件是否符合该页"
    //   （自动化→创建/定时、工具→MCP 配置、设置→保存更改…）才反推出是**误报**：
    //   容器解析到的元素（<main> 缺失时的兜底候选）其文本前缀跨页稳定，于是永远"没变化"。
    //   把容器与文本开头一并写进报告，下次一眼可判，不必再反推。
    const cls = String((areaAfter as HTMLElement).className || "");
    const tag = `${areaAfter.tagName.toLowerCase()}${cls ? "." + cls.split(/\s+/).slice(0, 2).join(".") : ""}`;
    step.suspicious.push(
      `点击导航后内容区文本未变化（容器=${tag}，文本长度=${afterTxt.length}，` +
        `开头=「${afterTxt.slice(0, 80).replace(/\s+/g, " ")}」）`,
    );
  }

  const area = mainArea();
  const content = (area.innerText || "").trim();
  const hasVisual = !!area.querySelector("canvas, img, svg, table, input, textarea");
  if (content.length < 20 && !hasVisual) {
    step.ok = false;
    step.suspicious.push(`页面内容近乎空白（${content.length} 字，且无 canvas/img/table/input）`);
  }
  if (/加载失败|出错了|Something went wrong|Error boundary|组件渲染异常/i.test(content)) {
    step.ok = false;
    step.suspicious.push("页面正文出现错误提示文案");
  }

  if (mode === "full") {
    const filled = await fillEmptyInputs(area);
    if (filled) await waitStable(400, 300, 1500);
  }

  const budget = mode === "full" ? BUDGET_FULL : BUDGET_SAFE;
  let guard = 0;
  while (guard++ < budget) {
    if (await drainDialog(ctx)) continue;

    const scope = mainArea();
    const cands = collectClickables(scope, mode, step.skipped);
    step.clickables = Math.max(step.clickables, cands.length);

    let target: HTMLElement | null = null;
    for (const el of cands) {
      const s = sigOf(el);
      if (ctx.clicked.has(s)) continue;
      const t = textOf(el);
      if (!t && el.tagName !== "SELECT") {
        ctx.clicked.add(s);
        continue;
      }
      if (NEVER.test(t)) {
        step.skipped.push(t);
        ctx.clicked.add(s);
        continue;
      }
      if (mode === "safe" && (!SAFE.test(t) || DANGER.test(t))) {
        if (DANGER.test(t)) step.skipped.push(t);
        ctx.clicked.add(s);
        continue;
      }
      ctx.clicked.add(s);
      target = el;
      break;
    }
    if (!target) break;
    await performAction(target, ctx, "page");
  }

  if (!appAlive()) {
    step.ok = false;
    step.suspicious.push("本页结束时应用根节点为空");
  }
  // 同一页可能重复登记跳过项（每轮都收集一次），去重后更可读
  step.skipped = Array.from(new Set(step.skipped));
  step.errors.push(...sink.slice(before));
  step.ok = step.ok && step.errors.length === 0;
  step.ms = Math.round(performance.now() - t0);
  return step;
}

async function postReport(rep: SelfTestReport): Promise<void> {
  try {
    // 必须用 API_BASE 拼绝对地址：生产构建里页面 origin 是 http://tauri.localhost，
    // 裸相对路径会打到那里而不是后端的 127.0.0.1:9845，且失败是静默的（真机踩过）。
    await fetch(`${API_BASE}/api/self_test_report`, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rep),
    });
  } catch (e) {
    console.warn("[SELFTEST] 上报失败:", String(e).slice(0, 200));
  }
}

export async function runSelfTest(
  pages = NAV_LABELS,
  mode: SelfTestMode = "safe",
): Promise<SelfTestReport> {
  const started = new Date();
  const guards = installGuards();
  const hooks = installErrorHooks();
  const steps: SelfTestStep[] = [];
  const rep: SelfTestReport = {
    startedAt: started.toISOString(),
    finishedAt: "",
    version: (window as unknown as { __NAIXI_VERSION__?: string }).__NAIXI_VERSION__ || "unknown",
    mode,
    done: false,
    steps,
    totalErrors: 0,
    failedPages: [],
  };
  console.log(`[SELFTEST] 开始（模式=${mode}，共 ${pages.length} 页）`);
  try {
    for (const p of pages) {
      let step: SelfTestStep;
      try {
        step = await testOnePage(p.key, p.label, mode, hooks.errors);
      } catch (e) {
        step = {
          page: p.key,
          label: p.label,
          ok: false,
          ms: 0,
          clickables: 0,
          actions: [],
          skipped: [],
          errors: [`页面级异常: ${String(e).slice(0, 300)}`],
          suspicious: [],
        };
      }
      steps.push(step);
      rep.totalErrors = steps.reduce((n, s) => n + s.errors.length, 0);
      rep.failedPages = steps.filter((s) => !s.ok).map((s) => s.page);
      await postReport(rep); // 增量上报：后面崩了也不丢已跑部分
      showBanner(
        `进度 ${steps.length}/${pages.length}（${p.label}：动作 ${step.actions.length}，错误 ${step.errors.length}）` +
          (step.errors[0] ? `\n首个错误：${step.errors[0].slice(0, 180)}` : ""),
        step.errors.length > 0,
      );
      console.log(
        `[SELFTEST] ${p.label}：动作 ${step.actions.length} 次，错误 ${step.errors.length}，可疑 ${step.suspicious.length}`,
      );
      await sleep(300);
    }
  } finally {
    guards.restore();
    hooks.restore();
  }
  rep.finishedAt = new Date().toISOString();
  rep.done = true;
  rep.totalErrors = steps.reduce((n, s) => n + s.errors.length, 0);
  rep.failedPages = steps.filter((s) => !s.ok).map((s) => s.page);
  return rep;
}

/**
 * 诊断横幅：自测的失败过去只进 console.warn，在无人值守的环境里等于不存在
 * （真机排查时就是这么卡住的）。这里在页面顶部插一条可见的横幅，抓屏即可读到原因。
 */
function showBanner(text: string, bad = false): void {
  try {
    const id = "naixi-selftest-banner";
    let d = document.getElementById(id);
    if (!d) {
      d = document.createElement("div");
      d.id = id;
      document.body.appendChild(d);
    }
    d.style.cssText =
      "position:fixed;left:0;right:0;top:0;z-index:2147483647;padding:6px 10px;" +
      "font:13px/1.5 Consolas,monospace;white-space:pre-wrap;word-break:break-all;" +
      (bad ? "background:#b00020;color:#fff;" : "background:#0b6;color:#fff;");
    d.textContent = "[SELFTEST] " + text;
  } catch {
    /* 忽略 */
  }
}

/** 由后端开关决定是否跑；跑完（或每页）把报告 POST 回后端落盘 */
export async function maybeRunSelfTest(): Promise<void> {
  try {
    // 同 postReport：Tauri 生产环境下必须用绝对基址（相对路径会打到 tauri.localhost）
    const url = `${API_BASE}/api/self_test_request`;
    let r: Response;
    try {
      r = await fetch(url, { mode: "cors" });
    } catch (e) {
      showBanner(`取开关失败 url=${url} origin=${location.origin} err=${String(e)}`, true);
      throw e;
    }
    if (!r.ok) {
      showBanner(`开关返回 ${r.status}（url=${url}）`, true);
      return;
    }
    showBanner(`已取到开关，开始全量自测（url=${url}）`);
    const j = (await r.json()) as { run?: boolean; mode?: SelfTestMode };
    if (!j.run) return;
    const mode: SelfTestMode = j.mode === "full" ? "full" : "safe";
    console.log(`[SELFTEST] 收到自测指令（模式=${mode}），开始遍历全部页面`);
    const report = await runSelfTest(NAV_LABELS, mode);
    await postReport(report);
    showBanner(
      `完成：${report.steps.length} 页，失败 ${report.failedPages.length} 页，错误 ${report.totalErrors} 条`,
      report.failedPages.length > 0,
    );
    console.log(
      `[SELFTEST] 完成：${report.steps.length} 页，失败 ${report.failedPages.length} 页，错误 ${report.totalErrors} 条`,
    );
  } catch (e) {
    showBanner(`自测执行失败: ${String(e)}`, true);
    console.warn("[SELFTEST] 自测执行失败:", String(e).slice(0, 200));
  }
}
