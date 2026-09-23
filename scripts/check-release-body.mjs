#!/usr/bin/env node
// 发布正文格式校验：按 .github/RELEASE_TEMPLATE.md 的「排版纪律」逐条机器检查。
//
// 为什么需要它（2026-09-23）：v1.0.0 的正文是照模板写的，v1.0.1 却是临时手写 ——
// 首行冒出 H1（与 Release 标题重复）、章节用 `## 本版修掉的问题`、条目降到 `###`，
// 于是在 Release 列表页一眼就能看出格式漂移。模板里那句「禁止在发布脚本里临时手写拼字符串
// 且无对照」说的就是这件事，现在把它变成可执行的门禁。
//
// 用法：
//   node scripts/check-release-body.mjs <body.md>
//   node scripts/check-release-body.mjs --self-test   # 用内置样例自检校验器本身

import fs from 'node:fs';

const RULES = '见 .github/RELEASE_TEMPLATE.md「排版纪律」';
const SECTIONS = ['## 变更内容', '## 验证', '## 下载', '## 升级说明'];
const GROUPS = ['### 新增', '### 修复', '### 其他'];

function check(text) {
  const errs = [];
  const warns = [];
  const lines = text.split(/\r?\n/);

  // 去代码围栏后再做结构判断（围栏内的 # 不是标题）
  let inFence = false;
  const outside = [];
  for (const ln of lines) {
    if (/^\s*```/.test(ln)) {
      inFence = !inFence;
      continue;
    }
    if (!inFence) outside.push(ln);
  }
  if (inFence) errs.push('代码围栏 ``` 未闭合（成对出现）');

  // 1) 禁止 H1；正文第一标题应为 H2
  const h1 = outside.filter((l) => /^#\s+\S/.test(l));
  if (h1.length) errs.push(`禁止 H1，发现 ${h1.length} 处：${h1.map((l) => l.slice(0, 40)).join(' / ')}`);
  const heads = outside.filter((l) => /^#{1,6}\s/.test(l));
  if (heads.length && /^###/.test(heads[0])) {
    errs.push('第一个标题就用了 H3：章节标题应统一 H2（`## …`）');
  }

  // 2) 首行必须是引用块（开头引用块 = 一句话说明来源 / 测试背景）
  const firstLine = (lines.find((l) => l.trim() !== '') || '').trim();
  if (!firstLine.startsWith('>')) errs.push(`正文首行必须是 "> " 引用块，实际是「${firstLine.slice(0, 40)}」`);
  if (/^#\s/.test(firstLine)) errs.push('正文首行是 H1（与 Release 标题重复）');

  // 3) 五个 `##` 段落齐全且顺序不可调换
  const h2 = outside.filter((l) => /^##\s+\S/.test(l)).map((l) => l.trim());
  let cursor = -1;
  for (const want of SECTIONS) {
    const at = h2.indexOf(want);
    if (at < 0) {
      errs.push(`缺少章节 ${want}`);
      continue;
    }
    if (at < cursor) errs.push(`章节顺序错误：${want} 应在上一段之后（顺序固定为 ${SECTIONS.join(' → ')}）`);
    cursor = at;
  }
  const extra = h2.filter((l) => !SECTIONS.includes(l));
  if (extra.length) warns.push(`出现模板外的 H2 章节（模板固定五段）：${extra.join(' / ')}`);

  // 4) 变更内容下必须用 ### 新增 / ### 修复 / ### 其他 分类
  const h3 = outside.filter((l) => /^###\s+\S/.test(l)).map((l) => l.trim());
  const groups = h3.filter((l) => GROUPS.includes(l));
  if (h2.includes('## 变更内容') && !groups.length) {
    errs.push(`## 变更内容 下必须按 ${GROUPS.join(' / ')} 分类（当前 H3：${h3.slice(0, 3).join(' / ') || '无'}）`);
  }

  // 5) 条目写法：#### N. 标题（P1/P2/QA）
  const items = outside.filter((l) => /^####\s/.test(l));
  if (h2.includes('## 变更内容') && !items.length) errs.push('变更内容里没有任何 `#### N. 标题（P1）` 形式的条目');
  for (const it of items) {
    if (!/^####\s+\d+\.\s+\S/.test(it)) errs.push(`条目标题缺少序号：${it.slice(0, 40)}`);
    if (!/（(P1|P2|QA|P1\/P2|P2\/QA)）\s*$/.test(it.trim())) {
      warns.push(`条目末尾建议带优先级文本标签（P1/P2/QA）：${it.slice(0, 40)}`);
    }
  }

  // 6) 标题里禁止 emoji / 图标
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{2B00}-\u{2BFF}]/u;
  for (const l of heads) {
    if (emoji.test(l)) errs.push(`章节标题含 emoji：${l.slice(0, 40)}`);
  }

  // 7) 下载段要能落到实际资产名与体积
  if (h2.includes('## 下载')) {
    if (!/naixi-desktop_\d+\.\d+\.\d+_x64-setup\.exe/.test(text)) errs.push('## 下载 段未写出安装包实际资产名');
    if (!/SHA256SUMS\.txt/.test(text)) warns.push('## 下载 段未提及 SHA256SUMS.txt');
  }

  return { errs, warns };
}

function selfTest() {
  const good = `> 本版本由真机测试产出。

## 变更内容

### 修复

#### 1. 某问题（P1）
- 修复前：慢。
- 修复后：快。

## 验证

- 12/12 PASS

## 下载

| 资产 | 体积 |
|---|---|
| \`naixi-desktop_1.0.1_x64-setup.exe\` | 1 B |

见 \`SHA256SUMS.txt\`。

## 升级说明

- 覆盖安装即可。
`;
  const bad = `# 奶昔 · 桌面智能体 v1.0.1 — 稳定性修复

## 本版修掉的问题

### 1. 某问题
- 修复后：快。

## 校验下载与安装

\`\`\`
x
`;
  const g = check(good);
  const b = check(bad);
  console.log('自检：合规样例应无 error ->', g.errs.length === 0 ? 'PASS' : 'FAIL ' + JSON.stringify(g.errs));
  console.log('自检：违规样例应报错 ->', b.errs.length >= 3 ? 'PASS' : 'FAIL（只报出 ' + b.errs.length + ' 条）');
  for (const e of b.errs) console.log('   - ' + e);
  return g.errs.length === 0 && b.errs.length >= 3 ? 0 : 1;
}

const arg = process.argv[2];
if (!arg) {
  console.error('用法: node scripts/check-release-body.mjs <body.md> | --self-test');
  process.exit(2);
}
if (arg === '--self-test') process.exit(selfTest());

const text = fs.readFileSync(arg, 'utf8');
const { errs, warns } = check(text);
console.log(`[check-release-body] ${arg}  （${text.length} 字符）`);
for (const w of warns) console.log('  [warn] ' + w);
for (const e of errs) console.log('  [err ] ' + e);
if (errs.length) {
  console.log(`\n未通过：${errs.length} 项违规。规则 ${RULES}`);
  process.exit(1);
}
console.log(warns.length ? '\n通过（有警告，建议一并处理）。' : '\n通过：正文符合发布规范。');
