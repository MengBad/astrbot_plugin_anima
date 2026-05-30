"""pytest 共享 fixture。

注意：仓库正在拆分模块（v0.7.0）。拆分后测试会直接 import 各 core/ 子模块，
不需要 import main.py（那个需要 astrbot 运行时）。
"""

import sys
from pathlib import Path

# 让测试可以 import 仓库根的子模块
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 让测试可以 import tests/ 目录下的共享辅助模块（如 _merged_eval_host）
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
