/* Mineflayer 桥：把 Minecraft 三维世界转成「以玩家为原点」的结构化一维状态，
 * 周期性写入 NAIXI_MC_STATE 指向的文件，供奶昔 game_agent 直接读取（最强 grounding）。
 *
 * 用法：
 *   npm install mineflayer
 *   node mc_bridge.js            # 连 localhost:55916，端口可用参数覆盖
 *   node mc_bridge.js 25565 myuser
 *
 * 桥职责（关键）：把实体世界坐标 → 相对玩家的 方位 + 距离 + 距离标签 + 靠近/远离，
 * 不再让 LLM 从原始像素猜三维。这是所有能真玩的项目（mindcraft/SmithAI/Optimus-3）的共同做法。
 */

const fs = require("fs");
const path = require("path");
const mineflayer = require("mineflayer");

const PORT = parseInt(process.argv[2] || "55916", 10);
const HOST = process.argv[3] || "localhost";
const USERNAME = process.argv[4] || "NaixiBot";

// 状态落盘路径：game_agent 通过环境变量 NAIXI_MC_STATE 读这个文件
const STATE_PATH = process.env.NAIXI_MC_STATE
  || path.join(__dirname, "..", "data", "mc_state.json");
fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });

const HOSTILE = new Set([
  "zombie", "skeleton", "spider", "creeper", "enderman", "witch", "slime",
  "phantom", "drowned", "husk", "pillager", "ravager", "vex", "evoker",
  "blaze", "ghast", "guardian", "shulker", "silverfish", "cave_spider",
  "zombified_piglin", "hoglin", "piglin_brute", "warden", "ender_dragon",
  "wither", "zoglin", "magma_cube", "strider", "zombie_villager",
]);

// 以玩家为原点，把世界坐标差转成第一人称相对方位（前/后/左/右/上/下 + 组合）
function relDir(dx, dy, dz, yawDeg) {
  // yaw: 0=朝南(-Z)，90=朝西(-X)，180=朝北(+Z)，270=朝东(+X)。Minecraft 约定。
  const rad = (yawDeg * Math.PI) / 180;
  // 把世界位移旋到以玩家朝向为基准的局部坐标：x'=向前，y'=向右
  const forward = dx * -Math.sin(rad) + dz * -Math.cos(rad); // 朝前为正
  const right = dx * Math.cos(rad) + dz * -Math.sin(rad);    // 朝右为正
  const tags = [];
  if (forward > 1) tags.push("前");
  else if (forward < -1) tags.push("后");
  if (right > 1) tags.push("右");
  else if (right < -1) tags.push("左");
  if (dy > 1) tags.push("上");
  else if (dy < -1) tags.push("下");
  if (tags.length === 0) return "中";
  return tags.join("-");
}

function distLabel(d) {
  if (d < 3) return "近";
  if (d < 10) return "中";
  return "远";
}

let lastPos = null;
let lastT = Date.now();

const bot = mineflayer.createBot({
  host: HOST, port: PORT, username: USERNAME, version: false,
});

bot.on("spawn", () => {
  console.log(`[mc_bridge] 已连接板端 ${HOST}:${PORT}，开始导出状态到 ${STATE_PATH}`);
  tick();
  setInterval(tick, 250); // 4Hz 导出，足够 LLM 决策且省资源
});

bot.on("end", () => console.log("[mc_bridge] 断开"));
bot.on("error", (e) => console.log("[mc_bridge] 错误:", e.message));

function tick() {
  if (!bot.entity) return;
  const me = bot.entity.position;
  const now = Date.now();
  const dt = Math.max(1, now - lastT) / 1000;
  let speed = 0;
  if (lastPos) {
    speed = me.distanceTo(lastPos) / dt; // 格/秒
  }
  lastPos = me.clone();
  lastT = now;

  // 收集附近实体（半径 16 格内）
  const entities = [];
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (e === bot.entity || !e.position) continue;
    const d = e.position.distanceTo(me);
    if (d > 16) continue;
    const dx = e.position.x - me.x;
    const dy = e.position.y - me.y;
    const dz = e.position.z - me.z;
    const isHostile = HOSTILE.has(e.name) || (e.type === "mob" && HOSTILE.has(e.name));
    // 运动：与玩家相对位移速度
    let motion = "未知";
    if (e.velocity) {
      const vmag = Math.hypot(e.velocity.x, e.velocity.y, e.velocity.z);
      if (vmag > 0.15) motion = "移动";
      else motion = "静止";
    }
    entities.push({
      type: e.name || e.type || "entity",
      dir: relDir(dx, dy, dz, bot.entity.yaw || 0),
      distance: Math.round(d * 10) / 10,
      distance_label: distLabel(d),
      motion,
      hostile: !!isHostile,
    });
  }

  const state = {
    health: Math.round(bot.health || 0),
    position: { x: Math.round(me.x), y: Math.round(me.y), z: Math.round(me.z) },
    self_speed: Math.round(speed * 10) / 10,
    situation: speed > 0.2 ? "移动中" : "静止",
    entities,
    ts: now,
  };
  try {
    fs.writeFileSync(STATE_PATH, JSON.stringify(state));
  } catch (e) {
    // 忽略瞬时写失败
  }
}
