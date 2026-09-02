"""
主State定义

连接所有子图的顶层State
"""

from typing import TypedDict, List, Dict, Any
from typing_extensions import NotRequired
from models.paper_metadata import PaperMetadata
from models.clarified_intent import ClarifiedIntent


class MainState(TypedDict):
    """
    主流程State

    连接意图澄清、文献检索、数据提取、数据清洗四个子图
    """

    # ========== 用户输入 ==========
    user_query: str
    """用户的自然语言查询（必填）"""

    auto_confirm: NotRequired[bool]
    """是否启用自动确认模式（用于非交互式测试）"""

    # ========== 意图澄清子图输出 ==========
    intent_params: NotRequired[ClarifiedIntent]
    """意图澄清子图的输出"""

    # ========== 文献检索子图中间结果 ==========
    expanded_queries: NotRequired[Dict[str, Any]]
    """扩展后的查询参数"""

    papers: NotRequired[List[PaperMetadata]]
    """搜索到的论文列表"""

    citation_papers: NotRequired[List[PaperMetadata]]
    """引用扩展的论文列表"""

    filtered_papers: NotRequired[List[PaperMetadata]]
    """过滤排序后的Top N论文（带PDF）"""

    # ========== 数据提取子图输出（未来） ==========
    # extracted_data: NotRequired[List[Dict]]
    # """从论文中提取的结构化数据"""

    # ========== 数据清洗子图输出（未来） ==========
    # cleaned_data: NotRequired[List[Dict]]
    # """清洗后的最终数据"""
