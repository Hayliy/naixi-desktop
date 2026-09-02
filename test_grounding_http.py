"""game_agent HTTP Mod 消费者自测（无需运行 Minecraft / 无需 Mod 实体）。

验证：
  1) _ingest_api_state 把样例 API JSON 正确归一化进 self._world + self._aim
  2) _policy_grounded 基于 aim 产出合理动作（attack/forward/aim）
  3) _grounding_http 在 Mod 未运行时优雅返回 False（视觉回退路径）

运行：python test_grounding_http.py
"""
import sys

sys.path.insert(0, r"D:\naixi_desktop")

from desktop_core.game_agent import GameAgent


def make_sample():
    return {
        "player": {"x": 10.0, "y": 64.0, "z": -5.0, "yaw": 90.0, "pitch": 0.0,
                   "hp": 18.0, "on_ground": True, "in_water": False},
        "entities": [
            {"type": "zombie", "x": 12.0, "y": 64.0, "z": -5.0, "dist": 2.0,
             "rel_bearing": 5.0, "dy": 0.0, "hostile": True, "category": "hostile"},
            {"type": "cow", "x": 8.0, "y": 64.0, "z": -5.0, "dist": 2.0,
             "rel_bearing": -170.0, "dy": 0.0, "hostile": False, "category": "animal"},
        ],
        "resources": [{"type": "oak_log", "x": 10.0, "y": 68.0, "z": -5.0,
                       "dist": 4.0, "rel_bearing": 2.0}],
        "aim": {"mx": 30.0, "my": -10.0, "category": "hostile", "dist": 2.0},
    }


def test_ingest():
    g = GameAgent()
    g._ingest_api_state(make_sample())
    assert g._grounding_ok is True, "grounding_ok 应为 True"
    assert g._world["self_hp"] == 18.0, f"hp 错误: {g._world['self_hp']}"
    assert g._world["self_pos"] == (10.0, 64.0, -5.0)
    # 威胁只收 hostile 且 dist<=14
    assert len(g._world["threats"]) == 1, g._world["threats"]
    assert g._world["threats"][0]["type"] == "zombie"
    assert g._world["threats"][0]["dir"] == "前", f"方位应=前, 实际={g._world['threats'][0]['dir']}"
    # 物体收非 hostile
    assert len(g._world["objects"]) == 1 and g._world["objects"][0]["type"] == "cow"
    # 资源
    assert len(g._world["resources"]) == 1 and g._world["resources"][0]["type"] == "oak_log"
    # aim 注入
    assert g._aim == (30.0, -10.0), g._aim
    assert g._aim_cat == "hostile" and g._aim_dist == 2.0


def test_policy_with_aim():
    g = GameAgent()
    g._ingest_api_state(make_sample())
    # 对准偏移>12 → 应返回 aim（继续闭合修正）
    g._step = 0
    act = g._policy_grounded()
    assert act in ("aim", "attack", "forward"), f"动作异常: {act}"
    # 把 aim 调小到已对准、近距离 → 应 attack
    g._aim = (5.0, 3.0)
    g._aim_dist = 2.0
    assert g._policy_grounded() == "attack"
    # 无目标 → 探索
    g._aim = None
    assert g._policy_grounded() in ("forward", "look_left", "look_right", "jump")


def test_fallback_when_no_mod():
    g = GameAgent()
    g._mc_api_url = "http://127.0.0.1:65530/state"  # 必然连不上的端口
    ok = g._grounding_http()
    assert ok is False, "Mod 未运行时应返回 False"
    assert g._grounding_ok is False


if __name__ == "__main__":
    test_ingest()
    test_policy_with_aim()
    test_fallback_when_no_mod()
    print("PASS: 消费者归一化 + 规则策略 + 视觉回退 全部通过")
