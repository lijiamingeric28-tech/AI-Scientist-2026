"""AstroQuery AI — 天文数据检索与提取流水线

三个子图串联：意图澄清 -> 并行检索 -> 多模态提取 -> 最终聚合

用法::

    from astroquery_ai import run_pipeline

    state = run_pipeline("M31 的距离是多少？")
    print(state["final_output"])
"""

from .main_graph import create_main_graph, run_pipeline
from .state import MainGraphState

__version__ = "2.0.0"

__all__ = [
    "create_main_graph",
    "run_pipeline",
    "MainGraphState",
]
