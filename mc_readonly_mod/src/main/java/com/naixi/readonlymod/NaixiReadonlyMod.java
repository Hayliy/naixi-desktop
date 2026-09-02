package com.naixi.readonlymod;

import com.google.gson.Gson;
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpExchange;
import net.fabricmc.api.ModInitializer;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.Entity;
import net.minecraft.entity.ItemEntity;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.entity.passive.AnimalEntity;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 奶昔 客户端只读 Mod（用户已批准的单机读取例外）。
 *
 * 红线（绝不可违反）：
 *  1) 端点只读——绝不接受任何写入/指令；绝不调用 setVelocity/lookAt/swing 等改变游戏状态的 API。
 *  2) 绝不 spawn/addEntity——不创建任何独立实体（不是 bot，只是传感器）。
 *  3) 只在 127.0.0.1 监听，不暴露到 0.0.0.0。
 *  4) 仅在用户自己的单机客户端运行，不依赖任何 multiplayer 服务端 / Open to LAN。
 *
 * 动作仍由奶昔后端的键鼠注入同一客户端（见 desktop_core/game_agent.py），本 Mod 不负责任何操控。
 */
public class NaixiReadonlyMod implements ModInitializer {
    public static final int PORT = 25566;
    private static final Gson GSON = new Gson();
    // 灵敏度校准：鼠标每像素约多少度（默认灵敏度近似）。若发现 AI 越转越偏，调此常数或 consumer 端 NAIXI_AIM_SIGN。
    private static final double DEG_PER_PIXEL = 0.15;
    private static final double MAX_PIXELS = 260.0;

    @Override
    public void onInitialize() {
        try {
            // 只绑定本机回环，拒绝外部连接
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            server.createContext("/state", new StateHandler());
            server.setExecutor(null);
            server.start();
            System.out.println("[NaixiReadonlyMod] 只读 API 已启动 http://127.0.0.1:" + PORT + "/state");
        } catch (Exception e) {
            System.err.println("[NaixiReadonlyMod] 启动失败: " + e);
        }
    }

    static class StateHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            Map<String, Object> state = buildState();
            String json = GSON.toJson(state);
            byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
            ex.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(bytes);
            }
        }
    }

    static Map<String, Object> buildState() {
        Map<String, Object> root = new HashMap<>();
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null || client.world == null) {
            return root; // 还没进游戏：返回空对象，consumer 侧会自动回退视觉
        }
        var player = client.player;

        // ── player ──
        Map<String, Object> p = new HashMap<>();
        p.put("x", player.getX());
        p.put("y", player.getY());
        p.put("z", player.getZ());
        p.put("yaw", player.getYaw());
        p.put("pitch", player.getPitch());
        p.put("hp", player.getHealth());
        p.put("on_ground", player.isOnGround());
        p.put("in_water", player.isSubmergedInWater());
        root.put("player", p);

        // ── entities ──
        List<Map<String, Object>> ents = new ArrayList<>();
        Entity best = null;
        double bestDist = Double.MAX_VALUE;
        for (Entity e : client.world.getEntities()) {
            if (e == player || e instanceof PlayerEntity) continue;
            double dist = player.distanceTo(e);
            Map<String, Object> m = new HashMap<>();
            Identifier id = Registries.ENTITY_TYPE.getId(e.getType());
            m.put("type", id.getNamespace().equals("minecraft") ? id.getPath() : id.toString());
            m.put("x", e.getX());
            m.put("y", e.getY());
            m.put("z", e.getZ());
            m.put("dist", dist);
            m.put("rel_bearing", relBearing(player, e));
            m.put("dy", e.getY() - player.getY());
            boolean hostile = e instanceof HostileEntity;
            m.put("hostile", hostile);
            m.put("category", hostile ? "hostile"
                    : (e instanceof AnimalEntity ? "animal"
                    : (e instanceof ItemEntity ? "item" : "other")));
            ents.add(m);
            if (hostile && dist <= 14 && dist < bestDist) {
                bestDist = dist;
                best = e;
            }
        }
        root.put("entities", ents);

        // ── resources：准星当前指向的方块（若有）──
        List<Map<String, Object>> res = new ArrayList<>();
        HitResult hit = client.crosshairTarget;
        if (hit instanceof BlockHitResult bhr) {
            BlockPos bp = bhr.getBlockPos();
            var bs = client.world.getBlockState(bp);
            Identifier bid = Registries.BLOCK.getId(bs.getBlock());
            Map<String, Object> r = new HashMap<>();
            r.put("type", bid.getNamespace().equals("minecraft") ? bid.getPath() : bid.toString());
            r.put("x", bp.getX());
            r.put("y", bp.getY());
            r.put("z", bp.getZ());
            r.put("dist", Math.sqrt(bp.getSquaredDistance(player.getPos(), false)));
            r.put("rel_bearing", relBearing(player, bp));
            res.add(r);
        }
        root.put("resources", res);

        // ── aim：朝最近敌对实体的鼠标增量（闭环对准用）──
        if (best != null) {
            double[] delta = aimDelta(player, best);
            Map<String, Object> aim = new HashMap<>();
            aim.put("mx", clamp(delta[0]));
            aim.put("my", clamp(delta[1]));
            aim.put("category", "hostile");
            aim.put("dist", bestDist);
            root.put("aim", aim);
        }
        return root;
    }

    /** 以玩家为原点：相对方位角(度) 0=正前, 正=右, 负=左 */
    static double relBearing(Entity player, Entity e) {
        return relBearingFromVec(player, e.getX() - player.getX(), e.getZ() - player.getZ());
    }
    static double relBearing(Entity player, BlockPos bp) {
        return relBearingFromVec(player, bp.getX() + 0.5 - player.getX(), bp.getZ() + 0.5 - player.getZ());
    }
    static double relBearingFromVec(Entity player, double dx, double dz) {
        double yaw = Math.toRadians(player.getYaw());
        double fx = -Math.sin(yaw), fz = -Math.cos(yaw); // 玩家前向水平向量（MC yaw:0=-Z）
        double len = Math.hypot(dx, dz);
        if (len < 1e-6) return 0;
        double dot = (dx * fx + dz * fz) / len;     // cos(夹角)
        double cross = (fx * dz - fz * dx) / len;   // sin(夹角)，右为正
        return Math.toDegrees(Math.atan2(cross, dot));
    }

    /** 把"看向目标"所需的 yaw/pitch 差换算成鼠标像素增量 */
    static double[] aimDelta(Entity player, Entity e) {
        double dx = e.getX() - player.getX();
        double dy = (e.getY() + e.getHeight() / 2.0) - (player.getY() + player.getEyeHeight());
        double dz = e.getZ() - player.getZ();
        double yawTo = Math.toDegrees(Math.atan2(-dx, -dz)); // MC yaw 约定
        double distH = Math.hypot(dx, dz);
        double pitchTo = Math.toDegrees(Math.atan2(-dy, distH));
        double dYaw = normDeg(yawTo - player.getYaw());
        double dPitch = normDeg(pitchTo - player.getPitch());
        return new double[]{dYaw / DEG_PER_PIXEL, dPitch / DEG_PER_PIXEL};
    }

    static double normDeg(double d) {
        while (d > 180) d -= 360;
        while (d < -180) d += 360;
        return d;
    }
    static double clamp(double v) {
        return Math.max(-MAX_PIXELS, Math.min(MAX_PIXELS, v));
    }
}
