"""character_card.py — Brain 层：角色卡 v2（SillyTavern 规范）+ RisuAI 表情标签。

借鉴（只借鉴架构/规范，不引代码）：
- SillyTavern 角色卡 v2：name / description(persona) / personality / scenario /
  first_mes(greeting) / mes_example(example_dialogue) / lorebook
- RisuAI 的 Emotion Images：LLM 输出里带 [happy] / [thinking] 之类表情标签
  → 解析后驱动 Body 层（Live2D）立绘切换

设计约束：
- 本地私有、零第三方依赖（仅标准库 json）；
- 零正则（铁则）：表情标签解析用字符串扫描；
- 表情词走白名单，避免把普通方括号内容误判为表情。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional


# RisuAI 式表情白名单（Body 层立绘应支持的状态；不在表里的 [xxx] 视为普通文本）
_BRACKET_EMOTIONS = (
    "happy", "sad", "angry", "thinking", "surprised", "love", "shy",
    "sleepy", "excited", "neutral", "wink", "cry", "laugh", "confused",
    "cool", "panic",
)


@dataclass
class LoreEntry:
    keys: List[str] = field(default_factory=list)
    content: str = ""

    def to_dict(self) -> dict:
        return {"keys": self.keys, "content": self.content}

    @classmethod
    def from_dict(cls, d: dict) -> "LoreEntry":
        if not isinstance(d, dict):
            return cls()
        raw_keys = d.get("keys") or d.get("key") or []
        if isinstance(raw_keys, str):
            raw_keys = [raw_keys]
        return cls(keys=list(raw_keys), content=d.get("content", "") or "")


@dataclass
class CharacterCard:
    name: str = "奶昔"
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    lorebook: List[LoreEntry] = field(default_factory=list)
    voice: str = "zh-CN-XiaoxiaoNeural"  # 默认 TTS 音色（tts_router 的 model 串）

    # ── 序列化（兼容 SillyTavern v2 字段名）──
    def to_dict(self) -> dict:
        d = asdict(self)
        d["lorebook"] = [e.to_dict() for e in self.lorebook]
        d["char_name"] = self.name
        d["char_persona"] = self.description
        d["char_greeting"] = self.first_mes
        d["world_scenario"] = self.scenario
        d["example_dialogue"] = self.mes_example
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterCard":
        if not isinstance(d, dict):
            return cls()
        lore = d.get("lorebook") or []
        if isinstance(lore, dict):
            lore = lore.get("entries", [])
        lore = [x if isinstance(x, LoreEntry) else LoreEntry.from_dict(x) for x in lore]
        return cls(
            name=d.get("name") or d.get("char_name") or "奶昔",
            description=d.get("description") or d.get("char_persona") or "",
            personality=d.get("personality") or "",
            scenario=d.get("scenario") or d.get("world_scenario") or "",
            first_mes=d.get("first_mes") or d.get("char_greeting") or "",
            mes_example=d.get("mes_example") or d.get("example_dialogue") or "",
            lorebook=lore,
            voice=d.get("voice") or "zh-CN-XiaoxiaoNeural",
        )

    @classmethod
    def load(cls, path: str) -> "CharacterCard":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def build_system_prompt(card: CharacterCard, include_lore: bool = True) -> str:
    """把角色卡结构化为 Brain 的 system prompt（零正则，纯字符串拼接）。"""
    parts: List[str] = [f"你是桌宠 {card.name}。"]
    if card.description:
        parts.append(f"【人设】\n{card.description}")
    if card.personality:
        parts.append(f"【性格】\n{card.personality}")
    if card.scenario:
        parts.append(f"【场景】\n{card.scenario}")
    if include_lore and card.lorebook:
        lore_text = "\n".join(
            f"- {', '.join(e.keys)}: {e.content}" for e in card.lorebook if e.content
        )
        if lore_text:
            parts.append(f"【世界观/记忆碎片(lorebook)】\n{lore_text}")
    if card.mes_example:
        parts.append(f"【对话示例】\n{card.mes_example}")
    parts.append(
        "用简短、口语化、带情绪的中文回应，可在句首加 [表情] 标签"
        "（如 [happy]）来驱动你的立绘切换。"
    )
    return "\n\n".join(parts)


def extract_emotions(text: str):
    """解析 RisuAI 式 [emotion] 标签，返回 (clean_text, emotions)。

    - 仅识别白名单表情词（支持 [happy] 与 [emotion:happy] 两种写法）；
    - 字符串扫描，零正则；
    - 同表情保序去重；非表情方括号内容原样保留。
    """
    if not text:
        return "", []
    emotions: List[str] = []
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            end = text.find("]", i + 1)
            if end != -1:
                inner = text[i + 1:end].strip().lower()
                if ":" in inner:  # [emotion:happy]
                    inner = inner.split(":", 1)[1].strip()
                if inner in _BRACKET_EMOTIONS and inner not in emotions:
                    emotions.append(inner)
                    i = end + 1
                    continue
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip(), emotions


def render_first_mes(card: CharacterCard) -> str:
    """首条开场白（去除表情标签，供气泡显示）。"""
    clean, _ = extract_emotions(card.first_mes)
    return clean or f"我是{card.name}，很高兴见到你~"
