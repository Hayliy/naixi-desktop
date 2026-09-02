// mc_observer.cjs —— 只读世界观察者（作弊级 grounding 数据源）
//
// 设计目标（对齐用户要求）：
//   1. 奶昔是「玩家」，通过键盘鼠标操控【用户的真实角色】，绝不生成独立 bot 来玩。
//   2. 但外挂脚本之所以各种能玩，是因为它握有游戏世界的【精确真相】。
//      本观察者就是奶昔的「真相传感器」：连进用户所在的世界（LAN 或 localhost 服务端），
//      只读不写地采集——用户角色坐标/朝向/血量、周围实体（敌对/动物/物品）的类型距离方位、
//      附近可采集方块——写入 naixi_grounding.json。
//   3. 观察者自身是一个 Mineflayer 客户端实体，但它【永不 move/look/attack/use】，
//      纯粹是传感器。真正的「玩」由 game_agent 用键鼠操控用户角色完成。
//
// 用法：
//   node mc_observer.cjs <port> [host] [playerName]
//   环境变量：NAIXI_GROUNDING=输出json路径（默认 <desktop_core>/../data/naixi_grounding.json）
//             NAIXI_PLAYER_NAME=要操控的用户角色名（默认取第一个非观察者玩家）
//             NAIXI_AIM_SIGN=瞄准鼠标符号（默认 -1；若发现越转越偏改成 1）
//             NAIXI_AIM_PX=每度像素（默认 8）
//
const fs = require("fs");
const path = require("path");
const mineflayer = require("mineflayer");

const PORT = parseInt(process.argv[2] || "25565", 10);
const HOST = process.argv[3] || "localhost";
const PLAYER_HINT = process.argv[4] || process.env.NAIXI_PLAYER_NAME || null;

const GROUNDING_PATH = process.env.NAIXI_GROUNDING
  || path.join(__dirname, "..", "data", "naixi_grounding.json");
fs.mkdirSync(path.dirname(GROUNDING_PATH), { recursive: true });

const AIM_SIGN = (process.env.NAIXI_AIM_SIGN === "1") ? 1 : -1;
const AIM_PX = parseFloat(process.env.NAIXI_AIM_PX || "8");

// 单实例锁，避免重复观察者双写同一文件
const LOCK = path.join(path.dirname(GROUNDING_PATH), "mc_observer.lock");
if (fs.existsSync(LOCK)) {
  try {
    const pid = parseInt(fs.readFileSync(LOCK, "utf8").trim(), 10);
    if (pid && pid !== process.pid) {
      try { process.kill(pid, 0); console.log(`[observer] 已有实例 pid=${pid} 在跑，退出`); process.exit(0); }
      catch (e) { /* 陈旧锁 */ }
    }
  } catch (e) {}
}
fs.writeFileSync(LOCK, String(process.pid));

// 感兴趣的方块（采集目标）：原木/树叶/石头/各类矿石/沙/泥土
const INTEREST_BLOCKS = new Set([
  "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log", "mangrove_log",
  "oak_leaves", "birch_leaves", "spruce_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves",
  "stone", "cobblestone", "coal_ore", "iron_ore", "copper_ore", "gold_ore", "diamond_ore",
  "sand", "dirt", "grass_block", "andesite", "granite", "diorite", "deepslate", "tuff",
]);
// 敌对生物（攻击目标）
const HOSTILE = new Set([
  "zombie", "skeleton", "creeper", "spider", "cave_spider", "enderman", "witch", "slime",
  "husk", "drowned", "phantom", "zombie_villager", "piglin", "hoglin", "blaze", "ghast",
  "guardian", "elder_guardian", "magma_cube", "zoglin", "ravager", "shulker", "silverfish",
  "vex", "pillager", "vindicator", "evoker", "ravager",
]);
const ANIMAL = new Set([
  "cow", "sheep", "pig", "chicken", "horse", "donkey", "mule", "rabbit", "wolf", "cat",
  "villager", "fox", "bee", "llama", "mooshroom", "panda", "turtle", "strider", "axolotl",
  "goat", "sniffer", "camel", "fish", "salmon", "cod", "tropical_fish",
]);

