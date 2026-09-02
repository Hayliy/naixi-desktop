#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 FK 正运动学探针：解析 VRMA 动画轨道，量化右臂抬起幅度随时间变化，
判断'重复举右胳膊'是片段内 choreography 还是循环接缝 snap。"""
import sys, math
import numpy as np
from pygltflib import GLTF2

def mat4_trs(t, r, s):
    # t: (3,), r: (4,) quaternion xyzw, s: (3,)
    x, y, z, w = r
    n = 1.0 / (x*x + y*y + z*z + w*w) ** 0.5 if (x*x+y*y+z*z+w*w) > 0 else 1.0
    x, y, z, w = x*n, y*n, z*n, w*n
    m = np.eye(4)
    m[0,0] = 1-2*(y*y+z*z); m[0,1] = 2*(x*y-z*w); m[0,2] = 2*(x*z+y*w)
    m[1,0] = 2*(x*y+z*w); m[1,1] = 1-2*(x*x+z*z); m[1,2] = 2*(y*z-x*w)
    m[2,0] = 2*(x*z-y*w); m[2,1] = 2*(y*z+x*w); m[2,2] = 1-2*(x*x+y*y)
    m[0,3] = t[0]; m[1,3] = t[1]; m[2,3] = t[2]
    ms = np.diag([s[0], s[1], s[2], 1.0])
    return m @ ms

def slerp(a, b, t):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if dot < 0:
        b = -b; dot = -dot
    if dot > 0.9995:
        r = a + (b - a) * t
        r = r / (np.linalg.norm(r) or 1.0)
    else:
        theta0 = math.acos(dot); theta = theta0 * t; sin0 = math.sin(theta0)
        s1 = math.sin(theta) / sin0; s0 = math.cos(theta) - dot * s1
        r = a * s0 + b * s1
    return r.tolist()

def lerp3(a, b, t):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return (a + (b - a) * t).tolist()

class GltfAnim:
    def __init__(self, gltf):
        self.gltf = gltf
        self.nodes = gltf.nodes
        self.parent = [-1]*len(self.nodes)
        for i, n in enumerate(self.nodes):
            for c in (n.children or []):
                self.parent[c] = i
        self.anim = gltf.animations[0] if gltf.animations else None
        self.channels = {}  # node -> {path: (times, values)}
        self.duration = 0.0
        if self.anim:
            for ch in self.anim.channels:
                node = ch.target.node
                path = ch.target.path
                smp = self.anim.samplers[ch.sampler]
                times = self._read(smp.input)
                vals = self._read(smp.output)
                self.channels.setdefault(node, {})[path] = (times, vals)
                self.duration = float(max(self.duration, float(np.max(times))))
        self._world_cache = {}

    def _read(self, acc_idx):
        import struct
        acc = self.gltf.accessors[acc_idx]
        bv = self.gltf.bufferViews[acc.bufferView]
        blob = self.gltf.binary_blob()
        start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
        comp_size = {5126:4, 5123:2, 5125:4, 5122:2, 5121:1, 5120:1}[acc.componentType]
        ncomp = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[acc.type]
        total = acc.count * ncomp * comp_size
        raw = blob[start:start+total]
        fmt = {5126:'f',5123:'H',5125:'I',5122:'h',5121:'B',5120:'b'}[acc.componentType]
        vals = struct.unpack('<%d%s' % (acc.count*ncomp, fmt), raw)
        arr = np.array(vals, dtype=float)
        if acc.type == 'SCALAR':
            return arr
        return arr.reshape(acc.count, ncomp)

    def local_trs(self, i, t):
        n = self.nodes[i]
        def f3(v): return [float(x) for x in (v if v is not None else [0,0,0])]
        def f4(v): return [float(x) for x in (v if v is not None else [0,0,0,1])]
        tr = f3(n.translation); ro = f4(n.rotation); sc = f3(n.scale)
        ch = self.channels.get(i)
        if ch:
            for path, (times, vals) in ch.items():
                if len(times) == 1:
                    if path == 'translation': tr = [float(x) for x in vals[0]]
                    elif path == 'rotation': ro = [float(x) for x in vals[0]]
                    elif path == 'scale': sc = [float(x) for x in vals[0]]
                    continue
                if t <= times[0]:
                    k = 0
                elif t >= times[-1]:
                    k = len(times)-2
                else:
                    k = int(np.searchsorted(times, t, side='right')-1)
                    k = min(max(k, 0), len(times)-2)
                t0, t1 = times[k], times[k+1]
                f = (t - t0)/(t1-t0) if (t1-t0) > 1e-9 else 0.0
                if path == 'translation':
                    tr = [float(x) for x in lerp3(vals[k].tolist(), vals[k+1].tolist(), f)]
                elif path == 'rotation':
                    ro = slerp(vals[k].tolist(), vals[k+1].tolist(), f)
                elif path == 'scale':
                    sc = [float(x) for x in lerp3(vals[k].tolist(), vals[k+1].tolist(), f)]
        return tr, ro, sc

    def world_matrix(self, i, t, memo=None):
        if memo is None: memo = {}
        if i in memo: return memo[i]
        tr, ro, sc = self.local_trs(i, t)
        local = mat4_trs(tr, ro, sc)
        p = self.parent[i]
        if p < 0:
            world = local
        else:
            world = self.world_matrix(p, t, memo) @ local
        memo[i] = world
        return world

    def node_world_pos(self, i, t):
        w = self.world_matrix(i, t)
        return np.array([w[0,3], w[1,3], w[2,3]])

    def find_node(self, side, *bone_kw):
        for i, n in enumerate(self.nodes):
            name = (n.name or '').lower()
            if side.lower() == 'r':
                side_ok = ('_r_' in name) or ('right' in name)
            else:
                side_ok = ('_l_' in name) or ('left' in name)
            if side_ok and all(k in name for k in bone_kw):
                return i
        return None

def analyze(path):
    gltf = GLTF2().load_binary(path)
    a = GltfAnim(gltf)
    print(f"\n===== {path} =====")
    print(f"动画数={len(gltf.animations)} 节点数={len(gltf.nodes)} 时长={a.duration:.3f}s")
    # 列出含 right/arm/hand 的节点名
    names = [(i, n.name) for i, n in enumerate(gltf.nodes) if n.name and any(k in n.name.lower() for k in ['right','arm','hand','shoulder'])]
    print("右臂相关节点:", names)
    rh = a.find_node('R', 'hand')
    ru = a.find_node('R', 'upper', 'arm')
    rl = a.find_node('R', 'lower', 'arm')
    rs = a.find_node('R', 'shoulder')
    sh = rs if rs is not None else ru
    if rh is None or sh is None:
        print("!! 未找到右臂节点，跳过")
        return
    # 采样右肩->右手 抬起角（与世界竖直方向夹角）随时间
    N = 80
    ts = np.linspace(0, a.duration, N)
    elev = []
    hand_y = []
    for t in ts:
        shp = a.node_world_pos(sh, t)
        hp = a.node_world_pos(rh, t)
        dirv = hp - shp
        L = np.linalg.norm(dirv)
        if L < 1e-6: elev.append(0); hand_y.append(hp[1]); continue
        dirv = dirv / L
        # 与世界向下 (0,-1,0) 夹角
        ang = math.degrees(math.acos(max(-1, min(1, -dirv[1]))))  # dirv·(0,-1,0) = -dirv[1]
        elev.append(ang)
        hand_y.append(hp[1])
    elev = np.array(elev); hand_y = np.array(hand_y)
    print(f"右臂抬起角(相对竖直): min={elev.min():.1f}° max={elev.max():.1f}° mean={elev.mean():.1f}° 振幅={elev.max()-elev.min():.1f}°")
    print(f"右手世界Y: min={hand_y.min():.3f} max={hand_y.max():.3f} 振幅={hand_y.max()-hand_y.min():.3f}")
    # 检测振荡：局部极大值数量
    peaks = 0
    for i in range(1, N-1):
        if elev[i] > elev[i-1] and elev[i] > elev[i+1] and elev[i] > elev.mean()+3:
            peaks += 1
    print(f"抬起角局部峰值数(>均值3°)={peaks}  -> {('片段内反复抬起!' if peaks>=2 else '无明显反复')}")
    # 接缝检测：首帧 vs 末帧
    print(f"接缝: t0 抬起角={elev[0]:.1f}°  t_end 抬起角={elev[-1]:.1f}°  差={abs(elev[0]-elev[-1]):.1f}°")
    print(f"接缝: t0 右手Y={hand_y[0]:.3f}  t_end 右手Y={hand_y[-1]:.3f}  差={abs(hand_y[0]-hand_y[-1]):.3f}")
    # 打印序列（每 ~10 个采一次）
    seq = " ".join(f"{e:4.0f}" for e in elev[::8])
    print(f"抬起角序列(抽样): {seq}")

if __name__ == '__main__':
    for p in sys.argv[1:]:
        analyze(p)
