"""
SedimentMixin —— 沉淀流程
=====================
v0.8.0 从 main.py 抽出：# ==================== 沉淀流程 ====================

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


class SedimentMixin:
    """沉淀流程 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    async def _sediment_process(self, event: AstrMessageEvent, response_text: str):
        """沉淀流程：评估情绪 -> 检索记忆 -> 生成独白 -> 存储"""
        if not self.config.get("enabled", True):
            return

        async with self._sediment_lock:
            try:
                # Phase 2: 压抑话题压力递增 + 伤痕衰减
                self._update_suppressed_pressure()
                self._decay_scar_sensitivity()

                # 欲望衰减（每次对话触发）
                if self.config.get("desire_enabled", False):
                    self._decay_desires()

                # Phase 2: 反馈闭环评估（v0.7.0: async + embedding）
                feedback = await self._evaluate_feedback(event)
                self._process_feedback(feedback, event)

                # Phase 2: 压抑话题释放检查
                combined_text = (event.message_str or "") + " " + response_text
                self._check_suppressed_resolution(combined_text)

                # 欲望满足检查（语义匹配优先）
                if self.config.get("desire_enabled", False):
                    combined = (event.message_str or "") + " " + response_text
                    await self._check_desire_satisfaction_semantic(combined, event)

                # 1. 存储对话到知识库（如果可用）
                # v0.8.5: 用户消息(in)和 bot 回复(out)独立限流，确保 bot 回复也能入库
                user_text = event.message_str or ""
                if user_text:
                    await self._store_memory(user_text, event, role="in")
                if response_text:
                    await self._store_memory(response_text, event, role="out")

                # 2. 评估情绪强度（伤痕维度放大）
                score = await self._evaluate_emotion(event, response_text)
                scar_mult = self._get_scar_multiplier(user_text + " " + response_text)
                if scar_mult > 1.0:
                    score = min(1.0, score * scar_mult)
                    logger.debug(f"[Anima] 伤痕放大情绪: ×{scar_mult:.1f} → {score:.2f}")

                # 极高情绪（>0.9）可能产生新伤痕
                if score > 0.9:
                    # 检测是否触及已知维度
                    for dim_kw in ["abandonment", "identity_denial", "trust_breach", "rejection", "being_replaced"]:
                        dim_words = {
                            "abandonment": ["离开", "不要我", "消失"],
                            "identity_denial": ["不是真的", "只是AI", "机器"],
                            "trust_breach": ["骗", "说谎", "假的"],
                            "rejection": ["讨厌", "滚", "闭嘴"],
                            "being_replaced": ["换一个", "新的", "别的AI"],
                        }
                        if any(w in user_text for w in dim_words.get(dim_kw, [])):
                            self._add_scar(dim_kw)
                            break

                threshold = self.config.get("emotion_threshold", 0.6)

                # 持久化情绪评分供上下文注入（原子读-改-写）
                def _update(state: dict):
                    state["last_emotion_score"] = score
                self._atomic_update_state(_update)

                # Phase 3: 记录用户情绪连续（用于跨关系传播）
                sender_uid = self._get_sender_user_id(event)
                self._update_user_low_emotion_streak(sender_uid, score)

                if self.config.get("log_level") == "debug":
                    logger.debug(
                        f"[Anima] 情绪评分: {score:.2f}, 阈值: {threshold}"
                    )

                if score < threshold:
                    return

                # 3. 检索相关记忆（如果知识库可用）
                query = f"{user_text} {response_text[:100]}"
                related_memories = await self._query_memory(query, n_results=3)

                # Phase 3: 记忆情绪染色重排（高情绪优先温暖记忆，低情绪优先冲突记忆）
                related_memories = self._rerank_memories_by_emotion(related_memories, score)

                # 3.5 唤醒被检索命中的旧记忆（重置时间戳）
                self._awaken_memories(related_memories)

                # 4. 生成内心独白
                monologue = await self._generate_monologue(
                    event, response_text, related_memories
                )
                if not monologue:
                    return

                # Phase 3: 根据独白 EMA 微调人格向量
                self._adjust_personality_from_monologue(monologue)

                # Phase 6+: 人格向量有明显变化时，触发内部能力反思/研究（更激进主动性）
                if abs(sum(self._get_personality_vector().values()) - 2.5) > 0.8:  # 简化漂移检测
                    asyncio.create_task(self._initiate_self_directed_research(
                        "人格倾向明显变化", "我的性格在改变，我需要新的方法来应对世界", force=False
                    ))

                # 5. 写入 self_notes，并同步到 WebUI 编辑器配置项
                # 敏感内容过滤
                if self._is_sensitive(monologue):
                    logger.warning("[Anima] 独白包含敏感内容，跳过写入")
                    return
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                entry = f"[{timestamp}] {monologue}"
                old_notes = self._read_self_notes()
                self._append_self_notes(entry)
                new_notes = self._read_self_notes()
                self.config["self_notes_editor"] = new_notes
                self._last_synced_editor_content = new_notes
                self.config.save_config()

                # 6. 记录演化日志
                self._append_evolution_log(
                    trigger=f"emotion_score={score:.2f}",
                    old_summary=old_notes[-200:] if old_notes else "",
                    new_content=entry,
                )

                # 7. 检查是否需要压缩
                await self._compress_notes(event)

                # 8. 沉淀计数 + 世界观更新
                self._sediment_count += 1
                self._save_state()
                logger.debug(f"[Anima] 沉淀计数: {self._sediment_count}")
                await self._maybe_update_worldview(event)

                # Phase 6+: 定期维护个人能力健康（修剪）
                if self._sediment_count % 15 == 0 and self.config.get("capability_health_pruning_enabled", True):
                    self._maintain_capabilities_health()

                # 9. 欲望生成
                sylanne_state = await self._try_read_sylanne_state(event)
                await self._maybe_generate_desire(event, sylanne_state, response_text)

                # 10. 矛盾检测
                await self._maybe_detect_contradiction(event)

                # 11. 高危功能
                self._danger_identity_crisis_update(sylanne_state)
                self._danger_identity_crisis_recover()
                await self._danger_active_info_collection(event, response_text)
                await self._danger_relationship_inference(event, response_text)
                await self._danger_stance_propagation(event)
                await self._danger_core_mutation(event)
                await self._danger_autonomous_web(event)
                await self._danger_memory_infection_check(event)

                logger.info(f"[Anima] 沉淀完成，情绪评分: {score:.2f}")

            except Exception as e:
                logger.warning(f"[Anima] 沉淀流程异常: {e}")
