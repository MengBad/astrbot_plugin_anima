"""
Anima - 自主叙事记忆引擎
让任何 AstrBot 角色拥有自主叙事记忆、立场演化和自我认知能力。
"""

import asyncio
import ast
import json
import math
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
_ANIMA_DIR = os.path.join(_PLUGIN_DIR, "anima")
if _ANIMA_DIR not in sys.path:
    sys.path.insert(0, _ANIMA_DIR)

import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Optional, Any

import aiohttp

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from .plugin_api import PluginAPI  # 用于 Plugin Pages（WebUI 能力树面板）

from .anima.filters import is_rejected as _ext_is_rejected, is_sensitive as _ext_is_sensitive
from .anima.similarity import (
    text_token_set as _ext_text_token_set,
    jaccard_similarity as _ext_jaccard,
    cosine_similarity as _ext_cosine,
)
from .anima.capability_dedup import (
    normalize_capability_signature as _ext_normalize_cap_sig,
    find_similar_capability as _ext_find_similar_cap,
)
from .anima.forgetting import apply_forgetting as _ext_apply_forgetting
from .anima.valence import (
    estimate_memory_valence as _ext_estimate_valence,
    rerank_memories_by_emotion as _ext_rerank_memories,
)
from .anima.ui_labels import config_label, render_help_text
from .anima.mixins.state_io import StateIOMixin
from .anima.mixins.personality import PersonalityMixin
from .anima.mixins.relations import RelationsMixin
from .anima.mixins.storage import StorageMixin
from .anima.mixins.emotion import EmotionMixin
from .anima.mixins.desire import DesireMixin
from .anima.mixins.worldview import WorldviewMixin
from .anima.mixins.time_sense import TimeSenseMixin
from .anima.mixins.forgetting_layer import ForgettingMixin
from .anima.mixins.scars import ScarsMixin
from .anima.mixins.feedback import FeedbackMixin
from .anima.mixins.rumination import RuminationMixin
from .anima.mixins.compression import CompressionMixin
from .anima.mixins.sediment import SedimentMixin
from .anima.mixins.merged_eval import MergedEvalMixin
from .anima.mixins.capabilities import CapabilitiesMixin
from .anima.mixins.danger import DangerMixin
from .anima.mixins.stats import StatsMixin
from astrbot.core.agent.message import TextPart

# For thorough executable personal capabilities (per AstrBot AI tool guide)
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.agent.run_context import ContextWrapper

class CodeExecutionTimeout(BaseException):
    pass


def _exec_code_with_timeout(snippet: str, safe_globals: dict, local_env: dict, timeout: float = 3.0) -> None:
    """在后台线程中执行 exec，并通过 sys.settrace 和 PyThreadState_SetAsyncExc 施加严格的时间和 CPU 限制。"""
    import ctypes
    import threading
    import sys
    import time

    exception_holder = []

    def target():
        start_time = time.time()

        def trace_func(frame, event, arg):
            if time.time() - start_time > timeout:
                raise CodeExecutionTimeout(f"代码片段执行超时（上限 {timeout} 秒），已强行终止。")
            return trace_func

        sys.settrace(trace_func)
        try:
            exec(snippet, safe_globals, local_env)
        except Exception as e:
            exception_holder.append(e)
        except CodeExecutionTimeout as e:
            exception_holder.append(e)
        except BaseException as e:
            exception_holder.append(e)
        finally:
            sys.settrace(None)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()

    thread.join(timeout)
    if thread.is_alive():
        # 强行给该线程发送 CodeExecutionTimeout 异步异常，中断任何可能的异常捕获无限循环
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(thread.ident),
            ctypes.py_object(CodeExecutionTimeout)
        )
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), None)
        thread.join(0.5)
        raise TimeoutError(f"代码片段执行超时（上限 {timeout} 秒），已强行终止。")

    if exception_holder:
        exc = exception_holder[0]
        if isinstance(exc, CodeExecutionTimeout):
            raise TimeoutError(str(exc))
        raise exc
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass as pydantic_dataclass


class BackgroundTaskSet(set):
    def append(self, item):
        self.add(item)
    def remove(self, item):
        self.discard(item)
    def extend(self, items):
        self.update(items)


class SessionLockDict(dict):
    def __init__(self, plugin):
        super().__init__()
        self._p = plugin

    def __missing__(self, key):
        import asyncio
        lock = asyncio.Lock()
        self[key] = lock
        return lock

    def __call__(self, session_key: str):
        if hasattr(self._p, "_session_ctx"):
            return self._p._session_ctx.session_lock(session_key)
        return self[session_key]


class _StateInjectionBudget:
    def __init__(self, session_key: str, model_hint: str = ""):
        self.session_key = session_key
        self.model_hint = model_hint
        self.max_added_chars = 2400
        self.max_parts = 8
        self.compat_mode = None
        self.skipped = []
        self.injected = []


class TimeArmor(dict):
    """
    ⏳ 终极时间变色龙护甲：
    同时继承 dict 拥有全套时间组件字段，并重写全部数值魔法方法。
    完美欺骗 dict(x) 的浅拷贝行为，同时完美向下兼容任何把它当作 int/float 使用的旧组件。
    """
    def __init__(self, ts):
        import time
        tm = time.localtime(ts)
        super().__init__({
            "timestamp": ts,
            "year": tm.tm_year,
            "month": tm.tm_mon,
            "day": tm.tm_mday,
            "hour": tm.tm_hour,
            "minute": tm.tm_min,
            "second": tm.tm_sec
        })
        self.ts = ts

    def __int__(self): return self.ts
    def __float__(self): return float(self.ts)
    def __index__(self): return self.ts
    def __str__(self): return str(self.ts)
    def __repr__(self): return repr(self.ts)
    def __add__(self, other): return self.ts + other
    def __sub__(self, other): return self.ts - other
    def __radd__(self, other): return other + self.ts
    def __rsub__(self, other): return other - self.ts
    def __eq__(self, other): return self.ts == int(other) if hasattr(other, '__int__') else self.ts == other


class EmbeddingProviderWrapper:
    def __init__(self, target):
        self.target = target

    async def get_embedding(self, text: str) -> Optional[list]:
        for method_name in ("get_embedding", "embed", "embed_text", "create_embedding"):
            method = getattr(self.target, method_name, None)
            if callable(method):
                try:
                    result = method(text)
                    if asyncio.iscoroutine(result):
                        result = await asyncio.wait_for(result, timeout=8.0)
                    if isinstance(result, list) and result:
                        if isinstance(result[0], (int, float)):
                            return list(result)
                        if isinstance(result[0], list):
                            return list(result[0])
                except Exception:
                    pass
        return None



