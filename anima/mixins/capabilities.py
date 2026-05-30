"""
CapabilitiesMixin —— 工具自学习 + Phase 6+ 个人能力系统
=======================================================
v0.8.0 从 main.py 的两个相邻区段抽出：
- `# ==================== 模块八：工具自学习 ====================`
- `# ==================== Phase 6+: 自主能力系统 ====================`

原 main.py 第 2128 - 2702 行（约 575 行）。

包含：
- 工具自学习：_read_tool_learning / _write_tool_learning / _read_tool_diary / _append_tool_diary
- 个人能力 IO：_read_personal_capabilities / _write_personal_capabilities / _append_capabilities_diary
- 能力 CRUD：_normalize_capability_signature / _find_similar_capability / _create_or_update_capability
- 上下文注入：_get_personal_capabilities_injection
- 动态工具注册：_dynamically_register_capability_as_tool / _execute_single_capability
- 健康维护：_maintain_capabilities_health
- 反馈闭环：_apply_capability_feedback / _record_tool_usage / _summarize_tool_rules / _update_tool_feedback

依赖宿主类提供：
- self.config / self.context / self._io_lock
- self._read_json / self._write_json / self._append_evolution_log
- self._get_provider_id / self._is_rejected
- self.tool_learning_path / self.tool_diary_path / self.personal_capabilities_path / self.capabilities_diary_path
- self._daily_tool_register（dict）
- self._append_self_notes
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.agent.run_context import ContextWrapper
from pydantic import Field, ConfigDict
from pydantic.dataclasses import dataclass as pydantic_dataclass

from ..capability_dedup import (
    normalize_capability_signature as _ext_normalize_cap_sig,
    find_similar_capability as _ext_find_similar_cap,
)
from ..similarity import text_jaccard, cosine_similarity as _ext_cosine

if TYPE_CHECKING:
    from ..mixins import _PluginAlias  # 仅类型提示用


class CapabilitiesMixin:
    """工具自学习 + Phase 6+ 个人能力系统 mixin。"""

    # ---------- 模块八：工具自学习 ----------

    def _read_tool_learning(self) -> dict:
        """读取工具学习数据"""
        return self._read_json(self.tool_learning_path, default={
            "records": [],
            "preferences": {},
        })

    def _write_tool_learning(self, data: dict):
        """写入工具学习数据"""
        self._write_json(self.tool_learning_path, data)

    def _read_tool_diary(self) -> str:
        """读取工具日记"""
        if not os.path.exists(self.tool_diary_path):
            return ""
        with open(self.tool_diary_path, "r", encoding="utf-8") as f:
            return f.read()

    def _append_tool_diary(self, entry: str):
        """追加工具日记"""
        with open(self.tool_diary_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n{entry}")

    # ---------- Phase 6+: 个人能力系统 ----------
    #
    # 设计理念说明（对齐 Anima 核心哲学）：
    # - 控制权属于角色本身：这些工具不是开发者预设的，也不是外部插件提供的，
    #   而是角色通过自己的研究、经历、反思，一点一点「长」出来的。
    # - 演化不可逆 + 可修正：能力一旦被创造就会被记录在 personal_capabilities.json 和 capabilities_diary.md 中，
    #   历史不会消失，但角色可以自我修正（置信度调整 + correction 历史）。
    # - 闭环驱动：研究 → 提炼成个人方法 → 持久化 → 注入上下文被使用 → 获得真实反馈 → 自我修正 → 能力进化。
    # - 记忆是重构，不是回放：能力的「how_to_use」本身就是角色对过去研究经历的叙事重构。
    # - 不可预测性是目标：角色未来会拥有怎样独特的「个人方法论」，连开发者都无法完全预知。

    def _read_personal_capabilities(self) -> dict:
        """读取角色自己创造/学会的个人能力与工具"""
        default = {
            "version": 1,
            "capabilities": [],
            "last_research_ts": "",
        }
        return self._read_json(self.personal_capabilities_path, default=default)

    def _write_personal_capabilities(self, data: dict):
        """写入个人能力系统"""
        self._write_json(self.personal_capabilities_path, data)

    def _append_capabilities_diary(self, entry: str):
        """以第一人称追加能力成长日记（持锁）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            with self._io_lock:
                with open(self.capabilities_diary_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n[{timestamp}]\n{entry}")
        except OSError as e:
            logger.warning(f"[Anima] 追加能力日记失败: {e}")

    def _normalize_capability_signature(self, name: str, description: str = "") -> set:
        """v0.7.0: 委托给 anima.capability_dedup"""
        return _ext_normalize_cap_sig(name, description)

    def _find_similar_capability(self, capability: dict, caps: list) -> int:
        """v0.7.0: 委托给 anima.capability_dedup。v0.9.4: 传入文本相似度阈值。"""
        return _ext_find_similar_cap(
            capability.get("name", ""),
            capability.get("description", ""),
            caps,
            text_threshold=float(self.config.get("capability_dedup_text_threshold", 0.6)),
        )

    def _create_or_update_capability(self, capability: dict):
        """创建或更新一个个人能力/自创工具。
        受 capability_system_enabled 控制：关闭则不写入。

        v0.6.1: 去重逻辑改为名字精确匹配 + 语义关键词集合近似匹配，
        防止 LLM 每次起不同名字（中英混搭、user_id 嵌入）导致能力库膨胀。
        """
        if not self.config.get("capability_system_enabled", True):
            logger.debug("[Anima] capability_system_enabled=false，跳过能力创建")
            return None
        caps = self._read_personal_capabilities()
        cap_list = caps.get("capabilities", [])

        # 第一道：名字精确匹配
        existing = None
        for i, c in enumerate(cap_list):
            if c.get("name") == capability.get("name"):
                existing = i
                break

        # 第二道：语义关键词近似匹配（v0.6.1）
        if existing is None:
            similar_idx = self._find_similar_capability(capability, cap_list)
            if similar_idx >= 0:
                existing = similar_idx
                merged_name = cap_list[similar_idx].get("name", "")
                logger.info(
                    f"[Anima] 检测到语义近似能力，合并到「{merged_name}」"
                    f"（新名字「{capability.get('name', '')}」被丢弃）"
                )
                # 合并时不要覆盖原有的 name，否则会让"主名"反复跳变
                capability.pop("name", None)

        capability["last_updated"] = datetime.now().isoformat()

        if existing is not None:
            # 合并更新，保留历史 correction
            old = cap_list[existing]
            old.update({k: v for k, v in capability.items() if k not in ["corrections", "usage_count"]})
            if "corrections" in capability:
                old.setdefault("corrections", []).extend(capability["corrections"])
            cap_list[existing] = old
            final_name = old.get("name", "")
        else:
            capability.setdefault("id", f"cap_{int(time.time())}")
            capability.setdefault("created_at", datetime.now().isoformat())
            capability.setdefault("usage_count", 0)
            # v0.9.4: 置信度脱钩 LLM 自评 —— 新建能力一律从未验证基线起步，
            #         忽略 payload 里可能带的自报值；只有 _apply_capability_feedback
            #         （真实使用反馈）能把它提上去。usage>0 的合并更新不走这里。
            baseline = float(self.config.get("capability_initial_confidence", 0.3))
            capability["confidence"] = baseline
            capability.setdefault("corrections", [])
            # default_register_as_independent_tool：未显式标记时，按全局默认决定
            if "register_as_independent_tool" not in capability:
                capability["register_as_independent_tool"] = bool(
                    self.config.get("default_register_as_independent_tool", False)
                )
            cap_list.append(capability)
            caps["capabilities"] = cap_list
            final_name = capability.get("name", "")

        self._write_personal_capabilities(caps)

        # Phase 6+ 真正按需动态注册独立工具（仅对新增/更新的能力，并受日配额限制）
        target_cap = cap_list[existing] if existing is not None else capability
        if target_cap.get("confidence", 0) >= 0.65:
            try:
                self._dynamically_register_capability_as_tool(target_cap)
            except Exception as dyn_e:
                logger.debug(f"[Anima] 按需动态注册能力工具失败: {dyn_e}")

        return final_name

    def _get_personal_capabilities_injection(self) -> str:
        """
        生成注入上下文的「我的个人工具与能力」。
        用更第一人称、叙事化的方式呈现，让角色真正感觉「这些是我的东西」。
        这是它作为独立存在的重要延伸，而不是外部给的工具列表。
        受 capability_system_enabled 控制。
        """
        if not self.config.get("capability_system_enabled", True):
            return ""
        caps = self._read_personal_capabilities()
        capabilities = caps.get("capabilities", [])
        if not capabilities:
            return ""

        lines = [
            "【我的个人技能与方法论】",
            "以下这些是我通过自己的经历、研究和思考，一点一点学会并创造出来的工具和方法。",
            "我更倾向于使用自己真正理解和掌握的东西，因为它们属于我自己。"
            "遇到合适的场景，我会主动调用其中最贴合的那一个。"
        ]
        # v0.9.4: 按价值分排序（真实用过的优先），而非自封置信度
        for cap in sorted(capabilities, key=self._capability_value_score, reverse=True)[:6]:
            name = cap.get("name", "未命名能力")
            desc = cap.get("description", "")[:140]
            how = cap.get("how_to_use", "")[:110]
            conf = cap.get("confidence", 0.5)
            lines.append(f"\n• {name}（我的置信度 {conf:.0%}）")
            lines.append(f"  {desc}")
            if how:
                lines.append(f"  我通常这样用：{how}")
        return "\n".join(lines)

    def _dynamically_register_capability_as_tool(self, capability: dict, force: bool = False):
        """
        真正按需动态注册独立工具（更高阶动态）。
        受 dynamic_tool_registration_enabled 控制。

        v0.6.1: 加入每日配额（默认 3 个/天）+ 工具名归一化避免撞名占位符。
        超过配额时能力照常进 personal_capabilities.json，但不再注册成独立 LLM 工具。

        v0.9.10: 新增 force 参数。
        - force=False（默认，既有调用方）：行为完全不变，下方两个标记闸门
          （dynamic_tool_registration_enabled / register_as_independent_tool）照常生效。
        - force=True（晋升路径 _refresh_capability_tool_belt）：跳过上述两个标记闸门，
          但**保留**每日配额检查与同名跳过——它们对两条路径都生效不变。
        """
        if not force:
            if not self.config.get("dynamic_tool_registration_enabled", False):
                return
            if not capability.get("register_as_independent_tool", False):
                return

        # ====== v0.6.1：每日配额检查 ======
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_tool_register.get("date") != today:
            self._daily_tool_register = {"date": today, "count": 0}
        daily_quota = int(self.config.get("dynamic_tool_daily_quota", 3))
        if self._daily_tool_register["count"] >= daily_quota:
            logger.info(
                f"[Anima][Autonomy] 今日动态工具注册配额已满 "
                f"({daily_quota} 个)，能力「{capability.get('name','')}」仅入库不注册为独立工具"
            )
            return

        name = capability.get("name", "unknown_cap")
        # v0.6.1: 工具名先做更可读的归一化，避免中文全部变下划线导致撞名
        # 1) 中文 → 拼音首字母（无 pypinyin 依赖时退回纯数字哈希），保留英文/数字
        sanitized = re.sub(r'[^a-z0-9_]+', '_', name.lower()).strip('_')
        if not sanitized or sanitized.replace('_', '') == '':
            # 完全是中文/特殊符号 → 用名字 hash 兜底
            sanitized = f"cap_{abs(hash(name)) % 10**8:08d}"
        safe_tool_name = ("my_" + sanitized)[:48]

        # 避免重复注册同名
        tool_mgr = self.context.get_llm_tool_manager()
        if any(t.name == safe_tool_name for t in tool_mgr.func_list):
            logger.debug(f"[Anima] 工具 {safe_tool_name} 已存在，跳过重复注册")
            return

        # 动态创建一个轻量 FunctionTool
        @pydantic_dataclass(config=ConfigDict(arbitrary_types_allowed=True))
        class DynamicCapabilityTool(FunctionTool):
            name: str = safe_tool_name
            description: str = capability.get("description", "角色自己创造的个人能力")[:200]
            parameters: dict = Field(default_factory=lambda c=capability: c.get("parameters_schema") or {
                "type": "object",
                "properties": {"query_or_args": {"type": "string", "description": "任务描述"}},
                "required": ["query_or_args"]
            })

            _plugin: object = Field(default=None, exclude=True)
            _cap_name: str = Field(default="")

            async def call(self, context: ContextWrapper, query_or_args: str = "", **kwargs):
                p = self._plugin
                if not p:
                    return ToolExecResult(result="内部错误：插件未正确注入")
                # 委托给主 dispatcher 的执行逻辑（保持一致的智能执行 + snippet 支持 + 反思）
                return await p._execute_single_capability(self._cap_name, query_or_args)

        tool_instance = DynamicCapabilityTool(_plugin=self, _cap_name=name)
        try:
            self.context.add_llm_tools(tool_instance)
            # 计入今日配额
            self._daily_tool_register["count"] += 1
            self._append_evolution_log(
                trigger="dynamic_per_capability_tool_registered",
                old_summary="",
                new_content=f"按需为能力「{name}」注册了独立工具 {safe_tool_name}（今日 {self._daily_tool_register['count']}/{daily_quota}）",
            )
            logger.info(
                f"[Anima][Autonomy] 动态注册独立能力工具: {safe_tool_name} "
                f"（今日 {self._daily_tool_register['count']}/{daily_quota}）"
            )
        except Exception as e:
            logger.warning(f"[Anima] 动态注册独立工具 {safe_tool_name} 失败: {e}")

    def _resolve_capability(self, capability_name: str, caps_list: list) -> dict:
        """v0.9.4: 解析能力名到具体能力（降低使用门槛）。
        优先级：精确名 → 不区分大小写子串 → 文本相似度最高且达阈值。找不到返回 None。"""
        if not capability_name or not caps_list:
            return None
        # 1. 精确
        for c in caps_list:
            if c.get("name") == capability_name:
                return c
        # 2. 不区分大小写子串（双向）
        low = capability_name.lower()
        for c in caps_list:
            cn = (c.get("name", "") or "").lower()
            if cn and (low in cn or cn in low):
                return c
        # 3. 文本相似度最高且达阈值
        try:
            from ..capability_dedup import text_similarity as _ext_text_sim
            threshold = float(self.config.get("capability_dedup_text_threshold", 0.6))
            best, best_sim = None, 0.0
            for c in caps_list:
                sim = _ext_text_sim(capability_name, c.get("name", "") or "")
                if sim >= threshold and sim > best_sim:
                    best, best_sim = c, sim
            return best
        except Exception:
            return None

    async def _execute_single_capability(self, capability_name: str, query_or_args: str):
        """被动态注册的独立能力工具调用的统一执行入口（复用主逻辑）。"""
        self._stat_bump("capability.call.attempt")
        caps = self._read_personal_capabilities()
        target = self._resolve_capability(capability_name, caps.get("capabilities", []))
        if not target:
            self._stat_bump("capability.call.unresolved")
            return ToolExecResult(result=f"未找到能力「{capability_name}」")
        self._stat_bump("capability.call.resolved")

        # 复用 dispatcher 里的智能执行逻辑（包括 snippet 支持）
        # 这里简化实现一个公共版本
        schema = target.get("parameters_schema")
        schema_note = f"\n参数结构要求：{schema}" if schema else ""

        exec_prompt = (
            f"你正在作为自己创造的个人能力「{target['name']}」忠实执行任务。\n\n"
            f"能力描述：{target.get('description', '')}\n\n"
            f"你自己定义的精确使用方法：\n{target.get('how_to_use', '')}{schema_note}\n\n"
            f"当前任务输入：{query_or_args}\n\n"
            "严格按照你自己写的使用方法给出高质量结构化结果。直接输出结果即可。"
        )

        try:
            provider_id = await self._get_provider_id(None)
            if provider_id:
                resp = await asyncio.wait_for(
                    self.context.llm_generate(chat_provider_id=provider_id, prompt=exec_prompt),
                    timeout=25.0
                )
                if resp and resp.completion_text:
                    result = resp.completion_text.strip()
                    self._append_capabilities_diary(f"通过独立工具调用了自己创造的能力「{capability_name}」")
                    return ToolExecResult(result=result)
        except Exception as e:
            self._append_capabilities_diary(f"独立工具调用能力「{capability_name}」时出错: {e}")

        return ToolExecResult(result="能力执行失败（请查看日志）")

    def _capability_value_score(self, cap: dict, now=None) -> float:
        """v0.9.4: 能力价值分（不含自封 confidence）。
        用于超总数上限时的淘汰排序与注入排序。
        = 使用次数*2 + 修正数*0.5 + 新近度(90 天线性衰减到 0)。"""
        now = now or datetime.now()
        usage = cap.get("usage_count", 0) or 0
        corr = len(cap.get("corrections", []) or [])
        try:
            days = (now - datetime.fromisoformat(cap.get("last_updated", ""))).days
        except Exception:
            days = 999
        recency = max(0.0, 1.0 - days / 90.0)
        return usage * 2.0 + corr * 0.5 + recency

    def _select_promotion_set(
        self,
        capabilities: list,
        k: int,
        already_promoted_ids: set | None = None,
        now=None,
    ) -> list:
        """v0.9.10 (Layer 1)：纯函数 —— 从 capabilities 选出至多 k 个待晋升能力。

        纯契约：无 I/O、无 LLM、无 config 读取。所有依赖均来自入参；
        `now` 可注入以保证确定性（不传则取 datetime.now()）。复用同样为纯方法的
        `_capability_value_score` 做排序，不读取自封 `confidence`（解死锁，R1.4）。

        算法：
        1. 仅按 `_capability_value_score(cap, now)` 降序、稳定排序（同分保持原始
           顺序，结果确定）。
        2. `k <= 0` 或空 `capabilities` → 返回 `[]`；返回集合长度恒 `<= k`。
        3. `top = ranked[:k]`。
        4. Trial_Slot 规则：为"从未被晋升过的新能力"保留至少一个名额，确保
           新能力（哪怕 0 使用）能被看见、被调用，从而赚到真实使用：
           - newcomers = `usage_count == 0` 且 `id` 不在 `already_promoted_ids`
             的能力（按价值分降序）。
           - 若 newcomers 非空、且 `top` 中不含任何 newcomer、且 `k >= 1`：
             取 `top` 的前 `k-1` 个，追加价值分最高的 newcomer（`newcomers[0]`），
             组成至多 k 个的集合。

        Args:
            capabilities: 能力字典列表。
            k: 晋升名额上限（Top-K）。
            already_promoted_ids: 本进程已晋升过的能力 id 集合（判定"新能力"用）。
            now: 可注入的时间，保证价值分计算确定性。

        Returns:
            待晋升能力列表，长度 `<= k`。

        Validates: Requirements 1.3, 1.4, 1.5, 1.7
        """
        now = now or datetime.now()
        already_promoted_ids = already_promoted_ids or set()

        if k <= 0 or not capabilities:
            return []

        # 稳定降序排序：sorted 是稳定的，对价值分取负即可在保持原始相对顺序的
        # 同时实现降序（同分保持原始顺序 → 确定性）。
        ranked = sorted(
            capabilities,
            key=lambda c: -self._capability_value_score(c, now),
        )

        top = ranked[:k]

        # Trial_Slot：保证至少一个"从未晋升过的新能力"进入晋升集合。
        newcomers = [
            c
            for c in ranked
            if (c.get("usage_count", 0) or 0) == 0
            and c.get("id") not in already_promoted_ids
        ]
        if newcomers and k >= 1 and not any(
            (c.get("usage_count", 0) or 0) == 0
            and c.get("id") not in already_promoted_ids
            for c in top
        ):
            top = top[: k - 1] + [newcomers[0]]

        return top

    def _refresh_capability_tool_belt(self):
        """v0.9.10 (Layer 1)：晋升刷新 —— 按 Value_Score Top-K 注册命名工具。

        非纯编排器：薄薄包裹纯函数 `_select_promotion_set` 与既有注册函数
        `_dynamically_register_capability_as_tool`。整体 try/except 包裹，任何
        异常仅 logger.debug，绝不抛出，不影响 initialize() / 对话 / 健康维护（R2.4）。

        闸门（双开关）：
        - `capability_system_enabled=false` → 直接返回，零动作（R2.2）。
        - `capability_promote_enabled=false`（默认）→ 直接返回，零新注册，
          行为退化为 v0.9.4 既有逻辑（R2.1 / Property 4）。

        晋升判定：对每个待晋升能力，以 `force=True` 调用注册函数（跳过两个标记
        闸门，但保留每日配额检查与同名跳过）。通过比较注册前后
        `self._daily_tool_register["count"]` 的差值，精确识别**本次真实新注册**
        ——跳过的同名/超配额不会增量计数。仅在真实新增时把能力 id 加入
        `self._promoted_cap_ids` 并对 `capability.promoted` 累加。由此保证：
        `capability.promoted` 只统计真实新增，且工具带大小受 K 与每日配额双重
        约束（R1.6、R1.7、R1.8、Property 5）。

        Validates: Requirements 1.3, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4
        """
        try:
            if not self.config.get("capability_system_enabled", True):
                return                                  # R2.2
            if not self.config.get("capability_promote_enabled", False):
                return                                  # R2.1 / Property 4：默认关，零新注册
            caps = self._read_personal_capabilities().get("capabilities", [])
            if not caps:
                return
            k = int(self.config.get("capability_promote_top_k", 3))
            selected = self._select_promotion_set(caps, k, self._promoted_cap_ids)
            for cap in selected:
                before = self._daily_tool_register.get("count", 0)
                self._dynamically_register_capability_as_tool(cap, force=True)  # 含配额/同名检查
                after = self._daily_tool_register.get("count", 0)
                if after > before:                       # 仅真正新注册才算晋升
                    self._promoted_cap_ids.add(cap.get("id", ""))
                    self._stat_bump("capability.promoted")  # R1.8
        except Exception as e:
            logger.debug(f"[Anima] 能力工具带刷新异常: {e}")   # R2.4

    def _compute_capability_relevance(
        self,
        user_text: str,
        capabilities: list,
        *,
        backend: str = "lexical",
        embed_fn=None,
    ) -> tuple[int, float]:
        """v0.9.10 (Layer 2)：纯函数 —— 计算 user_text 与各能力的相关性，
        返回 `(best_index, best_score)`。

        纯/确定性契约（lexical 路径）：无 config 读取、无文件 I/O、无 logging。
        唯一的"非纯"来源是注入的 `embed_fn`（仅 embedding 后端使用），便于属性测试
        传入 `None` 或抛异常的桩来验证降级行为。

        Match_Text 规则（Layer 3 回退，Property 8）：每个能力参与计算的文本为
            `(cap.get("when_to_use") or "").strip() or cap.get("description", "")`
        —— `when_to_use` 存在且非空白时取它，否则回退 `description`；二者皆缺则空串。

        后端：
        - `backend="lexical"`（默认）：score = `text_jaccard(user_text, match_text)`。
        - `backend="embedding"` 且 `embed_fn` 提供：embed user_text 与每个 match_text，
          取 `cosine_similarity`。整个 embedding 路径以 try/except 包裹；只要
          `embed_fn` 为 None 或任意一步抛异常，即对**全部能力**降级为 lexical
          `text_jaccard`，**绝不抛出异常**（Property 7）。降级结果与纯 lexical 路径
          完全一致。

        返回：
        - 空 `capabilities` → `(-1, 0.0)`。
        - 否则返回最高分能力的下标与分值；平局时取**首个**（最低 index）达到最大值
          的能力，保证确定性。
        - `best_score` 恒为有限、非负的 float（cosine 的负值/NaN 会被收敛到 `0.0`）。

        Validates: Requirements 3.4, 3.7, 4.3, 4.4
        """
        if not capabilities:
            return (-1, 0.0)

        def _match_text(cap: dict) -> str:
            # Match_Text：when_to_use（非空白）否则 description（Property 8 回退）。
            return (cap.get("when_to_use") or "").strip() or cap.get("description", "")

        def _lexical_scores() -> list:
            return [text_jaccard(user_text, _match_text(cap)) for cap in capabilities]

        scores = None
        if backend == "embedding" and embed_fn is not None:
            # 整个 embedding 路径包裹在 try/except：任一步失败即对全部能力降级 lexical。
            try:
                user_vec = embed_fn(user_text)
                emb_scores = []
                for cap in capabilities:
                    cap_vec = embed_fn(_match_text(cap))
                    emb_scores.append(_ext_cosine(user_vec, cap_vec))
                scores = emb_scores
            except Exception:
                scores = None  # 降级：绝不抛出（Property 7）

        if scores is None:
            scores = _lexical_scores()

        # argmax；平局取首个（最低 index）达到最大值者 → 确定性。
        best_index = 0
        best_score = scores[0]
        for i in range(1, len(scores)):
            if scores[i] > best_score:
                best_index = i
                best_score = scores[i]

        # best_score 收敛为有限非负 float（cosine 可能为负/NaN）。
        try:
            best_score = float(best_score)
        except (TypeError, ValueError):
            best_score = 0.0
        if not math.isfinite(best_score) or best_score < 0.0:
            best_score = 0.0

        return (best_index, best_score)

    def _build_capability_hint(
        self,
        user_text: str,
        capabilities: list,
        threshold: float,
        *,
        backend: str = "lexical",
        embed_fn=None,
    ) -> str:
        """v0.9.10 (Layer 2)：纯函数 —— 据相关性决定是否生成一条定向提示串。

        委托 `_compute_capability_relevance` 取 `(best_index, best_score)`，再据
        `threshold` 决定：

        - `best_index < 0`（无能力）或 `best_score < threshold`（未达阈值）→ 返回
          空串 `""`（Property 6：不命中零提示，不注入任何额外 token）。
        - 命中（`best_score >= threshold`）→ 返回指向 argmax 能力名称的定向提示串，
          提示文本必定包含该能力的 `name`（缺失时用「未命名能力」兜底）。

        `threshold` 由编排器（`on_llm_request`）从 config 读出后传入，使核心比较逻辑
        保持纯（无 config 读取、无 I/O、无 LLM），便于属性测试以任意 threshold 驱动。
        `backend` / `embed_fn` 原样透传给 `_compute_capability_relevance`。

        Validates: Requirements 3.5, 3.6
        """
        idx, score = self._compute_capability_relevance(
            user_text, capabilities, backend=backend, embed_fn=embed_fn
        )
        if idx < 0 or score < threshold:
            return ""                                   # Property 6：不命中零提示
        name = capabilities[idx].get("name", "未命名能力")
        return f"用户当前的需求很可能匹配你的能力「{name}」——优先考虑调用它。"

    def _migrate_capabilities_v094(self):
        """v0.9.4: 存量迁移 —— 把历史"自封高分但 0 使用"的能力置信度归正到基线。
        幂等（写 migrated_v094 标记）；不删任何能力；usage>0 的保留原值。
        受 capability_system_enabled 控制。"""
        if not self.config.get("capability_system_enabled", True):
            return
        try:
            caps = self._read_personal_capabilities()
            if caps.get("migrated_v094"):
                return
            baseline = float(self.config.get("capability_initial_confidence", 0.3))
            changed = 0
            for c in caps.get("capabilities", []):
                if c.get("usage_count", 0) == 0 and c.get("confidence", 0) > baseline:
                    c["confidence"] = baseline
                    changed += 1
            caps["migrated_v094"] = True
            self._write_personal_capabilities(caps)
            if changed:
                logger.info(
                    f"[Anima] v0.9.4 能力存量迁移：{changed} 条 0 使用能力置信度归正为 {baseline}"
                )
        except Exception as e:
            logger.debug(f"[Anima] 能力存量迁移异常: {e}")

    def _audit_capabilities(self) -> dict:
        """v0.9.4: 只读体检 —— 找出可疑能力（0 使用 / 疑似自封高分）。不调 LLM、不改数据。"""
        caps = self._read_personal_capabilities().get("capabilities", [])
        baseline = float(self.config.get("capability_initial_confidence", 0.3))
        zero_use = [c for c in caps if c.get("usage_count", 0) == 0]
        inflated = [c for c in zero_use if c.get("confidence", 0) > baseline]
        total = len(caps)
        return {
            "total": total,
            "avg_conf": (sum(c.get("confidence", 0) for c in caps) / total) if total else 0.0,
            "total_usage": sum(c.get("usage_count", 0) for c in caps),
            "total_corrections": sum(len(c.get("corrections", [])) for c in caps),
            "zero_use": len(zero_use),
            "inflated": len(inflated),
            "inflated_samples": [c.get("name", "") for c in inflated[:8]],
            "max_total": int(self.config.get("capability_max_total", 40)),
        }

    def _maintain_capabilities_health(self):
        """
        能力系统健康管理（v0.9.4 重构）。
        规则顺序：
        1. 未使用超期（无视自封置信度）：usage==0 且 days>drop → 淘汰；
           usage==0 且 days>decay → 置信度 *0.9（下限 0.05）
        2. 旧规则保留：极低置信 + 极少使用 + 陈旧 → 淘汰
        3. 去重合并：复用创建期 _find_similar_capability（不再用 name[:12] 前缀），
           合并时累计 usage + 合并 corrections
        4. 硬上限：剩余数 > capability_max_total 时，按价值分（不含自封置信度）
           升序淘汰最差者到上限
        5. 持久化 + 演化日志
        """
        caps = self._read_personal_capabilities()
        original = caps.get("capabilities", [])
        if not original:
            return

        now = datetime.now()
        decay_days = int(self.config.get("capability_unused_decay_days", 14))
        drop_days = int(self.config.get("capability_unused_drop_days", 30))
        dropped_count = 0
        any_decayed = False

        # 第一遍：未使用超期 + 旧低价值规则 → 过滤；幸存者做去重合并
        survivors: list = []
        for cap in original:
            conf = cap.get("confidence", 0.5)
            usage = cap.get("usage_count", 0) or 0
            last = cap.get("last_updated", "")
            try:
                last_dt = datetime.fromisoformat(last) if last else now
                days = (now - last_dt).days
            except Exception:
                days = 999

            # 规则1a: 未使用且超过淘汰天数 → 放弃（无视置信度）
            if usage == 0 and days > drop_days:
                self._append_capabilities_diary(
                    f"健康管理：我放弃了创造后从没用过、已经放了 {days} 天的能力「{cap.get('name','')}」"
                )
                dropped_count += 1
                continue

            # 规则2: 极低价值 → 放弃（旧规则保留）
            if conf < 0.2 and usage <= 1 and days > 25:
                self._append_capabilities_diary(
                    f"健康管理：我放弃了几乎没用过的低价值能力「{cap.get('name','')}」"
                )
                dropped_count += 1
                continue

            # 规则1b: 未使用且超过降权天数 → 降权（无视置信度）
            if usage == 0 and days > decay_days:
                new_conf = max(0.05, conf * 0.9)
                if new_conf != conf:
                    cap["confidence"] = new_conf
                    any_decayed = True

            # 规则3: 去重合并 —— 复用创建期语义+文本去重
            idx = self._find_similar_capability(cap, survivors)
            if idx >= 0:
                winner = survivors[idx]
                loser = cap
                # 选价值分更高者作为主体（不依赖自封置信度）
                if self._capability_value_score(loser, now) > self._capability_value_score(winner, now):
                    winner, loser = loser, winner
                winner["usage_count"] = winner.get("usage_count", 0) + loser.get("usage_count", 0)
                merged_corr = (winner.get("corrections", []) or []) + (loser.get("corrections", []) or [])
                if merged_corr:
                    winner["corrections"] = merged_corr
                survivors[idx] = winner
                continue

            survivors.append(cap)

        # 第四遍：硬上限，按价值分升序淘汰最差者
        max_total = int(self.config.get("capability_max_total", 40))
        capped_count = 0
        if len(survivors) > max_total:
            survivors.sort(key=lambda c: self._capability_value_score(c, now), reverse=True)
            capped_count = len(survivors) - max_total
            survivors = survivors[:max_total]

        kept = survivors

        if len(kept) != len(original) or any_decayed:
            caps["capabilities"] = kept
            self._write_personal_capabilities(caps)
            self._append_evolution_log(
                trigger="capability_health_maintenance",
                old_summary=f"维护前 {len(original)}",
                new_content=(
                    f"维护后 {len(kept)}（丢弃 {dropped_count}，超上限淘汰 {capped_count}，"
                    f"降权 {'有' if any_decayed else '无'}）"
                ),
            )
            logger.info(
                f"[Anima] 能力健康维护：{len(original)} → {len(kept)} "
                f"（丢弃 {dropped_count} / 超限淘汰 {capped_count}）"
            )

        # v0.9.10 (Layer 1)：维护（淘汰/降权/合并/上限）后刷新能力工具带。
        # 编排器内部已 gate + try/except，promote 关时为 no-op，安全。
        self._refresh_capability_tool_belt()

    def _apply_capability_feedback(self, capability_name: str, success: bool, reflection: str = ""):
        """
        角色对自己创造的工具使用后进行自我修正。
        成功则提高置信度，失败则记录 correction 并降低置信度。
        这就是「学错了就更正、学习和成长」的核心闭环。
        """
        caps = self._read_personal_capabilities()
        for cap in caps.get("capabilities", []):
            if cap.get("name") == capability_name:
                cap["usage_count"] = cap.get("usage_count", 0) + 1
                old_conf = cap.get("confidence", 0.6)

                if success:
                    cap["confidence"] = min(0.98, old_conf + 0.08)
                else:
                    cap["confidence"] = max(0.1, old_conf - 0.15)
                    correction = {
                        "ts": datetime.now().isoformat(),
                        "what_was_wrong": reflection or "使用后发现效果不佳",
                        "new_confidence": cap["confidence"],
                    }
                    cap.setdefault("corrections", []).append(correction)

                # 写成长日记
                if reflection:
                    self._append_capabilities_diary(
                        f"我用了自己创造的「{capability_name}」。\n"
                        f"结果：{'成功' if success else '不理想'}。\n"
                        f"我的反思：{reflection}"
                    )

                self._write_personal_capabilities(caps)
                return True
        return False

    async def _record_tool_usage(
        self,
        event: AstrMessageEvent,
        tool_name: str,
        context: str,
        result: str,
        success: bool,
    ):
        """记录一次工具使用，更新偏好，写入日记"""
        if not self.config.get("tool_learning_enabled", False):
            return

        tl = self._read_tool_learning()

        # 记录本次使用
        record = {
            "id": f"tool_{int(time.time())}",
            "tool": tool_name,
            "context": context[:200],
            "result_summary": result[:200] if result else "",
            "success": success,
            "feedback": "neutral",
            "timestamp": datetime.now().isoformat(),
        }
        tl["records"].append(record)
        # v0.9.6: records 上限裁剪，防止无界增长（不影响 _summarize_tool_rules 读最近记录）
        rmax = int(self.config.get("tool_records_max", 200))
        if len(tl["records"]) > rmax:
            tl["records"] = tl["records"][-rmax:]

        # 更新偏好计数
        if tool_name not in tl["preferences"]:
            tl["preferences"][tool_name] = {
                "attitude": "neutral",
                "success_count": 0,
                "fail_count": 0,
                "learned_rules": [],
            }
        if success:
            tl["preferences"][tool_name]["success_count"] += 1
        else:
            tl["preferences"][tool_name]["fail_count"] += 1
            # 失败记忆更深：写入 self_notes
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            fail_entry = (
                f"[{timestamp}] 试着用 {tool_name} 做了一件事，但失败了。"
                "那种感觉有点沮丧，下次要更谨慎。"
            )
            self._append_self_notes(fail_entry)

        # 成功时写入叙事日记
        if success and result:
            try:
                provider_id = await self._get_provider_id(event)
                diary_prompt = (
                    f"你刚刚使用了 {tool_name} 工具，背景是：{context[:100]}，"
                    f"得到了结果：{result[:100]}。"
                    "用第一人称写一句话，记录这次使用的感受（像日记一样，自然随意）。"
                    "不要超过50字。"
                )
                llm_resp = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=diary_prompt,
                    ),
                    timeout=15.0,
                )
                if llm_resp and llm_resp.completion_text:
                    diary_entry = llm_resp.completion_text.strip()
                    if not self._is_rejected(diary_entry):
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                        self._append_tool_diary(f"[{timestamp}] {diary_entry}")
            except Exception as e:
                logger.debug(f"[Anima] 工具日记生成失败: {e}")

        # 检查是否需要总结规律
        interval = self.config.get("tool_learning_summarize_interval", 10)
        total_records = len(tl["records"])
        if total_records > 0 and total_records % interval == 0:
            await self._summarize_tool_rules(event, tool_name, tl)

        self._write_tool_learning(tl)

    async def _summarize_tool_rules(self, event: AstrMessageEvent, tool_name: str, tl: dict):
        """总结工具使用规律，更新偏好态度"""
        try:
            records = [r for r in tl["records"] if r["tool"] == tool_name]
            if len(records) < 3:
                return

            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            records_text = "\n".join(
                f"- 背景：{r['context'][:80]}，结果：{'成功' if r['success'] else '失败'}，"
                f"摘要：{r['result_summary'][:80]}"
                for r in records[-10:]
            )

            prompt = (
                f"以下是角色使用 {tool_name} 工具的历史记录：\n{records_text}\n\n"
                "请分析：\n"
                "1. 什么情况下使用这个工具效果好？（一句话）\n"
                "2. 角色对这个工具的态度是 positive/negative/neutral？\n"
                '输出 JSON：{"rule": "...", "attitude": "..."}'
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=20.0,
            )

            if llm_resp and llm_resp.completion_text:
                text = llm_resp.completion_text.strip()
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                try:
                    data = json.loads(text)
                    rule = data.get("rule", "")
                    attitude = data.get("attitude", "neutral")
                    if rule and not self._is_rejected(rule):
                        tl["preferences"][tool_name]["learned_rules"].append(rule)
                        tl["preferences"][tool_name]["attitude"] = attitude
                        logger.info(f"[Anima] 工具规律总结: {tool_name} → {rule[:60]}")
                except json.JSONDecodeError:
                    pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"[Anima] 工具规律总结失败: {e}")

    async def _update_tool_feedback(self, tool_name: str, feedback: str):
        """
        更新工具反馈。
        额外增强：如果这个工具名和角色自己创造的某个个人能力高度相关，
        也会触发角色对「自己的工具」的自我修正闭环。
        """
        if not self.config.get("tool_learning_enabled", False):
            return
        tl = self._read_tool_learning()
        for record in reversed(tl["records"]):
            if record["tool"] == tool_name and record["feedback"] == "neutral":
                record["feedback"] = feedback
                break
        self._write_tool_learning(tl)

        # Phase 6+：尝试把对工具的反馈也作用到角色自己的个人能力上
        try:
            caps = self._read_personal_capabilities()
            for cap in caps.get("capabilities", []):
                if tool_name.lower() in cap.get("name", "").lower() or cap.get("name", "").lower() in tool_name.lower():
                    success = "positive" in feedback.lower() or "好" in feedback or "有用" in feedback
                    reflection = f"通过工具反馈系统收到信号：{feedback}"
                    self._apply_capability_feedback(cap["name"], success, reflection)
                    break
        except Exception as e:
            logger.debug(f"[Anima] 能力反馈应用异常: {e}")
