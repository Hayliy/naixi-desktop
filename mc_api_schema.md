# 奶昔游戏 Agent · 客户端只读 Mod API 契约

> 目的：让 AI 像真人一样操控用户**单机**角色，但把"感知源"从「截屏→视觉模型」升级为
> 「客户端只读 Mod 暴露的本机只读 API」——LLM 直接拿到精确世界态，决策质量远超像素猜测。
>
> **这是用户 2026-08-03 明确批准的约束 #1 字面 localhost 例外**：Mod 只装在**用户自己的单机
> Java 客户端**里，本机暴露**只读** HTTP 端点，动作仍由现有键鼠注入**同一客户端、用户角色**。
> Mod **绝不发任何游戏指令、绝不生成独立实体**（不是 bot，只是传感器）。
> multiplayer 服务端 / Open to LAN / 连服观察者 仍永久禁止。

## 端点

- 方法：`GET`
- 默认地址：`http://127.0.0.1:25566/state`（可用环境变量 `NAIXI_MC_API_URL` 覆盖）
- 返回：`application/json`，UTF-8，下面结构的快照（每请求实时生成）
- 超时：消费者侧 `0.6s`，连不上即视为 Mod 未运行 → 自动回退视觉 grounding

## JSON 结构

```json
{
  "player": {
    "x": 10.0, "y": 64.0, "z": -5.0,
    "yaw": 90.0, "pitch": 0.0,
    "hp": 18.0,
    "on_ground": true,
    "in_water": false
  },
  "entities": [
    {
      "type": "zombie",
      "x": 12.0, "y": 64.0, "z": -5.0,
      "dist": 2.0,
      "rel_bearing": 5.0,
      "dy": 0.0,
      "hostile": true,
      "category": "hostile"
    }
  ],
  "resources": [
    {
      "type": "oak_log",
      "x": 10.0, "y": 68.0, "z": -5.0,
      "dist": 4.0,
      "rel_bearing": 2.0
    }
  ],
  "aim": {
    "mx": 30.0, "my": -10.0,
    "category": "hostile",
    "dist": 2.0
  }
}
```

## 字段定义

### `player`
| 字段 | 类型 | 说明 |
|------|------|------|
| `x,y,z` | float | 玩家精确坐标（方块坐标，含小数） |
| `yaw` | float | 水平朝向角（度，0=朝 -Z，顺时针增加；与 MC 一致） |
| `pitch` | float | 俯仰角（度，负=抬头看天，正=低头看地） |
| `hp` | float | 当前血量（0~20，饥饿/困难模式可能更高上限）；未知可省略 |
| `on_ground` | bool | 是否站在地面上 |
| `in_water` | bool | 是否在水中 |

### `entities[]`（周围实体：怪物/动物/掉落物/其他玩家客户端可见者）
| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 实体 ID，如 `zombie`/`skeleton`/`cow`/`item`/`arrow` |
| `x,y,z` | float | 实体世界坐标 |
| `dist` | float | 到玩家的欧氏距离（方块） |
| `rel_bearing` | float | **以玩家为原点**的相对方位角（度）：0=正前方，正=玩家右侧，负=左侧，±180=正后方 |
| `dy` | float | 目标相对玩家脚底的垂直差（正=在上方，用于瞄头部/方块） |
| `hostile` | bool | 是否敌对（僵尸/骷髅/蜘蛛/苦力怕等） |
| `category` | string | `hostile` / `animal` / `item` / `other` |

### `resources[]`（附近可采集方块，可选；由 Mod 在玩家前方锥体内粗略枚举）
| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 方块 ID，如 `oak_log`/`stone`/`coal_ore` |
| `x,y,z` | float | 方块坐标 |
| `dist` | float | 距离 |
| `rel_bearing` | float | 相对方位角（同上） |

### `aim`（看向目标所需的鼠标增量，由 Mod 按灵敏度反算）
> 这是"瞄准闭环"的关键：消费者把 `(mx,my)` 当作相对鼠标位移注入，逐帧闭合修正直到对准。
| 字段 | 类型 | 说明 |
|------|------|------|
| `mx` | float | 水平鼠标增量（正=右转，负=左转），单位≈像素位移 |
| `my` | float | 垂直鼠标增量（正=低头，负=抬头） |
| `category` | string | 当前准星所瞄目标的类别（`hostile`/`animal`/`resource`/`none`） |
| `dist` | float | 瞄准目标距离；无目标时整体省略 `aim` 字段 |

## 消费者侧约定（game_agent.py）
- 首选 `_grounding_http`：GET 成功 → `_ingest_api_state` 归一化进 `self._world`，并据 `aim` 设 `self._aim`/`_aim_cat`/`_aim_dist`。
- `threats` = `hostile && dist<=14`；`objects` = 非 hostile 的 animal/item；`resources` 直采。
- 消费者**只读取**，从不向该端点 POST 任何指令——动作一律走 `_execute` 键鼠注入同一客户端。
- `ground_ok=False`（Mod 未装/未跑/超时）→ 自动回退 `_vision_ground`（截屏→VL→场景图）。

## 红线（实现 Mod 时务必遵守）
1. 端点**只读**：绝不接受任何写入/指令；绝不调用 `setVelocity`/`lookAt`/`swing` 等改变游戏状态的 API。
2. 绝不 `spawn`/`addEntity`——不创建任何独立实体（不是 bot）。
3. 只在 `127.0.0.1` 监听，不暴露到 `0.0.0.0`（防止被局域网其它机器读取）。
4. 仅在用户自己的单机客户端运行，不依赖任何 multiplayer 服务端。
