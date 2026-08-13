"""
Quality Pipeline (子图4) — 数据质量管线

职责：
  - Assessment: 完整性/一致性/可靠性评估
  - Conflict: 冲突检测与解决
  - Normalization: 单位换算/实体归一/数据补全
  - Insights: 生成科学洞察与质量报告
  - Export: 结构化输出

入口：
  from .graph import build_quality_graph
"""

__version__ = "3.0.0"

from .graph import build_quality_graph
from .quality_state import QualityGraphState

__all__ = ["build_quality_graph", "QualityGraphState"]
