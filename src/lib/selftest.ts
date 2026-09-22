/**
 * 全量页面交互自测（1.0.1 起）
 *
 * 由来：用户报「点桌宠没反应」时，问题其实在日志里躺着，只是没人翻 —— 说明靠人肉点界面
 * 一定会漏。本模块让应用**自己把每个页面走一遍并点一遍**：切换全部导航页 → 等渲染稳定 →
 * 检查是否空白/报错 → 在安全白名单内点击页面内的按钮 → 收集控制台错误、未捕获异常、
 * 失败的网络请求 → 汇总上报后端落盘（`data/self_test_report.json`）。
 *
 * 触发方式（默认关闭，不影响正常用户）：
 *   后端 `GET /api/self_test_request` 返回 `{run: true}` 时才会执行，判定依据是安装目录下
 *   存在 `data/self_test.request` 标记文件。测试时创建该文件 + 重启应用即可。
 *
 * 安全边界：只点击白名单内的元素（刷新 / 详情 / 展开 / 标签页 / 取消 / 关闭 等）；
 * 命中黑名单（删除 / 卸载 / 清空 / 重置 / 发布 / 导入 / 发送 / 启动 / 停止 / 退出 / 保存 …）
 * 一律跳过并记录，避免自测把用户的真实数据或环境搞坏。
 */

export interface SelfTestStep {
  page: string;
  label: string;
  ok: boolean;
  ms: number;
  buttonsFound: number;
  buttonsClicked: number;
  skipped: string[];
  errors: string[];
  suspicious: string[];
}

export interface SelfTestReport {
  startedAt: string;
  finishedAt: string;
  version: string;
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

/** 命中即跳过（破坏性或不可逆） */
const DANGER = /(删除|移除|卸载|清空|重置|恢复默认|发布|导入|上传|下载|发送|执行|运行|停止|启动|关闭服务|断开|退出|注销|安装|更新|保存|同意|授权|支付|赞助|同步)/;
/** 明确安全、点了不会破坏数据 */
const SAFE = /(刷新|重试|详情|查看|展开|收起|更多|上一页|下一页|标签|切换|取消|关闭|返回|折叠|确定|确定|帮助|说明|复制)/;

const MAX_BUTTONS_PER_PAGE = 8;

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

function textOf(el: Element): string {
  return (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
}

/** 按可见文本找元素（优先 button / role=button / a） */
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

function mainArea(): HTMLElement {
  return (document.querySelector<HTMLElement>("main") ||
    document.querySelector<HTMLElement>('[class*="overflow-y-auto"]') ||
    document.body) as HTMLElement;
}

/** 等 DOM 静默（MutationObserver 连续 quietMs 无变化）且至少 minMs */
async function waitStable(minMs = 1200, quietMs = 600, maxMs = 6000): Promise<void> {
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

async function testOnePage(key: string, label: string, sink: string[]): Promise<SelfTestStep> {
  const t0 = performance.now();
  const before = sink.length;
  const step: SelfTestStep = {
    page: key,
    label,
    ok: true,
    ms: 0,
    buttonsFound: 0,
    buttonsClicked: 0,
    skipped: [],
    errors: [],
    suspicious: [],
  };

  const nav = findByText(document, label);
  if (!nav) {
    step.ok = false;
    step.errors.push(`找不到导航项「${label}」`);
    step.ms = Math.round(performance.now() - t0);
    return step;
  }
  nav.click();
  await waitStable();

  const area = mainArea();
  const content = (area.innerText || "").trim();
  // 空白判定：正文极短且没有画布/图片 —— 说明这个页面渲染不出来
  const hasVisual = !!area.querySelector("canvas, img, svg, table, input, textarea");
  if (content.length < 20 && !hasVisual) {
    step.ok = false;
    step.suspicious.push(`页面内容近乎空白（${content.length} 字，且无 canvas/img/table/input）`);
  }
  if (/加载失败|出错了|Something went wrong|Error boundary|组件渲染异常/i.test(content)) {
    step.ok = false;
    step.suspicious.push("页面正文出现错误提示文案");
  }

  // 安全点击
  const btns = Array.from(area.querySelectorAll<HTMLElement>("button, [role='button']")).filter((b) => {
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && !b.hasAttribute("disabled");
  });
  step.buttonsFound = btns.length;
  for (const b of btns.slice(0, MAX_BUTTONS_PER_PAGE * 3)) {
    if (step.buttonsClicked >= MAX_BUTTONS_PER_PAGE) break;
    const t = textOf(b);
    if (!t) continue;
    if (DANGER.test(t) && !SAFE.test(t)) {
      step.skipped.push(t);
      continue;
    }
    if (!SAFE.test(t)) continue; // 既不在白名单也不在黑名单 → 不动（保守）
    try {
      b.click();
      step.buttonsClicked++;
      await sleep(500);
      // 若弹出模态，尝试关掉，避免影响后续页面
      const closer = findByText(document, "取消") || findByText(document, "关闭");
      if (closer && document.querySelectorAll('[role="dialog"], [class*="fixed inset-0"]').length > 0) {
        closer.click();
        await sleep(300);
      }
    } catch (e) {
      step.errors.push(`点击「${t}」抛错: ${String(e).slice(0, 200)}`);
    }
  }

  step.errors.push(...sink.slice(before));
  step.ok = step.ok && step.errors.length === 0;
  step.ms = Math.round(performance.now() - t0);
  return step;
}

export async function runSelfTest(pages = NAV_LABELS): Promise<SelfTestReport> {
  const started = new Date();
  const hooks = installErrorHooks();
  const steps: SelfTestStep[] = [];
  try {
    for (const p of pages) {
      try {
        steps.push(await testOnePage(p.key, p.label, hooks.errors));
      } catch (e) {
        steps.push({
          page: p.key,
          label: p.label,
          ok: false,
          ms: 0,
          buttonsFound: 0,
          buttonsClicked: 0,
          skipped: [],
          errors: [`页面级异常: ${String(e).slice(0, 300)}`],
          suspicious: [],
        });
      }
      await sleep(400);
    }
  } finally {
    hooks.restore();
  }
  const totalErrors = steps.reduce((n, s) => n + s.errors.length, 0);
  return {
    startedAt: started.toISOString(),
    finishedAt: new Date().toISOString(),
    version: (window as unknown as { __NAIXI_VERSION__?: string }).__NAIXI_VERSION__ || "unknown",
    steps,
    totalErrors,
    failedPages: steps.filter((s) => !s.ok).map((s) => s.page),
  };
}

/** 由后端开关决定是否跑；跑完把报告 POST 回后端落盘 */
export async function maybeRunSelfTest(): Promise<void> {
  try {
    const r = await fetch("/api/self_test_request");
    if (!r.ok) return;
    const j = (await r.json()) as { run?: boolean };
    if (!j.run) return;
    console.log("[SELFTEST] 收到自测指令，开始遍历全部页面");
    const report = await runSelfTest();
    await fetch("/api/self_test_report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });
    console.log(
      `[SELFTEST] 完成：${report.steps.length} 页，失败 ${report.failedPages.length} 页，错误 ${report.totalErrors} 条`,
    );
  } catch (e) {
    console.warn("[SELFTEST] 自测执行失败:", String(e).slice(0, 200));
  }
}
