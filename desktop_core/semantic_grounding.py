# -*- coding: utf-8 -*-
"""semantic_grounding.py — 无标签游戏对象的「像素→语义」三层映射
================================================================

解决 ui_grounding 不覆盖的问题：资源矿（铜/铅/煤）等**没有 UI 文字标签**、
不会提示「点我」的对象，怎么把「像素位置」关联到「语义信息」。

三层机制（不是「分析像素推理」，而是「先验知识 + 形态 + 规则」）：

  L1 颜色/模板特征分类  — 游戏美术颜色固定，不靠 LLM 分析。
      有官方精灵时用 ore-* 模板匹配（Perception 层）；无精灵时用 HSV 阈值分割。
  L2 形态学定位          — 连通区域 → 每个矿脉的中心/面积/包围盒（精确坐标）。
  L3 规则推理            — 游戏规则决定「该点什么」（以核心为原点、距离阈值），
      视觉只负责「在哪」，决策是 Strategy 职权（见 game_agent_mindustry）。

HSV 先验（OpenCV 量纲：H 0-179 / S 0-255 / V 0-255）：
  铜矿 = 暖橙   H(3,13)   S(120,255) V(120,255)
  铅矿 = 冷蓝灰 H(43,58)  S(40,180)  V(60,200)
  煤   = 近黑   H(0,179)  S(0,80)    V(0,70)
  核心 = 高饱和亮橙 H(0,9) S(180,255) V(170,255)  （与 ore/core 精灵一致）

红线：零正则、零 VLM 依赖、本地实时、不写 C 盘（资源检测纯算法，无落盘）。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import numpy as np
import cv2

log = logging.getLogger("semantic_grounding")


# ── L1：颜色先验（OpenCV HSV 量纲）──
# 值为 (lower_tuple, upper_tuple)。调参在真机校准，初始用已验证近似值。
COLOR_DEFS = {
    "copper": ((3, 120, 120), (13, 255, 255)),     # 暖橙
    "lead":   ((43, 40, 60), (58, 180, 200)),      # 冷蓝灰
    "coal":   ((0, 0, 0), (179, 80, 70)),          # 近黑（S/V 双低）
    "core":   ((0, 180, 170), (9, 255, 255)),      # 高饱和亮橙（核心菱形）
}


@dataclass
class ResourceRegion:
    """单个无标签资源区域（L2 形态学定位结果）。"""
    cat: str = ""               # copper / lead / coal / core
    cx: int = 0                 # 中心 X（窗口内像素）
    cy: int = 0                 # 中心 Y
    area: int = 0               # 连通区域面积（像素）
    x1: int = 0                 # 包围盒
    y1: int = 0
    x2: int = 0
    y2: int = 0
    screen_x: int = 0           # 屏幕绝对坐标（由外层加窗口偏移）
    screen_y: int = 0
    dist_to_core: float = -1.0  # 到核心的像素距离（-1=未知）
    mineable: bool = False      # 是否在可开采范围


def _mask_color(img_hsv, cat: str) -> Optional[np.ndarray]:
    """L1：生成某类别的颜色掩码。"""
    rng = COLOR_DEFS.get(cat)
    if rng is None:
        return None
    lo, hi = rng
    return cv2.inRange(img_hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))


def _connected_regions(mask: np.ndarray, min_area: int = 200):
    """L2：连通区域 → 列表 of (cx, cy, area, bbox)。"""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_area:
            continue
        m = cv2.moments(c)
        if m["m00"] == 0:
            continue
        cx = int(m["m10"] / m["m00"])
        cy = int(m["m01"] / m["m00"])
        x, y, w, h = cv2.boundingRect(c)
        out.append((cx, cy, int(a), (x, y, x + w, y + h)))
    return out


class SemanticGrounding:
    """无标签资源的「像素→语义」定位器。

    用法：
        sg = SemanticGrounding()
        regions = sg.analyze(scene_rgb, core_pos=(cx, cy))
        # regions: List[ResourceRegion]，含 mineable 决策
    """

    def __init__(self, mine_radius_px: float = 260.0, min_area: int = 200):
        self.mine_radius = mine_radius_px
        self.min_area = min_area

    def _to_hsv(self, scene):
        if scene is None:
            return None
        if scene.ndim == 2:
            return cv2.cvtColor(scene, cv2.COLOR_GRAY2HSV)
        if scene.shape[2] == 4:
            rgb = cv2.cvtColor(scene, cv2.COLOR_BGRA2RGB)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        return cv2.cvtColor(scene, cv2.COLOR_RGB2HSV)

    def analyze(self, scene, core_pos: Optional[Tuple[int, int]] = None,
                window_offset=(0, 0)) -> List[ResourceRegion]:
        """分析一帧，返回无标签资源区域列表（带 mineable 决策）。

        Args:
            scene: RGB ndarray（或带 alpha）。
            core_pos: 核心中心（窗口内像素坐标），用于算矿脉距离。
                      为 None 时先尝试用 core 颜色自定位。
            window_offset: (ox, oy) 窗口左上角屏幕坐标，用于回填 screen_x/y。
        Returns:
            List[ResourceRegion]
        """
        hsv = self._to_hsv(scene)
        if hsv is None:
            return []
        ox, oy = window_offset
        regions: List[ResourceRegion] = []

        if core_pos is None:
            cm = _mask_color(hsv, "core")
            if cm is not None:
                cr = _connected_regions(cm, min_area=self.min_area)
                if cr:
                    cr.sort(key=lambda r: r[2], reverse=True)
                    core_pos = (cr[0][0], cr[0][1])

        for cat in ("copper", "lead", "coal", "core"):
            if cat == "core" and core_pos is not None:
                if any(r.cat == "core" for r in regions):
                    continue
                m = _mask_color(hsv, "core")
                if m is None:
                    continue
                cr = _connected_regions(m, min_area=self.min_area)
                for (cx, cy, a, bb) in cr:
                    regions.append(self._make_region(
                        "core", cx, cy, a, bb, core_pos, ox, oy, mineable=False))
                continue
            m = _mask_color(hsv, cat)
            if m is None:
                continue
            for (cx, cy, a, bb) in _connected_regions(m, min_area=self.min_area):
                regions.append(self._make_region(
                    cat, cx, cy, a, bb, core_pos, ox, oy,
                    mineable=(core_pos is not None)))

        regions.sort(key=lambda r: (r.cat != "core", -r.area))
        return regions

    def _make_region(self, cat, cx, cy, area, bbox, core_pos, ox, oy, mineable):
        dist = -1.0
        if core_pos is not None and cat != "core":
            dist = float(np.hypot(cx - core_pos[0], cy - core_pos[1]))
            mineable = mineable and (dist <= self.mine_radius)
        return ResourceRegion(
            cat=cat, cx=cx, cy=cy, area=area,
            x1=bbox[0], y1=bbox[1], x2=bbox[2], y2=bbox[3],
            screen_x=cx + ox, screen_y=cy + oy,
            dist_to_core=dist, mineable=mineable,
        )

    def summarize(self, regions: List[ResourceRegion]) -> Dict[str, object]:
        """把区域列表压成策略层可用的摘要（不依赖 LLM）。"""
        cats = {}
        mineable = []
        core = None
        for r in regions:
            cats[r.cat] = cats.get(r.cat, 0) + 1
            if r.cat == "core":
                core = (r.cx, r.cy)
            elif r.mineable:
                mineable.append({"cat": r.cat, "cx": r.cx, "cy": r.cy,
                                 "area": r.area, "dist": round(r.dist_to_core, 1)})
        return {
            "counts": cats,
            "core": core,
            "mineable": mineable,
            "total_regions": len(regions),
        }

    def render_overlay(self, scene, regions: List[ResourceRegion], out_path: str):
        """把检测结果画到画面上，存盘（供验证/复盘查看）。"""
        if scene is None:
            return
        vis = scene.copy()
        if vis.ndim == 2:
            vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
        elif vis.shape[2] == 4:
            vis = cv2.cvtColor(vis, cv2.COLOR_BGRA2BGR)
        else:
            vis = cv2.cvtColor(vis, cv2.COLOR_RGB2BGR)
        color_map = {"copper": (0, 165, 255), "lead": (200, 200, 60),
                     "coal": (80, 80, 80), "core": (0, 200, 255)}
        for r in regions:
            c = color_map.get(r.cat, (0, 255, 0))
            cv2.rectangle(vis, (r.x1, r.y1), (r.x2, r.y2), c, 2)
            label = r.cat + ("*" if r.mineable else "")
            cv2.putText(vis, label, (r.x1, max(0, r.y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)
        try:
            cv2.imwrite(out_path, vis)
        except Exception as e:
            log.warning(f"[semantic_grounding] 渲染失败: {e}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    sg = SemanticGrounding()
    if len(sys.argv) > 1:
        img = cv2.imread(sys.argv[1])
        if img is not None:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            regs = sg.analyze(rgb)
            summ = sg.summarize(regs)
            print("检测结果:", summ)
            out = sys.argv[1] + ".semantic.png"
            sg.render_overlay(rgb, regs, out)
            print("叠加图:", out)
        else:
            print("无法读取", sys.argv[1])
    else:
        print("用法: python semantic_grounding.py <frame.png>")
