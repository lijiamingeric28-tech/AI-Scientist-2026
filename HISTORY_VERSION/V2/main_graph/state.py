"""
主图State定义 (main_graph/state.py)

职责：
    定义主管道的全局State，整合所有子图的输入输出

用法：
    from main_graph.state import MainState

    state: MainState = {
        "user_query": "查询文本",
        "intent_params": {...},
        # ... 其他字段
    }

State字段说明：
    - 以 _ 开头的字段为内部字段，不传递给用户
    - 每个子图有独立的输出字段
"""

from typing import TypedDict, Optional, List, Dict, Any


class MainState(TypedDict, total=False):
    """
    主管道State定义

    流程数据流：
        user_query
        → intent_params (子图1输出)
        → papers (子图2输出)
        → grounded_data (子图3输出)
        → final_output (子图4输出)
    """

    # === 输入 ===
    user_query: str                                    # 用户原始查询

    # === 子图1：意图澄清 输出 ===
    intent_params: Optional[Dict[str, Any]]            # 结构化意图参数
    compromise_flag: Optional[bool]                    # 是否包含AI推测

    # === 子图2：检索 输出 ===
    expanded_queries: Optional[Dict[str, Any]]         # 扩展查询
    papers: Optional[List[Dict[str, Any]]]             # 论文列表
    citation_papers: Optional[List[Dict[str, Any]]]    # 引用扩展
    filtered_papers: Optional[List[Dict[str, Any]]]    # 去重后论文

    # === 子图3：提取 输出 ===
    grounded_data: Optional[Dict[str, Any]]            # 带溯源的结构化数据
    verification_rate: Optional[float]                 # 验证率
    extraction_report: Optional[str]                   # 提取报告

    # === 子图4：质检 输出 ===
    final_output: Optional[Dict[str, Any]]             # 最终输出
    quality_summary: Optional[Dict[str, Any]]          # 质量摘要

    # === 内部字段 ===
    _workflow_status: Optional[str]                    # 工作流状态
    _error_log: Optional[List[str]]                    # 错误日志
