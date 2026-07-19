"""
骨骼动画系统——基于 ECS 的骨架+动作驱动
"""
from __future__ import annotations
from .ecs import Entity, Component, System, World
from .transform import Transform

class BoneData(Component):
    """骨骼数据：名称、长度"""
    def __init__(self, name: str = "", length: float = 0):
        self.name = name
        self.length = length
        self.target_rotation: float = 0.0  # 目标角度

class SkeletalAnimator(System):
    """骨骼动画系统——每帧向目标角度插值"""
    speed: float = 0.12

    def update(self, world: World, dt: float):
        for entity in world.get_entities_with(Transform, BoneData):
            t = entity.get(Transform)
            b = entity.get(BoneData)
            # 向目标角度平滑插值
            diff = b.target_rotation - t.rotation
            t.rotation += diff * min(1.0, self.speed * dt * 60)

def build_skeleton() -> Entity:
    """创建默认上半身骨骼骨架"""
    # 根
    root = Entity("root", Transform(0, 0, 0), BoneData("root"))
    # 脊柱
    spine = Entity("spine", Transform(0, 0, 0), BoneData("spine"))
    spine.set_parent(root)
    # 颈
    neck = Entity("neck", Transform(0, -15, 0), BoneData("neck", 15))
    neck.set_parent(spine)
    # 头
    head = Entity("head", Transform(0, -15, 0), BoneData("head", 15))
    head.set_parent(neck)
    # 左肩
    shoulder_l = Entity("shoulder_l", Transform(-5, -5, 0), BoneData("shoulder_l"))
    shoulder_l.set_parent(spine)
    # 左上臂
    arm_l_upper = Entity("arm_l_upper", Transform(0, -15, 0), BoneData("arm_l_upper", 30))
    arm_l_upper.set_parent(shoulder_l)
    # 左前臂
    arm_l_lower = Entity("arm_l_lower", Transform(0, -25, 0), BoneData("arm_l_lower", 25))
    arm_l_lower.set_parent(arm_l_upper)
    # 左手
    hand_l = Entity("hand_l", Transform(0, -15, 0), BoneData("hand_l", 10))
    hand_l.set_parent(arm_l_lower)
    # 右肩
    shoulder_r = Entity("shoulder_r", Transform(5, -5, 0), BoneData("shoulder_r"))
    shoulder_r.set_parent(spine)
    # 右上臂
    arm_r_upper = Entity("arm_r_upper", Transform(0, -15, 0), BoneData("arm_r_upper", 30))
    arm_r_upper.set_parent(shoulder_r)
    # 右前臂
    arm_r_lower = Entity("arm_r_lower", Transform(0, -25, 0), BoneData("arm_r_lower", 25))
    arm_r_lower.set_parent(arm_r_upper)
    # 右手
    hand_r = Entity("hand_r", Transform(0, -15, 0), BoneData("hand_r", 10))
    hand_r.set_parent(arm_r_lower)

    # 关联父子 Transform
    _link_transforms(root)
    return root

def _link_transforms(e: Entity):
    t = e.get(Transform)
    for child in e.children:
        ct = child.get(Transform)
        if t and ct:
            ct.link_parent(t)
        _link_transforms(child)

# 动作→骨骼目标角度映射
ACTION_POSES: dict[str, dict[str, float]] = {
    "idle":     {"arm_l_upper": 5, "arm_r_upper": -5},
    "wave":     {"arm_r_upper": -30, "arm_r_lower": -15, "head": 5},
    "wave_l":   {"arm_l_upper": 30, "arm_l_lower": 15},
    "arms_up":  {"arm_l_upper": -80, "arm_r_upper": 80, "head": 8},
    "point_r":  {"arm_r_upper": -20, "arm_r_lower": -5, "head_tilt": -5},
    "point_l":  {"arm_l_upper": 20, "arm_l_lower": 5, "head_tilt": 5},
    "hello":    {"arm_r_upper": -25, "arm_r_lower": -10, "head": 8},
    "bye":      {"arm_r_upper": -35, "arm_r_lower": -20},
    "bow":      {"spine": 15, "head": 15},
    "shrug":    {"shoulder_l": -10, "shoulder_r": 10},
}

def set_pose(root: Entity, pose_name: str):
    """将骨骼设定到指定动作"""
    pose = ACTION_POSES.get(pose_name)
    if not pose:
        return
    _apply_pose(root, pose)

def _apply_pose(e: Entity, pose: dict[str, float]):
    b = e.get(BoneData)
    if b and b.name in pose:
        b.target_rotation = pose[b.name]
    for child in e.children:
        _apply_pose(child, pose)

def get_bone_angles(root: Entity) -> dict[str, float]:
    """获取所有骨骼的世界角度"""
    angles = {}
    _collect_angles(root, angles)
    return angles

def _collect_angles(e: Entity, out: dict[str, float]):
    b = e.get(BoneData)
    t = e.get(Transform)
    if b:
        out[b.name] = t.world_rotation if t else 0
    for child in e.children:
        _collect_angles(child, out)

def _collect_all(e: Entity, out: list[Entity]):
    """递归收集所有骨骼实体"""
    out.append(e)
    for child in e.children:
        _collect_all(child, out)
