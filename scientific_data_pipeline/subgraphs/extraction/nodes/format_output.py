"""
Agent 5: Format_Output_Node
格式化输出
"""

import logging
from typing import Optional, List
from subgraphs.extraction.state import ExtractionState
from subgraphs.extraction.tools import generate_extraction_report

logger = logging.getLogger(__name__)


def convert_bbox_8_to_4(bbox_8: Optional[List]) -> Optional[list[float]]:
    """
    将 8 个值的多边形 bbox 转换为 4 个值的矩形 bbox

    Args:
        bbox_8: [x1, y1, x2, y2, x3, y3, x4, y4] 四边形顶点坐标

    Returns:
        [x_min, y_min, x_max, y_max] 矩形边界框，或 None
    """
    if not bbox_8 or len(bbox_8) != 8:
        return None

    try:
        xs = [bbox_8[0], bbox_8[2], bbox_8[4], bbox_8[6]]
        ys = [bbox_8[1], bbox_8[3], bbox_8[5], bbox_8[7]]

        return [min(xs), min(ys), max(xs), max(ys)]
    except (TypeError, IndexError) as e:
        logger.warning(f"bbox conversion failed: {e}, bbox_8={bbox_8}")
        return None


def format_output_node(state: ExtractionState) -> ExtractionState:
    logger.info("=" * 80)
    logger.info("[Agent 5] Format_Output_Node started")
    logger.info("=" * 80)

    verified_records = state["verified_records"]
    papers = state["filtered_papers"]
    normalized_params = state["normalized_params"]

    logger.info(f"[Agent 5] Input:")
    logger.info(f"  - Verified records: {len(verified_records)}")
    logger.info(f"  - Papers: {len(papers)}")
    logger.info(f"  - Entity type: {normalized_params['entity_type']}")
    logger.info(f"  - Property name: {normalized_params['property_name']}")

    # 构建papers映射
    papers_map = {}
    for paper in papers:
        paper_id = paper.id  # PaperMetadata是Pydantic模型，使用属性访问
        if paper_id:
            papers_map[paper_id] = paper

    # Step 1: 构建sources
    logger.info("[Agent 5][Step 1] Building sources")
    source_ids = set(r["paper_id"] for r in verified_records)
    sources = []

    for source_id in source_ids:
        paper = papers_map.get(source_id)
        if not paper:
            logger.warning(f"[Agent 5] Paper {source_id} not found in papers_map")
            continue

        sources.append({
            "source_id": paper.id,
            "source_type": "paper",
            "doi": paper.doi,
            "title": paper.title,
            "authors": paper.authors or [],
            "year": paper.year,
            "journal": paper.journal,
            "access_path": paper.local_path,
            "retrieval_priority": min(max(paper.score / 100.0, 0.0), 1.0) if paper.score else 0.0  # 归一化到 [0, 1]
        })

    logger.info(f"[Agent 5][Step 1] Created {len(sources)} sources")

    # Step 2: 构建records
    logger.info("[Agent 5][Step 2] Building records")
    records = []

    for i, rec in enumerate(verified_records):
        obs = rec["observation"]
        verification = rec["verification"]

        # 获取 bbox（8 个值格式）
        prop_bbox = verification["property_verification"].get("bbox")
        entity_bbox = verification["entity_verification"].get("bbox")
        bbox_8 = prop_bbox if prop_bbox else entity_bbox

        # 转换为 4 个值格式（矩形边界框）
        bbox = convert_bbox_8_to_4(bbox_8)

        entity_name_safe = obs.get("entity_name", "unknown").replace(" ", "_").replace("/", "_")
        field_name = normalized_params["property_name"]
        record_id = f"{rec['paper_id']}_{entity_name_safe}_{field_name}_{i}"

        field_value = obs.get("property_value")
        try:
            field_value = float(field_value)
        except (ValueError, TypeError):
            field_value = str(field_value)

        records.append({
            "record_id": record_id,
            "source_id": rec["paper_id"],
            "entity_type": normalized_params["entity_type"],
            "field_name": normalized_params["property_name"],
            "entity_name": obs.get("entity_name"),
            "field_value": field_value,
            "field_unit": obs.get("property_unit"),
            "trace_id": f"doc{i}_p{obs.get('source_page')}",
            "provenance": {
                "page": int(obs.get("source_page", 0)),
                "bbox": bbox
            },
            "extraction_method": "vlm_text"
        })

        if i < 3:
            logger.debug(f"[Agent 5] Record {i}: {obs.get('entity_name')} = {field_value}")

    logger.info(f"[Agent 5][Step 2] Created {len(records)} records")

    # Step 3: 组装grounded_data
    logger.info("[Agent 5][Step 3] Assembling grounded_data V1.1")
    grounded_data = {
        "schema_version": "1.1.0",
        "sources": sources,
        "records": records
    }

    state["grounded_data"] = grounded_data

    logger.info(f"[Agent 5][Step 3] grounded_data assembled: {len(sources)} sources, {len(records)} records")

    # Step 4: 生成报告
    from config.constants import ENABLE_EXTRACTION_REPORT

    if ENABLE_EXTRACTION_REPORT:
        logger.info("[Agent 5][Step 4] Generating extraction report")
        try:
            report_path = generate_extraction_report(state)
            state["extraction_report"] = report_path
            logger.info(f"[Agent 5][Step 4] Report generated: {report_path}")
        except Exception as e:
            logger.error(f"[Agent 5][Step 4] Report generation failed: {e}")
            state["extraction_report"] = ""
    else:
        logger.info("[Agent 5][Step 4] Report generation disabled")
        state["extraction_report"] = ""

    logger.info("=" * 80)
    logger.info("[Agent 5] Format_Output_Node completed")
    logger.info("=" * 80)

    return state
