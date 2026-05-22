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

        logger.info("[Anima] 插件初始化完成")

    # ==================== 通用工具方法 ====================

    def _is_rejected(self, text: str) -> bool:
        """检查文本是否包含拒绝短语"""
        reject_phrases = self.config.get("reject_phrases", [
            "I can't discuss", "I cannot", "我无法", "我不能",
            "I'm not able", "I don't think I should",
        ])
        return any(phrase.lower() in text.lower() for phrase in reject_phrases)

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
        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if kb:
                await kb.upload_document(
                    file_name=f"memory_{int(time.time())}",
                    file_content=None,
                    file_type="txt",
                    pre_chunked_text=[text],
                )
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 存储记忆: {text[:50]}...")
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
                return [r["content"] for r in result["results"]]
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
                                    return state_str
                        return str(result)
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
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
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
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
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
        """检查对话内容是否满足某个欲望（简单关键词匹配）"""
        desires = self._read_desires()
        if not desires:
            return
        changed = False
        for d in desires:
            if d.get("satisfied"):
                continue
            content = d.get("content", "")
            # 提取欲望中的关键词（长度>=2的中文词或英文词）
            keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content)
            if any(kw in text for kw in keywords):
                d["satisfied"] = True
                changed = True
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 欲望已满足: {content[:50]}")
        if changed:
            # 移除已满足的
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
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
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
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            if not provider_id:
                return

            current_wv = self._read_worldview()
            recent_notes = self._read_self_notes()[-1500:]

            prompt = (
                "根据最近的对话记录和已有的世界观认知，更新你对这个群的理解。\n"
                "包括：environment（环境氛围）、social_graph（群友画像，用 user_id 做 key）、"
                "norms（群内规范）、my_position（你的位置）。\n"
                "输出纯 JSON 格式，不要 markdown 代码块。\n\n"
                f"已有世界观：{json.dumps(current_wv, ensure_ascii=False)[:500]}\n\n"
                f"最近的自我认知：{recent_notes[:500]}"
            )

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

    # ==================== 压缩 ====================

    async def _compress_notes(self, event: AstrMessageEvent):
        """当 self_notes 超过最大长度时，调用 LLM 压缩"""
        try:
            notes = self._read_self_notes()
            max_len = self.config.get("notes_max_length", 5000)
            if len(notes) <= max_len:
                return

            logger.info("[Anima] self_notes 超出长度限制，开始压缩...")

            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
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

                # 欲望满足检查
                if self.config.get("desire_enabled", False):
                    combined = (event.message_str or "") + " " + response_text
                    self._check_desire_satisfaction(combined)

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
        injection_parts = [f"[Anima] 当前自我认知：\n{notes}"]

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

    async def terminate(self):
        """插件卸载时清理资源"""
        logger.info("[Anima] 插件正在卸载...")
