"""Anima 插件的内部模块包。

v0.7.0: 从 4000+ 行的 main.py 拆分出来的可测试纯函数库。
所有这里的函数都不依赖 AstrBot 运行时，可以直接被 pytest 单独测试。

模块说明：
- filters: 拒绝语过滤、敏感内容过滤
- similarity: 文本相似度（Jaccard / Cosine / ngram tokenize）
- capability_dedup: 能力归一化签名 + 近似匹配
- forgetting: 遗忘机制（时间戳模糊化）
- valence: 记忆情感效价估算
"""
