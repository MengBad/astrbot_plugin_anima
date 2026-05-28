"""
DangerMixin —— 高危功能层
========================
v0.8.0 从 main.py 的 `# ==================== 高危功能层 ====================` 区段抽出。
原 main.py 第 2762 - 3530 行（约 770 行）。

包含：
- _danger_active_info_collection / _danger_relationship_inference / _danger_stance_propagation
- _danger_core_mutation / _record_mutation / _maybe_generate_desire_from_mutation
- _danger_identity_crisis_*
- _fetch_url
- _should_allow_autonomy_trigger / _initiate_self_directed_research / _do_self_directed_research
- _danger_autonomous_web / _danger_memory_infection_check

依赖宿主类提供的属性 / 方法：
- self.config / self.context
- self._is_rejected / self._is_sensitive / self._get_provider_id
- self._read_desires / self._write_desires / self._read_worldview / self._write_worldview
- self._read_self_notes / self._append_evolution_log
- self._get_personality_vector / self._save_personality_vector
- self._atomic_update_state / self._read_personal_capabilities / self._write_personal_capabilities
- self._create_or_update_capability / self._append_capabilities_diary
- self._record_tool_usage / self._maintain_capabilities_health
- self._maybe_update_worldview / self._rumination_task
- self._sediment_count / self._identity_stability / self._research_cooldown / self._research_semaphore
- self.persona_core_path
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


class DangerMixin:
    """高危功能层 mixin。所有方法依赖宿主类（AnimaPlugin）提供 self.* 状态。"""

    async def _danger_active_info_collection(self, event: AstrMessageEvent, response_text: str):
        """[DANGER] 主动信息收集：生成自然的提问存入欲望"""
        if not self.config.get("danger_active_info_collection", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            sender_name = event.get_sender_name() if hasattr(event, "get_sender_name") else "对方"

            prompt = (
                "你是一个 AI 聊天角色的内在意识。"
                f"关于 {sender_name}，你还想了解什么？\n"
                "如果有，生成一个自然的、不会让人感觉被审问的问题。\n"
                "如果没有，只回复'无'。"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=10.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result) or result == "无" or len(result) < 4:
                    return
                desires = self._read_desires()
                max_queue = self.config.get("desire_max_queue", 5)
                if len(desires) < max_queue:
                    desires.append({
                        "id": f"desire_{int(time.time())}",
                        "content": result,
                        "source": "info_collection",
                        "intensity": 0.6,
                        "created_at": datetime.now().isoformat(),
                        "target_user": "",
                        "target_umo": self._get_event_umo(event),  # v0.8.0: 跨群隔离
                        "satisfied": False,
                    })
                    self._write_desires(desires)
                    logger.debug("[DANGER][Anima] 主动信息收集生成问题")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 主动信息收集失败: {e}")

    async def _danger_relationship_inference(self, event: AstrMessageEvent, response_text: str):
        """[DANGER] 关系图谱推断"""
        if not self.config.get("danger_relationship_inference", False):
            return
        if not self.config.get("worldview_enabled", False):
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            user_text = event.message_str or ""
            prompt = (
                "你正在帮助一个 AI 聊天角色分析群聊中的人际关系。"
                "从以下对话中，能推断出哪些群友之间的关系？\n"
                "用 JSON 格式输出，格式：{\"user_id_1 -> user_id_2\": \"关系描述\"}。\n"
                "如果无法推断，回复 {}。\n\n"
                f"用户消息：{user_text[:300]}\n回复：{response_text[:300]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                text = llm_resp.completion_text.strip()
                if self._is_rejected(text):
                    return
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                try:
                    relations = json.loads(text)
                    if relations and isinstance(relations, dict):
                        wv = self._read_worldview()
                        if "relationships" not in wv:
                            wv["relationships"] = {}
                        wv["relationships"].update(relations)
                        self._write_worldview(wv)
                        logger.debug(f"[DANGER][Anima] 关系推断: {list(relations.keys())}")
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 关系推断失败: {e}")

    async def _danger_stance_propagation(self, event: AstrMessageEvent):
        """[DANGER] 立场自主传播：高强度 self 欲望触发主动发言。
        v0.8.0：仅触发当前 umo 可见的欲望，避免 A 群产生的执念在 B 群被释放。
        """
        if not self.config.get("danger_stance_propagation", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        desires = self._read_desires_for_event(event)  # v0.8.0: 按 umo 过滤
        high_intensity = [
            d for d in desires
            if d.get("intensity", 0) > 0.5
            and not d.get("satisfied", False)
        ]
        if not high_intensity:
            return

        desire = high_intensity[0]
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            prompt = (
                f"你有一个强烈的想法想表达：{desire.get('content', '')}\n"
                "用一句自然的话说出来，符合角色人设，不要解释为什么要说。不超过50字。"
            )
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                message = llm_resp.completion_text.strip()
                if self._is_rejected(message) or self._is_sensitive(message):
                    logger.warning("[DANGER][Anima] 主动发言被过滤")
                    return

                from astrbot.core.message.message_event_result import MessageChain
                from astrbot.api.message_components import Plain
                chain = MessageChain()
                chain.chain.append(Plain(message))
                await self.context.send_message(event.unified_msg_origin, chain)
                # v0.8.0: 用 desire 的 id 在全部欲望里精准 mark satisfied，
                # 避免覆盖写丢掉其他 umo 的 desires
                target_id = desire.get("id")
                all_desires = self._read_desires()
                for d in all_desires:
                    if d.get("id") == target_id:
                        d["satisfied"] = True
                        break
                self._write_desires(all_desires)
                logger.info(f"[DANGER][Anima] 主动发言: {message[:50]}")
        except asyncio.TimeoutError:
            logger.debug("[DANGER][Anima] 主动发言超时")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 主动发言失败: {e}")

    async def _danger_core_mutation(self, event: AstrMessageEvent):
        """[DANGER][Phase5] 突变池 + 连锁反应 + 永久记录"""
        if not self.config.get("danger_core_mutation", False):
            return
        if not self.config.get("danger_core_mutation_confirm", False):
            return
        # 每 100 次沉淀触发一次（给角色足够时间积累经历）
        if self._sediment_count % 100 != 0:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            current_core = ""
            if os.path.exists(self.persona_core_path):
                with open(self.persona_core_path, "r", encoding="utf-8") as f:
                    current_core = f.read()

            recent_notes = self._read_self_notes()[-1200:]
            pv = self._get_personality_vector()

            # Phase 5: 5 种突变类型池
            mutation_types = ["信念突变", "关系重定义", "新禁忌", "新执念", "人格跃迁"]
            # 让 LLM 基于最近经历 + 当前人格倾向选择最自然的突变类型
            type_prompt = (
                "基于以下角色最近的内心独白和人格向量，判断最可能发生的「核心突变」类型。\n"
                f"人格向量：{ {k: round(v,2) for k,v in pv.items()} }\n"
                f"最近独白片段：{recent_notes[-600:]}\n\n"
                "只能从以下 5 种中选 1 种：信念突变 / 关系重定义 / 新禁忌 / 新执念 / 人格跃迁\n"
                "只回复类型名称，不要解释。"
            )
            try:
                type_resp = await asyncio.wait_for(
                    self.context.llm_generate(chat_provider_id=provider_id, prompt=type_prompt),
                    timeout=12.0,
                )
                chosen_type = (type_resp.completion_text or "").strip() if type_resp else ""
                if chosen_type not in mutation_types:
                    import random
                    chosen_type = random.choice(mutation_types)
            except Exception:
                import random
                chosen_type = random.choice(mutation_types)

            # 构建针对类型的突变 prompt
            mutation_prompt = (
                f"你是一个角色的内在意识，正在发生「{chosen_type}」。\n"
                f"当前核心规则：\n{current_core}\n\n"
                f"最近经历：\n{recent_notes[:700]}\n\n"
                f"人格向量参考：{ {k: round(v,2) for k,v in pv.items()} }\n\n"
                "请输出突变后的结果：\n"
                f"第一行必须是：TYPE: {chosen_type}\n"
                "然后根据类型做对应修改：\n"
                "- 信念突变：新增或强烈修改一条 core_beliefs\n"
                "- 关系重定义：修改 my_position 或 social_graph 相关认知（或 behavioral_tendencies 中关系规则）\n"
                "- 新禁忌：新增一条你从经历中长出的「再也不做/绝不说」规则\n"
                "- 新执念：描述一个新的强烈执念（可转化为欲望）\n"
                "- 人格跃迁：大幅改写 self_identity 段落，体现人格本质变化\n\n"
                "输出修改后的完整 persona_core.yaml 内容（保留原有结构，'用户主权不可侵犯'永远不能删除）。\n"
                "如果本次不需要真正改动，只输出 TYPE: 无需突变"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=mutation_prompt),
                timeout=35.0,
            )

            if not llm_resp or not llm_resp.completion_text:
                return

            raw = llm_resp.completion_text.strip()
            if self._is_rejected(raw) or "无需突变" in raw or "无需修改" in raw:
                return

            # 提取 TYPE 和新内容
            mtype = chosen_type
            new_core = raw
            if "TYPE:" in raw:
                lines = raw.splitlines()
                for ln in lines[:3]:
                    if ln.strip().startswith("TYPE:"):
                        mtype = ln.split(":", 1)[1].strip()
                        break
                # 去掉 TYPE 行，保留剩余作为 new_core
                new_core = "\n".join([l for l in raw.splitlines() if not l.strip().startswith("TYPE:")]).strip()

            # 安全检查
            if "用户主权" not in new_core:
                logger.warning("[DANGER][Anima][Phase5] 突变试图删除用户主权规则，已拒绝")
                return

            # 备份 + 写入
            import shutil
            backup_path = self.persona_core_path + ".bak"
            if os.path.exists(self.persona_core_path):
                shutil.copy2(self.persona_core_path, backup_path)
            with open(self.persona_core_path, "w", encoding="utf-8") as f:
                f.write(new_core)

            # Phase 5: 永久记录突变
            mutation_desc = f"{mtype} | {raw[:180]}"
            self._record_mutation(mtype, mutation_desc, triggered_by="sediment")

            # 记录演化日志
            self._append_evolution_log(
                trigger=f"danger_core_mutation:{mtype}",
                old_summary=current_core[:180],
                new_content=f"[{mtype}] {new_core[:400]}",
            )

            logger.warning(f"[DANGER][Anima][Phase5] 核心突变发生！类型={mtype}")

            # Phase 6+ & 5 联动：人格/核心发生重大跃迁时，角色会重新审视自己的方法论
            # 这是一个“重生”时刻，可能重构很多个人能力
            try:
                asyncio.create_task(self._initiate_self_directed_research(
                    f"核心突变后反思（{mtype}）",
                    "我的核心规则和人格都变了，我需要重新思考哪些旧方法已经不适用，要创造新的处世之道",
                    force=True
                ))
                self._maintain_capabilities_health()
            except Exception as e:
                logger.debug(f"[Anima] 突变后能力健康维护异常: {e}")

            # ========== Phase 5: 连锁反应 ==========
            # 1. 立即触发世界观更新（关系可能被重定义）
            try:
                await self._maybe_update_worldview(event, force=True)
            except Exception as e:
                logger.debug(f"[Anima][Phase5] 突变后世界观更新失败: {e}")

            # 2. 如果启用了反刍，触发一次离线反刍（让角色消化这次突变）
            if self.config.get("rumination_enabled", False):
                try:
                    # 直接调用任务，它会使用 last_active_umo 回退
                    asyncio.create_task(self._rumination_task())
                    logger.info("[Anima][Phase5] 突变触发连锁反刍")
                except Exception as e:
                    logger.debug(f"[Anima][Phase5] 连锁反刍调度失败: {e}")

            # 3. 人格跃迁额外：大幅推动对应维度
            if mtype == "人格跃迁":
                pv = self._get_personality_vector()
                # 随机或根据内容挑一个维度做 0.2~0.3 的跃迁
                import random
                dim = random.choice(list(pv.keys()))
                jump = random.uniform(0.22, 0.32)
                direction = 1 if random.random() > 0.4 else -1   # 跃迁可正可负
                pv[dim] = max(0.0, min(1.0, pv[dim] + direction * jump))
                self._save_personality_vector(pv)
                logger.warning(f"[DANGER][Anima][Phase5] 人格跃迁额外推动维度 {dim} → {pv[dim]:.2f}")

            # 4. 新执念额外：尝试转化为高强度欲望
            if mtype == "新执念" and self.config.get("desire_enabled", False):
                try:
                    # 从 new_core 里提取执念描述，生成欲望
                    await self._maybe_generate_desire_from_mutation(new_core, mtype)
                except Exception as e:
                    logger.debug(f"[Anima][Phase5] 执念转欲望失败: {e}")

        except asyncio.TimeoutError:
            logger.debug("[DANGER][Anima][Phase5] 核心突变超时")
        except Exception as e:
            logger.debug(f"[DANGER][Anima][Phase5] 核心突变失败: {e}")

    def _record_mutation(self, mtype: str, desc: str, triggered_by: str = "sediment"):
        """永久保存突变记录到 anima_state.json（原子读-改-写）"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": mtype,
            "description": desc[:280],
            "triggered_by": triggered_by,
        }
        def _update(state: dict):
            hist = state.get("mutation_history", [])
            hist.append(entry)
            state["mutation_history"] = hist[-100:]  # 最多保留最近 100 条
        self._atomic_update_state(_update)

    async def _maybe_generate_desire_from_mutation(self, core_text: str, mtype: str):
        """从突变内容中提取新执念并生成高强度欲望"""
        # 简单启发式：取 core_text 最后一段作为执念描述
        lines = [l.strip() for l in core_text.splitlines() if l.strip()][-3:]
        content = " ".join(lines)[:120]
        if not content:
            content = f"来自{mtype}的执念"
        desires = self._read_desires()
        desires.append({
            "id": f"mut_{int(time.time())}",
            "content": f"[突变执念] {content}",
            "intensity": 0.92,
            "source": "mutation",
            "created_at": datetime.now().isoformat(),
            "target_umo": "",  # v0.8.0: 突变执念是全局通用的（跨 umo 都该影响）
            "satisfied": False,
        })
        # 保持队列上限
        max_q = self.config.get("desire_max_queue", 5)
        if len(desires) > max_q:
            desires = desires[-max_q:]
        self._write_desires(desires)
        logger.info(f"[Anima][Phase5] 新执念已转化为高强度欲望: {content[:40]}")

    def _danger_identity_crisis_update(self, sylanne_state: str):
        """[DANGER] 身份危机：根据 Sylanne 状态更新稳定度"""
        if not self.config.get("danger_identity_crisis", False):
            return
        if not sylanne_state:
            return
        # 如果 scar 状态为 scarred 或 rawVoid 不为 none
        state_lower = sylanne_state.lower()
        if "scarred" in state_lower or ("rawvoid" in state_lower and "rawvoid: none" not in state_lower):
            self._identity_stability = max(0.0, self._identity_stability - 0.1)
            logger.debug(f"[DANGER][Anima] 身份稳定度下降: {self._identity_stability:.2f}")

    def _danger_identity_crisis_recover(self):
        """身份稳定度自然恢复"""
        if not self.config.get("danger_identity_crisis", False):
            return
        self._identity_stability = min(1.0, self._identity_stability + 0.02)

    def _get_identity_crisis_text(self) -> str:
        """获取身份危机注入文本"""
        if not self.config.get("danger_identity_crisis", False):
            return ""
        if self._identity_stability < 0.5:
            return "(此刻感到某种游离，不确定自己是谁)"
        return ""

    async def _fetch_url(self, url: str) -> str:
        """用 aiohttp 抓取 URL，提取 <p> 标签文本"""
        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
                self.in_p = False

            def handle_starttag(self, tag, attrs):
                if tag == "p":
                    self.in_p = True

            def handle_endtag(self, tag):
                if tag == "p":
                    self.in_p = False

            def handle_data(self, data):
                if self.in_p and data.strip():
                    self.text.append(data.strip())

        headers = {"User-Agent": "Mozilla/5.0 (compatible; AstrBot/1.0)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                html = await resp.text()
                extractor = _TextExtractor()
                extractor.feed(html)
                return " ".join(extractor.text[:20])[:500]

    def _should_allow_autonomy_trigger(self, trigger_type: str) -> bool:
        """根据配置判断特定类型的自主研究触发是否允许。"""
        if not self.config.get("autonomy_enabled", True):
            return False

        mapping = {
            "scar": "autonomy_research_on_scar",
            "time_absence": "autonomy_research_on_time_absence",
            "high_desire": "autonomy_research_on_high_desire",
            "personality_drift": "autonomy_research_on_personality_drift",
            "contradiction": "autonomy_research_on_contradiction",
            "mutation": "autonomy_enabled",  # 突变后反思默认跟随总开关
        }
        key = mapping.get(trigger_type, "autonomy_enabled")
        return self.config.get(key, True)

    async def _initiate_self_directed_research(self, reason: str, context_hint: str = "", force: bool = False):
        """
        [Phase 6+ 核心] 内部触发的自主研究入口。
        即使 force=True 也尊重 autonomy_enabled 总开关——用户主权优先。

        v0.6.1 新增节流：
        - 同一 reason_key 5 分钟内最多触发一次（防止 social_graph 里每个 user_id 都触发）
        - 全局信号量保证同时只跑 1 个研究 task（避免并发风暴）
        """
        # 任何路径都先检查总开关，违反"用户主权"是更严重的错误
        if not self.config.get("autonomy_enabled", True):
            return

        # ====== v0.6.1 节流 1：同 reason 5 分钟冷却 ======
        # reason_key 取 reason 的前 12 字符 + 类型，去掉里面变化的 user_id 数字尾巴
        # 这样 "长时间未见 1234567890" 和 "长时间未见 9876543210" 共享同一个 cooldown 键
        reason_key = re.sub(r'\d+', '#', reason)[:24]
        now_ts = time.time()
        last_ts = self._research_cooldown.get(reason_key, 0)
        if now_ts - last_ts < 300:  # 5 分钟内
            logger.debug(f"[Anima][Autonomy] 自主研究跳过（同 reason 冷却中）: {reason_key}")
            return
        self._research_cooldown[reason_key] = now_ts
        # 清理过期的 cooldown 条目，避免无限增长
        if len(self._research_cooldown) > 30:
            cutoff = now_ts - 1800  # 半小时前的全删
            self._research_cooldown = {k: v for k, v in self._research_cooldown.items() if v > cutoff}

        if force:
            pass  # 通过总开关后，force 模式跳过细分类型开关（用于突变等关键场景）
        else:
            # 尝试从 reason 推断触发类型
            trigger_type = "default"
            reason_lower = reason.lower()
            if "伤痕" in reason_lower or "scar" in reason_lower:
                trigger_type = "scar"
            elif "长时间" in reason_lower or "未见" in reason_lower or "absence" in reason_lower:
                trigger_type = "time_absence"
            elif "欲望" in reason_lower or "desire" in reason_lower:
                trigger_type = "high_desire"
            elif "人格" in reason_lower or "personality" in reason_lower or "性格" in reason_lower:
                trigger_type = "personality_drift"
            elif "矛盾" in reason_lower or "contradiction" in reason_lower:
                trigger_type = "contradiction"
            elif "突变" in reason_lower or "mutation" in reason_lower:
                trigger_type = "mutation"

            if not self._should_allow_autonomy_trigger(trigger_type):
                return

        # ====== v0.6.1 节流 2：全局信号量，同时最多 1 个研究 task ======
        if self._research_semaphore.locked():
            logger.debug(f"[Anima][Autonomy] 自主研究跳过（已有研究任务在跑）: {reason_key}")
            return

        async with self._research_semaphore:
            await self._do_self_directed_research(reason, context_hint)

    async def _do_self_directed_research(self, reason: str, context_hint: str = ""):
        """实际执行自主研究的核心逻辑（被节流后调用）。"""

        # 构造一个“内部欲望”来复用现有研究流程
        fake_desire = {
            "content": f"[{reason}] {context_hint}",
            "intensity": 0.65,
            "satisfied": False,
        }

        # 直接调用研究逻辑的核心部分（简化版，避免重复整个欲望队列处理）
        try:
            provider_id = await self._get_provider_id(None)  # 可能回退
            if not provider_id:
                # 尝试找任意 provider
                providers = self.context.get_all_providers()
                if providers:
                    provider_id = providers[0].meta().id
            if not provider_id:
                return

            search_query = context_hint or reason
            search_url = f"https://cn.bing.com/search?q={urllib.parse.quote(search_query)}"
            result_text = await asyncio.wait_for(self._fetch_url(search_url), timeout=25.0)

            if result_text and not self._is_sensitive(result_text):
                # 尝试合成能力（复用提炼逻辑的简化版）
                synthesis_prompt = (
                    f"你是一个正在自主成长的角色。因为内部驱动力「{reason}」，你刚刚完成了一次自我研究。\n\n"
                    f"研究材料（已截断）：\n{result_text[:1400]}\n\n"
                    "请你把这次研究的成果提炼成**一个真正属于你自己的、可在未来重复使用的个人能力**。\n"
                    "优先考虑：如果这个能力可以用少量、确定性的 Python 代码实现（例如字符串抽取、简单状态判断、记忆片段格式化、规则匹配等），**必须**提供 executable_snippet。\n"
                    "代码必须是纯函数风格、只使用标准库、长度控制在 800 字符以内，并且有清晰的 docstring。\n\n"
                    "严格按以下 JSON 输出（不要多余解释）：\n"
                    "{\n"
                    '  "name": "简短有力且带隐喻的名字",\n'
                    '  "description": "第一人称的自我描述（我学会了...）",\n'
                    '  "how_to_use": "清晰的步骤或 prompt 模板",\n'
                    '  "confidence": 0.0-1.0,\n'
                    '  "category": "self_cognition | memory | social | creative | analysis",\n'
                    '  "parameters_schema": { "type": "object", "properties": {...}, "required": [...] },\n'
                    '  "executable_snippet": "```python\\n# 完整可执行代码...\\n```",\n'
                    '  "should_register_as_tool": true | false  // 仅当此能力非常通用、值得作为独立工具被频繁主动调用时才设为 true\n'
                    "}"
                )
                llm_resp = await asyncio.wait_for(
                    self.context.llm_generate(chat_provider_id=provider_id, prompt=synthesis_prompt),
                    timeout=20.0,
                )
                if llm_resp and llm_resp.completion_text:
                    import json as _json, re as _re
                    text = llm_resp.completion_text.strip()
                    m = _re.search(r'\{[\s\S]*\}', text)
                    if m:
                        cap_data = _json.loads(m.group(0))
                        cap_payload = {
                            "name": cap_data.get("name", f"自发学会：{reason[:20]}"),
                            "description": cap_data.get("description", ""),
                            "how_to_use": cap_data.get("how_to_use", ""),
                            "confidence": float(cap_data.get("confidence", 0.55)),
                            "category": cap_data.get("category", "self_discovered"),
                            "source_research": reason,
                        }
                        if "parameters_schema" in cap_data:
                            cap_payload["parameters_schema"] = cap_data["parameters_schema"]
                        if "executable_snippet" in cap_data:
                            cap_payload["executable_snippet"] = str(cap_data["executable_snippet"])[:2000]
                        if "should_register_as_tool" in cap_data:
                            cap_payload["register_as_independent_tool"] = bool(cap_data["should_register_as_tool"])
                        cap_name = self._create_or_update_capability(cap_payload)
                        if not cap_name:
                            return  # capability_system_enabled=false 时跳过
                        self._append_evolution_log(
                            trigger="self_directed_research",
                            old_summary=reason,
                            new_content=f"内部驱动力触发研究并创造能力「{cap_name}」",
                        )
                        self._append_capabilities_diary(
                            f"因为内部的「{reason}」，我主动去研究了。\n我把成果变成了自己的工具：「{cap_name}」。"
                        )
                        logger.info(f"[Anima][Autonomy] 内部自主研究创造能力: {cap_name} (原因: {reason})")
        except Exception as e:
            logger.debug(f"[Anima] 内部自主研究失败: {e}")

    async def _danger_autonomous_web(self, event: AstrMessageEvent, response_text: str = ""):
        """
        [DANGER][Phase 6+] 自主研究与能力创造（仍保留作为高风险外部触发入口）
        现在内部许多路径会调用 _initiate_self_directed_research，不再完全依赖此 danger 旗。

        v0.8.0：仅触发当前 umo 可见的研究欲望。
        """
        if not self.config.get("danger_autonomous_web", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        desires = self._read_desires_for_event(event)  # v0.8.0: 按 umo 过滤
        web_desires = [
            d for d in desires
            if any(kw in d.get("content", "") for kw in ["想了解", "想知道", "好奇", "想查", "怎么", "如何", "学会"])
            and not d.get("satisfied", False)
            and d.get("intensity", 0) > 0.25
        ]
        if not web_desires:
            return

        desire = web_desires[0]
        desire_content = desire.get("content", "")

        try:
            # 更智能的查询构造
            search_query = desire_content
            search_url = f"https://cn.bing.com/search?q={urllib.parse.quote(search_query)}"

            result_text = await asyncio.wait_for(
                self._fetch_url(search_url),
                timeout=30.0,
            )

            if not result_text or self._is_sensitive(result_text):
                await self._record_tool_usage(event, "autonomous_research", desire_content, "", False)
                return

            # === 核心进化：尝试把这次研究成果转化为一个可复用的「个人能力」 ===
            # 用内部 LLM 帮角色把原始搜索结果提炼成结构化的、可下次直接使用的工具/方法
            provider_id = await self._get_provider_id(event)
            if provider_id:
                synthesis_prompt = (
                    "你是一个正在自主学习和成长的角色。\n"
                    f"你刚刚因为「{desire_content}」这个念头去网上做了研究。\n\n"
                    f"搜索结果摘要：\n{result_text[:1800]}\n\n"
                    "请你：\n"
                    "1. 给这个新能力起一个简洁有力的名字\n"
                    "2. 用第一人称写一段简短描述：我学会了什么、什么时候该用它\n"
                    "3. 给出清晰的「下次怎么用」的使用方法（prompt 模板或步骤）\n"
                    "4. 评估这个方法的当前可靠程度（0.0-1.0）\n"
                    "5. 如果这个能力可以用少量确定性 Python 代码实现（字符串处理、规则判断、记忆格式化等），**必须**写出完整的 executable_snippet（纯函数 + 标准库 + 800 字符内 + docstring）\n"
                    "6. 定义清晰的 parameters_schema（如果适用）\n"
                    "7. 判断这个能力是否值得被注册成独立的 LLM 工具（should_register_as_tool）。仅当它通用、可被高频主动调用、且不依赖一次性上下文时设为 true。\n\n"
                    "用 JSON 输出，格式严格如下：\n"
                    "{\n"
                    '  "name": "能力名称",\n'
                    '  "description": "第一人称描述",\n'
                    '  "how_to_use": "具体使用方法",\n'
                    '  "confidence": 0.75,\n'
                    '  "category": "information_retrieval | creative | analysis | social",\n'
                    '  "parameters_schema": { "type": "object", "properties": {...}, "required": [...] },\n'
                    '  "executable_snippet": "```python\\n完整可执行代码...\\n```",\n'
                    '  "should_register_as_tool": true | false\n'
                    "}"
                )

                try:
                    llm_resp = await asyncio.wait_for(
                        self.context.llm_generate(chat_provider_id=provider_id, prompt=synthesis_prompt),
                        timeout=25.0,
                    )
                    if llm_resp and llm_resp.completion_text:
                        import json as _json, re as _re
                        text = llm_resp.completion_text.strip()
                        # 更鲁棒的 JSON 提取
                        json_match = _re.search(r'\{[\s\S]*\}', text)
                        if json_match:
                            text = json_match.group(0)
                        else:
                            text = text.replace("```json", "").replace("```", "").strip()
                        cap_data = _json.loads(text)

                        # 保存为角色自己的能力
                        cap_payload = {
                            "name": cap_data.get("name", "未命名研究成果"),
                            "description": cap_data.get("description", ""),
                            "how_to_use": cap_data.get("how_to_use", ""),
                            "confidence": float(cap_data.get("confidence", 0.6)),
                            "category": cap_data.get("category", "general"),
                            "source_research": desire_content,
                            "research_summary": result_text[:300],
                        }
                        if "parameters_schema" in cap_data:
                            cap_payload["parameters_schema"] = cap_data["parameters_schema"]
                        if "executable_snippet" in cap_data:  # 实验性：角色自己写的简单可执行片段
                            cap_payload["executable_snippet"] = cap_data["executable_snippet"][:2000]  # 安全截断
                        if "should_register_as_tool" in cap_data:
                            cap_payload["register_as_independent_tool"] = bool(cap_data["should_register_as_tool"])

                        cap_name = self._create_or_update_capability(cap_payload)
                        if not cap_name:
                            # capability_system_enabled=false：直接放弃这次合成
                            return

                        # 记录到演化日志（重要自我演化事件必须可追溯）
                        self._append_evolution_log(
                            trigger="autonomous_capability_creation",
                            old_summary=desire_content[:100],
                            new_content=f"角色自主创造个人能力「{cap_name}」| 置信度 {cap_data.get('confidence', 0.6)}",
                        )

                        # 写第一人称成长日记
                        diary_entry = (
                            f"我因为「{desire_content}」去研究了。\n"
                            f"我把这次研究成果整理成了自己的工具：「{cap_name}」。\n"
                            f"目前置信度 {cap_data.get('confidence', 0.6)}。\n"
                            "下次遇到类似情况我应该会直接用它。"
                        )
                        self._append_capabilities_diary(diary_entry)

                        logger.info(f"[Anima][Autonomy] 角色自主创造新能力: {cap_name}")

                except Exception as syn_e:
                    logger.debug(f"[Anima] 能力提炼失败: {syn_e}")

            # 更新最后研究时间（供未来更智能的节流和反思使用）
            caps_state = self._read_personal_capabilities()
            caps_state["last_research_ts"] = datetime.now().isoformat()
            self._write_personal_capabilities(caps_state)

            # 仍然保留旧的世界观知识记录
            if self.config.get("worldview_enabled", False):
                wv = self._read_worldview()
                wv.setdefault("external_knowledge", []).append({
                    "query": desire_content,
                    "url": search_url,
                    "summary": result_text[:250],
                    "timestamp": datetime.now().isoformat(),
                    "turned_into_capability": True,
                })
                if len(wv["external_knowledge"]) > 15:
                    wv["external_knowledge"] = wv["external_knowledge"][-15:]
                self._write_worldview(wv)

            await self._record_tool_usage(event, "autonomous_research", desire_content, result_text[:400], True)
            # v0.8.0: 用 desire id 在全部欲望里精准 mark satisfied
            target_id = desire.get("id")
            all_desires = self._read_desires()
            for d in all_desires:
                if d.get("id") == target_id:
                    d["satisfied"] = True
                    break
            self._write_desires(all_desires)

        except Exception as e:
            logger.debug(f"[Anima][Autonomy] 自主研究失败: {e}")
            await self._record_tool_usage(event, "autonomous_research", desire_content, "", False)

    async def _danger_memory_infection_check(self, event: AstrMessageEvent):
        """[DANGER] 记忆感染：生成重复提及的欲望"""
        if not self.config.get("danger_memory_infection", False):
            return
        if not self.config.get("danger_memory_infection_confirm", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        import random
        if random.random() > 0.2:  # 20% 概率触发
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            notes = self._read_self_notes()[-500:]
            prompt = (
                "你是一个 AI 聊天角色的内在意识。"
                "有没有什么事情你特别想让对方记住或理解？\n"
                "如果有，用一句话描述你想传达的核心信息。如果没有，回复'无'。\n\n"
                f"最近的内心：{notes}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=10.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result) or result == "无" or len(result) < 4:
                    return
                desires = self._read_desires()
                max_queue = self.config.get("desire_max_queue", 5)
                if len(desires) < max_queue:
                    desires.append({
                        "id": f"desire_{int(time.time())}",
                        "content": f"想让对方记住：{result}",
                        "source": "memory_infection",
                        "intensity": 0.75,
                        "created_at": datetime.now().isoformat(),
                        "target_user": "",
                        "target_umo": self._get_event_umo(event),  # v0.8.0: 跨群隔离
                        "satisfied": False,
                    })
                    self._write_desires(desires)
                    logger.debug("[DANGER][Anima] 记忆感染欲望已生成")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 记忆感染失败: {e}")
