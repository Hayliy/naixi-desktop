"""
Transform 组件——位置/旋转/缩放 + 父子层级世界坐标
"""
from __future__ import annotations
import math
from typing import Optional
from .ecs import Component

class Transform(Component):
    def __init__(self, x: float = 0, y: float = 0, rotation: float = 0,
                 scale_x: float = 1, scale_y: float = 1):
        self._x = x; self._y = y
        self._rotation = rotation
        self._sx = scale_x; self._sy = scale_y
        self._parent_transform: Optional[Transform] = None

    @property
    def x(self): return self._x
    @x.setter
    def x(self, v): self._x = v
    @property
    def y(self): return self._y
    @y.setter
    def y(self, v): self._y = v
    @property
    def rotation(self): return self._rotation
    @rotation.setter
    def rotation(self, v): self._rotation = v
    @property
    def scale_x(self): return self._sx
    @scale_x.setter
    def scale_x(self, v): self._sx = v
    @property
    def scale_y(self): return self._sy
    @scale_y.setter
    def scale_y(self, v): self._sy = v

    @property
    def world_x(self) -> float:
        if self._parent_transform:
            px = self._parent_transform.world_x
            py = self._parent_transform.world_y
            pr = math.radians(self._parent_transform.rotation)
            lx = self._x * self._parent_transform.scale_x
            ly = self._y * self._parent_transform.scale_y
            return px + lx * math.cos(pr) - ly * math.sin(pr)
        return self._x

    @property
    def world_y(self) -> float:
        if self._parent_transform:
            px = self._parent_transform.world_x
            py = self._parent_transform.world_y
            pr = math.radians(self._parent_transform.rotation)
            lx = self._x * self._parent_transform.scale_x
            ly = self._y * self._parent_transform.scale_y
            return py + lx * math.sin(pr) + ly * math.cos(pr)
        return self._y

    @property
    def world_rotation(self) -> float:
        if self._parent_transform:
            return self._parent_transform.world_rotation + self._rotation
        return self._rotation

    def link_parent(self, parent: Transform):
        self._parent_transform = parent
