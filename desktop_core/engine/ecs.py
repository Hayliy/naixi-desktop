"""
轻量 ECS 核心：Entity、Component、System、World
"""

from __future__ import annotations
import uuid, math
from typing import Optional, Type

class Component:
    """组件基类——纯数据"""
    def __repr__(self): return f"{type(self).__name__}()"

class System:
    """系统基类——无状态逻辑"""
    order: int = 0  # 执行顺序，小的先执行

    def update(self, world: 'World', dt: float):
        raise NotImplementedError

class Entity:
    """实体——组件的容器"""
    def __init__(self, name: str = "", *components: Component):
        self._id = uuid.uuid4().hex[:12]
        self._name = name or f"Entity_{self._id[:6]}"
        self._components: dict[Type[Component], Component] = {}
        self._active = True
        self._parent: Optional[Entity] = None
        self._children: list[Entity] = []
        for c in components:
            self.add(c)

    @property
    def id(self): return self._id
    @property
    def name(self): return self._name
    @property
    def parent(self): return self._parent
    @property
    def children(self): return list(self._children)
    @property
    def active(self): return self._active

    def set_parent(self, parent: 'Entity'):
        if self._parent:
            self._parent._children.remove(self)
        self._parent = parent
        if parent:
            parent._children.append(self)

    def add(self, component: Component):
        self._components[type(component)] = component

    def get(self, T: Type[Component]) -> Optional[Component]:
        return self._components.get(T)

    def has(self, T: Type[Component]) -> bool:
        return T in self._components

    def remove(self, T: Type[Component]):
        self._components.pop(T, None)

class World:
    """世界——管理实体和系统"""
    def __init__(self):
        self._entities: dict[str, Entity] = {}
        self._systems: list[System] = []

    def add_entity(self, e: Entity):
        self._entities[e.id] = e

    def remove_entity(self, e: Entity):
        self._entities.pop(e.id, None)

    def add_system(self, s: System):
        self._systems.append(s)
        self._systems.sort(key=lambda x: x.order)

    def get_entities_with(self, *component_types: Type[Component]) -> list[Entity]:
        return [e for e in self._entities.values()
                if all(e.has(t) for t in component_types)]

    def update(self, dt: float):
        for system in self._systems:
            system.update(self, dt)