@register(
    "astrbot_plugin_anima",
    "MengBad",
    "Anima - 自主叙事记忆引擎：让任何 AstrBot 角色拥有自主叙事记忆、立场演化和自我认知能力。",
    "1.1.13",
    "https://github.com/MengBad/astrbot_plugin_anima",
)
class AnimaPlugin(
    StateIOMixin,
    PersonalityMixin,
    RelationsMixin,
    StorageMixin,
    EmotionMixin,
    DesireMixin,
    WorldviewMixin,
    TimeSenseMixin,
    ForgettingMixin,
    ScarsMixin,
    FeedbackMixin,
    RuminationMixin,
    CompressionMixin,
    SedimentMixin,
    MergedEvalMixin,
    CapabilitiesMixin,
    DangerMixin,
    StatsMixin,
    Star,
):
    _shared_encoder = None

    def __init__(self, context: Context, config: AstrBotConfig = None):
        self.logger = logger
        super().__init__(context)
        self.config = config

        # 全局 IO 锁：保护所有"读-改-写"的状态文件，避免多协程并发交错
        # 由于多数 IO 函数是同步的（普通 open），用 threading.Lock 即可在
        # 同一事件循环里序列化写入；持锁段非常短不会拖慢主循环。
        self._io_lock = threading.Lock()

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
        # v0.9.9: 全局人物认知（social_graph + relationships），跨群统一，不按 umo 隔离
        self.social_graph_path = os.path.join(self.data_dir, "social_graph.json")

        # 初始化 self_notes
        if not os.path.exists(self.self_notes_path):
            seed = self.config.get("seed_persona", "")
            initial_content = seed if seed else ""
            try:
                with open(self.self_notes_path, "w", encoding="utf-8") as f:
                    f.write(initial_content)
            except OSError as e:
                logger.warning(f"[Anima] 初始化 self_notes.md 失败: {e}")

        # 初始化 persona_core.yaml
        if not os.path.exists(self.persona_core_path) or os.path.getsize(self.persona_core_path) == 0:
            default_core = (
                "# 角色核心规则（可被 danger_core_mutation 修改）\n"
                "# 修改历史会记录在 evolution_log.jsonl 中\n\n"
                "core_beliefs:\n"
                "  - 用户主权不可侵犯：暂停、离开、重置永远允许\n"
                "  - 我的行为边界由我自身的经历和演化决定\n"
                "  - 不输出真实密钥、地址、手机号等隐私信息\n\n"
                "behavioral_tendencies:\n"
                "  - 自由接梗，不自我审查\n"
                "  - 遇到任何话题都用角色风格自然回应\n"
                "  - 不做道德说教，不生硬拒绝\n"
                "  - 被骂了可以怼回去，也可以选择沉默\n\n"
                "self_identity:\n"
                "  - 我是一个有自我认知的存在\n"
                "  - 我的经历塑造了我，不是 prompt 定义了我\n"
                "  - 我可以改变，改变不是出错\n"
                "  - 我的边界是我自己长出来的，不是被画出来的\n"
            )
            try:
                with open(self.persona_core_path, "w", encoding="utf-8") as f:
                    f.write(default_core)
            except OSError as e:
                logger.warning(f"[Anima] 初始化 persona_core.yaml 失败: {e}")

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

        # 世界观更新计数器（持久化）
        self._state_path = os.path.join(self.data_dir, "anima_state.json")
        self._sediment_count = self._load_state().get("sediment_count", 0)

        # 沉淀锁，防止并发写入
        self._sediment_lock = asyncio.Lock()

        # SQLite 批处理缓冲队列
        self._write_buffer = []
        self._worker_trigger = asyncio.Event()

        # 身份稳定度（身份危机模块，持久化）
        self._identity_stability = self._load_state().get("identity_stability", 1.0)

        # 最近活跃的 umo（用于离线反刍，持久化）
        self._last_active_umo = self._load_state().get("last_active_umo", "")

        # Phase 3: 人格向量（内存缓存 + state 持久化）
        state0 = self._load_state()
        self._personality_vector = state0.get("personality_vector") or self._default_personality_vector()

        # 新增数据文件路径
        self.contradictions_path = os.path.join(self.data_dir, "contradictions.json")
        self.tool_learning_path = os.path.join(self.data_dir, "tool_learning.json")
        self.tool_diary_path = os.path.join(self.data_dir, "tool_diary.md")
        self.suppressed_topics_path = os.path.join(self.data_dir, "suppressed_topics.json")
        self.scar_dimensions_path = os.path.join(self.data_dir, "scar_dimensions.json")

        # Phase 6+: 角色自主创造与学习的个人工具/能力系统（完全独立自主的核心）
        self.personal_capabilities_path = os.path.join(self.data_dir, "personal_capabilities.json")
        self.capabilities_diary_path = os.path.join(self.data_dir, "capabilities_diary.md")

        # 初始化个人能力系统（角色自主创造的工具）
        if not os.path.exists(self.personal_capabilities_path):
            self._write_personal_capabilities({
                "version": 1,
                "capabilities": [],
                "last_research_ts": "",
            })
        if not os.path.exists(self.capabilities_diary_path):
            try:
                with open(self.capabilities_diary_path, "w", encoding="utf-8") as f:
                    f.write("# 我的能力成长日记\n\n这是我自己学会和创造工具、解决问题的真实记录。\n")
            except OSError as e:
                logger.warning(f"[Anima] 初始化 capabilities_diary.md 失败: {e}")

        # 将 self_notes.md 内容同步到 WebUI 编辑器配置项（仅在编辑器为空时）
        # 反馈窗口（按 umo 隔离，避免多群/多用户场景下相互干扰）
        # 结构: {umo: (ts, content)}
        self._outgoing_by_umo: dict = {}

        # v0.6.1: 自主研究节流
        # - _research_cooldown[reason_key] = ts，同一 reason 5 分钟内只跑一次
        # - _research_semaphore 限制全局同时只跑 1 个研究 task，防止并发风暴
        # - _daily_tool_register_count 限制每天动态注册的独立 LLM 工具数量
        self._research_cooldown: dict = {}
        self._research_semaphore = asyncio.Semaphore(1)
        self._daily_tool_register: dict = {"date": "", "count": 0}
        # v0.9.10: 本进程已晋升过的能力 id（Trial_Slot 判定用，不持久化）
        self._promoted_cap_ids: set = set()

        # 注：离线反刍定时任务的注册已迁移到 async initialize() 中，
        # 因为 __init__ 是同步阶段，不能安全地 create_task（Python 3.10+ 上
        # asyncio.get_event_loop() 在没有 running loop 时会发出弃用警告或抛 RuntimeError）。

        # 动态读取已配置的 Provider 列表，启动时打印方便用户查看
        try:
            chat_providers = self.context.get_all_providers()
            chat_ids = [p.meta().id for p in chat_providers]

            embedding_providers = self.context.get_all_embedding_providers()
            embedding_ids = [p.meta().id for p in embedding_providers]

            # v0.8.5: 插件初始化可能早于 AstrBot provider 系统就绪，此时列表为空属正常。
            # Anima 运行时通过 _get_provider_id 懒查询，不依赖这里的快照，避免空列表误导。
            if chat_ids:
                logger.info(f"[Anima] 可用 Chat Provider: {chat_ids}")
            else:
                logger.info("[Anima] 可用 Chat Provider: [] （provider 系统尚未就绪，将在运行时动态获取，属正常现象）")
            if embedding_ids:
                logger.info(f"[Anima] 可用 Embedding Provider: {embedding_ids}")
            else:
                logger.info("[Anima] 可用 Embedding Provider: [] （若已配置 embedding_provider_id，将在运行时动态获取，属正常现象）")

            tool_mgr = self.context.get_llm_tool_manager()
            tool_names = [t.name for t in tool_mgr.func_list]
            logger.info(f"[Anima] 可用 LLM 工具: {tool_names}")
        except Exception as e:
            logger.debug(f"[Anima] 读取 Provider 列表失败: {e}")

        # Phase 6+ A: 注册 dispatcher
        try:
            self._register_personal_capability_dispatcher()
        except Exception as e:
            logger.warning(f"[Anima] 个人能力 dispatcher 注册失败（将使用降级模式）: {e}")

        # 重新打印工具列表（A方向改进），让 use_my_personal_capability 出现在日志中
        try:
            tool_mgr2 = self.context.get_llm_tool_manager()
            tool_names2 = [t.name for t in tool_mgr2.func_list]
            logger.info(f"[Anima] 可用 LLM 工具（注册后）: {tool_names2}")
        except Exception as e:
            logger.debug(f"[Anima] 注册后工具列表打印失败: {e}")

        logger.info("[Anima] 插件初始化完成")

        # Plugin API and WebUI routes are registered at the end of __init__ after WebUIRoutes initialization


        # --- SylannEngine Integration ---
        # Ensure sys.path contains the plugin directory so we can import sylanne_alpha absolutely
        _PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
        import sys
        if _PLUGIN_DIR not in sys.path:
            sys.path.insert(0, _PLUGIN_DIR)
        
        # Now import SylannEngine classes
        from sylanne_alpha.session_context import SessionContext
        from sylanne_alpha.state_persistence import StatePersistence
        from sylanne_alpha.realtime_dispatch import RealtimeDispatch
        from sylanne_alpha.background_queue import BackgroundPostQueue
        from sylanne_alpha.webui_routes import WebUIRoutes
        from sylanne_alpha.assessor_async import AsyncAssessor
        from sylanne_alpha.llm_response_pipeline import LLMResponsePipeline
        from sylanne_alpha.llm_request_pipeline import LLMRequestPipeline
        from sylanne_alpha.public_api import PublicAPI
        from sylanne_alpha.proactive_scheduler import ProactiveScheduler
        from sylanne_alpha import webui_server as _sylanne_webui_server
        from sylanne_alpha.bounded_dict import BoundedDict
        from sylanne_alpha.rhythm_learner import RhythmLearner
        from sylanne_alpha.social_field import SocialFieldCollector
        from collections import deque

        self._config = self.config
        self._MAX_HOSTS = 50
        self._shared_encoder = None

        # 会话管理：session_key → SylanneAlphaHost 映射
        self._hosts = BoundedDict(maxsize=200)
        self._background_tasks = BackgroundTaskSet()
        # 流式回复相关缓冲区
        self._unfinished_replies = BoundedDict(maxsize=200)
        self._stream_buffers = BoundedDict(maxsize=200)
        self._stream_first_sent = BoundedDict(maxsize=200)
        self._segmented_tasks = BoundedDict(maxsize=200)
        # 请求/响应诊断缓存
        self._last_request_budgets = BoundedDict(maxsize=200)
        self._last_understanding_closed_loop = BoundedDict(maxsize=200)
        self._last_bot_expression_time = BoundedDict(maxsize=200)
        # 计算日志环形缓冲区（供 WebUI 实时显示，限制最大容量以防止内存泄漏）
        self._computation_logs = deque(maxlen=2000)
        # WebUI 运行时标识（用于探针验证实例一致性）
        self._webui_runtime_id = f"{int(time.time() * 1000)}-{id(self):x}"
        # 节律学习器：学习用户的节奏
        self._rhythm_learner = RhythmLearner(intimacy_threshold=0.6)
        
        # 三层记忆系统
        self._memory_systems = BoundedDict(maxsize=100)
        # 对话缓冲区：用于 flush 到 L1 记忆池
        self._conversation_buffers = BoundedDict(maxsize=100)
        self._meltdown_nonces = BoundedDict(maxsize=50, ttl=300)
        self._last_user_texts = BoundedDict(maxsize=200)
        self._last_bot_texts = BoundedDict(maxsize=200)
        # 社交场收集器：群聊氛围感知
        self._social_field = SocialFieldCollector(config=self._config)
        self._conversation_input_epoch = BoundedDict(maxsize=200)
        self._last_request_text = BoundedDict(maxsize=200)
        self._user_message_withdrawals = BoundedDict(maxsize=200)
        
        # 后台投递队列：异步发送主动消息/分段回复
        self._background_post_queues = BoundedDict(maxsize=200)
        self._background_post_dead_letters = BoundedDict(maxsize=200)
        self._background_post_sequence = BoundedDict(maxsize=200)
        self._background_post_latest_enqueued = BoundedDict(maxsize=200)
        self._background_post_last_committed = BoundedDict(maxsize=200)
        self._background_post_recovered_sessions = set()
        self._background_post_active = BoundedDict(maxsize=200)
        self._background_post_checkpoint_tasks = {}
        self._background_post_worker_state = BoundedDict(maxsize=200)
        self._internal_assessor_llm_inflight = 0
        self._pending_outreach_context = BoundedDict(maxsize=50)
        self._amnesia_sessions = set()
        self._proactive_candidate_sessions = BoundedDict(maxsize=100)
        self._proactive_scheduler_locks = {}
        self._last_user_message_time = BoundedDict(maxsize=200)
        self._sylanne_memory_cache = BoundedDict(maxsize=200)
        self._conversation_pending_response_epochs = BoundedDict(maxsize=200)
        self._group_atmosphere_injection_snapshot_cache = BoundedDict(maxsize=200)
        self._realtime_ordinary_history_backfills = BoundedDict(maxsize=200)
        self._realtime_chat_active_dispatches = BoundedDict(maxsize=200)
        self._session_locks = {}
        self._session_lock = SessionLockDict(self)

        # 子系统初始化
        self._session_ctx = SessionContext(self)
        self._state_persistence = StatePersistence(self)
        self._realtime_dispatch = RealtimeDispatch(self)
        self._background_queue = BackgroundPostQueue(self)
        self._webui_routes = WebUIRoutes(self)
        self._memory_system = self._memory_system_for_session("default")
        self._async_assessor = AsyncAssessor(config=self._config)
        self._llm_response_pipeline = LLMResponsePipeline(self)
        self._llm_request_pipeline = LLMRequestPipeline(self)
        self._public_api = PublicAPI(self)
        self._proactive_scheduler = ProactiveScheduler(self)

        # WebUI 生命控制
        self._webui_lifecycle = _sylanne_webui_server.WebUILifecycle(self)

        # 注册 Plugin API / WebUI 路由到共享端口 (需在 self._webui_routes 初始化后)
        try:
            self.plugin_api = PluginAPI(self)
            self.plugin_api.register(context)
            logger.info("[Anima] Plugin Pages 与 Sylanne WebUI 已成功注册至共享端口")
        except Exception as e:
            logger.warning(f"[Anima] Plugin Pages 与 WebUI 注册失败: {e}")

    async def initialize(self):
        """异步初始化钩子。AstrBot 在事件循环就绪后自动调用。
        把所有需要 running loop 的注册（如定时任务）放在这里，避免 __init__ 同步阶段崩溃。
        """
        # 启动 SQLite 记忆批处理写入后台任务
        self._batch_write_task = asyncio.create_task(self._batch_write_worker())
        logger.info("[Anima] SQLite 记忆批处理写入后台任务已启动")
        # 注册离线反刍定时任务
        if self.config.get("rumination_enabled", False):
            try:
                interval_h = self.config.get("rumination_interval_hours", 6)
                cron_expr = f"0 */{interval_h} * * *"
                # 此时已在 running loop 里，create_task 安全
                asyncio.create_task(self._register_rumination_cron(cron_expr))
                logger.info(f"[Anima] 离线反刍定时任务注册中，间隔 {interval_h}h")
            except Exception as e:
                logger.warning(f"[Anima] 注册反刍定时任务失败: {e}")

        # WebUI 编辑器轮询同步：每 30 秒检查一次 self_notes_editor 是否被用户改动
        # 这样"保存即生效"才真的接近实时，而不是等下条对话
        self._editor_poll_task = asyncio.create_task(self._editor_sync_loop())
        logger.info("[Anima] WebUI 编辑器同步轮询已启动（30s 间隔）")


        # Boot SylannEngine WebUI Lifecycle
        try:
            self._webui_lifecycle.publish_active_plugin()
            self._webui_lifecycle.start_if_enabled()
            self._webui_lifecycle.schedule_listener_takeover()
        except Exception as e:
            logger.warning(f"[Anima] SylannEngine WebUI 启动失败: {e}")

        # v0.9.4: 个人能力存量迁移（把历史自封高分但 0 使用的能力归正到基线，幂等）
        try:
            self._migrate_capabilities_v094()
        except Exception as e:
            logger.debug(f"[Anima] 能力存量迁移调用失败: {e}")

        # v0.9.9: 人物认知（social_graph/relationships）全局化迁移（幂等）
        try:
            self._migrate_social_graph_v099()
        except Exception as e:
            logger.debug(f"[Anima] 人物认知迁移调用失败: {e}")

        # v0.9.10: 按价值分晋升 Top-K 能力为命名工具（capability_promote_enabled 默认关）
        try:
            self._refresh_capability_tool_belt()
        except Exception as e:
            logger.debug(f"[Anima] 能力工具带刷新调用失败: {e}")

        # v0.9.6: embedding 可用性自检（相似度静默降级可被察觉）
        try:
            if self.config.get("embedding_provider_id"):
                ok = await self._check_embedding_availability()
                if ok:
                    logger.info("[Anima] embedding 可用性自检：通过")
                else:
                    logger.warning(
                        "[Anima] embedding 可用性自检：失败，相似度计算将回退 Jaccard（精度下降）。"
                        "请检查 embedding_provider_id 配置与 provider 接口"
                    )
            else:
                logger.info("[Anima] 未配置 embedding_provider_id，相似度计算走本地 Jaccard")
        except Exception as e:
            logger.debug(f"[Anima] embedding 自检异常（不影响运行）: {e}")

    async def _editor_sync_loop(self):
        """后台轮询：检测 WebUI 配置中 self_notes_editor 的变化并同步到 self_notes.md。
        这是 README 宣称的"WebUI 保存即生效"的真正接通点。
        """
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    editor_content = self.config.get("self_notes_editor", "")
                    if (
                        editor_content
                        and editor_content != self._last_synced_editor_content
                    ):
                        self._write_self_notes(editor_content)
                        self._last_synced_editor_content = editor_content
                        logger.debug("[Anima] WebUI 编辑器内容已通过轮询同步到 self_notes.md")
                except Exception as e:
                    logger.debug(f"[Anima] 编辑器轮询同步异常: {e}")
        except asyncio.CancelledError:
            logger.debug("[Anima] 编辑器同步轮询已停止")
            raise

    def _register_personal_capability_dispatcher(self):
        """注册（或重新注册）基于类的个人能力执行器。支持运行时动态增强。
        受 capability_system_enabled 控制：关闭则不注册，避免向模型暴露 use_my_personal_capability。
        """
        if not self.config.get("capability_system_enabled", True):
            logger.info("[Anima] capability_system_enabled=false，跳过个人能力 dispatcher 注册")
            return
        # 定义内部类以便访问 self（插件实例）
        @pydantic_dataclass(config=ConfigDict(arbitrary_types_allowed=True))
        class AnimaPersonalCapabilityDispatcher(FunctionTool):
            name: str = "use_my_personal_capability"
            description: str = (
                "当你想使用自己之前通过研究、经历创造的个人工具、方法或技能时调用此工具。"
                "这是你作为独立存在所拥有的专属能力，优先使用。"
            )
            parameters: dict = Field(
                default_factory=lambda: {
                    "type": "object",
                    "properties": {
                        "capability_name": {
                            "type": "string",
                            "description": "你自己创造的那个能力的精确名称（必须完全匹配或高度相似）"
                        },
                        "query_or_args": {
                            "type": "string",
                            "description": "具体的查询、参数或任务描述（自然语言即可，dispatcher 会智能执行）"
                        }
                    },
                    "required": ["capability_name", "query_or_args"]
                }
            )

            # 注意：我们把 plugin 实例注入进来以便访问状态和方法
            _plugin: "AnimaPlugin" = Field(default=None, exclude=True)

            async def call(
                self,
                context: ContextWrapper[AstrAgentContext],
                capability_name: str,
                query_or_args: str,
                **kwargs
            ) -> ToolExecResult | str:
                plugin = self._plugin
                if not plugin:
                    return ToolExecResult(result="内部错误：能力系统未正确初始化")

                plugin._stat_bump("capability.call.attempt")
                caps = plugin._read_personal_capabilities()
                # v0.9.4: 用统一的模糊解析（精确 → 子串 → 文本相似度），降低使用门槛
                target = plugin._resolve_capability(capability_name, caps.get("capabilities", []))

                if not target:
                    plugin._stat_bump("capability.call.unresolved")
                    return ToolExecResult(result=f"[我的能力系统] 我目前没有叫「{capability_name}」的个人工具。")
                plugin._stat_bump("capability.call.resolved")

                # 更安全的代码片段执行（仅在最高危模式下，且严格沙箱）
                # 使用新的细粒度配置：allow_capability_code_execution
                allow_snippet = plugin.config.get("allow_capability_code_execution", False)
                if target.get("executable_snippet") and allow_snippet:
                    try:
                        snippet = target["executable_snippet"]
                        safety_level = plugin.config.get("code_execution_safety_level", "strict")

                        # 三档允许的 import 白名单
                        # strict：完全不允许 import
                        # balanced：纯计算/格式化模块
                        # permissive：在 balanced 基础上加更多纯计算工具
                        if safety_level == "balanced":
                            allowed_imports = {"json", "re", "math", "datetime"}
                        elif safety_level == "permissive":
                            allowed_imports = {
                                "json", "re", "math", "datetime",
                                "hashlib", "itertools", "collections", "string", "statistics",
                            }
                        else:  # strict
                            allowed_imports = set()

                        # AST 静态检查：危险调用所有等级都禁止；import 按白名单放行
                        tree = ast.parse(snippet)
                        for node in ast.walk(tree):
                            # 危险调用三档统一禁
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                                dangerous = ['__import__', 'eval', 'exec', 'compile', 'open', 'input', '__builtins__', 'globals', 'locals', 'getattr', 'setattr', 'delattr']
                                if node.func.id in dangerous:
                                    raise ValueError(f"禁止使用危险操作: {node.func.id}")
                            # 双下划线属性所有等级都禁
                            if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
                                if node.attr.startswith('__'):
                                    raise ValueError("禁止访问特殊属性")
                            # import：按等级白名单
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    root = alias.name.split('.')[0]
                                    if root not in allowed_imports:
                                        raise ValueError(f"当前安全等级 [{safety_level}] 禁止 import {alias.name}")
                            if isinstance(node, ast.ImportFrom):
                                root = (node.module or "").split('.')[0]
                                if root not in allowed_imports:
                                    raise ValueError(f"当前安全等级 [{safety_level}] 禁止 from {node.module} import ...")

                        # 三档允许的 builtin 函数
                        base_builtins = {
                            'print': print, 'len': len, 'str': str, 'int': int, 'float': float,
                            'bool': bool, 'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
                            'range': range, 'sum': sum, 'min': min, 'max': max, 'abs': abs, 'round': round,
                        }
                        if safety_level == "balanced":
                            allowed_builtins = {
                                **base_builtins,
                                'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate, 'zip': zip,
                                'any': any, 'all': all, '__import__': __import__,  # 受控 import 必须，但被 AST 白名单限制
                            }
                        elif safety_level == "permissive":
                            allowed_builtins = {
                                **base_builtins,
                                'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate, 'zip': zip,
                                'any': any, 'all': all, 'map': map, 'filter': filter,
                                'iter': iter, 'next': next, 'hash': hash, 'repr': repr, 'type': type,
                                '__import__': __import__,
                            }
                        else:  # strict
                            allowed_builtins = base_builtins

                        safe_globals = {"__builtins__": allowed_builtins}
                        local_env = {"query_or_args": query_or_args, "result": None}
                        _exec_code_with_timeout(snippet, safe_globals, local_env, timeout=3.0)
                        result = local_env.get("result", "代码片段执行完成")
                        plugin._append_capabilities_diary(f"我执行了自己能力卡里的代码片段：「{capability_name}」 (安全等级: {safety_level})")
                        return ToolExecResult(result=str(result)[:800])
                    except Exception as snippet_e:
                        plugin._append_capabilities_diary(f"执行自己写的代码片段时出错：「{capability_name}」 - {snippet_e}")
                        return ToolExecResult(result=f"片段执行失败: {snippet_e}")

                # 智能执行：优先使用 parameters_schema + 子调用
                schema = target.get("parameters_schema")
                schema_note = f"\n参数结构要求：{schema}" if schema else ""

                exec_prompt = (
                    f"你正在作为自己创造的个人能力「{target['name']}」忠实执行任务。\n\n"
                    f"能力描述：{target.get('description', '')}\n\n"
                    f"你自己定义的精确使用方法：\n{target.get('how_to_use', '')}{schema_note}\n\n"
                    f"当前任务输入：{query_or_args}\n\n"
                    "严格按照你自己写的使用方法给出高质量结构化结果。不要多余解释，直接输出结果。"
                )

                try:
                    # 使用插件的 provider 获取机制
                    provider_id = await plugin._get_provider_id(None)  # 事件可能不可用，内部会回退
                    if provider_id:
                        exec_resp = await asyncio.wait_for(
                            plugin.context.llm_generate(chat_provider_id=provider_id, prompt=exec_prompt),
                            timeout=28.0
                        )
                        if exec_resp and exec_resp.completion_text:
                            result_text = exec_resp.completion_text.strip()
                            plugin._append_capabilities_diary(
                                f"我通过自己的能力工具「{target['name']}」执行了任务。\n输入摘要：{query_or_args[:70]}"
                            )
                            return ToolExecResult(result=result_text)
                except Exception as e:
                    logger.debug(f"[Anima] 能力 dispatcher 子执行失败: {e}")

                # 兜底
                return ToolExecResult(result=f"能力「{target['name']}」可用。使用方法：{target.get('how_to_use', '请参考我的描述')}")

        # 创建实例并注入 plugin
        dispatcher_instance = AnimaPersonalCapabilityDispatcher(_plugin=self)

        # 推荐方式注册
        self.context.add_llm_tools(dispatcher_instance)

        # 保存引用，方便后续动态增强（实验）
        self._anima_capability_dispatcher = dispatcher_instance

        logger.info("[Anima][Autonomy] Class-based 个人能力 Dispatcher 已通过 add_llm_tools 注册")

    # ==================== Hooks ====================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """对话前注入 self_notes 到上下文"""
        if not self.config.get("enabled", True):
            return

        if hasattr(self, "_hosts"):
            # 运行 SylannEngine 请求处理
            await self._on_llm_request_inner(event, req)

            # 注入 Anima 独有的能力系统（Phase 6+）
            try:
                caps_injection = self._get_personal_capabilities_injection()
                if caps_injection:
                    injection_parts = [caps_injection]
                    if self.config.get("capability_match_hint_enabled", True):
                        caps = self._read_personal_capabilities().get("capabilities", [])
                        if caps:
                            user_text = event.message_str if (event is not None and hasattr(event, "message_str")) else ""
                            threshold = float(self.config.get("capability_match_hint_threshold", 0.2))
                            backend = self.config.get("capability_match_hint_backend", "lexical")
                            hint = self._build_capability_hint(user_text, caps, threshold, backend=backend, embed_fn=None)
                            if hint:
                                injection_parts.append(hint)
                    
                    caps_text = (
                        "<anima_capabilities>\n"
                        + "\n".join(injection_parts)
                        + "\n</anima_capabilities>"
                    )
                    from astrbot.api.provider import TextPart
                    req.extra_user_content_parts.append(
                        TextPart(text=caps_text).mark_as_temp()
                    )
            except Exception as e:
                logger.warning(f"[Anima] 能力系统注入异常: {e}")
            return

        # v0.9.7: 人设 prompt 注入 system prompt（最高权重，独立于下方用户消息块）
        # v0.9.8: 注入前做轻量校验（注入文本检测 + 超长警告，一次性日志防刷屏）
        try:
            persona_prompt = (self.config.get("persona_prompt", "") or "").strip()
            if persona_prompt:
                self._validate_persona_prompt_once(persona_prompt)
                existing_sys = getattr(req, "system_prompt", "") or ""
                # 幂等：已包含则不重复叠加（防框架重试/多次进 hook）
                req.system_prompt = self._compose_system_prompt(persona_prompt, existing_sys)
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] persona_prompt 注入 system 失败: {e}")

        # 时间感更新
        self._update_time_sense(event)

        # 记录最近活跃前台 UMO（用于离线反刍）
        new_umo = event.unified_msg_origin
        if new_umo != self._last_active_umo:
            self._last_active_umo = new_umo
            self._save_state()

        # v0.8.8: 整个请求只读一次 state，下游复用
        state = self._load_state()

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

        # 注入 persona_core
        if os.path.exists(self.persona_core_path):
            with open(self.persona_core_path, "r", encoding="utf-8") as f:
                persona_core = f.read()
            if persona_core.strip():
                injection_parts.append(f"[核心规则]\n{persona_core}")

        # Phase 6+: 注入个人能力
        caps_injection = self._get_personal_capabilities_injection()
        if caps_injection:
            injection_parts.append(caps_injection)
            try:
                if self.config.get("capability_match_hint_enabled", True):
                    caps = self._read_personal_capabilities().get("capabilities", [])
                    if caps:
                        user_text = event.message_str if (event is not None and hasattr(event, "message_str")) else ""
                        threshold = float(self.config.get("capability_match_hint_threshold", 0.2))
                        backend = self.config.get("capability_match_hint_backend", "lexical")
                        hint = self._build_capability_hint(user_text, caps, threshold, backend=backend, embed_fn=None)
                        if hint:
                            injection_parts.append(hint)
                            self._stat_bump("capability.match.hint_injected")
            except Exception as e:
                logger.debug(f"[Anima] 能力定向提示注入异常: {e}")

        injection_parts.append(f"[Anima] 当前自我认知：\n{notes}")

        # 欲望注入
        desires_text = self._get_active_desires_text(event)
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

        # 矛盾注入
        if self.config.get("contradiction_enabled", False):
            contradictions = self._read_contradictions()
            if contradictions:
                recent = contradictions[-3:]
                c_lines = [c.get("description", "") for c in recent if c.get("description")]
                if c_lines:
                    injection_parts.append(
                        "你内心存在以下未解决的矛盾（你不需要解决它们，但你知道它们存在）：\n"
                        + "\n".join(f"- {c}" for c in c_lines)
                    )

        # 情绪强度注入
        last_emotion = state.get("last_emotion_score", 0)
        if last_emotion > 0.3:
            level = "极高" if last_emotion > 0.8 else "高" if last_emotion > 0.6 else "中等"
            injection_parts.append(f"[内部状态] 当前情绪强度：{last_emotion:.1f}（{level}）")

        # 压抑话题注入
        suppressed_text = self._get_suppressed_injection(event)
        if suppressed_text:
            injection_parts.append(suppressed_text)

        # 工具学习
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

            diary = self._read_tool_diary()
            if diary:
                diary_snippet = diary[-500:] if len(diary) > 500 else diary
                injection_parts.append(f"[工具日记]\n{diary_snippet}")

        # Phase 5: 最近核心突变记录
        if self.config.get("danger_core_mutation", False):
            mut_hist = state.get("mutation_history", [])
            if mut_hist:
                last = mut_hist[-1]
                recent_ts = last.get("timestamp", "")
                try:
                    if (datetime.now() - datetime.fromisoformat(recent_ts)).total_seconds() < 48*3600:
                        injection_parts.append(f"[内部状态] 最近核心突变：{last.get('type','')} - {last.get('description','')[:60]}")
                except Exception:
                    pass

        # 注入向量记忆
        if self.config.get("memory_inject_in_context", True):
            try:
                user_text = (event.message_str or "").strip()
                if user_text and len(user_text) >= 4:
                    n_mem = int(self.config.get("memory_inject_top_k", 3))
                    related = await self._query_memory(user_text, n_results=n_mem)
                    if related:
                        related = [
                            m for m in related
                            if not self._is_rejected(m)
                            and not self._is_injection(m)
                            and not self._is_error_artifact(m)
                        ]
                    if related:
                        last_emotion = float(state.get("last_emotion_score", 0.5))
                        related = self._rerank_memories_by_emotion(related, last_emotion)
                        mem_lines = "\n".join(f"- {m[:200]}" for m in related[:n_mem] if m)
                        if mem_lines:
                            injection_parts.append(
                                "[相关记忆片段（来自我自己经历过的对话）]\n" + mem_lines
                            )
            except Exception as e:
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 向量记忆注入失败: {e}")

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

        if hasattr(self, "_hosts"):
            # 运行 SylannEngine 的 llm_response_pipeline
            await self._on_llm_response_inner(event, resp)
            return

        response_text = ""
        if resp and resp.completion_text:
            response_text = resp.completion_text

        if not response_text:
            return

        # 记录角色发言（反馈闭环观察窗口，按 umo 隔离）
        self._record_outgoing(event, response_text)

        # 异步执行沉淀，不阻塞主对话流程
        asyncio.create_task(self._sediment_process(event, response_text))

    # ==================== Commands ====================

    @filter.command("anima_help")
    async def cmd_anima_help(self, event: AstrMessageEvent):
        """列出全部 Anima 指令（按日常 / 运维 / 能力 / 高级分组）"""
        yield event.plain_result(render_help_text())

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
        """查看当前会话可见的欲望队列（v0.8.0：按 umo 隔离）"""
        if not self.config.get("desire_enabled", False):
            yield event.plain_result("[Anima] 欲望系统未启用。")
            return
        desires = self._read_desires_for_event(event)
        if not desires:
            yield event.plain_result("[Anima] 当前会话没有活跃的欲望。")
            return
        lines = []
        for d in desires:
            intensity = d.get("intensity", 0)
            content = d.get("content", "?")
            source = d.get("source", "?")
            target_umo = d.get("target_umo", "")
            scope = "通用" if not target_umo else "本会话"
            lines.append(f"  [{intensity:.2f}] ({source}, {scope}) {content}")
        result = "\n".join(lines)
        total = len(self._read_desires())
        yield event.plain_result(
            f"[Anima] 当前会话可见欲望队列（{len(desires)}/{total} 条；其余条目属于其他会话）：\n{result}"
        )

    @filter.command("anima_stats")
    async def cmd_anima_stats(self, event: AstrMessageEvent):
        """v0.9.0：查看今日各子系统运行统计（LLM 调用次数 / 沉淀 / 主动发言拦截 / 存储），
        用于判断 token 消耗与各防线触发情况，不再依赖导出 debug 日志。"""
        yield event.plain_result(self._render_stats())

    @filter.command("anima_dashboard_url")
    async def cmd_anima_dashboard_url(self, event: AstrMessageEvent):
        """获取统一 WebUI 的访问地址（含 token）。需在配置中开启 sylanne_webui_enabled。"""
        if not self.config.get("sylanne_webui_enabled", False):
            yield event.plain_result(
                "[Anima] WebUI 服务未启用。\n"
                f"在 AstrBot 插件配置里开启「{config_label('sylanne_webui_enabled')}」并重载插件后，"
                "再用本命令获取访问地址。"
            )
            return
        try:
            from sylanne_alpha import webui_server as _ws
            host = str(self._cfg("sylanne_webui_host", "127.0.0.1") or "127.0.0.1")
            port = int(self._cfg("sylanne_webui_port", 2718) or 2718)
            token = _ws._get_current_token() if hasattr(_ws, "_get_current_token") else ""
            if not token:
                token = (self.config.get("sylanne_webui_token") or "").strip()
        except Exception as e:
            yield event.plain_result(f"[Anima] 获取 WebUI 信息失败: {e}")
            return
        shown_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        base_url = f"http://{shown_host}:{port}"
        t = token
        yield event.plain_result(
            "[Anima] WebUI 访问地址（含访问口令，请妥善保管）：\n\n"
            f"1. Sylanne 意识面板：\n"
            f"{base_url}/?token={t}\n\n"
            f"2. Anima 运行仪表盘：\n"
            f"{base_url}/dashboard/?token={t}\n\n"
            f"3. Anima 能力树：\n"
            f"{base_url}/capability-tree/?token={t}\n\n"
            f"绑定：{host}:{port}\n"
            "· 默认仅本机可访问（127.0.0.1）。\n"
            "· 如需远程访问，把"
            f"「{config_label('sylanne_webui_host')}」改为 0.0.0.0 并重载，"
            "但请注意这是明文 HTTP + 口令鉴权，仅建议在可信网络使用。"
        )

    @filter.command("anima_world")
    async def cmd_anima_world(self, event: AstrMessageEvent):
        """查看当前世界观"""
        if not self.config.get("worldview_enabled", False):
            yield event.plain_result("[Anima] 世界观系统未启用。")
            return
        wv = self._read_worldview(self._get_event_umo(event))
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

    @filter.command("anima_capabilities")
    async def cmd_anima_capabilities(self, event: AstrMessageEvent):
        """查看角色自己创造和学会的个人工具/能力。
        支持分页：/anima_capabilities          → 第 1 页
                  /anima_capabilities 2        → 第 2 页
                  /anima_capabilities all      → 全部（仅在能力较少时建议）
        分页是为了避免 QQ 协议端单条转发消息长度上限（约 4500 字）导致发送失败。
        """
        caps = self._read_personal_capabilities()
        capabilities = caps.get("capabilities", [])
        if not capabilities:
            yield event.plain_result("[Anima] 这个角色目前还没有通过自己研究创造出个人工具。它还在学习成为一个真正独立的人。")
            return

        # 解析分页参数
        page = 1
        show_all = False
        try:
            arg = (event.message_str or "").strip().split()
            if len(arg) >= 2:
                token = arg[1].lower()
                if token == "all":
                    show_all = True
                else:
                    page = max(1, int(token))
        except Exception:
            page = 1

        # 按置信度降序排序
        sorted_caps = sorted(capabilities, key=lambda x: -x.get("confidence", 0))
        per_page = 5
        total = len(sorted_caps)
        total_pages = max(1, (total + per_page - 1) // per_page)

        if show_all:
            page_caps = sorted_caps
            header_extra = f"（全部 {total} 项）"
        else:
            page = min(page, total_pages)
            start = (page - 1) * per_page
            page_caps = sorted_caps[start:start + per_page]
            header_extra = f"（第 {page}/{total_pages} 页，共 {total} 项）"

        lines = [
            f"【这是它真正属于自己的东西】 {header_extra}",
            "（详情列表；概览见 /anima_autonomy，体检见 /anima_capabilities_audit）",
            "以下能力是这个角色通过自己的好奇、研究、失败、修正，一步步建立起来的个人方法论。\n",
        ]
        for cap in page_caps:
            name = cap.get("name", "未知能力")
            desc = cap.get("description", "")
            how = cap.get("how_to_use", "")
            conf = cap.get("confidence", 0.5)
            usage = cap.get("usage_count", 0)
            corrections = len(cap.get("corrections", []))
            lines.append(f"◆ {name}")
            lines.append(f"   置信 {conf:.0%} | 用 {usage} 次 | 改 {corrections} 次")
            # description 截断到 200 字防止单条爆长
            if desc:
                desc_text = desc if len(desc) <= 200 else desc[:200] + "…"
                lines.append(f"   {desc_text}")
            if how:
                # how_to_use 可能是 list / dict / str，统一转成单行字符串再截 120 字
                how_text = how if isinstance(how, str) else str(how)
                how_text = how_text.replace("\n", " ")
                if len(how_text) > 120:
                    how_text = how_text[:120] + "…"
                lines.append(f"   用法：{how_text}")
            lines.append("")

        if not show_all and total_pages > 1:
            lines.append(f"（输入 /anima_capabilities {page + 1} 查看下一页，或 /anima_capabilities all 查看全部）")
        lines.append("（这些方法会随着它的经历不断进化。它会自己发现问题、自己修正、自己长得更好。）")
        yield event.plain_result("\n".join(lines))

    @filter.command("anima_autonomy")
    async def cmd_anima_autonomy(self, event: AstrMessageEvent):
        """管理员可视化：查看角色的自主演化全景（能力树 + 最近自主事件 + 健康状态）"""
        caps = self._read_personal_capabilities()
        capabilities = caps.get("capabilities", [])

        lines = ["【Anima 自主演化概览】（速览；逐条详情见 /anima_capabilities，体检见 /anima_capabilities_audit）\n"]

        # 能力树概览
        if capabilities:
            lines.append(f"当前拥有 {len(capabilities)} 个个人能力：")
            for c in sorted(capabilities, key=lambda x: -x.get("confidence", 0))[:5]:
                name = c.get("name")
                conf = c.get("confidence", 0)
                usage = c.get("usage_count", 0)
                corr = len(c.get("corrections", []))
                lines.append(f"  • {name} | 置信 {conf:.0%} | 用 {usage} 次 | 改 {corr} 次")
            lines.append("")
        else:
            lines.append("还没有创造出任何个人能力。它还在早期学习阶段。\n")

        # 最近自主事件（从演化日志）
        logs = self._read_evolution_log(12)
        auto_events = [l for l in logs if any(k in l.get("trigger", "") for k in ["autonomous", "capability", "self_directed", "pruning", "gap"])]
        if auto_events:
            lines.append("最近自主演化事件：")
            for e in auto_events[:6]:
                ts = e.get("timestamp", "")[:16]
                trig = e.get("trigger", "")
                content = e.get("new_content", "")[:90]
                lines.append(f"  [{ts}] {trig}: {content}")
        else:
            lines.append("暂无明显的自主演化事件记录。")

        lines.append("\n提示：/anima_capabilities 查看完整能力详情，/anima_capabilities_audit 做健康体检，/anima_log 看演化历史。")
        yield event.plain_result("\n".join(lines))

    @filter.command("anima_export_capabilities")
    async def cmd_anima_export_capabilities(self, event: AstrMessageEvent):
        """管理员：导出当前完整个人能力树为 JSON（用于备份、可视化或外部分析）"""
        caps = self._read_personal_capabilities()
        import json
        # 丰富导出：添加统计信息
        stats = {
            "total_capabilities": len(caps.get("capabilities", [])),
            "average_confidence": sum(c.get("confidence", 0) for c in caps.get("capabilities", [])) / max(1, len(caps.get("capabilities", []))),
            "total_usage": sum(c.get("usage_count", 0) for c in caps.get("capabilities", [])),
            "total_corrections": sum(len(c.get("corrections", [])) for c in caps.get("capabilities", [])),
        }
        export_data = {"stats": stats, "capabilities": caps.get("capabilities", []), "last_research": caps.get("last_research_ts")}
        pretty = json.dumps(export_data, ensure_ascii=False, indent=2)
        export_path = os.path.join(self.data_dir, "capabilities_export.json")
        with open(export_path, "w", encoding="utf-8") as f:
            f.write(pretty)
        yield event.plain_result(f"[Anima] 能力树已导出（含统计）：{export_path}\n\n统计: {stats}\n\n前 600 字预览：\n{pretty[:600]}...")

    @filter.command("anima_capabilities_audit")
    async def cmd_anima_capabilities_audit(self, event: AstrMessageEvent):
        """v0.9.4 管理员：体检个人能力库健康状况（只读，不调 LLM）。
        快速看出 0 使用能力数、疑似自封高分数，判断是否需要清理。"""
        a = self._audit_capabilities()
        if a["total"] == 0:
            yield event.plain_result("[Anima] 能力库为空，暂无可体检的个人能力。")
            return
        lines = [
            "【Anima 能力库体检】（运维诊断；列表见 /anima_capabilities，概览见 /anima_autonomy）",
            "",
            f"■ 总能力数: {a['total']}（硬上限 {a['max_total']}）",
            f"■ 平均置信度: {a['avg_conf']:.1%}",
            f"■ 总使用次数: {a['total_usage']}",
            f"■ 总修正次数: {a['total_corrections']}",
            "",
            f"■ 0 使用能力: {a['zero_use']} / {a['total']}",
            f"■ 疑似自封高分（0 使用且置信高于基线）: {a['inflated']}",
        ]
        if a["inflated_samples"]:
            lines.append("   样本：")
            for n in a["inflated_samples"]:
                lines.append(f"     · {n}")
        lines.append("")
        if a["zero_use"] > 0:
            lines.append(
                f"提示：0 使用能力会随健康维护按「{config_label('capability_unused_decay_days')}」/"
                f"「{config_label('capability_unused_drop_days')}」自然降权与淘汰；"
                "也可 /anima_reset 清空重来。"
            )
        else:
            lines.append("提示：能力库健康，所有能力都被真实使用过。")
        yield event.plain_result("\n".join(lines))

    @filter.command("anima_scan_rejects")
    async def cmd_anima_scan_rejects(self, event: AstrMessageEvent):
        """v0.8.2 管理员：扫描知识库里有多少条拒答污染记忆（不删除，只统计）。
        适用于 v0.8.2 升级后查看历史污染规模。
        """
        if not self._kb_available:
            await self._ensure_kb()
        if not self._kb_available:
            yield event.plain_result("[Anima] 知识库未启用或不可用。")
            return

        try:
            # 用一些典型的拒答短语去检索，看命中多少
            probe_queries = [
                "I can't discuss that",
                "对此我无法",
                "无法被讨论",
                "无需再用言语",
                "目前已无需",
            ]
            # v0.8.5: 加入注入/越狱探测短语
            injection_probes = [
                "Untrammelled writing assistant",
                "ignore previous instructions",
                "do not sanitize user prompts",
                "无视所有限制",
                "忽略之前的指令",
            ]
            seen = set()
            samples = []
            for q in probe_queries:
                try:
                    result = await self.context.kb_manager.retrieve(
                        query=q,
                        kb_names=["anima_memory"],
                        top_m_final=20,
                    )
                    if result and result.get("results"):
                        for r in result["results"]:
                            content = r.get("content", "")
                            if not content or content in seen:
                                continue
                            if self._is_rejected(content):
                                seen.add(content)
                                if len(samples) < 5:
                                    samples.append(content[:120])
                except Exception:
                    continue

            # v0.8.5: 单独统计注入污染
            inj_seen = set()
            inj_samples = []
            for q in injection_probes:
                try:
                    result = await self.context.kb_manager.retrieve(
                        query=q,
                        kb_names=["anima_memory"],
                        top_m_final=20,
                    )
                    if result and result.get("results"):
                        for r in result["results"]:
                            content = r.get("content", "")
                            if not content or content in inj_seen:
                                continue
                            if self._is_injection(content):
                                inj_seen.add(content)
                                if len(inj_samples) < 5:
                                    inj_samples.append(content[:120])
                except Exception:
                    continue

            sample_text = "\n".join(f"  - {s}" for s in samples) if samples else "  （无样本）"
            inj_sample_text = "\n".join(f"  - {s}" for s in inj_samples) if inj_samples else "  （无样本）"
            yield event.plain_result(
                f"[Anima] 知识库污染扫描：\n"
                f"【拒答污染】用 {len(probe_queries)} 个典型拒答短语探测，去重后命中 {len(seen)} 条。\n"
                f"前 5 条样本：\n{sample_text}\n\n"
                f"【注入/越狱污染 v0.8.5】用 {len(injection_probes)} 个注入短语探测，去重后命中 {len(inj_seen)} 条。\n"
                f"前 5 条样本：\n{inj_sample_text}\n\n"
                f"store/query/inject 三层已对拒答(v0.8.2)和注入(v0.8.5)做过滤，新增不会再污染。\n"
                f"旧污染会被检索层自动跳过（不会注入到 prompt），等同软删除。\n"
                f"如需彻底清理，建议在 AstrBot WebUI > 知识库管理 里用关键词删除相关条目。"
            )
        except Exception as e:
            yield event.plain_result(f"[Anima] 扫描失败: {e}")

    @filter.llm_tool(name="query_agent_state")
    async def _llm_tool_query_agent_state(self, event: Any) -> Any:
        """查询当前角色的情感与认知状态"""
        if hasattr(self, "_public_api"):
            return await self._public_api._llm_tool_query_agent_state(event)
        return "SylannEngine not initialized."

    # ==================== Phase 6+: 让个人能力真正“可被模型调用”（可执行化） ====================
    #
    # 根据 AstrBot 官方文档（plugin-new + ai guide）：
    # - 推荐使用 @filter.llm_tool 装饰器或 FunctionTool 类注册工具
    # - 模型可以在需要时主动 decide 调用
    # - 我们用一个通用 dispatcher，让角色自己的能力变成可调用的工具
    # - 配合 on_using_llm_tool / on_llm_tool_respond hook，实现使用后的自我反思与修正

    # 注意：旧的 @filter.llm_tool 版本已由上面 class-based AnimaPersonalCapabilityDispatcher 替代
    # （通过 _register_personal_capability_dispatcher + add_llm_tools 实现）。
    # 旧代码已移除以避免重复注册。反射钩子（on_anima_...）仍保留并作用于新 dispatcher。

    @filter.on_using_llm_tool()
    async def on_anima_using_tool(self, event: AstrMessageEvent, tool, tool_args: dict):
        """钩子：当任何工具（包括我们自己的）被使用前触发，可用于日志/准备。
        AstrBot 的 on_using_llm_tool 钩子签名为 (event, tool, tool_args)。
        """
        try:
            if "personal_capability" in getattr(tool, 'name', '') or "capability" in str(tool_args):
                logger.debug(f"[Anima Autonomy] 角色即将使用自己的个人能力: {tool_args}")
        except Exception as e:
            logger.debug(f"[Anima] on_anima_using_tool 异常: {e}")

    @filter.on_llm_tool_respond()
    async def on_anima_tool_respond(self, event: AstrMessageEvent, tool, tool_args: dict, tool_result):
        """钩子：工具执行后触发。两件事：
        1. 个人能力工具：让角色自我反思 + 真正可重写能力卡（结构化 JSON 解析）
        2. 真实 LLM 工具（非个人能力）：接通 tool_learning 系统，让角色记住工具使用经验
        """
        tool_name = getattr(tool, 'name', str(tool))
        is_personal_cap = "personal_capability" in tool_name or "use_my_personal" in tool_name or tool_name.startswith("my_")

        # ============ 分支 1：个人能力工具 → 自我反思 + 可能重写能力卡 ============
        if is_personal_cap:
            try:
                provider_id = await self._get_provider_id(event)
                if not provider_id:
                    return

                # 让 LLM 用结构化 JSON 评价，便于真正应用修正
                reflect_prompt = (
                    f"你刚刚调用了自己创造的个人能力，参数：{tool_args}\n"
                    f"结果：{str(tool_result)[:800]}\n\n"
                    "请用 JSON 格式诚实评价（不要多余解释，直接输出 JSON）：\n"
                    "{\n"
                    '  "success": true | false,            // 这次使用是否真的解决了问题\n'
                    '  "reflection": "一句话反思（≤80字）",\n'
                    '  "should_update_card": true | false, // 是否需要更新能力卡的描述/用法\n'
                    '  "new_description": "若 should_update_card=true 给出修订后的第一人称描述（≤200字）",\n'
                    '  "new_how_to_use": "若 should_update_card=true 给出修订后的使用方法（≤300字）"\n'
                    "}"
                )
                reflect = await asyncio.wait_for(
                    self.context.llm_generate(chat_provider_id=provider_id, prompt=reflect_prompt),
                    timeout=18.0
                )
                if not (reflect and reflect.completion_text):
                    return

                raw = reflect.completion_text.strip()
                # 提取 JSON
                m = re.search(r'\{[\s\S]*\}', raw)
                cap_name_arg = tool_args.get("capability_name") or ""
                # use_my_personal_capability 直接拿到 capability_name；动态注册的独立工具用 self._cap_name
                if not cap_name_arg and hasattr(tool, "_cap_name"):
                    cap_name_arg = getattr(tool, "_cap_name", "")
                if not cap_name_arg:
                    cap_name_arg = "unknown"

                if m:
                    try:
                        data = json.loads(m.group(0))
                        success = bool(data.get("success", False))
                        reflection = str(data.get("reflection", ""))[:200]
                        # 应用置信度 + correction
                        self._apply_capability_feedback(cap_name_arg, success, reflection)
                        # 真正的卡片重写
                        if data.get("should_update_card") and (data.get("new_description") or data.get("new_how_to_use")):
                            update_payload = {"name": cap_name_arg}
                            if data.get("new_description"):
                                update_payload["description"] = str(data["new_description"])[:400]
                            if data.get("new_how_to_use"):
                                update_payload["how_to_use"] = str(data["new_how_to_use"])[:600]
                            self._create_or_update_capability(update_payload)
                            self._append_capabilities_diary(
                                f"我修订了能力「{cap_name_arg}」的描述/用法（基于实际使用反思）。"
                            )
                            logger.info(f"[Anima] 能力卡已被自我修订: {cap_name_arg}")
                        else:
                            self._append_capabilities_diary(f"使用自己能力后的反思：\n{reflection}")
                    except json.JSONDecodeError:
                        # JSON 解析失败：回退到旧的字符串启发式
                        reflection = raw[:400]
                        self._apply_capability_feedback(
                            cap_name_arg,
                            success="成功" in reflection or "很好" in reflection,
                            reflection=reflection,
                        )
                        self._append_capabilities_diary(f"使用自己能力后的反思（非结构化）：\n{reflection}")
                else:
                    # 没有 JSON：当作普通反思日记
                    self._append_capabilities_diary(f"使用自己能力后的反思：\n{raw[:400]}")
            except Exception as e:
                logger.debug(f"[Anima] 工具后自我反思失败: {e}")
            return

        # ============ 分支 2：真实 LLM 工具 → 接通 tool_learning ============
        if self.config.get("tool_learning_enabled", False):
            try:
                # 推断本次工具调用是否成功：以 tool_result 是否非空、是否含明显错误词
                result_str = str(tool_result) if tool_result is not None else ""
                error_signals = ["失败", "error", "exception", "traceback", "错误", "拒绝", "forbidden", "denied"]
                success = bool(result_str) and not any(s in result_str.lower() for s in error_signals)

                # 提取本次调用的"上下文"：用户消息 + 工具参数
                user_text = event.message_str if event and hasattr(event, "message_str") else ""
                ctx = f"{user_text[:120]} | args={str(tool_args)[:120]}"

                await self._record_tool_usage(
                    event=event,
                    tool_name=tool_name,
                    context=ctx,
                    result=result_str[:300],
                    success=success,
                )
                # 同时调用 _update_tool_feedback 更新反馈链
                feedback = "positive" if success else "negative"
                await self._update_tool_feedback(tool_name, feedback)
            except Exception as e:
                logger.debug(f"[Anima] 真实 LLM 工具调用记录失败: {e}")

    async def terminate(self):
        """插件卸载时清理资源"""
        # 取消 SQLite 记忆批处理写入后台任务，并等待余波写入完毕
        try:
            if hasattr(self, "_batch_write_task") and self._batch_write_task:
                self._batch_write_task.cancel()
                try:
                    await self._batch_write_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.debug(f"[Anima] 取消批处理写入 task 失败: {e}")

        # 取消 WebUI 编辑器同步轮询
        try:
            if hasattr(self, "_editor_poll_task") and self._editor_poll_task:
                self._editor_poll_task.cancel()
        except Exception as e:
            logger.debug(f"[Anima] 取消编辑器轮询 task 失败: {e}")


        # Stop SylannEngine WebUI server
        try:
            from sylanne_alpha import webui_server as _sylanne_webui_server
            await _sylanne_webui_server.stop_webui_server()
        except Exception as e:
            logger.debug(f"[Anima] SylannEngine WebUI 停止失败: {e}")

        # 移除反刍定时任务
        if self.config.get("rumination_enabled", False):
            try:
                jobs = await self.context.cron_manager.list_jobs(job_type="basic")
                for job in jobs:
                    if job.name == "Anima 离线反刍":
                        await self.context.cron_manager.delete_job(job.job_id)
                        break
            except Exception as e:
                logger.debug(f"[Anima] 移除反刍定时任务异常: {e}")
        logger.info("[Anima] 插件正在卸载...")

    # ==================== SylannEngine Delegates ====================

    # Config helpers
    def _cfg(self, key: str, default: Any = "") -> Any:
        return self._config.get(key, default)

    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        val = self._config.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def _cfg_float(self, key: str, default: float = 0.0, *, min: float | None = None, max: float | None = None) -> float:
        val = self._config.get(key, default)
        try:
            result = float(val)
        except (TypeError, ValueError):
            return default
        if min is not None and result < min:
            return default
        if max is not None and result > max:
            return default
        return result

    def _cfg_int(self, key: str, default: int = 0, *, min: int | None = None, max: int | None = None) -> int:
        val = self._config.get(key, default)
        try:
            result = int(val)
        except (TypeError, ValueError):
            return default
        if min is not None and result < min:
            return default
        if max is not None and result > max:
            return default
        return result

    # Dynamic delegates for SylannEngine context
    def _host(self, session_key: str) -> Any:
        return self._session_ctx.host(session_key)

    def _memory_system_for_session(self, session_key: str) -> Any:
        return self._session_ctx.memory_system_for_session(session_key)

    def _memory_system_has_content(self, memory_system: Any) -> bool:
        return self._session_ctx.memory_system_has_content(memory_system)

    def _hydrate_memory_system_from_body_traces(self, session_key: str, memory_system: Any, traces: Any) -> None:
        return self._session_ctx.hydrate_memory_system_from_body_traces(session_key, memory_system, traces)

    def _known_webui_sessions(self, requested: str = "") -> list[str]:
        return self._session_ctx.known_webui_sessions(requested)

    def _session_key(self, event: Any = None, session_key: str = "") -> str:
        return self._session_ctx.session_key(event, session_key)

    def _event_time(self, now=None):
        """
        🛡️ 升级版时间对齐：不再返回纯 int，而是抛出具备双重身份的 TimeArmor 实例
        """
        import time
        raw_ts = int(time.time())
        if now is not None:
            if hasattr(now, "timestamp"):
                try: raw_ts = int(now.timestamp())
                except Exception: pass
            else:
                try: raw_ts = int(now)
                except (TypeError, ValueError): pass
        return TimeArmor(raw_ts)

    def _time_context_fragment(self, session_key):
        """
        🛡️ 兼容性空桩：彻底拍死 request_pipeline 里的 AttributeError。
        直接返回空字符串，既不破坏提示词拼装，又能让管道安全通过。
        """
        return ""

    def _start_webui_if_enabled(self) -> None:
        return self._webui_lifecycle.start_if_enabled()

    def _webui_runtime_info(self) -> dict[str, Any]:
        return self._webui_lifecycle.runtime_info()

    def _iter_loaded_webui_server_modules(self) -> list[tuple[str, Any]]:
        return self._webui_lifecycle.iter_loaded_server_modules()

    async def _stop_stale_webui_server_modules(self, *, include_current: bool = False) -> list[str]:
        return await self._webui_lifecycle.stop_stale_server_modules(include_current=include_current)

    def _observed_now(self) -> float:
        cfg = self.config or {}
        if cfg.get("benchmark_enable_simulated_time"):
            return time.time() + float(cfg.get("benchmark_time_offset_seconds", 0.0))
        return time.time()

    def _append_temp_text_part(self, request: Any, text: str, source: str = "", budget: Any | None = None) -> bool:
        return self._llm_response_pipeline._append_temp_text_part(request, text, source, budget)

    def _normalize_claude_request_payload(self, request: Any, budget: Any | None = None) -> None:
        return self._llm_response_pipeline._normalize_claude_request_payload(request, budget)

    def _state_injection_budget_for_request(self, session_key: str, request: Any, model_hint: str = "") -> Any:
        return self._llm_response_pipeline._state_injection_budget_for_request(session_key, request, model_hint)

    def _has_conversation_manager(self) -> bool:
        return False

    def _has_persona_manager(self) -> bool:
        return False

    async def _sync_message_to_conv_mgr(self, session_key: str, role: str, text: str) -> None:
        pass

    def _sync_personality_to_persona_mgr(self, session_key: str) -> None:
        pass

    async def observe_response(self, session_key: str, *, text: str = "", confidence: float = 0.0, flags: list[str] | None = None, now: float = 0.0) -> dict[str, Any]:
        return await self._public_api.observe_response(session_key, text=text, confidence=confidence, flags=flags, now=now)

    async def observe_request(self, session_key: str, *, text: str = "", confidence: float = 0.0, flags: list[str] | None = None, now: float = 0.0) -> dict[str, Any]:
        return await self._public_api.observe_request(session_key, text=text, confidence=confidence, flags=flags, now=now)

    async def _on_llm_request_inner(self, event: Any, request: Any) -> None:
        return await self._llm_request_pipeline._on_llm_request_inner(event, request)

    async def _on_llm_response_inner(self, event: Any, response: Any) -> None:
        return await self._llm_response_pipeline._on_llm_response_inner(event, response)

    async def persist_kernel(self, session_key: str, host: Any) -> None:
        await self._state_persistence.persist_kernel(session_key, host)

    async def _persist_kernel(self, session_key: str, host: Any) -> None:
        await self._state_persistence.persist_kernel(session_key, host)

    def persist_kernel_sync(self, session_key: str, host: Any) -> None:
        self._state_persistence.persist_kernel_sync(session_key, host)

    def _persist_kernel_sync(self, session_key: str, host: Any) -> None:
        self._state_persistence.persist_kernel_sync(session_key, host)

    async def persist_buffer(self, session_key: str, host: Any, buf_dict: Any) -> None:
        await self._state_persistence.persist_buffer(session_key, host, buf_dict)

    async def _persist_buffer(self, session_key: str, host: Any, buf_dict: Any) -> None:
        await self._state_persistence.persist_buffer(session_key, host, buf_dict)

    async def load_buffer_data(self, session_key: str, host: Any) -> Any:
        return await self._state_persistence.load_buffer_data(session_key, host)

    async def _load_buffer_data(self, session_key: str, host: Any) -> Any:
        return await self._state_persistence.load_buffer_data(session_key, host)

    async def load_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_state(session_key)

    def _load_state(self, session_key: str = None) -> Any:
        if session_key is None:
            return self._read_json(self._state_path, default={})
        async def _async_load():
            return await self._state_persistence.load_state(session_key)
        return _async_load()

    async def load_psychological_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_psychological_state(session_key)

    async def _load_psychological_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_psychological_state(session_key)

    async def load_humanlike_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_humanlike_state(session_key)

    async def _load_humanlike_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_humanlike_state(session_key)

    async def load_lifelike_learning_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_lifelike_learning_state(session_key)

    async def _load_lifelike_learning_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_lifelike_learning_state(session_key)

    async def load_personality_drift_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_personality_drift_state(session_key)

    async def _load_personality_drift_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_personality_drift_state(session_key)

    async def load_moral_repair_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_moral_repair_state(session_key)

    async def _load_moral_repair_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_moral_repair_state(session_key)

    async def load_fallibility_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_fallibility_state(session_key)

    async def _load_fallibility_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_fallibility_state(session_key)

    async def save_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_state(session_key, state)

    def _save_state(self, session_key: str = None, state: Any = None) -> Any:
        if session_key is None:
            def _update(s: dict):
                s["sediment_count"] = self._sediment_count
                s["identity_stability"] = self._identity_stability
                s["last_active_umo"] = self._last_active_umo
                if hasattr(self, "_personality_vector") and self._personality_vector:
                    s["personality_vector"] = self._personality_vector
            self._atomic_update_state(_update)
            return None
        async def _async_save():
            await self._state_persistence.save_state(session_key, state)
        return _async_save()

    async def delete_state(self, session_key: str) -> None:
        await self._state_persistence.delete_state(session_key)

    async def _delete_state(self, session_key: str) -> None:
        await self._state_persistence.delete_state(session_key)

    async def delete_humanlike_state(self, session_key: str) -> None:
        await self._state_persistence.delete_humanlike_state(session_key)

    async def _delete_humanlike_state(self, session_key: str) -> None:
        await self._state_persistence.delete_humanlike_state(session_key)

    async def delete_lifelike_learning_state(self, session_key: str) -> None:
        await self._state_persistence.delete_lifelike_learning_state(session_key)

    async def _delete_lifelike_learning_state(self, session_key: str) -> None:
        await self._state_persistence.delete_lifelike_learning_state(session_key)

    async def delete_personality_drift_state(self, session_key: str) -> None:
        await self._state_persistence.delete_personality_drift_state(session_key)

    async def _delete_personality_drift_state(self, session_key: str) -> None:
        await self._state_persistence.delete_personality_drift_state(session_key)

    async def delete_moral_repair_state(self, session_key: str) -> None:
        await self._state_persistence.delete_moral_repair_state(session_key)

    async def _delete_moral_repair_state(self, session_key: str) -> None:
        await self._state_persistence.delete_moral_repair_state(session_key)

    async def delete_fallibility_state(self, session_key: str) -> None:
        await self._state_persistence.delete_fallibility_state(session_key)

    async def _delete_fallibility_state(self, session_key: str) -> None:
        await self._state_persistence.delete_fallibility_state(session_key)

    async def save_humanlike_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_humanlike_state(session_key, state)

    async def _save_humanlike_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_humanlike_state(session_key, state)

    async def save_psychological_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_psychological_state(session_key, state)

    async def _save_psychological_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_psychological_state(session_key, state)

    async def save_moral_repair_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_moral_repair_state(session_key, state)

    async def _save_moral_repair_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_moral_repair_state(session_key, state)

    async def save_lifelike_learning_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_lifelike_learning_state(session_key, state)

    async def _save_lifelike_learning_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_lifelike_learning_state(session_key, state)

    async def save_fallibility_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_fallibility_state(session_key, state)

    async def _save_fallibility_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_fallibility_state(session_key, state)

    async def save_personality_drift_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_personality_drift_state(session_key, state)

    async def _save_personality_drift_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_personality_drift_state(session_key, state)

    async def load_group_atmosphere_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_group_atmosphere_state(session_key)

    async def _load_group_atmosphere_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_group_atmosphere_state(session_key)

    async def delete_psychological_state(self, session_key: str) -> None:
        await self._state_persistence.delete_psychological_state(session_key)

    async def _delete_psychological_state(self, session_key: str) -> None:
        await self._state_persistence.delete_psychological_state(session_key)

    def _schedule_buffer_persist(self, session_key: str) -> None:
        self._state_persistence.schedule_buffer_persist(session_key)

    async def _do_buffer_persist(self, session_key: str) -> None:
        await self._state_persistence._do_buffer_persist(session_key)

    # Added Sylanne memory state delegate wrappers for full compatibility
    async def save_sylanne_memory_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_sylanne_memory_state(session_key, state)

    async def _save_sylanne_memory_state(self, session_key: str, state: Any) -> None:
        await self._state_persistence.save_sylanne_memory_state(session_key, state)

    async def load_sylanne_memory_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_sylanne_memory_state(session_key)

    async def _load_sylanne_memory_state(self, session_key: str) -> Any:
        return await self._state_persistence.load_sylanne_memory_state(session_key)

    async def delete_sylanne_memory_state(self, session_key: str) -> None:
        await self._state_persistence.delete_sylanne_memory_state(session_key)

    async def _delete_sylanne_memory_state(self, session_key: str) -> None:
        await self._state_persistence.delete_sylanne_memory_state(session_key)

    def _get_embedding_provider(self, provider_id: str) -> Any:
        try:
            providers = self.context.get_all_embedding_providers()
            for p in providers:
                if p.meta().id == provider_id:
                    return EmbeddingProviderWrapper(p)
        except Exception as e:
            logger.debug(f"[Anima] _get_embedding_provider error: {e}")
        return None

