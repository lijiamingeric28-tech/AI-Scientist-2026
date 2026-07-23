"""
检索子图的State定义
"""

from typing import TypedDict, NotRequired, Any, Dict
from shared.models.clarified_intent import ClarifiedIntent
from shared.models.paper_metadata import PaperMetadata


class RetrievalState(TypedDict, total=False):
    """检索子图State"""

    # ===== Input (从上游接收) =====
    intent_params: ClarifiedIntent
    query_context: NotRequired[Dict[str, Any]]  # 查询上下文配置（包含max_papers, enable_citation_expansion等）

    # ===== Output (传递给下游) =====
    expanded_queries: NotRequired[Dict[str, Any]]  # 扩展后的查询参数
    papers: NotRequired[list[PaperMetadata]]  # OpenAlex检索结果
    pubmed_papers: NotRequired[list[PaperMetadata]]  # PubMed检索结果
    citation_papers: NotRequired[list[PaperMetadata]]  # 引用扩展结果
    filtered_papers: NotRequired[list[PaperMetadata]]  # 过滤排序后的论文列表（最终输出）