function normAngle(a) { // 归一化到 (-180, 180]
  while (a > 180) a -= 360;
  while (a <= -180) a += 360;
  return a;
}

let bot = null;
let lastTick = 0;

function findTargetPlayer() {
  if (!bot || !bot.entities) return null;
  const players = [];
  for (const e of Object.values(bot.entities)) {
    if (e.type === "player" && e.username && e.username !== bot.username && e.position) {
      if (!PLAYER_HINT || e.username === PLAYER_HINT) players.push(e);
    }
  }
  if (players.length) return players[0];
  // 没找到其他玩家时，退化用观察者自身（仅用于无用户联机时的自测）
  return bot.entity;
}

function aimTo(fromPos, fromYawDeg, fromPitchDeg, targetPos, targetEye) {
  // 复制 Mineflayer lookAt 的 yaw/pitch 约定，算出「看向目标」所需角度
  const dx = targetPos.x - fromPos.x;
  const dy = (targetEye != null ? targetEye : targetPos.y) - fromPos.y;
  const dz = targetPos.z - fromPos.z;
  const horiz = Math.sqrt(dx * dx + dz * dz);
  const desiredYaw = Math.atan2(dx, -dz) * 180 / Math.PI;
  const desiredPitch = Math.atan2(-dy, horiz) * 180 / Math.PI;
  const dYaw = normAngle(desiredYaw - fromYawDeg);
  const dPitch = normAngle(desiredPitch - fromPitchDeg);
  // 鼠标：右移(dx>0)在 MC 原始输入下使 yaw 减小 → 乘 AIM_SIGN（默认 -1）
  const mx = AIM_SIGN * dYaw * AIM_PX;
  const my = dPitch * AIM_PX; // 抬头(pitch负)→鼠标上移(my负)
  return { mx, my, dYaw, dPitch, dist: Math.sqrt(dx * dx + dy * dy + dz * dz) };
}

