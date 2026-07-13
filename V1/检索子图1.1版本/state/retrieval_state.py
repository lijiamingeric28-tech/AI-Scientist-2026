"""
检索子图State定义
"""

from typing import TypedDict, List, Dict, Any
from typing_extensions import NotRequired
from models.paper_metadata import PaperMetadata
from models.clarified_intent import ClarifiedIntent


class RetrievalState(TypedDict):
    """检索子图的State定义"""

    intent_params: ClarifiedIntent
    """意图澄清子图的输出（必填）"""

    expanded_queries: NotRequired[Dict[str, Any]]
    """Agent A输出：扩展后的查询参数"""

    papers: NotRequired[List[PaperMetadata]]
    """Agent B输出：搜索到的论文列表"""

    citation_papers: NotRequired[List[PaperMetadata]]
    """Agent D输出：引用链扩展的论文列表"""

    filtered_papers: NotRequired[List[PaperMetadata]]
    """Agent E输出：过滤排序后的Top N论文"""
