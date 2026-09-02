# Naixi 客户端只读 Mod（单机 AI 操控的感知源）

> **这是什么**：一个 Fabric Mod，只在**你自己的单机 Java 客户端**里运行，本机暴露一个
> **只读** HTTP 端点 `http://127.0.0.1:25566/state`，把你的角色世界态（坐标/朝向/血量/
> 周围实体/准星方块/瞄准增量）以 JSON 形式提供给奶昔后端。
>
> **它绝不发任何游戏指令、绝不生成独立实体**——不是 bot，只是个传感器。动作仍由奶昔后端
> 用键鼠注入**同一个客户端、你自己的角色**（见 `desktop_core/game_agent.py`）。
>
> 这是用户 2026-08-03 明确批准的「不连服」铁律的**唯一例外**（约束 #1 字面 localhost 开例外）。

## 状态 JSON 契约
见 `D:/naixi_desktop/mc_api_schema.md`（消费者 `game_agent._ingest_api_state` 按此解析）。

## 安装（一次性）
1. 装 Java 17+（MC 1.20.4 需 Java 17/21）。
2. 装 Fabric 加载器：https://fabricmc.net/use/ 下载 `fabric-installer`，装到你的 MC 目录。
3. 启动一次 Fabric 客户端，确认能进单机世界（生成 `fabric` 配置档）。
4. 把本 Mod 打成的 `naixi-readonly-mod-1.0.0.jar` 放进 `.minecraft/mods/`。
5. 进单机世界 → Mod 自动在 `127.0.0.1:25566` 起只读 API。验证：`curl http://127.0.0.1:25566/state` 应返回 JSON。

## 构建（开发者侧，需联网拉 gradle 依赖）
```bash
cd mc_readonly_mod
./gradlew build            # Linux/macOS
gradlew.bat build         # Windows
# 产物：build/libs/naixi-readonly-mod-1.0.0.jar
```

## 校准（若 AI 瞄准越转越偏）
- Mod 端：`NaixiReadonlyMod.java` 里 `DEG_PER_PIXEL`（默认 0.15）按你的鼠标灵敏度微调。
- 后端端：环境变量 `NAIXI_AIM_SIGN`（默认 1，若左右/上下反了改 `-1`）。
- 端点地址可用 `NAIXI_MC_API_URL` 覆盖；感知源切换用 `NAIXI_GROUNDING_SRC`（`auto`/`http`/`vision`）。

## 红线（实现/使用务必遵守）
1. 端点**只读**：绝不接受写入/指令；绝不调用 `setVelocity`/`lookAt`/`swing` 等改变游戏状态 API。
2. 绝不 `spawn`/`addEntity`——不创建任何独立实体（不是 bot）。
3. 只在 `127.0.0.1` 监听，不暴露 `0.0.0.0`。
4. 仅限用户自己的单机客户端，不依赖任何 multiplayer 服务端 / Open to LAN。
