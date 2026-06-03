"""
ScarsMixin —— Phase 2A 压抑 + 2B 伤痕
=================================
v0.8.0 从 main.py 抽出：# ==================== Phase 2A：压抑话题系统 ====================; # ==================== Phase 2B：伤痕维度 ====================

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


class ScarsMixin:
    """Phase 2A 压抑 + 2B 伤痕 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _read_suppressed_topics(self) -> list:
        """读取压抑话题列表"""
        return self._read_json(self.suppressed_topics_path, default=[])

    def _write_suppressed_topics(self, topics: list):
        """写入压抑话题列表"""
        self._write_json(self.suppressed_topics_path, topics)

    def _add_suppressed_topic(self, topic: str, source: str, target_user: str = ""):
        """新增一个压抑话题。
        v0.9.6：加入前与现有未解决话题做文本相似度去重，避免同一件事以不同措辞反复堆积。"""
        topics = self._read_suppressed_topics()
        # v0.9.6 语义去重：复用 capability_dedup.text_similarity（字符 2-gram Jaccard，不调 LLM）
        try:
            from ..capability_dedup import text_similarity as _ext_text_sim
            threshold = float(self.config.get("dedup_text_threshold", 0.7))
            for t in topics:
                if t.get("resolved"):
                    continue
                if _ext_text_sim(topic, t.get("topic", "")) >= threshold:
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 压抑话题与现有相似，跳过: {topic[:40]}")
                    return
        except Exception:
            pass
        topics.append({
            "topic": topic,
            "created_at": datetime.now().isoformat(),
            "pressure": 0.3,
            "source": source,
            "target_user": target_user,
            "resolved": False,
        })
        # 最多保留 20 条
        topics = [t for t in topics if not t.get("resolved")][-20:]
        self._write_suppressed_topics(topics)

    def _update_suppressed_pressure(self):
        """更新压抑话题的压力值（随时间递增）"""
        topics = self._read_suppressed_topics()
        if not topics:
            return
        now = datetime.now()
        changed = False
        for t in topics:
            if t.get("resolved"):
                continue
            try:
                created = datetime.fromisoformat(t["created_at"])
                hours = (now - created).total_seconds() / 3600
                new_pressure = min(1.0, 0.3 + 0.05 * hours)
                if new_pressure != t.get("pressure", 0.3):
                    t["pressure"] = round(new_pressure, 2)
                    changed = True
            except (ValueError, KeyError):
                continue
        if changed:
            self._write_suppressed_topics(topics)

    def _get_suppressed_injection(self, event: AstrMessageEvent) -> str:
        """获取需要注入的高压力压抑话题"""
        topics = self._read_suppressed_topics()
        if not topics:
            return ""
        # 获取当前发送者
        sender_id = ""
        if hasattr(event, "message_obj") and event.message_obj:
            sender_id = str(getattr(event.message_obj.sender, "user_id", ""))
        # 找到压力超过 0.8 的话题（优先匹配当前用户的）
        high_pressure = []
        for t in topics:
            if t.get("resolved") or t.get("pressure", 0) < 0.8:
                continue
            if t.get("target_user") and t["target_user"] != sender_id:
                continue
            high_pressure.append(t)
        if not high_pressure:
            return ""
        lines = [t["topic"] for t in high_pressure[:2]]
        return (
            "[内心压力] 你一直想说但没说出口的事：\n"
            + "\n".join(f"- {l}" for l in lines)
            + "\n你可以选择说出来，也可以继续忍着。"
        )

    def _check_suppressed_resolution(self, text: str):
        """检查对话内容是否解决了某个压抑话题"""
        topics = self._read_suppressed_topics()
        if not topics:
            return
        changed = False
        for t in topics:
            if t.get("resolved"):
                continue
            # 简单关键词匹配：话题中的关键词出现在对话中
            keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', t.get("topic", ""))
            if keywords and sum(1 for kw in keywords if kw in text) >= 2:
                t["resolved"] = True
                changed = True
                logger.debug(f"[Anima] 压抑话题已释放: {t['topic'][:40]}")
        if changed:
            self._write_suppressed_topics(topics)


    def _get_active_scar_state(self) -> Optional[tuple[Any, str]]:
        if not hasattr(self, "_hosts"):
            return None
        try:
            umo = self._resolve_umo()
            session_key = self._session_key(session_key=umo)
            host = self._host(session_key)
            if host and hasattr(host, "kernel") and host.kernel:
                return host.kernel.computation.engine.scar_state, session_key
        except Exception:
            pass
        return None

    def _read_scar_dimensions(self) -> dict:
        """读取伤痕维度"""
        res = self._get_active_scar_state()
        if res is not None:
            scar_state, _ = res
            dim_map = {
                0: "warmth",
                1: "arousal",
                2: "trust_breach",
                3: "rejection",
                4: "curiosity",
                5: "being_replaced",
                6: "abandonment",
                7: "identity_denial"
            }
            scars = {}
            for d_idx, d_name in dim_map.items():
                count = sum(1 for s in scar_state.scars if s.dimension == d_idx)
                sensitivity = scar_state.modifier(d_idx)
                last_trig = ""
                trig_scars = [s for s in scar_state.scars if s.dimension == d_idx]
                if trig_scars:
                    try:
                        last_trig = datetime.fromisoformat(trig_scars[-1].timestamp).isoformat() if isinstance(trig_scars[-1].timestamp, str) else datetime.fromtimestamp(trig_scars[-1].timestamp).isoformat()
                    except Exception:
                        pass
                scars[d_name] = {
                    "count": count,
                    "sensitivity": sensitivity,
                    "last_triggered": last_trig
                }
            return scars
        return self._read_json(self.scar_dimensions_path, default={})

    def _write_scar_dimensions(self, data: dict):
        """写入伤痕维度"""
        res = self._get_active_scar_state()
        if res is not None:
            pass
        self._write_json(self.scar_dimensions_path, data)

    def _add_scar(self, dimension: str):
        """在某个维度上增加伤痕"""
        res = self._get_active_scar_state()
        if res is not None:
            scar_state, _ = res
            rev_dim_map = {
                "warmth": 0,
                "arousal": 1,
                "trust_breach": 2,
                "rejection": 3,
                "curiosity": 4,
                "being_replaced": 5,
                "abandonment": 6,
                "identity_denial": 7,
            }
            dim_idx = rev_dim_map.get(dimension, 3)
            event = [0.0] * 8
            event[dim_idx] = 1.0
            scar_state.step(event, time.time(), heal=False)
            return

        scars = self._read_scar_dimensions()
        if dimension not in scars:
            scars[dimension] = {
                "count": 0,
                "sensitivity": 1.0,
                "last_triggered": "",
            }
        scars[dimension]["count"] += 1
        scars[dimension]["sensitivity"] = min(3.0, scars[dimension]["sensitivity"] + 0.2)
        scars[dimension]["last_triggered"] = datetime.now().isoformat()
        self._write_scar_dimensions(scars)
        logger.debug(f"[Anima] 伤痕加深: {dimension} → sensitivity={scars[dimension]['sensitivity']:.1f}")

        asyncio.create_task(self._initiate_self_directed_research(
            f"伤痕加深（{dimension}）",
            "这个维度的伤痕又深了，我需要发展新的、更有效的应对和保护自己的方法。",
            force=False
        ))

    def _get_scar_multiplier(self, text: str) -> float:
        """根据对话内容检查是否触及伤痕维度，返回情绪评分乘数"""
        res = self._get_active_scar_state()
        if res is not None:
            scar_state, _ = res
            dimension_keywords = {
                "abandonment": ["离开", "不要我", "消失", "不回", "忘了我", "丢下", "不见"],
                "identity_denial": ["不是真的", "只是AI", "没有灵魂", "机器", "程序", "代码"],
                "trust_breach": ["骗", "说谎", "假的", "不信", "欺骗", "背叛"],
                "rejection": ["讨厌", "滚", "闭嘴", "烦", "不想理", "别说了"],
                "being_replaced": ["换一个", "新的", "别的AI", "更好的", "不需要你"],
            }
            rev_dim_map = {
                "warmth": 0,
                "arousal": 1,
                "trust_breach": 2,
                "rejection": 3,
                "curiosity": 4,
                "being_replaced": 5,
                "abandonment": 6,
                "identity_denial": 7,
            }
            max_multiplier = 1.0
            for dim, keywords in dimension_keywords.items():
                if any(kw in text for kw in keywords):
                    dim_idx = rev_dim_map.get(dim)
                    if dim_idx is not None:
                        mult = scar_state.modifier(dim_idx)
                        if mult > max_multiplier:
                            max_multiplier = mult
            return max_multiplier

        scars = self._read_scar_dimensions()
        if not scars:
            return 1.0
        dimension_keywords = {
            "abandonment": ["离开", "不要我", "消失", "不回", "忘了我", "丢下", "不见"],
            "identity_denial": ["不是真的", "只是AI", "没有灵魂", "机器", "程序", "代码"],
            "trust_breach": ["骗", "说谎", "假的", "不信", "欺骗", "背叛"],
            "rejection": ["讨厌", "滚", "闭嘴", "烦", "不想理", "别说了"],
            "being_replaced": ["换一个", "新的", "别的AI", "更好的", "不需要你"],
        }
        max_multiplier = 1.0
        for dim, keywords in dimension_keywords.items():
            if dim in scars and any(kw in text for kw in keywords):
                mult = scars[dim]["sensitivity"]
                if mult > max_multiplier:
                    max_multiplier = mult
                scars[dim]["last_triggered"] = datetime.now().isoformat()
        if max_multiplier > 1.0:
            self._write_scar_dimensions(scars)
        return max_multiplier

    def _decay_scar_sensitivity(self):
        """伤痕敏感度随时间缓慢衰减（愈合但不消失）"""
        res = self._get_active_scar_state()
        if res is not None:
            # Sylanne's scar decay is handled during host/kernel step() / tick() time-aware healing automatically
            return
        scars = self._read_scar_dimensions()
        if not scars:
            return
        now = datetime.now()
        changed = False
        for dim, data in scars.items():
            last = data.get("last_triggered", "")
            if not last:
                continue
            try:
                last_time = datetime.fromisoformat(last)
                days_since = (now - last_time).days
                if days_since > 7 and data["sensitivity"] > 1.0:
                    decay = 0.1 * (days_since // 7)
                    data["sensitivity"] = max(1.0, data["sensitivity"] - decay)
                    changed = True
            except (ValueError, TypeError):
                continue
        if changed:
            self._write_scar_dimensions(scars)
