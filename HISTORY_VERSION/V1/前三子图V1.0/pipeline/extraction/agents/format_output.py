"""
Agent 5: Format_Output_Agent
格式化输出
"""

import logging
from state.extraction_state import ExtractionState
from tools.extraction import generate_extraction_report

logger = logging.getLogger(__name__)


def format_output_agent(state: ExtractionState) -> ExtractionState:
    logger.info("=" * 80)
    logger.info("[Agent 5] Format_Output_Agent started")
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
            "retrieval_priority": paper.score  # Agent E的排序分数
        })
    
    logger.info(f"[Agent 5][Step 1] Created {len(sources)} sources")
    
    # Step 2: 构建records
    logger.info("[Agent 5][Step 2] Building records")
    records = []
    
    for i, rec in enumerate(verified_records):
        obs = rec["observation"]
        verification = rec["verification"]
        
        prop_bbox = verification["property_verification"].get("bbox")
        entity_bbox = verification["entity_verification"].get("bbox")
        bbox = prop_bbox if prop_bbox else entity_bbox
        
        entity_name_safe = obs.get("entity_name", "unknown").replace(" ", "_").replace("/", "_")
        property_name = normalized_params["property_name"]
        record_id = f"{rec['paper_id']}_{entity_name_safe}_{property_name}_{i}"
        
        property_value = obs.get("property_value")
        try:
            property_value = float(property_value)
        except (ValueError, TypeError):
            property_value = str(property_value)
        
        records.append({
            "record_id": record_id,
            "source_id": rec["paper_id"],
            "entity_type": normalized_params["entity_type"],
            "property_name": normalized_params["property_name"],
            "entity_name": obs.get("entity_name"),
            "property_value": property_value,
            "property_unit": obs.get("property_unit"),
            "trace_id": f"doc{i}_p{obs.get('source_page')}",
            "provenance": {
                "page": int(obs.get("source_page", 0)),
                "bbox": bbox
            },
            "extraction_method": "vlm_text"
        })
        
        if i < 3:
            logger.debug(f"[Agent 5] Record {i}: {obs.get('entity_name')} = {property_value}")
    
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
    from configs.constants import ENABLE_EXTRACTION_REPORT
    
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
    logger.info("[Agent 5] Format_Output_Agent completed")
    logger.info("=" * 80)
    
    return state
