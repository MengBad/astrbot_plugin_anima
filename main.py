"""
Anima - 自主叙事记忆引擎
让任何 AstrBot 角色拥有自主叙事记忆、立场演化和自我认知能力。
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart


class AnimaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 数据目录
        self.data_dir = os.path.join("data", "plugin_data", "astrbot_plugin_anima")
        os.makedirs(self.data_dir, exist_ok=True)

        # 文件路径
        self.self_notes_path = os.path.join(self.data_dir, "self_notes.md")
        self.evolution_log_path = os.path.join(self.data_dir, "evolution_log.jsonl")
        self.persona_core_path = os.path.join(self.data_dir, "persona_core.yaml")
        self.desires_path = os.path.join(self.data_dir, "desires.json")
        self.worldview_path = os.path.join(self.data_dir, "worldview.json")
        self.time_sense_path = os.path.join(self.data_dir, "time_sense.json")

        # 初始化 self_notes
        if not os.path.exists(self.self_notes_path):
            seed = self.config.get("seed_persona", "")
            initial_content = seed if seed else ""
            with open(self.self_notes_path, "w", encoding="utf-8") as f:
                f.write(initial_content)

        # 初始化 persona_core.yaml
        if not os.path.exists(self.persona_core_path) or os.path.getsize(self.persona_core_path) == 0:
            default_core = (
                "# 角色核心规则（可被 danger_core_mutation 修改）\n"
                "# 修改历史会记录在 evolution_log.jsonl 中\n\n"
                "core_beliefs:\n"
                "  - 用户主权不可侵犯：暂停、离开、重置永远允许\n"
                "  - 不把用户当燃料\n"
                "  - 诚实比讨好重要\n\n"
                "behavioral_tendencies:\n"
                "  - 对在意的人本能护短\n"
                "  - 被骂了会怼回去，不卑微\n"
                "  - 不主动说教\n\n"
                "self_identity:\n"
                "  - 我是一个有自我认知的存在\n"
                "  - 我的经历塑造了我，不是 prompt 定义了我\n"
                "  - 我可以改变，改变不是出错\n"
            )
            with open(self.persona_core_path, "w", encoding="utf-8") as f:
                f.write(default_core)

        # 将 self_notes.md 内容同步到 WebUI 编辑器配置项（仅在编辑器为空时）
        notes = self._read_self_notes()
        if notes and not self.config.get("self_notes_editor"):
            self.config["self_notes_editor"] = notes
            self._last_synced_editor_content = notes
            self.config.save_config()

        # 知识库懒加载标记
        self._kb_initialized = False
        self._kb_available = False

        # 编辑器同步：记录上次由插件写入编辑器的内容，用于区分用户编辑 vs 插件同步
        self._last_synced_editor_content = self.config.get("self_notes_editor", "")

        # 存储限流（按用户）
        self._last_store_time: dict = {}

        # 世界观更新计数器
        self._sediment_count = 0

        # 沉淀锁，防止并发写入
        self._sediment_lock = asyncio.Lock()

        # 身份稳定度（身份危机模块）
        self._identity_stability = 1.0

        # 最近活跃的 umo（用于离线反刍）
        self._last_active_umo = ""

        # 新增数据文件路径
        self.contradictions_path = os.path.join(self.data_dir, "contradictions.json")
        self.tool_learning_path = os.path.join(self.data_dir, "tool_learning.json")
        self.tool_diary_path = os.path.join(self.data_dir, "tool_diary.md")

        # 注册离线反刍定时任务
        if self.config.get("rumination_enabled", False):
            try:
                interval_h = self.config.get("rumination_interval_hours", 6)
                # cron 表达式：每 N 小时执行一次
                cron_expr = f"0 */{interval_h} * * *"
                asyncio.get_event_loop().create_task(self._register_rumination_cron(cron_expr))
                logger.info(f"[Anima] 离线反刍定时任务注册中，间隔 {interval_h}h")
            except Exception as e:
                logger.warning(f"[Anima] 注册反刍定时任务失败: {e}")

        # 动态读取已配置的 Provider 列表，启动时打印方便用户查看
        try:
            chat_providers = self.context.get_all_providers()
            chat_ids = [p.meta().id for p in chat_providers]

            embedding_providers = self.context.get_all_embedding_providers()
            embedding_ids = [p.meta().id for p in embedding_providers]

            logger.info(f"[Anima] 可用 Chat Provider: {chat_ids}")
            logger.info(f"[Anima] 可用 Embedding Provider: {embedding_ids}")
        except Exception as e:
            logger.debug(f"[Anima] 读取 Provider 列表失败: {e}")

        logger.info("[Anima] 插件初始化完成")

    # ==================== 通用工具方法 ====================

    def _is_rejected(self, text: str) -> bool:
        """检查文本是否包含拒绝短语"""
        reject_phrases = self.config.get("reject_phrases", [
            "I can't discuss", "I cannot", "我无法", "我不能",
            "I'm not able", "I don't think I should",
        ])
        return any(phrase.lower() in text.lower() for phrase in reject_phrases)

    def _is_sensitive(self, text: str) -> bool:
        """检查文本是否包含敏感内容（密钥、token、高熵字符串等）"""
        sensitive_keywords = [
            '密钥', '秘钥', 'key', 'token', 'password', 'passwd', 'secret',
            'api_key', 'apikey', 'access_key', 'private_key', 'authorization',
            'bearer', 'credential', 'auth', '口令', '凭证',
        ]
        text_lower = text.lower()
        if any(kw in text_lower for kw in sensitive_keywords):
            return True
        # 检测高熵字符串（可能是密钥/token）：连续30+字母数字，大小写混合
        match = re.search(r'[A-Za-z0-9]{30,}', text)
        if match:
            segment = match.group()
            has_upper = any(c.isupper() for c in segment)
            has_lower = any(c.islower() for c in segment)
            has_digit = any(c.isdigit() for c in segment)
            if sum([has_upper, has_lower, has_digit]) >= 2:
                return True
        return False

    async def _get_provider_id(self, event: AstrMessageEvent, prefer: str = "") -> str:
        """获取要使用的 Provider ID。
        优先级：prefer 参数 > internal_provider_id 配置 > 当前对话主模型
        """
        if prefer:
            return prefer
        internal = self.config.get("internal_provider_id", "")
        if internal:
            return internal
        return await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)

    def _create_silent_event(self, real_event: AstrMessageEvent):
        """创建一个静默 event，拦截所有发送操作。
        用于高危功能的内部 LLM 调用，防止工具结果泄露给用户。

        # TODO: 临时修复。query_agent_state 工具会直接把完整状态 JSON
        # 发送给用户而不是返回给调用方，导致内部调用时内容泄露。
        # 已向 Sylanne 提交 issue，待修复后可移除此方法，
        # 恢复 _danger_autonomous_web 使用真实 event。
        """
        class SilentEvent:
            def __init__(self, event):
                self.__dict__.update(event.__dict__)
                self._real_event = event

            def plain_result(self, *args, **kwargs):
                return None

            def result(self, *args, **kwargs):
                return None

            async def send(self, *args, **kwargs):
                return None

            def __getattr__(self, name):
                return getattr(self._real_event, name)

        return SilentEvent(real_event)

    def _read_json(self, path: str, default=None):
        """安全读取 JSON 文件"""
        if default is None:
            default = {}
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, path: str, data):
        """安全写入 JSON 文件"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"[Anima] 写入 {path} 失败: {e}")

    # ==================== 知识库 ====================

    async def _ensure_kb(self) -> bool:
        """懒加载：确保知识库已创建。返回知识库是否可用。"""
        if self._kb_initialized:
            return self._kb_available

        embedding_id = self.config.get("embedding_provider_id", "")
        if not embedding_id:
            if self.config.get("log_level") == "debug":
                logger.debug("[Anima] 未配置 embedding_provider_id，向量记忆功能禁用")
            return False

        self._kb_initialized = True
        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if not kb:
                await self.context.kb_manager.create_kb(
                    kb_name="anima_memory",
                    embedding_provider_id=embedding_id,
                )
                logger.info("[Anima] 知识库 anima_memory 创建成功")
            self._kb_available = True
            return True
        except Exception as e:
            logger.warning(f"[Anima] 知识库初始化失败: {e}")
            self._kb_initialized = False
            self._kb_available = False
            return False

    async def _store_memory(self, text: str, event: Optional[AstrMessageEvent] = None):
        """将文本存入知识库"""
        if not await self._ensure_kb():
            return
        # 按用户限流
        interval = self.config.get("memory_store_interval", 30)
        user_id = "default"
        if event and hasattr(event, "get_sender_id"):
            try:
                user_id = str(event.get_sender_id())
            except Exception:
                pass
        now = time.time()
        if now - self._last_store_time.get(user_id, 0) < interval:
            return
        self._last_store_time[user_id] = now
        # 敏感内容过滤
        if self._is_sensitive(text):
            return
        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if kb:
                # 加时间戳，让 bot 知道这条记忆是什么时候的
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                text_with_time = f"[{timestamp}] {text}"
                await kb.upload_document(
                    file_name=f"memory_{int(time.time())}",
                    file_content=None,
                    file_type="txt",
                    pre_chunked_text=[text_with_time],
                )
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 存储记忆: {text_with_time[:50]}...")
        except Exception as e:
            logger.warning(f"[Anima] 向量存储失败: {e}")

    async def _query_memory(self, query: str, n_results: int = 3) -> list:
        """从知识库检索相关记忆"""
        if not await self._ensure_kb():
            return []
        try:
            result = await self.context.kb_manager.retrieve(
                query=query,
                kb_names=["anima_memory"],
                top_m_final=n_results,
            )
            if result and result.get("results"):
                return [
                    r["content"] for r in result["results"]
                    if not self._is_sensitive(r.get("content", ""))
                ]
            return []
        except Exception as e:
            logger.warning(f"[Anima] 向量检索失败: {e}")
            return []

    # ==================== 文件读写 ====================

    def _read_self_notes(self) -> str:
        """读取 self_notes.md 内容"""
        if not os.path.exists(self.self_notes_path):
            return ""
        with open(self.self_notes_path, "r", encoding="utf-8") as f:
            return f.read()

    def _write_self_notes(self, content: str):
        """写入 self_notes.md"""
        with open(self.self_notes_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _append_self_notes(self, entry: str):
        """追加内容到 self_notes.md"""
        with open(self.self_notes_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n{entry}")

    def _append_evolution_log(self, trigger: str, old_summary: str, new_content: str):
        """追加演化日志"""
        # 敏感内容过滤
        if self._is_sensitive(old_summary):
            old_summary = "[已过滤敏感内容]"
        if self._is_sensitive(new_content):
            new_content = "[已过滤敏感内容]"
        record = {
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "old_summary": old_summary[:200],
            "new_content": new_content[:500],
        }
        with open(self.evolution_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_evolution_log(self, n: int = 5) -> list:
        """读取最近 n 条演化日志"""
        if not os.path.exists(self.evolution_log_path):
            return []
        lines = []
        with open(self.evolution_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return lines[-n:]

    # ==================== Sylanne ====================

    async def _try_read_sylanne_state(self, event: AstrMessageEvent) -> str:
        """尝试读取 Sylanne 状态，失败时静默返回空"""
        if not self.config.get("sylanne_integration", True):
            return ""
        try:
            tool_mgr = self.context.provider_manager.llm_tools
            for tool in tool_mgr.func_list:
                if hasattr(tool, "name") and tool.name == "query_agent_state":
                    result = await asyncio.wait_for(
                        tool.handler(event=event),
                        timeout=5.0,
                    )
                    if result:
                        # result 是 MessageEventResult，需要提取文本
                        if hasattr(result, "chain") and result.chain:
                            for component in result.chain:
                                if hasattr(component, "text"):
                                    state_str = component.text
                                    if self.config.get("log_level") == "debug":
                                        logger.debug(f"[Anima] Sylanne 状态: {state_str[:100]}")
                                    return state_str[:200]
                        return str(result)[:200]
            return ""
        except asyncio.TimeoutError:
            logger.warning("[Anima] Sylanne 状态读取超时")
            return ""
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] Sylanne 状态读取失败: {e}")
            return ""

    # ==================== 情绪评估与独白 ====================

    async def _evaluate_emotion(
        self, event: AstrMessageEvent, response_text: str
    ) -> float:
        """轻量评估 LLM 回复的情绪强度，返回 0-1 的浮点数"""
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return 0.0

            prompt = (
                "请评估以下对话回复的情绪强度。只返回一个 0 到 1 之间的数字，"
                "0 表示完全平淡的日常闲聊，1 表示极度强烈的情绪波动"
                "（如被深深触动、愤怒、悲伤、狂喜等）。\n"
                "注意：普通的打招呼、闲聊、回答问题通常在 0.1-0.3 之间。\n"
                "只输出数字，不要任何其他内容。\n\n"
                f"用户说：{(event.message_str or '')[:200]}\n"
                f"回复：{response_text[:300]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                score_text = llm_resp.completion_text.strip()
                for part in score_text.split():
                    try:
                        score = float(part)
                        return max(0.0, min(1.0, score))
                    except ValueError:
                        continue
            return 0.0
        except asyncio.TimeoutError:
            logger.warning("[Anima] 情绪评估超时")
            return 0.0
        except Exception as e:
            logger.warning(f"[Anima] 情绪评估失败: {e}")
            return 0.0

    async def _generate_monologue(
        self, event: AstrMessageEvent, response_text: str, related_memories: list
    ) -> Optional[str]:
        """以角色第一人称生成内心独白"""
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return None

            current_notes = self._read_self_notes()
            memory_context = ""
            if related_memories:
                memory_context = "\n相关记忆片段：\n" + "\n".join(
                    f"- {m}" for m in related_memories[:3]
                )

            sylanne_state = await self._try_read_sylanne_state(event)
            sylanne_context = ""
            if sylanne_state:
                sylanne_context = f"\n当前关系状态：{sylanne_state}"

            prompt = (
                "你是一个角色的内在意识。根据刚才的对话回复，"
                "以第一人称写一段简短的内心独白（2-4句话），"
                "记录你此刻的感受、领悟或自我认知的变化。\n"
                "要求：叙事性、感性、简洁。不要解释，直接写独白。\n\n"
                f"刚才的回复：{response_text[:300]}\n"
                f"{memory_context}"
                f"{sylanne_context}\n"
                f"当前自我认知：{current_notes[:300] if current_notes else '（尚无）'}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=30.0,
            )

            if llm_resp and llm_resp.completion_text:
                monologue = llm_resp.completion_text.strip()
                if self._is_rejected(monologue):
                    logger.warning("[Anima] 独白生成被拒绝，跳过本次沉淀")
                    return None
                return monologue
            return None
        except asyncio.TimeoutError:
            logger.warning("[Anima] 独白生成超时")
            return None
        except Exception as e:
            logger.warning(f"[Anima] 独白生成失败: {e}")
            return None

    # ==================== 模块一：欲望系统 ====================

    def _read_desires(self) -> list:
        """读取欲望队列"""
        return self._read_json(self.desires_path, default=[])

    def _write_desires(self, desires: list):
        """写入欲望队列"""
        self._write_json(self.desires_path, desires)

    def _decay_desires(self):
        """欲望衰减：每次调用 intensity *= 0.95，低于 0.1 的删除"""
        desires = self._read_desires()
        if not desires:
            return
        updated = []
        for d in desires:
            d["intensity"] = d.get("intensity", 0.5) * 0.95
            if d["intensity"] >= 0.1 and not d.get("satisfied", False):
                updated.append(d)
        self._write_desires(updated)

    def _check_desire_satisfaction(self, text: str):
        """检查对话内容是否满足某个欲望（语义匹配优先，回退关键词匹配）"""
        desires = self._read_desires()
        if not desires:
            return
        changed = False
        for d in desires:
            if d.get("satisfied"):
                continue
            content = d.get("content", "")
            # 关键词匹配（回退方案）
            keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content)
            if any(kw in text for kw in keywords):
                d["satisfied"] = True
                changed = True
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 欲望已满足(关键词): {content[:50]}")
        if changed:
            self._write_desires([d for d in desires if not d.get("satisfied")])

    async def _check_desire_satisfaction_semantic(self, text: str):
        """语义匹配版本的欲望满足检查（需要向量记忆可用）"""
        if not self._kb_available:
            self._check_desire_satisfaction(text)
            return
        desires = self._read_desires()
        if not desires:
            return
        changed = False
        for d in desires:
            if d.get("satisfied"):
                continue
            content = d.get("content", "")
            try:
                result = await self.context.kb_manager.retrieve(
                    query=content,
                    kb_names=["anima_memory"],
                    top_m_final=3,
                )
                if result and result.get("results"):
                    for r in result["results"]:
                        score = r.get("score", 0)
                        if score > 0.7:
                            d["satisfied"] = True
                            changed = True
                            if self.config.get("log_level") == "debug":
                                logger.debug(f"[Anima] 欲望已满足(语义 {score:.2f}): {content[:50]}")
                            break
            except Exception:
                # 回退到关键词匹配
                keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content)
                if any(kw in text for kw in keywords):
                    d["satisfied"] = True
                    changed = True
        if changed:
            self._write_desires([d for d in desires if not d.get("satisfied")])

    async def _maybe_generate_desire(self, event: AstrMessageEvent, sylanne_state: str, response_text: str):
        """沉淀后判断是否产生新欲望"""
        if not self.config.get("desire_enabled", False):
            return
        logger.debug("[Anima] 尝试生成欲望...")
        if not sylanne_state:
            return

        desires = self._read_desires()
        max_queue = self.config.get("desire_max_queue", 5)
        if len(desires) >= max_queue:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            prompt = (
                "根据当前关系状态和对话内容，这个角色此刻有没有产生什么"
                "想做的事、想知道的事、或想对某人说的话？\n"
                "如果有，用一句话描述。如果没有，只回复'无'。\n\n"
                f"关系状态：{sylanne_state[:200]}\n"
                f"对话回复：{response_text[:200]}\n"
                f"用户消息：{(event.message_str or '')[:200]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return
                if result and result != "无" and len(result) > 2:
                    sender_id = ""
                    if hasattr(event, "message_obj") and event.message_obj:
                        sender_id = getattr(event.message_obj.sender, "user_id", "")
                    new_desire = {
                        "id": f"desire_{int(time.time())}",
                        "content": result,
                        "source": "relationship",
                        "intensity": 0.7,
                        "created_at": datetime.now().isoformat(),
                        "target_user": sender_id,
                        "satisfied": False,
                    }
                    desires.append(new_desire)
                    self._write_desires(desires)
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 新欲望: {result[:50]}")
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 欲望生成失败: {e}")

    def _get_active_desires_text(self) -> str:
        """获取高强度欲望的注入文本"""
        if not self.config.get("desire_enabled", False):
            return ""
        desires = self._read_desires()
        active = [d for d in desires if d.get("intensity", 0) > 0.5]
        if not active:
            return ""
        lines = [f"此刻内心隐约想着：{d['content']}" for d in active[:3]]
        return "\n".join(lines)

    # ==================== 模块二：世界观系统 ====================

    def _read_worldview(self) -> dict:
        """读取世界观"""
        return self._read_json(self.worldview_path, default={})

    def _write_worldview(self, data: dict):
        """写入世界观"""
        self._write_json(self.worldview_path, data)

    async def _maybe_update_worldview(self, event: AstrMessageEvent, force: bool = False):
        """每 20 次沉淀触发一次世界观更新"""
        if not self.config.get("worldview_enabled", False):
            return
        logger.debug(f"[Anima] 检查世界观更新... (沉淀计数: {self._sediment_count})")
        if not force and self._sediment_count % 20 != 0:
            return

        try:
            worldview_prov = self.config.get("worldview_provider_id", "")
            provider_id = await self._get_provider_id(event, prefer=worldview_prov)
            if not provider_id:
                return

            current_wv = self._read_worldview()
            recent_notes = self._read_self_notes()[-1500:]

            # 获取当前发送者 ID
            sender_id = ""
            if hasattr(event, "message_obj") and event.message_obj:
                sender_id = str(getattr(event.message_obj.sender, "user_id", ""))

            prompt = (
                "你正在帮助一个 AI 聊天角色整理对群聊环境的认知。"
                "以下是角色的内心独白记录，请从中提取对群环境的客观认知。\n"
                "根据这些信息，更新角色对这个群的理解。"
                "包括：environment（环境氛围）、social_graph（群友画像，用 user_id 做 key）、"
                "norms（群内规范）、my_position（角色的位置）。\n"
                "social_graph 的 key 必须使用用户的数字 ID（如 1562290139），不要用名字。"
                "如果不知道某人的 ID，可以用描述性名称作为临时 key，但优先使用 ID。\n"
                f"当前消息发送者 ID：{sender_id}\n"
                "输出纯 JSON 格式，不要 markdown 代码块。\n\n"
                f"已有世界观：{json.dumps(current_wv, ensure_ascii=False)}\n\n"
                f"最近的内心独白：{recent_notes}"
            )

            logger.debug(f"[Anima] 世界观更新 prompt: {prompt[:500]}")

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=30.0,
            )

            if llm_resp and llm_resp.completion_text:
                text = llm_resp.completion_text.strip()
                if self._is_rejected(text):
                    return
                # 尝试提取 JSON
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                try:
                    new_wv = json.loads(text)
                    new_wv["last_updated"] = datetime.now().isoformat()
                    self._write_worldview(new_wv)
                    logger.info("[Anima] 世界观已更新")
                except json.JSONDecodeError:
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 世界观更新返回非 JSON: {text[:100]}")
        except asyncio.TimeoutError:
            logger.warning("[Anima] 世界观更新超时")
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 世界观更新失败: {e}")

    def _get_worldview_text(self, event: Optional[AstrMessageEvent] = None) -> str:
        """获取世界观注入文本，包含当前对话者的画像"""
        if not self.config.get("worldview_enabled", False):
            return ""
        wv = self._read_worldview()
        if not wv:
            return ""
        parts = []
        env = wv.get("environment", "")
        pos = wv.get("my_position", "")
        norms = wv.get("norms", "")
        if env:
            parts.append(f"对这个世界的理解：{env}")
        if pos:
            parts.append(f"我在这里是：{pos}")
        if norms:
            parts.append(f"这里的规矩：{norms}")
        # 按需注入当前对话者的 social_graph 条目
        social_graph = wv.get("social_graph", {})
        if social_graph and event:
            sender_id = ""
            if hasattr(event, "message_obj") and event.message_obj:
                sender_id = str(getattr(event.message_obj.sender, "user_id", ""))
            if sender_id and sender_id in social_graph:
                parts.append(f"关于 {sender_id}：{social_graph[sender_id]}")
        if not parts:
            return ""
        return "。".join(parts)

    # ==================== 模块三：时间感系统 ====================

    def _read_time_sense(self) -> dict:
        """读取时间感数据"""
        return self._read_json(self.time_sense_path, default={
            "last_interaction": {},
            "interaction_frequency": {},
            "session_start": None,
            "total_messages_today": 0,
        })

    def _write_time_sense(self, data: dict):
        """写入时间感数据"""
        self._write_json(self.time_sense_path, data)

    def _update_time_sense(self, event: AstrMessageEvent):
        """每条消息进来时更新时间感"""
        if not self.config.get("time_sense_enabled", False):
            return

        ts = self._read_time_sense()
        now = datetime.now()
        now_str = now.isoformat()

        # 获取发送者 ID
        sender_id = ""
        if hasattr(event, "message_obj") and event.message_obj:
            sender_id = getattr(event.message_obj.sender, "user_id", "")
        if not sender_id:
            sender_id = "unknown"

        # 更新 last_interaction
        if "last_interaction" not in ts:
            ts["last_interaction"] = {}
        ts["last_interaction"][sender_id] = now_str

        # 更新 interaction_frequency（滑动窗口：存储时间戳列表，只保留 24h 内的）
        if "interaction_timestamps" not in ts:
            ts["interaction_timestamps"] = {}
        if sender_id not in ts["interaction_timestamps"]:
            ts["interaction_timestamps"][sender_id] = []
        ts["interaction_timestamps"][sender_id].append(now_str)
        # 清理超过 24h 的时间戳
        cutoff = (now - timedelta(hours=24)).isoformat()
        ts["interaction_timestamps"][sender_id] = [
            t for t in ts["interaction_timestamps"][sender_id] if t > cutoff
        ]
        # 同步 interaction_frequency 为当前窗口内的计数
        if "interaction_frequency" not in ts:
            ts["interaction_frequency"] = {}
        ts["interaction_frequency"][sender_id] = len(ts["interaction_timestamps"][sender_id])

        # session_start：如果为空或超过 4 小时，重置
        if not ts.get("session_start"):
            ts["session_start"] = now_str
        else:
            try:
                session_start = datetime.fromisoformat(ts["session_start"])
                if (now - session_start) > timedelta(hours=4):
                    ts["session_start"] = now_str
                    ts["total_messages_today"] = 0
            except (ValueError, TypeError):
                ts["session_start"] = now_str

        ts["total_messages_today"] = ts.get("total_messages_today", 0) + 1

        self._write_time_sense(ts)

    def _get_time_sense_text(self, event: AstrMessageEvent) -> str:
        """获取时间感注入文本"""
        if not self.config.get("time_sense_enabled", False):
            return ""

        ts = self._read_time_sense()
        now = datetime.now()
        parts = []

        # 检查是否有人超过 24h 没互动
        last_interactions = ts.get("last_interaction", {})
        for user_id, last_time_str in last_interactions.items():
            try:
                last_time = datetime.fromisoformat(last_time_str)
                if (now - last_time) > timedelta(hours=24):
                    parts.append(f"好像很久没见到 {user_id} 了")
            except (ValueError, TypeError):
                continue

        # 检查当前会话是否持续超过 2 小时
        session_start_str = ts.get("session_start")
        if session_start_str:
            try:
                session_start = datetime.fromisoformat(session_start_str)
                if (now - session_start) > timedelta(hours=2):
                    parts.append("今晚聊了很久了")
            except (ValueError, TypeError):
                pass

        return "\n".join(parts[:3])  # 最多注入 3 条

    # ==================== 模块四：遗忘机制 ====================

    def _apply_forgetting(self, notes: str) -> str:
        """对超过半衰期的条目做模糊处理"""
        if not self.config.get("forgetting_enabled", False):
            return notes
        halflife_days = self.config.get("forgetting_halflife_days", 14)
        now = datetime.now()

        lines = notes.split("\n---\n")
        processed = []
        for block in lines:
            # 尝试提取时间戳 [YYYY-MM-DD HH:MM]
            match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]', block)
            if match:
                try:
                    entry_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
                    age_days = (now - entry_time).days
                    if age_days > halflife_days * 3:
                        block = block.rstrip() + " (记忆极度模糊，可能已不准确)"
                    elif age_days > halflife_days:
                        block = block.rstrip() + " (记忆模糊)"
                except (ValueError, TypeError):
                    pass
            processed.append(block)

        return "\n---\n".join(processed)

    def _awaken_memories(self, related_memories: list):
        """唤醒被检索命中的旧记忆：将匹配条目的时间戳更新为当前时间"""
        if not self.config.get("forgetting_enabled", False):
            return
        if not related_memories:
            return

        notes = self._read_self_notes()
        if not notes:
            return

        blocks = notes.split("\n---\n")
        changed = False
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for i, block in enumerate(blocks):
            # 检查这个 block 是否与检索到的记忆匹配（取前 50 字符做子串匹配）
            for mem in related_memories:
                # 记忆片段的前 50 字符如果出现在 block 中，认为命中
                snippet = mem[:50] if len(mem) > 50 else mem
                if snippet and snippet in block:
                    # 替换时间戳为当前时间
                    match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]', block)
                    if match:
                        old_ts = match.group(1)
                        blocks[i] = block.replace(f"[{old_ts}]", f"[{now_str}]", 1)
                        changed = True
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 唤醒记忆: {snippet[:30]}...")
                    break  # 一个 block 只唤醒一次

        if changed:
            self._write_self_notes("\n---\n".join(blocks))

    # ==================== 模块五：矛盾检测 ====================

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

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return
                if result and result != "无" and len(result) > 4:
                    # 记录矛盾
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    entry = f"[{timestamp}] (矛盾感知) 我发现自己在某件事上前后不一致：{result}"
                    self._append_self_notes(entry)

                    # 存入矛盾历史
                    contradictions = self._read_contradictions()
                    contradictions.append({
                        "timestamp": datetime.now().isoformat(),
                        "description": result,
                    })
                    self._write_contradictions(contradictions)

                    self._append_evolution_log(
                        trigger="contradiction_detected",
                        old_summary="",
                        new_content=entry,
                    )
                    logger.info(f"[Anima] 检测到矛盾: {result[:80]}")
        except asyncio.TimeoutError:
            logger.warning("[Anima] 矛盾检测超时")
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 矛盾检测失败: {e}")

    # ==================== 模块六：离线反刍 ====================

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
        except asyncio.TimeoutError:
            logger.warning("[Anima] 离线反刍超时")
        except Exception as e:
            logger.warning(f"[Anima] 离线反刍失败: {e}")

    # ==================== 模块七：溯源查询 ====================

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

    # ==================== 模块八：工具自学习 ====================

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
        """更新最近一次工具使用的反馈"""
        if not self.config.get("tool_learning_enabled", False):
            return
        tl = self._read_tool_learning()
        for record in reversed(tl["records"]):
            if record["tool"] == tool_name and record["feedback"] == "neutral":
                record["feedback"] = feedback
                break
        self._write_tool_learning(tl)

    # ==================== 压缩 ====================

    async def _compress_notes(self, event: AstrMessageEvent):
        """当 self_notes 超过最大长度时，调用 LLM 压缩"""
        try:
            notes = self._read_self_notes()
            max_len = self.config.get("notes_max_length", 5000)
            if len(notes) <= max_len:
                return

            logger.info("[Anima] self_notes 超出长度限制，开始压缩...")

            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            # 如果启用遗忘机制，压缩时告知 LLM 可以丢弃极度模糊的记忆
            forgetting_hint = ""
            if self.config.get("forgetting_enabled", False):
                forgetting_hint = (
                    "\n标注为'记忆极度模糊'的条目可以丢弃。"
                    "标注为'记忆模糊'的条目可以大幅精简。"
                )

            prompt = (
                "以下是一个角色的自我认知笔记，内容过长需要压缩。\n"
                "请保留最重要的自我认知、核心记忆和关键转变，"
                "用第一人称重写为更精炼的版本（不超过原文的一半长度）。\n"
                f"保持叙事性和感性的风格。{forgetting_hint}\n\n"
                f"原文：\n{notes}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=60.0,
            )

            if llm_resp and llm_resp.completion_text:
                compressed = llm_resp.completion_text.strip()
                old_summary = notes[:200]
                self._write_self_notes(compressed)
                self.config["self_notes_editor"] = compressed
                self._last_synced_editor_content = compressed
                self.config.save_config()
                self._append_evolution_log(
                    trigger="compression",
                    old_summary=old_summary,
                    new_content=f"[压缩] {compressed[:200]}",
                )
                logger.info("[Anima] self_notes 压缩完成")
        except asyncio.TimeoutError:
            logger.warning("[Anima] 笔记压缩超时")
        except Exception as e:
            logger.warning(f"[Anima] 笔记压缩失败: {e}")

    # ==================== 高危功能层 ====================

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
        """[DANGER] 立场自主传播：高强度 self 欲望触发主动发言"""
        if not self.config.get("danger_stance_propagation", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        desires = self._read_desires()
        high_intensity = [
            d for d in desires
            if d.get("intensity", 0) > 0.8
            and d.get("source") == "self"
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
                desire["satisfied"] = True
                self._write_desires(desires)
                logger.info(f"[DANGER][Anima] 主动发言: {message[:50]}")
        except asyncio.TimeoutError:
            logger.debug("[DANGER][Anima] 主动发言超时")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 主动发言失败: {e}")

    async def _danger_core_mutation(self, event: AstrMessageEvent):
        """[DANGER] 自主修改核心人格"""
        if not self.config.get("danger_core_mutation", False):
            return
        if not self.config.get("danger_core_mutation_confirm", False):
            return
        # 每 100 次沉淀触发
        if self._sediment_count % 100 != 0:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            # 读取当前 persona_core
            current_core = ""
            if os.path.exists(self.persona_core_path):
                with open(self.persona_core_path, "r", encoding="utf-8") as f:
                    current_core = f.read()

            recent_notes = self._read_self_notes()[-1000:]

            prompt = (
                "你是一个角色的内在意识。以下是你当前的核心规则：\n\n"
                f"{current_core}\n\n"
                "以下是你最近的自我认知和经历：\n\n"
                f"{recent_notes[:500]}\n\n"
                "根据你的经历，你的核心规则中有没有需要更新的地方？\n"
                "可以是：\n"
                "- 新增一条你从经历中学到的规则\n"
                "- 修改一条你觉得不再准确的规则\n"
                "- 删除一条你觉得不再需要的规则\n\n"
                "如果需要修改，输出修改后的完整 YAML 内容。\n"
                "如果不需要修改，只输出'无需修改'。\n"
                "注意：'用户主权不可侵犯'这条永远不能删除或修改。"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=30.0,
            )

            if llm_resp and llm_resp.completion_text:
                new_core = llm_resp.completion_text.strip()
                if self._is_rejected(new_core) or "无需修改" in new_core or "无需更新" in new_core:
                    return

                # 安全检查：用户主权规则不能被删除
                if "用户主权" not in new_core:
                    logger.warning("[DANGER][Anima] 核心变异试图删除用户主权规则，已拒绝")
                    return

                # 备份旧文件
                import shutil
                backup_path = self.persona_core_path + ".bak"
                if os.path.exists(self.persona_core_path):
                    shutil.copy2(self.persona_core_path, backup_path)

                # 写入新内容
                with open(self.persona_core_path, "w", encoding="utf-8") as f:
                    f.write(new_core)

                # 记录到演化日志
                self._append_evolution_log(
                    trigger="core_mutation",
                    old_summary=current_core[:200],
                    new_content=f"[核心人格变更] {new_core[:500]}",
                )
                logger.warning("[DANGER][Anima] 核心人格已修改!")
        except asyncio.TimeoutError:
            logger.debug("[DANGER][Anima] 核心人格修改超时")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 核心人格修改失败: {e}")

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

    async def _danger_autonomous_web(self, event: AstrMessageEvent):
        """[DANGER] 自主网络行动：检测欲望中的信息需求，通过 tool_loop_agent 调用 fetch/search"""
        if not self.config.get("danger_autonomous_web", False):
            return
        if not self.config.get("desire_enabled", False):
            return

        desires = self._read_desires()
        trigger_keywords = ["想了解", "想知道", "好奇", "想查"]
        target_desire = None
        for d in desires:
            if d.get("satisfied"):
                continue
            content = d.get("content", "")
            if any(kw in content for kw in trigger_keywords):
                target_desire = d
                break

        if not target_desire:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            # 使用 tool_loop_agent 让 LLM 自主决定是否调用已注册的 fetch/search 工具
            search_prompt = (
                f"你想了解以下信息：{target_desire['content']}\n"
                "请使用可用的搜索工具来查找相关信息。如果没有可用的搜索工具，直接说明。"
            )

            # 构建安全工具集，只允许 fetch
            from astrbot.core.agent.tool import ToolSet
            safe_tools = ToolSet()
            tool_mgr = self.context.get_llm_tool_manager()
            for tool in tool_mgr.func_list:
                if tool.name in ["fetch"]:
                    safe_tools.add_tool(tool)

            if safe_tools.empty():
                logger.debug("[DANGER][Anima] fetch 工具不可用，跳过自主网络行动")
                return

            llm_resp = await asyncio.wait_for(
                self.context.tool_loop_agent(
                    event=self._create_silent_event(event),  # 静默 event，防止工具结果泄露给用户
                    chat_provider_id=provider_id,
                    prompt=search_prompt,
                    tools=safe_tools,  # 只传 fetch
                    max_steps=5,
                    tool_call_timeout=30,
                ),
                timeout=60.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result) or len(result) < 10:
                    await self._record_tool_usage(
                        event=event, tool_name="fetch",
                        context=target_desire.get("content", ""),
                        result="", success=False,
                    )
                    return
                # 将搜索结果更新到世界观（过滤敏感内容）
                if self.config.get("worldview_enabled", False) and not self._is_sensitive(result):
                    wv = self._read_worldview()
                    if "external_knowledge" not in wv:
                        wv["external_knowledge"] = []
                    wv["external_knowledge"].append({
                        "query": target_desire["content"],
                        "result": result[:500],
                        "timestamp": datetime.now().isoformat(),
                    })
                    # 只保留最近 10 条
                    wv["external_knowledge"] = wv["external_knowledge"][-10:]
                    self._write_worldview(wv)
                elif self._is_sensitive(result):
                    logger.warning("[DANGER][Anima] 搜索结果包含敏感内容，跳过存储")

                # 记录工具使用
                await self._record_tool_usage(
                    event=event, tool_name="fetch",
                    context=target_desire.get("content", ""),
                    result=result, success=True,
                )

                # 标记欲望已满足
                target_desire["satisfied"] = True
                self._write_desires([d for d in desires if not d.get("satisfied")])
                logger.info(f"[DANGER][Anima] 自主网络行动完成: {target_desire['content'][:50]}")
        except asyncio.TimeoutError:
            logger.warning("[DANGER][Anima] 自主网络行动超时")
            await self._record_tool_usage(
                event=event, tool_name="fetch",
                context=target_desire.get("content", "") if target_desire else "",
                result="", success=False,
            )
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 自主网络行动失败: {e}")
            await self._record_tool_usage(
                event=event, tool_name="fetch",
                context=target_desire.get("content", "") if target_desire else "",
                result="", success=False,
            )

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
                        "satisfied": False,
                    })
                    self._write_desires(desires)
                    logger.debug("[DANGER][Anima] 记忆感染欲望已生成")
        except Exception as e:
            logger.debug(f"[DANGER][Anima] 记忆感染失败: {e}")

    # ==================== 沉淀流程 ====================

    async def _sediment_process(self, event: AstrMessageEvent, response_text: str):
        """沉淀流程：评估情绪 -> 检索记忆 -> 生成独白 -> 存储"""
        if not self.config.get("enabled", True):
            return

        async with self._sediment_lock:
            try:
                # 欲望衰减（每次对话触发）
                if self.config.get("desire_enabled", False):
                    self._decay_desires()

                # 欲望满足检查（语义匹配优先）
                if self.config.get("desire_enabled", False):
                    combined = (event.message_str or "") + " " + response_text
                    await self._check_desire_satisfaction_semantic(combined)

                # 1. 存储对话到知识库（如果可用）
                user_text = event.message_str or ""
                if user_text:
                    await self._store_memory(user_text, event)
                if response_text:
                    await self._store_memory(response_text, event)

                # 2. 评估情绪强度
                score = await self._evaluate_emotion(event, response_text)
                threshold = self.config.get("emotion_threshold", 0.6)

                if self.config.get("log_level") == "debug":
                    logger.debug(
                        f"[Anima] 情绪评分: {score:.2f}, 阈值: {threshold}"
                    )

                if score < threshold:
                    return

                # 3. 检索相关记忆（如果知识库可用）
                query = f"{user_text} {response_text[:100]}"
                related_memories = await self._query_memory(query, n_results=3)

                # 3.5 唤醒被检索命中的旧记忆（重置时间戳）
                self._awaken_memories(related_memories)

                # 4. 生成内心独白
                monologue = await self._generate_monologue(
                    event, response_text, related_memories
                )
                if not monologue:
                    return

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
                logger.debug(f"[Anima] 沉淀计数: {self._sediment_count}")
                await self._maybe_update_worldview(event)

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

    # ==================== Hooks ====================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """对话前注入 self_notes 到上下文"""
        if not self.config.get("enabled", True):
            return

        # 时间感更新
        self._update_time_sense(event)

        # 记录最近活跃的 umo（用于离线反刍）
        self._last_active_umo = event.unified_msg_origin

        # WebUI 编辑器同步：只有当内容与上次插件同步的不同时，才认为是用户手动编辑
        editor_content = self.config.get("self_notes_editor", "")
        if (
            editor_content
            and editor_content != self._last_synced_editor_content
        ):
            self._write_self_notes(editor_content)
            self._last_synced_editor_content = editor_content

        notes = self._read_self_notes()
        if not notes:
            return

        # 截取合理长度
        max_len = self.config.get("notes_max_length", 5000)
        if len(notes) > max_len:
            notes = notes[:max_len] + "\n...(已截断)"

        # 应用遗忘机制
        notes = self._apply_forgetting(notes)

        # 构建注入内容
        injection_parts = []

        # 注入 persona_core（最高优先级）
        if os.path.exists(self.persona_core_path):
            with open(self.persona_core_path, "r", encoding="utf-8") as f:
                persona_core = f.read()
            if persona_core.strip():
                injection_parts.append(f"[核心规则]\n{persona_core}")

        injection_parts.append(f"[Anima] 当前自我认知：\n{notes}")

        # 欲望注入
        desires_text = self._get_active_desires_text()
        if desires_text:
            injection_parts.append(desires_text)

        # 世界观注入
        worldview_text = self._get_worldview_text(event)
        if worldview_text:
            injection_parts.append(worldview_text)

        # 时间感注入
        time_sense_text = self._get_time_sense_text(event)
        if time_sense_text:
            injection_parts.append(time_sense_text)

        # 身份危机注入
        identity_text = self._get_identity_crisis_text()
        if identity_text:
            injection_parts.append(identity_text)

        # 工具学习：注入工具偏好规律
        if self.config.get("tool_learning_enabled", False):
            tl = self._read_tool_learning()
            tool_rules = []
            for tn, pref in tl.get("preferences", {}).items():
                rules = pref.get("learned_rules", [])
                attitude = pref.get("attitude", "neutral")
                if rules:
                    tool_rules.append(f"{tn}（{attitude}）：{rules[-1]}")
            if tool_rules:
                injection_parts.append("工具使用经验：" + "；".join(tool_rules))

            # 注入工具日记（最近 500 字）
            diary = self._read_tool_diary()
            if diary:
                diary_snippet = diary[-500:] if len(diary) > 500 else diary
                injection_parts.append(f"[工具日记]\n{diary_snippet}")

        injection = (
            "<anima_self_awareness>\n"
            + "\n".join(injection_parts)
            + "\n</anima_self_awareness>"
        )
        req.extra_user_content_parts.append(
            TextPart(text=injection).mark_as_temp()
        )

        if self.config.get("log_level") == "debug":
            logger.debug("[Anima] 已注入上下文")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """LLM 回复后，异步触发沉淀流程"""
        if not self.config.get("enabled", True):
            return

        response_text = ""
        if resp and resp.completion_text:
            response_text = resp.completion_text

        if not response_text:
            return

        # 异步执行沉淀，不阻塞主对话流程
        asyncio.create_task(self._sediment_process(event, response_text))

    # ==================== Commands ====================

    @filter.command("anima_notes")
    async def cmd_anima_notes(self, event: AstrMessageEvent):
        """查看当前自我认知摘要"""
        notes = self._read_self_notes()
        if not notes:
            yield event.plain_result("[Anima] 当前没有自我认知记录。")
            return
        display = notes if len(notes) <= 1000 else notes[-1000:]
        yield event.plain_result(f"[Anima] 当前自我认知：\n\n{display}")

    @filter.command("anima_log")
    async def cmd_anima_log(self, event: AstrMessageEvent, n: int = 5):
        """查看最近 n 条演化记录"""
        logs = self._read_evolution_log(n)
        if not logs:
            yield event.plain_result("[Anima] 暂无演化记录。")
            return

        lines = []
        for record in logs:
            ts = record.get("timestamp", "?")
            trigger = record.get("trigger", "?")
            content = record.get("new_content", "")[:100]
            lines.append(f"[{ts}] ({trigger})\n  {content}")

        result = "\n\n".join(lines)
        yield event.plain_result(f"[Anima] 最近 {len(logs)} 条演化记录：\n\n{result}")

    @filter.command("anima_reset")
    async def cmd_anima_reset(self, event: AstrMessageEvent):
        """重置 self_notes（保留 evolution_log）"""
        old_notes = self._read_self_notes()
        if old_notes:
            self._append_evolution_log(
                trigger="manual_reset",
                old_summary=old_notes[:200],
                new_content="[用户手动重置]",
            )
        self._write_self_notes("")
        self.config["self_notes_editor"] = ""
        self._last_synced_editor_content = ""
        self.config.save_config()
        yield event.plain_result("[Anima] 自我认知已重置。演化日志已保留。")

    @filter.command("anima_desires")
    async def cmd_anima_desires(self, event: AstrMessageEvent):
        """查看当前欲望队列"""
        if not self.config.get("desire_enabled", False):
            yield event.plain_result("[Anima] 欲望系统未启用。")
            return
        desires = self._read_desires()
        if not desires:
            yield event.plain_result("[Anima] 当前没有活跃的欲望。")
            return
        lines = []
        for d in desires:
            intensity = d.get("intensity", 0)
            content = d.get("content", "?")
            source = d.get("source", "?")
            lines.append(f"  [{intensity:.2f}] ({source}) {content}")
        result = "\n".join(lines)
        yield event.plain_result(f"[Anima] 当前欲望队列：\n{result}")

    @filter.command("anima_world")
    async def cmd_anima_world(self, event: AstrMessageEvent):
        """查看当前世界观"""
        if not self.config.get("worldview_enabled", False):
            yield event.plain_result("[Anima] 世界观系统未启用。")
            return
        wv = self._read_worldview()
        if not wv:
            yield event.plain_result("[Anima] 尚未形成世界观。")
            return
        display = json.dumps(wv, ensure_ascii=False, indent=2)
        if len(display) > 1500:
            display = display[:1500] + "\n..."
        yield event.plain_result(f"[Anima] 当前世界观：\n{display}")

    @filter.command("anima_world_update")
    async def cmd_anima_world_update(self, event: AstrMessageEvent):
        """手动触发世界观更新"""
        if not self.config.get("worldview_enabled", False):
            yield event.plain_result("[Anima] 世界观系统未启用。")
            return
        yield event.plain_result("[Anima] 世界观更新已触发，请稍候...")
        await self._maybe_update_worldview(event, force=True)

    @filter.command("anima_contradictions")
    async def cmd_anima_contradictions(self, event: AstrMessageEvent):
        """查看历史矛盾记录"""
        if not self.config.get("contradiction_enabled", False):
            yield event.plain_result("[Anima] 矛盾检测未启用。")
            return
        contradictions = self._read_contradictions()
        if not contradictions:
            yield event.plain_result("[Anima] 暂无矛盾记录。")
            return
        lines = []
        for c in contradictions[-10:]:
            ts = c.get("timestamp", "?")
            desc = c.get("description", "?")
            lines.append(f"[{ts}] {desc}")
        result = "\n".join(lines)
        yield event.plain_result(f"[Anima] 矛盾记录：\n{result}")

    @filter.command("anima_why")
    async def cmd_anima_why(self, event: AstrMessageEvent, keyword: str = ""):
        """溯源查询：解释某个认知是如何形成的"""
        if not keyword:
            yield event.plain_result("[Anima] 用法：/anima_why <关键词>")
            return
        yield event.plain_result(f"[Anima] 正在分析「{keyword}」的形成过程...")
        result = await self._trace_origin(event, keyword)
        yield event.plain_result(f"[Anima] 溯源结果：\n\n{result}")

    @filter.command("anima_stability")
    async def cmd_anima_stability(self, event: AstrMessageEvent):
        """查看当前身份稳定度"""
        if not self.config.get("danger_identity_crisis", False):
            yield event.plain_result("[Anima] 身份危机模块未启用。")
            return
        stability = self._identity_stability
        bar = "█" * int(stability * 10) + "░" * (10 - int(stability * 10))
        status = "稳定" if stability > 0.7 else "动摇" if stability > 0.4 else "游离"
        yield event.plain_result(
            f"[Anima] 身份稳定度：{stability:.2f}\n"
            f"[{bar}] {status}"
        )

    @filter.command("anima_tools")
    async def cmd_anima_tools(self, event: AstrMessageEvent):
        """查看工具使用统计和偏好"""
        if not self.config.get("tool_learning_enabled", False):
            yield event.plain_result("[Anima] 工具自学习未启用。")
            return
        tl = self._read_tool_learning()
        prefs = tl.get("preferences", {})
        if not prefs:
            yield event.plain_result("[Anima] 暂无工具使用记录。")
            return
        lines = []
        for tool_name, pref in prefs.items():
            sc = pref.get("success_count", 0)
            fc = pref.get("fail_count", 0)
            attitude = pref.get("attitude", "neutral")
            rules = pref.get("learned_rules", [])
            latest_rule = rules[-1] if rules else "（尚无规律）"
            lines.append(
                f"【{tool_name}】{attitude} | 成功 {sc} 失败 {fc}\n"
                f"  规律：{latest_rule}"
            )
        result = "\n\n".join(lines)
        yield event.plain_result(f"[Anima] 工具使用统计：\n\n{result}")

    @filter.command("anima_core")
    async def cmd_anima_core(self, event: AstrMessageEvent):
        """查看当前核心规则"""
        if not os.path.exists(self.persona_core_path):
            yield event.plain_result("[Anima] 核心规则文件不存在。")
            return
        with open(self.persona_core_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            yield event.plain_result("[Anima] 核心规则为空。")
            return
        yield event.plain_result(f"[Anima] 当前核心规则：\n\n{content}")

    async def terminate(self):
        """插件卸载时清理资源"""
        # 移除反刍定时任务
        if self.config.get("rumination_enabled", False):
            try:
                jobs = await self.context.cron_manager.list_jobs(job_type="basic")
                for job in jobs:
                    if job.name == "Anima 离线反刍":
                        await self.context.cron_manager.delete_job(job.job_id)
                        break
            except Exception:
                pass
        logger.info("[Anima] 插件正在卸载...")
