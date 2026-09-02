"""
提取子图 State定义
"""

from typing import TypedDict, Optional, List, Dict, Any


class ExtractionState(TypedDict, total=False):
    """提取子图State"""

    # ===== 输入（来自上游） =====
    intent_params: Dict[str, Any]       # 意图参数（ClarifiedIntent对象）
    filtered_papers: List[Dict[str, Any]]  # 下载成功的论文列表

    # ===== Agent 1 输出（准备阶段） =====
    normalized_params: Dict[str, Any]   # 规范化后的参数 {entity_type, property_name}
    extraction_prompt: str              # 生成的VLM Prompt
    extraction_tasks: List[Dict[str, Any]]  # 提取任务队列

    # ===== Agent 2 输出（VLM提取） =====
    vlm_results: List[Dict[str, Any]]   # VLM提取结果
    vlm_stats: Dict[str, Any]           # VLM统计信息

    # ===== Agent 3 输出（OCR提取） =====
    ocr_results: Dict[str, List[Dict[str, Any]]]  # OCR结果 {pdf_page_key: words_info}
    ocr_stats: Dict[str, Any]           # OCR统计信息

    # ===== Agent 4 输出（验证阶段） =====
    verified_records: List[Dict[str, Any]]  # 验证通过的记录
    failed_records: List[Dict[str, Any]]    # 验证失败的记录
    verification_rate: float            # 验证通过率

    # ===== Agent 5 输出（最终产物） =====
    grounded_data: Dict[str, Any]       # grounded_data V1.1格式
    extraction_report: str              # Markdown报告路径
