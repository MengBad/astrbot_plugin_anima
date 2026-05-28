"""
Anima 子系统 Mixin 包
====================
v0.8.0 大模块拆分：把 main.py 中按 `# ==================== xxx ====================` 分段的
子系统逻辑抽出成独立 Mixin 类。每个 Mixin 只承载方法，依赖宿主类（AnimaPlugin）提供的
self.* 状态字段（self.config / self.context / self.data_dir / self._io_lock 等）。

这一层与 anima/ 包下的纯函数模块（filters / similarity / capability_dedup / forgetting / valence）
形成双层架构：
- anima/*.py        ：纯函数，无 self 依赖，直接单元测试
- anima/mixins/*.py ：方法集合，依赖宿主 self.* 状态，通过 mixin 注入到 AnimaPlugin

使用方式：
    from .anima.mixins.danger import DangerMixin
    class AnimaPlugin(DangerMixin, ..., Star):
        ...
"""
