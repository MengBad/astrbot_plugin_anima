"""
MergedEvalMixin —— v0.9.2 沉淀三调用合并
=====================================

把沉淀流程里串行发起的三次独立内部 LLM 调用——情绪评估、关系推断、欲望生成——
合并为**一次结构化 JSON 内部 LLM 调用**，约省 2/3 内部 token。

组件：
- MergedResult         ：合并评估器的返回结构（emotion_score / relationships / desire）
- _build_merged_prompt ：纯函数，按开关条件化拼装提示词与"请求字段集合"
- _parse_merged_response：纯函数，剥围栏 → JSON 解析 → 逐级降级
- _apply_relationships_from_map / _apply_desire_from_text：下游统一写入（新旧路径共用）
- _merged_evaluate     ：编排单次合并调用（组装 → provider → 调用 → 解析 → 埋点）

设计原则见 .kiro/specs/merge-sediment-llm-calls/design.md：
- 下游零改动：合并只改"如何取得三类结果"，不改"取得后怎么用"。
- 纯逻辑可测：组装与解析为不调 LLM 的纯函数。
- 降级不反噬节省：解析失败绝不回退旧路径三次调用。
- 可逆：默认走旧路径，开关关闭即完全恢复 v0.9.1 行为。

依赖宿主类（AnimaPlugin）提供：self.config / self.context / self._get_provider_id /
self._stat_bump / self._is_rejected / self._is_desire_already_expressed /
self._read_worldview / self._write_worldview / self._read_desires / self._write_desires /
self._get_event_umo。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


@dataclass
class MergedResult:
    """合并评估器的返回结构。

    - emotion_score：恒为 [0.0, 1.0] 内的浮点数；任何失败路径回退 0.0。
    - relationships：None 表示本轮不写关系（未请求/缺失/非映射/解析失败降级）；
                     dict 表示候选映射（可能为空 dict，下游对空 dict 视为无写入）。
    - desire：None 表示本轮不产欲望；str 表示候选欲望文本（仍需下游过滤）。
    """
    emotion_score: float = 0.0
    relationships: Optional[dict] = None
    desire: Optional[str] = None


# 关系推断上限（与旧 _danger_relationship_inference 保持一致）
_MAX_RELATIONSHIPS = 30
# 合并调用超时（秒），与旧三调用一致
_MERGED_TIMEOUT = 15.0


class MergedEvalMixin:
    """沉淀三调用合并 mixin。所有方法依赖宿主类提供的 self.* 状态。"""

    # ── Prompt_Assembler（纯函数） ────────────────────────────────────────────

    def _build_merged_prompt(
        self,
        event: AstrMessageEvent,
        response_text: str,
        sylanne_state: str,
        *,
        relationship_on: bool,
        desire_on: bool,
    ) -> "tuple[str, frozenset]":
        """按开关条件化拼装合并提示词与请求字段集合。

        返回 (prompt, requested)：
        - requested ⊆ {"emotion_score","relationships","desire"}，"emotion_score" 恒在。
        - relationship_on：调用方按 (danger_relationship_inference and worldview_enabled) 计算。
        - desire_on：调用方按 (desire_enabled and bool(sylanne_state)) 计算。

        纯函数：不读配置、不读文件、不调用 LLM。
        """
        user_text = (getattr(event, "message_str", "") or "") if event is not None else ""

        requested = {"emotion_score"}
        # 字段说明分段
        field_specs = [
            '  "emotion_score": 0到1之间的浮点数，'
            "0=完全平淡的日常闲聊，1=极度强烈的情绪波动（被深深触动/愤怒/悲伤/狂喜等）。"
            "普通打招呼、闲聊、回答问题通常 0.1-0.3。"
        ]
        # 任务说明分段
        task_lines = [
            "你在帮一个 AI 聊天角色做内部评估。请只返回一个 JSON 对象，不要任何额外文字、不要 Markdown 代码块。",
            "",
            "需要评估的对话：",
            f"用户说：{user_text[:200]}",
            f"回复：{response_text[:300]}",
        ]

        if relationship_on:
            requested.add("relationships")
            field_specs.append(
                '  "relationships": 从对话推断的群友人际关系，'
                '格式 {"user_id_1 -> user_id_2": "关系描述"}；无法推断则为 {}。'
            )

        if desire_on:
            requested.add("desire")
            field_specs.append(
                '  "desire": 这个角色此刻想做的事、想知道的事、或想对某人说的话，用一句话描述；'
                '没有则为 "无" 或 null。'
            )
            task_lines.append(f"当前关系状态：{(sylanne_state or '')[:200]}")

        # 组装 JSON 骨架说明
        prompt_parts = list(task_lines)
        prompt_parts.append("")
        prompt_parts.append("返回的 JSON 字段说明：")
        prompt_parts.append("{")
        prompt_parts.append(",\n".join(field_specs))
        prompt_parts.append("}")
        prompt_parts.append("")
        prompt_parts.append("再次强调：只输出这一个 JSON 对象本身。")

        return "\n".join(prompt_parts), frozenset(requested)

    # ── Response_Parser（纯函数） ─────────────────────────────────────────────

    def _parse_merged_response(self, text: str, requested: frozenset) -> MergedResult:
        """剥围栏 → JSON 解析 → 字段钳制；失败逐级降级。

        纯函数：不调用 LLM、不回退旧路径。
        """
        if not text:
            return MergedResult(emotion_score=0.0)

        # 1. 剥 Markdown 围栏（与 _danger_relationship_inference 一致）
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

        # 2. JSON 解析
        try:
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                raise ValueError("非对象 JSON")
        except (json.JSONDecodeError, ValueError):
            # 3. 解析失败：正则提取首个 0–1 数字作情绪分，关系/欲望均跳过
            score = self._extract_first_unit_float(text)
            return MergedResult(emotion_score=score, relationships=None, desire=None)

        # JSON 解析成功
        score = self._clamp_unit(data.get("emotion_score"))

        relationships = None
        if "relationships" in requested:
            rel = data.get("relationships")
            if isinstance(rel, dict) and rel:
                relationships = rel

        desire = None
        if "desire" in requested:
            d = data.get("desire")
            if isinstance(d, str):
                desire = d

        return MergedResult(emotion_score=score, relationships=relationships, desire=desire)

    @staticmethod
    def _clamp_unit(value) -> float:
        """把任意值钳制到 [0.0, 1.0]；非数字（含缺失）返回 0.0。"""
        if isinstance(value, bool):
            # 避免 True/False 被当 1/0
            return 0.0
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        # 字符串形式的数字也尽力接受
        if isinstance(value, str):
            try:
                return max(0.0, min(1.0, float(value.strip())))
            except (ValueError, AttributeError):
                return 0.0
        return 0.0

    @staticmethod
    def _extract_first_unit_float(text: str) -> float:
        """从文本中正则提取首个 0–1 之间的数字（钳制后）；提不到返回 0.0。"""
        if not text:
            return 0.0
        m = re.search(r'(?<![\d.])(0?\.\d+|0|1(?:\.0+)?)(?![\d.])', text)
        if not m:
            return 0.0
        try:
            return max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            return 0.0

    # ── 下游统一写入（新旧路径共用） ──────────────────────────────────────────

    def _apply_relationships_from_map(self, relations: object) -> None:
        """把关系映射写入 worldview.relationships（含 _is_rejected 过滤与 cap 30）。
        relations 非 dict 或为空时静默跳过；任何情形不抛异常。"""
        try:
            if not isinstance(relations, dict) or not relations:
                return
            # 对关系文本做拒答过滤（与旧路径对 LLM 文本过滤同思路）
            try:
                rel_text = json.dumps(relations, ensure_ascii=False)
            except Exception:
                rel_text = str(relations)
            if self._is_rejected(rel_text):
                return
            wv = self._read_worldview()
            if "relationships" not in wv or not isinstance(wv.get("relationships"), dict):
                wv["relationships"] = {}
            wv["relationships"].update(relations)
            if len(wv["relationships"]) > _MAX_RELATIONSHIPS:
                wv["relationships"] = dict(
                    list(wv["relationships"].items())[-_MAX_RELATIONSHIPS:]
                )
            self._write_worldview(wv)
            logger.debug(f"[Anima] 关系写入（合并路径）: {list(relations.keys())}")
        except Exception as e:
            logger.debug(f"[Anima] 关系写入异常: {e}")

    async def _apply_desire_from_text(
        self, desire_text: object, response_text: str, event: AstrMessageEvent
    ) -> None:
        """把欲望文本经既有过滤后写入欲望队列。
        退化值/命中拒答/队列满/已表达 → 不写；任何情形不抛异常。"""
        try:
            if not isinstance(desire_text, str):
                return
            result = desire_text.strip()
            # 退化值过滤
            if not result or result == "无" or len(result) <= 2:
                return
            # 拒答过滤
            if self._is_rejected(result):
                return
            desires = self._read_desires()
            max_queue = self.config.get("desire_max_queue", 5)
            if len(desires) >= max_queue:
                return
            # 去重：已在 bot 回复里表达过则跳过
            if await self._is_desire_already_expressed(result, response_text, event):
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 欲望已在回复中表达，跳过（合并路径）: {result[:40]}")
                return
            sender_id = ""
            if hasattr(event, "message_obj") and event.message_obj:
                sender_id = getattr(event.message_obj.sender, "user_id", "")
            new_desire = {
                "id": f"desire_{int(time.time())}",
                "content": result,
                "source": "relationship",
                "kind": "outward",
                "intensity": 0.7,
                "created_at": datetime.now().isoformat(),
                "target_user": sender_id,
                "target_umo": self._get_event_umo(event),
                "satisfied": False,
            }
            desires.append(new_desire)
            self._write_desires(desires)
            self._stat_bump("desire.created.outward")
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 新欲望（合并路径）: {result[:50]}")
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 欲望写入异常: {e}")

    # ── Merged_Evaluator（编排） ─────────────────────────────────────────────

    async def _merged_evaluate(
        self,
        event: AstrMessageEvent,
        response_text: str,
        sylanne_state: str,
    ) -> MergedResult:
        """单次结构化合并调用，产出情绪分 / 关系映射 / 欲望。

        任意失败路径都返回安全的 MergedResult（emotion_score=0.0, None, None），
        绝不抛异常、绝不回退旧的三次分离调用。
        """
        # 计算两个子任务的"是否请求"布尔
        relationship_on = bool(
            self.config.get("danger_relationship_inference", False)
            and self.config.get("worldview_enabled", False)
        )
        desire_on = bool(
            self.config.get("desire_enabled", False) and bool(sylanne_state)
        )

        prompt, requested = self._build_merged_prompt(
            event,
            response_text,
            sylanne_state,
            relationship_on=relationship_on,
            desire_on=desire_on,
        )

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return MergedResult(emotion_score=0.0)

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=_MERGED_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[Anima] 合并评估超时")
            return MergedResult(emotion_score=0.0)
        except Exception as e:
            logger.warning(f"[Anima] 合并评估失败: {e}")
            return MergedResult(emotion_score=0.0)

        # 实际完成一次物理调用后才计数（无论解析成败）
        self._stat_bump("llm.sediment_merged")

        if not llm_resp or not getattr(llm_resp, "completion_text", None):
            return MergedResult(emotion_score=0.0)

        return self._parse_merged_response(llm_resp.completion_text, requested)
