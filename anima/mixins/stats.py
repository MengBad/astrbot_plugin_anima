"""
StatsMixin —— v0.9.0 运行可观测性（轻量计数器 + /anima_stats 仪表盘数据）
============================================================

目的：不用再靠导出几千行 debug 日志来判断各子系统在干什么、token 烧在哪、
哪条防线在频繁触发。提供一个按天滚动的内存计数器，关键节点 _stat_bump()，
/anima_stats 命令一次性打印。

设计要点：
- 内存计数 + 懒持久化到 anima_state.json 的 "stats_daily" 字段，插件重载/重启
  当天数据不丢；跨天自动归零（按本地日期 key）。
- 完全旁路：埋点失败绝不影响主流程（_stat_bump 内吞掉所有异常）。
- 不调用任何 LLM，纯本地累加，自身零 token。

计数项（约定 key）：
- llm.<purpose>      ：内部 LLM 调用次数（emotion/monologue/desire/relation/
                       worldview/info_collection/stance/memory_infection/...）
- sediment.run       ：沉淀流程执行次数
- sediment.skip_low  ：情绪低于阈值跳过沉淀次数
- desire.created.<kind>：产生的 inward/outward 欲望数
- stance.sent        ：实际发出的主动发言数
- stance.blocked.<reason>：主动发言被各防线拦截数（monologue/irrelevant/dedup/...）
- store.in / store.out ：记忆存储次数
"""
from __future__ import annotations

from datetime import datetime

from astrbot.api import logger


class StatsMixin:
    """运行计数器 mixin。依赖宿主类的 self._atomic_update_state / self._load_state。"""

    def _today_key(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _ensure_stats_loaded(self):
        """懒初始化内存计数器 self._stats = {"date": "YYYY-MM-DD", "counts": {...}}。
        从 state 恢复当天数据；跨天则归零。"""
        today = self._today_key()
        cur = getattr(self, "_stats", None)
        if cur is not None and cur.get("date") == today:
            return
        # 尝试从持久化 state 恢复当天数据
        counts = {}
        try:
            saved = self._load_state().get("stats_daily", {})
            if isinstance(saved, dict) and saved.get("date") == today:
                counts = dict(saved.get("counts", {}))
        except Exception:
            counts = {}
        self._stats = {"date": today, "counts": counts}

    def _stat_bump(self, key: str, n: int = 1):
        """给某个计数 key 累加 n。埋点绝不抛异常影响主流程。
        v0.9.1: 受 dashboard_enabled 开关控制 —— 关闭时连内存累加都跳过。"""
        try:
            if getattr(self, "config", None) and not self.config.get("dashboard_enabled", True):
                return
            self._ensure_stats_loaded()
            self._stats["counts"][key] = self._stats["counts"].get(key, 0) + n
            # 懒持久化：写回 state（_atomic_update_state 持锁，安全）
            snapshot = {"date": self._stats["date"], "counts": dict(self._stats["counts"])}

            def _update(state: dict):
                state["stats_daily"] = snapshot

            if hasattr(self, "_atomic_update_state"):
                self._atomic_update_state(_update)
        except Exception as e:
            if getattr(self, "config", None) and self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] _stat_bump 失败({key}): {e}")

    def _stats_get(self, key: str) -> int:
        try:
            self._ensure_stats_loaded()
            return int(self._stats["counts"].get(key, 0))
        except Exception:
            return 0

    def _stats_snapshot(self) -> dict:
        """v0.9.1: 返回结构化统计快照，供网页仪表盘（Plugin Pages）消费。
        纯读，不调 LLM。结构稳定，前端按字段渲染。"""
        self._ensure_stats_loaded()
        c = dict(self._stats["counts"])

        def _bucket(prefix):
            return {
                k[len(prefix):]: v
                for k, v in sorted(c.items(), key=lambda kv: -kv[1])
                if k.startswith(prefix)
            }

        llm = _bucket("llm.")
        blocked = _bucket("stance.blocked.")
        return {
            "date": self._stats["date"],
            "llm_calls": llm,
            "llm_total": sum(llm.values()),
            "sediment": {
                "run": c.get("sediment.run", 0),
                "skip_low": c.get("sediment.skip_low", 0),
            },
            "desire": {
                "outward": c.get("desire.created.outward", 0),
                "inward": c.get("desire.created.inward", 0),
            },
            "stance": {
                "sent": c.get("stance.sent", 0),
                "blocked": blocked,
                "blocked_total": sum(blocked.values()),
            },
            "store": {
                "in": c.get("store.in", 0),
                "out": c.get("store.out", 0),
            },
            "raw": c,
        }

    def _render_stats(self) -> str:
        """渲染 /anima_stats 文本。"""
        if getattr(self, "config", None) and not self.config.get("dashboard_enabled", True):
            return "[Anima] 运行仪表盘已在配置中禁用（dashboard_enabled=false）。开启后可查看今日统计。"
        self._ensure_stats_loaded()
        c = self._stats["counts"]
        if not c:
            return f"[Anima] 今日（{self._stats['date']}）暂无统计数据。"

        # LLM 调用分桶
        llm_items = sorted(
            ((k[len("llm."):], v) for k, v in c.items() if k.startswith("llm.")),
            key=lambda kv: -kv[1],
        )
        llm_total = sum(v for _, v in llm_items)

        stance_blocked = sorted(
            ((k[len("stance.blocked."):], v) for k, v in c.items() if k.startswith("stance.blocked.")),
            key=lambda kv: -kv[1],
        )
        stance_blocked_total = sum(v for _, v in stance_blocked)

        lines = [f"[Anima] 今日运行统计（{self._stats['date']}）", ""]

        lines.append(f"■ 内部 LLM 调用：共 {llm_total} 次")
        for name, v in llm_items:
            lines.append(f"   · {name}: {v}")

        lines.append("")
        lines.append("■ 沉淀流程")
        lines.append(f"   · 触发沉淀: {c.get('sediment.run', 0)}")
        lines.append(f"   · 情绪未达阈值跳过: {c.get('sediment.skip_low', 0)}")

        lines.append("")
        lines.append("■ 欲望")
        lines.append(f"   · 新增 outward(可外发): {c.get('desire.created.outward', 0)}")
        lines.append(f"   · 新增 inward(只内省): {c.get('desire.created.inward', 0)}")

        lines.append("")
        lines.append("■ 主动发言")
        lines.append(f"   · 实际发出: {c.get('stance.sent', 0)}")
        lines.append(f"   · 被防线拦截: {stance_blocked_total}")
        for name, v in stance_blocked:
            lines.append(f"      - {name}: {v}")

        lines.append("")
        lines.append("■ 记忆存储")
        lines.append(f"   · 用户消息(in): {c.get('store.in', 0)}")
        lines.append(f"   · bot 回复(out): {c.get('store.out', 0)}")

        lines.append("")
        lines.append("提示：内部 LLM 调用越多越费 token。可在配置里按 🔴/🟡 标注关闭高耗项。")
        return "\n".join(lines)
