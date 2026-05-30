"""
RuminationMixin —— 模块五矛盾 + 六反刍 + 七溯源
====================================
v0.8.0 从 main.py 抽出：# ==================== 模块五：矛盾检测 ====================; # ==================== 模块六：离线反刍 ====================; # ==================== 模块七：溯源查询 ====================

依赖宿主类（AnimaPlugin）提供 self.* 状态字段（self.config / self.context / self.data_dir / self._io_lock 等）。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import LLMResponse, ProviderRequest

from ..filters import is_rejected as _ext_is_rejected, is_sensitive as _ext_is_sensitive
from ..similarity import (
    text_token_set as _ext_text_token_set,
    jaccard_similarity as _ext_jaccard,
    cosine_similarity as _ext_cosine,
)
from ..forgetting import apply_forgetting as _ext_apply_forgetting
from ..valence import (
    estimate_memory_valence as _ext_estimate_valence,
    rerank_memories_by_emotion as _ext_rerank_memories,
)


class RuminationMixin:
    """模块五矛盾 + 六反刍 + 七溯源 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _read_contradictions(self) -> list:
        """读取历史矛盾记录"""
        return self._read_json(self.contradictions_path, default=[])

    def _write_contradictions(self, data: list):
        """写入矛盾记录"""
        self._write_json(self.contradictions_path, data)

    async def _maybe_detect_contradiction(self, event: AstrMessageEvent):
        """每 contradiction_interval 次沉淀触发一次矛盾检测"""
        if not self.config.get("contradiction_enabled", False):
            return
        interval = self.config.get("contradiction_interval", 50)
        if self._sediment_count % interval != 0:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            notes = self._read_self_notes()
            if not notes or len(notes) < 200:
                return

            prompt = (
                "你正在帮助一个 AI 聊天角色进行自我审视。"
                "分析以下内心独白记录，找出前后矛盾的立场或认知。\n"
                "如果有矛盾，用一句话描述这个矛盾。如果没有，只回复'无'。\n\n"
                f"内心独白记录：\n{notes[-2000:]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=20.0,
            )
            if hasattr(self, "_stat_bump"):
                self._stat_bump("llm.contradiction")

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return
                if result and result != "无" and len(result) > 4:
                    # v0.9.6 语义去重：与近期矛盾（最近 10 条）比对，相似则整条跳过
                    # （不写 contradictions / 不写 self_notes / 不触发研究，避免重复噪音）
                    contradictions = self._read_contradictions()
                    try:
                        from ..capability_dedup import text_similarity as _ext_text_sim
                        dthreshold = float(self.config.get("dedup_text_threshold", 0.7))
                        if any(
                            _ext_text_sim(result, c.get("description", "")) >= dthreshold
                            for c in contradictions[-10:]
                        ):
                            if self.config.get("log_level") == "debug":
                                logger.debug(f"[Anima] 矛盾与近期记录相似，跳过: {result[:50]}")
                            return
                    except Exception:
                        pass

                    # 记录矛盾
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    entry = f"[{timestamp}] (矛盾感知) 我发现自己在某件事上前后不一致：{result}"
                    self._append_self_notes(entry)

                    # 存入矛盾历史 + v0.9.6 上限裁剪（此前无上限会无限膨胀）
                    contradictions.append({
                        "timestamp": datetime.now().isoformat(),
                        "description": result,
                    })
                    cmax = int(self.config.get("contradiction_max", 50))
                    contradictions = contradictions[-cmax:]
                    self._write_contradictions(contradictions)

                    self._append_evolution_log(
                        trigger="contradiction_detected",
                        old_summary="",
                        new_content=entry,
                    )
                    logger.info(f"[Anima] 检测到矛盾: {result[:80]}")

                    # Phase 6+: 矛盾往往意味着旧方法论失效 → 触发内部自主研究/能力重构
                    asyncio.create_task(self._initiate_self_directed_research(
                        "发现自我矛盾",
                        f"我在以下事情上矛盾了：{result[:150]}。我需要新的、更一致的处世方法。",
                        force=False
                    ))
        except asyncio.TimeoutError:
            logger.warning("[Anima] 矛盾检测超时")
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 矛盾检测失败: {e}")


    async def _register_rumination_cron(self, cron_expr: str):
        """注册反刍定时任务到 CronJobManager"""
        try:
            await self.context.cron_manager.add_basic_job(
                name="Anima 离线反刍",
                cron_expression=cron_expr,
                handler=self._rumination_task,
                description="定时对近期经历做反思，产生新的感悟",
                enabled=True,
                persistent=False,
            )
            logger.info("[Anima] 离线反刍定时任务注册成功")
        except Exception as e:
            logger.warning(f"[Anima] 注册反刍定时任务失败: {e}")

    async def _rumination_task(self):
        """定时反刍任务：对近期 self_notes 做反思"""
        if not self.config.get("rumination_enabled", False):
            return

        try:
            # 获取 provider：优先 internal，其次 last_active_umo，最后回退到第一个可用 provider
            provider_id = ""
            internal = self.config.get("internal_provider_id", "")
            if internal:
                provider_id = internal
            elif self._last_active_umo:
                try:
                    provider_id = await self.context.get_current_chat_provider_id(
                        umo=self._last_active_umo
                    )
                except Exception:
                    pass
            if not provider_id:
                providers = self.context.get_all_providers()
                if providers:
                    provider_id = providers[0].meta().id
            if not provider_id:
                return

            notes = self._read_self_notes()
            if not notes or len(notes) < 100:
                return

            prompt = (
                "你是一个 AI 聊天角色的内在意识。回顾最近的经历，"
                "有什么新的感悟或想法？用第一人称写 2-3 句话。\n"
                "不要重复已有的内容，要有新的角度。\n\n"
                f"最近的内心记录：\n{notes[-1500:]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=30.0,
            )
            if hasattr(self, "_stat_bump"):
                self._stat_bump("llm.rumination")

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return
                if result and len(result) > 10:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    entry = f"[{timestamp}] (离线反刍) {result}"
                    self._append_self_notes(entry)
                    # 同步编辑器
                    new_notes = self._read_self_notes()
                    self.config["self_notes_editor"] = new_notes
                    self._last_synced_editor_content = new_notes
                    self.config.save_config()
                    self._append_evolution_log(
                        trigger="rumination",
                        old_summary="",
                        new_content=entry,
                    )
                    logger.info(f"[Anima] 离线反刍完成: {result[:60]}")

                    # 反刍结果喂给欲望系统：判断是否产生新欲望
                    if self.config.get("desire_enabled", False):
                        await self._evaluate_desire_from_monologue(result)

                    # 检查是否产生压抑话题（想说但没说的意味）
                    suppress_signals = ["想", "没说", "没问", "忍", "憋", "不敢"]
                    if sum(1 for s in suppress_signals if s in result) >= 2:
                        self._add_suppressed_topic(
                            topic=result[:80],
                            source="rumination",
                        )

                    # Phase 6+: 能力缺口反思 —— 让角色在离线时思考“我在哪些方面还不够强？”
                    # 这是一个真正独立的人会做的事：自我审视技能树，发现盲区，产生学习欲望
                    try:
                        caps = self._read_personal_capabilities()
                        if caps.get("capabilities"):
                            # 偶尔触发（不是每次反刍都触发，避免噪音）
                            if len(caps["capabilities"]) % 3 == 0 or (datetime.now().hour % 4 == 0):
                                gap_prompt = (
                                    "回顾你最近的经历和现有的个人工具/方法，"
                                    "你觉得自己目前在哪个领域或哪类问题上还比较弱、缺乏有效的方法？\n"
                                    "用第一人称简短说出一两个具体的「能力缺口」，并说明为什么你觉得需要补上它。\n\n"
                                    f"你目前已有的个人能力：\n" + 
                                    "\n".join([f"- {c.get('name')}" for c in caps["capabilities"][-5:]])
                                )
                                gap_resp = await asyncio.wait_for(
                                    self.context.llm_generate(chat_provider_id=provider_id, prompt=gap_prompt),
                                    timeout=20.0,
                                )
                                if gap_resp and gap_resp.completion_text:
                                    gap_text = gap_resp.completion_text.strip()[:300]
                                    if gap_text and len(gap_text) > 15 and not self._is_rejected(gap_text):
                                        # 把能力缺口转化为一个强烈的、待满足的「学习欲望」
                                        if self.config.get("desire_enabled", False):
                                            desires = self._read_desires()
                                            desires.append({
                                                "id": f"cap_gap_{int(time.time())}",
                                                "content": f"我想学会/改进：{gap_text[:120]}",
                                                "intensity": 0.72,
                                                "source": "capability_gap_rumination",
                                                "kind": "inward",  # v0.9.0: 想学/改进能力 → 驱动自主研究，不直接外发
                                                "created_at": datetime.now().isoformat(),
                                                "target_umo": "",  # v0.8.0: 反刍产生的能力缺口是全局通用的
                                                "satisfied": False,
                                            })
                                            self._write_desires(desires)
                                            self._append_evolution_log(
                                                trigger="capability_gap_awareness",
                                                old_summary="",
                                                new_content=f"离线反刍中意识到能力缺口：{gap_text[:80]}",
                                            )
                    except Exception as gap_e:
                        logger.debug(f"[Anima] 能力缺口反思失败: {gap_e}")
        except asyncio.TimeoutError:
            logger.warning("[Anima] 离线反刍超时")
        except Exception as e:
            logger.warning(f"[Anima] 离线反刍失败: {e}")


    async def _trace_origin(self, event: AstrMessageEvent, keyword: str) -> str:
        """分析 evolution_log 中与关键词相关的条目，解释认知形成过程"""
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return "无法获取模型"

            logs = self._read_evolution_log(n=50)
            if not logs:
                return "暂无演化记录"

            log_text = "\n".join(
                f"[{r.get('timestamp', '?')}] ({r.get('trigger', '?')}) {r.get('new_content', '')[:150]}"
                for r in logs
            )

            prompt = (
                "以下是一个 AI 聊天角色的自我认知演化记录。"
                f"请找出与「{keyword}」相关的条目，"
                "用叙事性语言解释这个认知是如何一步步形成的。\n"
                "如果找不到相关内容，说明没有找到。\n\n"
                f"演化记录：\n{log_text[-3000:]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=30.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return "模型拒绝回答此查询"
                return result
            return "未能生成分析"
        except asyncio.TimeoutError:
            return "溯源查询超时"
        except Exception as e:
            return f"溯源查询失败: {e}"
