"""
骨骼动画系统：为 Live2D 模型增加独立肢体骨骼
骨骼定义 → 动画逻辑 → 驱动渲染
"""

import time, math
from typing import Optional

class Bone:
    """骨骼节点"""
    def __init__(self, name: str, parent: Optional['Bone'] = None,
                 length: float = 0, angle: float = 0):
        self.name = name
        self.parent = parent
        self.children: list['Bone'] = []
        self.length = length        # 骨骼长度（相对父级）
        self.angle = angle          # 当前角度（度）
        self.target_angle = angle   # 目标角度
        if parent:
            parent.children.append(self)

    def set_target(self, angle: float):
        self.target_angle = angle

    def update(self, speed: float = 0.1):
        """向目标角度平滑插值"""
        diff = self.target_angle - self.angle
        self.angle += diff * speed
        for child in self.children:
            child.update(speed)

    def get_world_angle(self) -> float:
        """递归计算世界坐标角度"""
        if self.parent:
            return self.angle + self.parent.get_world_angle()
        return self.angle


class Skeleton:
    """完整骨骼定义"""
    def __init__(self):
        self.root = Bone("root")
        self.bones: dict[str, Bone] = {"root": self.root}

    def add_bone(self, name: str, parent: str, length: float = 0) -> Bone:
        p = self.bones[parent]
        b = Bone(name, p, length)
        self.bones[name] = b
        return b

    def set_pose(self, pose: dict[str, float]):
        """批量设置骨骼目标角度"""
        for name, angle in pose.items():
            if name in self.bones:
                self.bones[name].set_target(angle)

    def update(self, speed: float = 0.1):
        self.root.update(speed)

    def get_world_angles(self) -> dict[str, float]:
        return {n: b.get_world_angle() for n, b in self.bones.items()}


class SkeletalAnimator:
    """骨骼动画驱动——定义动作→骨骼映射"""
    def __init__(self, skeleton: Skeleton):
        self.skeleton = skeleton
        # 动作→骨骼姿态映射
        self.action_poses: dict[str, dict[str, float]] = {}

    def set_action(self, name: str, pose: dict[str, float]):
        self.action_poses[name] = pose

    def play(self, action: str, speed: float = 0.1):
        pose = self.action_poses.get(action)
        if pose:
            self.skeleton.set_pose(pose)


def create_default_skeleton() -> Skeleton:
    """创建默认上半身骨骼（适用于半身模型）"""
    sk = Skeleton()
    # body → shoulders
    sk.add_bone("spine", "root")
    # left arm
    sk.add_bone("shoulder_l", "spine")
    sk.add_bone("arm_l_upper", "shoulder_l", length=30)
    sk.add_bone("arm_l_lower", "arm_l_upper", length=25)
    sk.add_bone("hand_l", "arm_l_lower", length=10)
    # right arm
    sk.add_bone("shoulder_r", "spine")
    sk.add_bone("arm_r_upper", "shoulder_r", length=30)
    sk.add_bone("arm_r_lower", "arm_r_upper", length=25)
    sk.add_bone("hand_r", "arm_r_lower", length=10)
    # head/neck
    sk.add_bone("neck", "spine")
    sk.add_bone("head", "neck", length=15)
    return sk


def create_default_animator(skeleton: Skeleton) -> SkeletalAnimator:
    """创建默认动作映射"""
    anim = SkeletalAnimator(skeleton)
    # 各动作的骨骼角度定义（正=顺时针）
    anim.set_action("idle", {"arm_l_upper": 5, "arm_r_upper": -5})
    anim.set_action("wave", {
        "arm_r_upper": -30,     # 右臂抬起
        "arm_r_lower": -15,     # 右小臂弯曲
    })
    anim.set_action("wave_l", {
        "arm_l_upper": 30,
        "arm_l_lower": 15,
    })
    anim.set_action("arms_up", {
        "arm_l_upper": -80,
        "arm_r_upper": 80,
    })
    anim.set_action("point_r", {
        "arm_r_upper": -20,
        "arm_r_lower": -5,
    })
    anim.set_action("point_l", {
        "arm_l_upper": 20,
        "arm_l_lower": 5,
    })
    anim.set_action("hello", {
        "arm_r_upper": -25,
        "arm_r_lower": -10,
        "head": 5,
    })
    anim.set_action("bye", {
        "arm_r_upper": -35,
        "arm_r_lower": -20,
    })
    anim.set_action("shrug", {
        "shoulder_l": -10,
        "shoulder_r": 10,
    })
    return anim