function collectGrounding() {
  if (!bot || !bot.entity) return;
  const t0 = Date.now();
  const tp = findTargetPlayer();
  const playerPos = tp ? tp.position : bot.entity.position;
  const playerYaw = tp ? (tp.yaw || 0) : (bot.entity.yaw || 0);
  const playerPitch = tp ? (tp.pitch || 0) : (bot.entity.pitch || 0);

  const out = {
    ts: t0,
    observer: bot.username,
    player: {
      name: tp ? tp.username : null,
      x: +playerPos.x.toFixed(2), y: +playerPos.y.toFixed(2), z: +playerPos.z.toFixed(2),
      yaw: +playerYaw.toFixed(1), pitch: +playerPitch.toFixed(1),
      on_ground: tp ? !!tp.onGround : !!bot.entity.onGround,
      in_water: tp ? !!tp.inWater : false,
      hp: tp && tp.health != null ? +tp.health.toFixed(1) : null,
      food: tp && tp.food != null ? tp.food : null,
    },
    entities: [],
    resources: [],
    aim: null,
  };

  // 周围实体
  for (const e of Object.values(bot.entities)) {
    if (e === bot.entity) continue;
    if (!e.position) continue;
    const dx = e.position.x - playerPos.x;
    const dz = e.position.z - playerPos.z;
    const dy = e.position.y - playerPos.y;
    const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (dist > 32) continue;
    const type0 = (e.name || e.type || "unknown").toLowerCase();
    const isHostile = HOSTILE.has(type0);
    const isAnimal = ANIMAL.has(type0);
    const isItem = type0.includes("item") || (e.type === "object" && !isHostile && !isAnimal);
    const isOtherPlayer = (e.type === "player");
    let category = "other";
    if (isHostile) category = "hostile";
    else if (isAnimal) category = "animal";
    else if (isItem) category = "item";
    else if (isOtherPlayer) category = "player";
    // 相对方位（以玩家为原点、第一人称）：用于决策
    const bearing = normAngle(Math.atan2(dx, -dz) * 180 / Math.PI - playerYaw);
    out.entities.push({
      id: e.id, type: type0, category, dist: +dist.toFixed(1),
      rel_bearing: +bearing.toFixed(1), dy: +dy.toFixed(1),
      x: +e.position.x.toFixed(2), y: +e.position.y.toFixed(2), z: +e.position.z.toFixed(2),
    });
  }
  out.entities.sort((a, b) => a.dist - b.dist);

  // 附近可采集方块
  try {
    const blocks = bot.findBlocks({
      matching: (b) => INTEREST_BLOCKS.has(b.name),
      maxDistance: 16, count: 24,
    });
    const seen = new Map();
    for (const p of blocks) {
      const b = bot.blockAt(p);
      if (!b) continue;
      const key = b.name;
      if (!seen.has(key)) {
        const dx = p.x - playerPos.x, dy = p.y - playerPos.y, dz = p.z - playerPos.z;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        seen.set(key, {
          type: b.name, dist: +dist.toFixed(1),
          x: p.x, y: p.y, z: p.z,
          rel_bearing: +normAngle(Math.atan2(dx, -dz) * 180 / Math.PI - playerYaw).toFixed(1),
        });
      }
      if (seen.size >= 12) break;
    }
    out.resources = [...seen.values()].sort((a, b) => a.dist - b.dist);
  } catch (e) {}

  // 自动选取当前瞄准目标（最近敌对 > 最近动物 > 最近资源），算出鼠标增量
  // 资源需 dist>2.5，避免瞄着脚底下方块挖（外挂脚本也会跳过脚下不可达方块）
  const target =
    out.entities.find((e) => e.category === "hostile" && e.dist <= 12) ||
    out.entities.find((e) => e.category === "animal" && e.dist <= 10) ||
    out.resources.find((r) => r.dist > 2.5 && r.dist <= 12) || null;
  if (target) {
    const tpos = { x: target.x, y: target.y, z: target.z };
    // 实体看胸口(+1.2)，方块看中心(+0.5)
    const eye = (target.category === "hostile" || target.category === "animal") ? target.y + 1.2 : target.y + 0.5;
    const a = aimTo(playerPos, playerYaw, playerPitch, tpos, eye);
    out.aim = {
      target_id: target.id != null ? target.id : `${target.type}@${target.x},${target.y},${target.z}`,
      target_type: target.type, category: target.category || "resource",
      mx: +a.mx.toFixed(1), my: +a.my.toFixed(1),
      d_yaw: +a.dYaw.toFixed(1), d_pitch: +a.dPitch.toFixed(1), dist: +a.dist.toFixed(1),
    };
  }

  try { fs.writeFileSync(GROUNDING_PATH, JSON.stringify(out, null, 2)); } catch (e) {}
  lastTick = t0;
}

function connect() {
  bot = mineflayer.createBot({
    host: HOST, port: PORT, username: "NaixiSensor",
    version: false, // 自动协商
    hideErrors: true,
  });
  bot.on("spawn", () => { console.log(`[observer] 已连入 ${HOST}:${PORT}，观察者=${bot.username}`); });
  bot.on("error", (e) => console.log(`[observer] error: ${e.message}`));
  bot.on("end", () => { console.log("[observer] 断开，3s 后重连"); setTimeout(connect, 3000); });
  // 心跳：即便世界静止也持续写 grounding（含瞄准增量）
  setInterval(() => { if (bot && bot.entity) collectGrounding(); }, 250);
}

process.on("SIGINT", () => {
  try { fs.unlinkSync(LOCK); } catch (e) {}
  try { if (bot) bot.end(); } catch (e) {}
  process.exit(0);
});
process.on("exit", () => { try { fs.unlinkSync(LOCK); } catch (e) {} });

console.log(`[observer] 启动：host=${HOST} port=${PORT} grounding=${GROUNDING_PATH}`);
connect();
