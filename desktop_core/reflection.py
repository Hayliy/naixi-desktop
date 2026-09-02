# -*- coding: utf-8 -*-
"""reflection.py — Agent 的「元认知」子系统（看不见的问题）
================================================================

把用户问的几类「看不见的问题」对应到业界现成轮子，并做**离线化适配**
（不依赖 LLM / 不连网 / 许可干净，全部 MIT 思路可借鉴）：

  看不见的问题                  现成轮子（已查 GitHub，许可证干净）        本模块对应
  ──────────────────────────  ────────────────────────────────────  ──────────────
  正确/错误步骤的反馈          Reflexion (NeurIPS'23, MIT 实现)         Reflector.evaluate / feedback_recent
                               Actor→Evaluator→Self-Reflection→Memory
  错误分类                      Reflexion Error Categorization          feedback_recent 的 error_category
  局部最优 vs 全局最优冲突      Tree of Thoughts (MIT) /                Curriculum + Reflector.detect_local_optimum
                               LATS (MCTS+Reflexion, ICML'24)           （UCT 思想简化为阶段价值守卫）
  发现问题与处理问题            Voyager 迭代提示+自校验 (MIT)            Reflector.discover_problems → 恢复动作
                               Reflexion 失败重试
  成功/失败经验教训与复盘       ExpeL (AAAI'24) 经验池+洞察抽取         ExperienceMemory（经验池+相似召回+复盘）
                               + 相似召回；Generative Agents 反思

设计取舍：原论文用 LLM 生成「自然语言反思」与「价值评估」。本模块在单机/离线/
无 API 约束下，把同样的**闭环结构**用确定性启发式实现：
  - 反馈 = 用独立第二证据（帧差/感知 diff）判定步骤成败，不认动作自报
  - 反思文本 = 结构化模板拼接（可喂给奶昔吐槽，也可落盘复盘）
  - 经验召回 = 情境签名 token 重叠（零正则，纯集合运算）

红线：零正则、不写 C 盘（落盘走 data/ 经 __file__ 推导）、无 AGPL 依赖。
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("reflection")


# ── 路径推导（不写死 C 盘）──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
DATA_DIR = os.environ.get("NAIXI_REFLECTION_DATA") or os.path.join(_PROJECT_ROOT, "data")
EXP_FILE = os.path.join(DATA_DIR, "mindustry_experience.json")


# ───────────────────────── 步骤记录（反馈的最小单元） ─────────────────────────
@dataclass
class StepRecord:
    """单步记录：决策 + 执行前后独立证据 + 成败标签。

    成败不靠动作模块自报——由 Reflector 用 pre/post 的「独立第二证据」
    （帧差、感知实体 diff）判定，满足「禁止循环验证」铁则。
    """
    step: int = 0
    phase: str = ""
    situation: str = ""        # 情境签名，如 "mining@core" / "defense@wave"
    action_kind: str = ""      # place_drill / place_conveyor / place_turret / wait ...
    decision: dict = field(default_factory=dict)
    pre_motion: float = 0.0
    post_motion: float = 0.0
    pre_entities: dict = field(default_factory=dict)   # name -> count
    post_entities: dict = field(default_factory=dict)
    expected_delta: str = ""   # 期望发生的世界变化（由策略声明）
    observed_delta: str = ""   # 实际观测到的变化（自动计算）
    outcome: str = "unknown"   # success / partial / fail
    error_category: str = ""   # none / no_change / wrong_target / blocked / timeout
    ts: float = 0.0

    def to_dict(self):
        return asdict(self)


# ───────────────────────── 经验记忆（ExpeL 经验池 + 相似召回） ─────────────────────────
class ExperienceMemory:
    """经验池：持久化步骤记录 + 洞察（lessons learned）。

    借鉴 ExpeL：
      - 经验池（experience pool）：存成功/失败轨迹
      - 洞察抽取（insight extraction）：把失败归纳成可复用教训
      - 相似召回（experience recall）：按情境相似度取历史经验辅助决策
    本实现用「情境签名 token 重叠」做相似度（零正则，纯集合运算）。
    """

    def __init__(self, path: str = EXP_FILE, max_steps: int = 2000):
        self.path = path
        self.max_steps = max_steps
        self._steps: List[dict] = []
        self._insights: List[dict] = []
        self._load()

    # ── 持久化 ──
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._steps = d.get("steps", [])
            self._insights = d.get("insights", [])
        except Exception as e:
            log.warning(f"[reflection] 经验库加载失败: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"steps": self._steps, "insights": self._insights},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"[reflection] 经验库保存失败: {e}")

    # ── 写入 ──
    def record_step(self, rec: StepRecord):
        self._steps.append(rec.to_dict())
        if len(self._steps) > self.max_steps:
            self._steps = self._steps[-self.max_steps:]
        self.save()

    def add_insight(self, tag: str, text: str, trigger: str = ""):
        """写入一条可复用教训（lessons learned）。trigger 为情境签名片段。"""
        ins = {"tag": tag, "text": text, "trigger": trigger, "ts": time.time()}
        # 去重：同 tag 已存在则更新
        for i, old in enumerate(self._insights):
            if old.get("tag") == tag:
                self._insights[i] = ins
                self.save()
                return
        self._insights.append(ins)
        self.save()

    # ── 读取/召回 ──
    @staticmethod
    def _tokens(sig: str) -> set:
        """情境签名 → token 集合（零正则：按非字母数字切分）。"""
        out = set()
        cur = []
        for ch in sig:
            if ch.isalnum():
                cur.append(ch)
            else:
                if cur:
                    out.add("".join(cur))
                    cur = []
        if cur:
            out.add("".join(cur))
        return out

    def recall(self, situation_signature: str) -> List[dict]:
        """按情境相似度召回历史洞察（ExpeL experience recall）。"""
        q = self._tokens(situation_signature)
        if not q:
            return []
        scored = []
        for ins in self._insights:
            t = self._tokens(ins.get("trigger", "") or ins.get("tag", ""))
            overlap = len(q & t)
            if overlap > 0:
                scored.append((overlap, ins))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored]

    def failures_like(self, situation_signature: str, limit: int = 5) -> List[dict]:
        """召回与当前情境相似的历史失败步骤（用于规避重复错误）。"""
        q = self._tokens(situation_signature)
        out = []
        for s in reversed(self._steps):
            if s.get("outcome") != "fail":
                continue
            t = self._tokens(s.get("situation", ""))
            if q & t:
                out.append(s)
                if len(out) >= limit:
                    break
        return out

    def summarize_session(self, phase_tag: str = "") -> str:
        """复盘（retrospective）：统计成败 + 列出洞察 + 高频失败。

        对应 ExpeL「从经验中抽取洞察」+ Generative Agents「反思生成摘要」。
        """
        recent = [s for s in self._steps
                  if not phase_tag or phase_tag in s.get("situation", "")]
        if not recent:
            return "（本轮无步骤记录）"
        succ = sum(1 for s in recent if s["outcome"] == "success")
        fail = sum(1 for s in recent if s["outcome"] == "fail")
        part = sum(1 for s in recent if s["outcome"] == "partial")
        by_kind: Dict[str, Dict[str, int]] = {}
        for s in recent:
            k = s.get("action_kind", "?")
            d = by_kind.setdefault(k, {"success": 0, "fail": 0, "partial": 0})
            d[s["outcome"]] = d.get(s["outcome"], 0) + 1
        lines = [f"【复盘】共 {len(recent)} 步：成功 {succ} / 部分 {part} / 失败 {fail}"]
        for k, d in sorted(by_kind.items()):
            lines.append(f"  - {k}: 成功{d['success']} 部分{d.get('partial',0)} 失败{d['fail']}")
        if self._insights:
            lines.append("【经验教训】")
            for ins in self._insights[-8:]:
                lines.append(f"  * [{ins.get('tag','')}] {ins.get('text','')}")
        return "\n".join(lines)


# ───────────────────────── 反思器（Reflexion + ToT/LATS 思想） ─────────────────────────
class Reflector:
    """把「看不见的问题」转成可执行的反馈/检测/恢复。

    - 反馈（正确/错误步骤）：用独立证据判定每步成败 + 错误分类
    - 局部最优检测：同动作重复无进展 → 提示换策略（LATS backprop 思想）
    - 问题发现与处理：异常 → 恢复动作列表
    """

    def __init__(self, memory: ExperienceMemory = None,
                 motion_success_thresh: float = 0.006,
                 local_opt_k: int = 4):
        self.mem = memory or ExperienceMemory()
        self.motion_thresh = motion_success_thresh
        self.local_opt_k = local_opt_k   # 同动作连续 N 次无进展即判局部最优

    # ── 正确/错误步骤的反馈 ──
    def evaluate_step(self, *, step: int, phase: str, situation: str,
                      decision: dict, action_kind: str,
                      pre_motion: float, post_motion: float,
                      pre_entities: dict, post_entities: dict,
                      expected_delta: str) -> StepRecord:
        """用独立证据判定一步的成败（不认动作自报）。"""
        # 观测到的世界变化（自动）：实体数变化 + 帧运动
        pre_n = sum(pre_entities.values())
        post_n = sum(post_entities.values())
        changed = post_n != pre_n
        moved = (post_motion - pre_motion) >= self.motion_thresh

        if changed or moved:
            # 期望有变化且确实有变化 → 成功（部分：有变化但非预期变化）
            outcome = "success" if (changed or moved) else "partial"
            # 若期望有放置但实体未增，仅帧动（可能点空）→ partial
            if expected_delta and not changed and moved:
                outcome = "partial"
            err = ""
        else:
            outcome = "fail"
            # 错误分类（Reflexion Error Categorization）
            if expected_delta:
                err = "no_change"      # 期望变化却无变化：放置可能失败/被拦截
            else:
                err = "none"

        observed = []
        if changed:
            observed.append("实体数变化")
        if moved:
            observed.append("画面运动")
        rec = StepRecord(
            step=step, phase=phase, situation=situation, action_kind=action_kind,
            decision=decision, pre_motion=pre_motion, post_motion=post_motion,
            pre_entities=pre_entities, post_entities=post_entities,
            expected_delta=expected_delta,
            observed_delta=";".join(observed) or "无变化",
            outcome=outcome, error_category=err, ts=time.time(),
        )
        self.mem.record_step(rec)
        return rec

    def feedback_recent(self, recent: List[StepRecord], k: int = 6) -> str:
        """生成最近步骤的反馈文本（哪些有效/无效 + 错误分类）。"""
        if not recent:
            return "（暂无步骤可反馈）"
        last = recent[-k:]
        eff = [s for s in last if s.outcome == "success"]
        ineff = [s for s in last if s.outcome in ("fail", "partial")]
        lines = [f"【步骤反馈】近 {len(last)} 步：有效 {len(eff)} / 无效 {len(ineff)}"]
        for s in ineff:
            cat = s.error_category or "未知"
            lines.append(f"  - 步{s.step} [{s.action_kind}] 无效({cat})："
                         f"期望[{s.expected_delta}] 实际[{s.observed_delta}]")
        if ineff:
            lines.append("  → 建议：无效步骤勿重复，参考历史经验或更换目标。")
        else:
            lines.append("  → 近期步骤均有效，继续当前策略。")
        return "\n".join(lines)

    # ── 局部最优 vs 全局最优 ──
    def detect_local_optimum(self, phase: str, action_kind: str,
                             recent: List[StepRecord],
                             global_progress: float) -> Tuple[bool, str]:
        """检测「局部最优陷阱」：

        同一动作连续重复 >= K 次，但全局进度（如 core 周边建成度/防御覆盖）
        未提升 → 判定陷入局部最优（LATS/MCTS 中胜率不增的节点）。
        返回 (是否陷阱, 建议文本)。
        """
        same = [s for s in recent if s.action_kind == action_kind]
        if len(same) < self.local_opt_k:
            return False, ""
        # 看这串同动作里成功步是否停滞（连续失败或部分）
        tail = same[-self.local_opt_k:]
        stagnant = all(s.outcome in ("fail", "partial") for s in tail)
        if stagnant and global_progress < 0.5:
            tip = (f"检测到局部最优：连续 {len(tail)} 次 [{action_kind}] 无进展，"
                   f"全局进度 {global_progress:.2f}。建议：跳出该动作，"
                   f"推进阶段或改用替代策略（如先布防/先拉物流）。")
            return True, tip
        return False, ""

    # ── 发现问题与处理问题 ──
    def discover_problems(self, world_state: dict,
                          recent: List[StepRecord]) -> List[dict]:
        """基于世界态 + 近期步骤发现异常，返回恢复动作列表（Voyager 自校验思想）。

        返回 [{"problem": str, "recovery": dict, "priority": int}, ...]
        按 priority 升序（越小越先处理）。
        """
        problems = []
        # 问题1：威胁存在但无防御 → 最高优先级
        if world_state.get("threat") and not world_state.get("has_defense"):
            problems.append({
                "problem": "敌人威胁出现但核心无炮塔",
                "recovery": {"op": "place", "block": "turret_hail"},
                "priority": 0,
            })
        # 问题2：连续失败（动作被拦截）→ 重试+扰动 或 跳过
        fails = [s for s in recent[-4:] if s.outcome == "fail"]
        if len(fails) >= 2:
            problems.append({
                "problem": f"连续 {len(fails)} 步失败（可能被拦截/坐标失效）",
                "recovery": {"op": "retry_perturb"},
                "priority": 1,
            })
        # 问题3：核心无矿可采但仍在 mining 阶段 → 推进物流
        if world_state.get("phase") == "mining" and not world_state.get("has_mineable"):
            problems.append({
                "problem": "采矿阶段但核心周边无可采资源",
                "recovery": {"op": "advance_phase", "to": "logistics"},
                "priority": 2,
            })
        problems.sort(key=lambda p: p["priority"])
        return problems

    def build_reflection(self, recent: List[StepRecord], world_state: dict,
                         phase: str, action_kind: str,
                         global_progress: float = 0.0) -> dict:
        """汇总一轮反思：反馈 + 局部最优 + 问题 + 召回经验。"""
        fb = self.feedback_recent(recent)
        trapped, tip = self.detect_local_optimum(phase, action_kind, recent, global_progress)
        probs = self.discover_problems(world_state, recent)
        sig = world_state.get("situation", f"{phase}@{action_kind}")
        recalled = self.mem.recall(sig)
        rec_text = ""
        if recalled:
            rec_text = "；".join(i.get("text", "") for i in recalled[:3])
        # 若发现陷阱，写入一条经验（教训沉淀）
        if trapped:
            self.mem.add_insight(
                tag=f"local_opt_{phase}_{action_kind}",
                text=tip,
                trigger=f"{phase} {action_kind}",
            )
        reflection_text = fb
        if trapped:
            reflection_text += "\n" + tip
        if probs:
            reflection_text += "\n【发现问题】" + "；".join(p["problem"] for p in probs)
        if rec_text:
            reflection_text += f"\n【历史经验】{rec_text}"
        return {
            "text": reflection_text,
            "local_optimum_trapped": trapped,
            "problems": probs,
            "local_tip": tip,
            "recalled_insights": [i.get("text", "") for i in recalled],
        }


# ───────────────────────── 自动课程（Voyager curriculum + 全局最优守卫） ─────────────────────────
class Curriculum:
    """阶段式课程（Voyager automatic curriculum）+ 全局最优守卫。

    解决「局部最优 vs 全局最优」：策略的即时贪心可能被全局守卫覆盖。
    例如：mining 阶段想继续挖，但波次将至且无防御 → 守卫强制切入 defense。
    """

    PHASES = ["init", "mining", "logistics", "defense", "sustain"]

    def __init__(self, max_phase_steps: int = 12):
        self.phase = "init"
        self.phase_steps = 0
        self.max_phase_steps = max_phase_steps
        self._done = set()

    def _idx(self, p: str) -> int:
        return self.PHASES.index(p) if p in self.PHASES else -1

    def advance(self, to: str = None):
        """推进阶段（显式目标 or 自动下一阶段）。"""
        if to and to in self.PHASES:
            self.phase = to
        else:
            i = self._idx(self.phase)
            if i < len(self.PHASES) - 1:
                self.phase = self.PHASES[i + 1]
        self.phase_steps = 0
        log.info(f"[curriculum] 阶段推进 -> {self.phase}")
        return self.phase

    def tick(self, world_state: dict) -> str:
        """每步调用：先全局守卫，再阶段内推进。

        返回当前应处阶段（可能被守卫覆盖）。
        """
        self.phase_steps += 1
        # 全局最优守卫：威胁来了且没防御 → 无论当前阶段，强制 defense
        if world_state.get("threat") and not world_state.get("has_defense"):
            if self.phase != "defense":
                self.phase = "defense"
                self.phase_steps = 0
                log.info("[curriculum] 全局守卫触发：威胁出现→切入 defense")
            return self.phase
        # 阶段超时（避免卡在某阶段=局部最优）→ 自动推进
        if self.phase_steps >= self.max_phase_steps and self.phase != "sustain":
            self.advance()
        return self.phase


if __name__ == "__main__":
    # 离线自检：构造合成步骤，验证反馈/局部最优/复盘链路。
    logging.basicConfig(level=logging.INFO)
    mem = ExperienceMemory()
    ref = Reflector(mem)
    # 模拟：连续 4 次同一动作失败 → 应判局部最优
    recs = []
    for i in range(5):
        r = ref.evaluate_step(
            step=i, phase="mining", situation="mining@core",
            decision={"op": "place", "block": "drill"}, action_kind="place_drill",
            pre_motion=0.0, post_motion=0.001, pre_entities={"core": 1},
            post_entities={"core": 1}, expected_delta="放置钻机",
        )
        recs.append(r)
    trapped, tip = ref.detect_local_optimum("mining", "place_drill", recs, 0.1)
    print("局部最优陷阱:", trapped)
    print(tip)
    print("反馈:\n", ref.feedback_recent(recs))
    print("复盘:\n", mem.summarize_session())
    print("OK")
