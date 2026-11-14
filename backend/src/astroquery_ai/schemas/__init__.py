"""共享状态契约层（Phase 2 收敛）

职责：
1. 统一跨子图字段命名（以主图契约为准）
2. 每个子图的 Input/Output Pydantic schema —— 包装节点入口/出口验证用，
   使子图接口成为可验证的契约（而非手写投影的隐式约定）

历史：5 个 TypedDict 字段名互相冲突（original_query/user_query、
downloaded_papers/download_paths），靠 adapters.py 手写改名胶合。
现在：命名统一，投影退化为"选键 + 组装"，接口由 Pydantic 契约声明。
"""

from .subgraph1_io import Sg1Input, Sg1Output
from .subgraph2_io import Sg2Input, Sg2Output
from .subgraph3_io import Sg3Input, Sg3Output

__all__ = [
    "Sg1Input",
    "Sg1Output",
    "Sg2Input",
    "Sg2Output",
    "Sg3Input",
    "Sg3Output",
]
