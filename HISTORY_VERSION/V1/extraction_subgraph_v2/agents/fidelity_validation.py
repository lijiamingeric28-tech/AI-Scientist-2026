"""
Agent 4: Fidelity_Validation_Agent
忠实度验证
"""

import logging
from state.extraction_state import ExtractionState
from tools import verify_observation
from configs.constants import ENTITY_THRESHOLD, PROPERTY_THRESHOLD

logger = logging.getLogger(__name__)


def fidelity_validation_agent(state: ExtractionState) -> ExtractionState:
    logger.info("=" * 80)
    logger.info("[Agent 4] Fidelity_Validation_Agent started")
    logger.info("=" * 80)
    
    vlm_results = state["vlm_results"]
    ocr_results = state["ocr_results"]
    
    logger.info(f"[Agent 4] Configuration:")
    logger.info(f"  - Entity threshold: {ENTITY_THRESHOLD}")
    logger.info(f"  - Property threshold: {PROPERTY_THRESHOLD}")
    logger.info(f"  - VLM results: {len(vlm_results)}")
    logger.info(f"  - OCR results: {len(ocr_results)} pages")
    
    verified_records = []
    failed_records = []
    
    total_obs = 0
    no_page_count = 0
    no_ocr_count = 0
    verification_failed_count = 0
    
    logger.info("[Agent 4] Starting verification...")
    
    for result in vlm_results:
        if result["status"] != "success":
            continue
        
        paper_id = result["paper_id"]
        pdf_path = result["pdf_path"]
        observations = result.get("observations", [])
        
        logger.debug(f"[Agent 4] Validating {paper_id}: {len(observations)} observations")
        
        for obs in observations:
            total_obs += 1
            page_num = obs.get("source_page", "")
            
            if not page_num:
                no_page_count += 1
                failed_records.append({
                    "paper_id": paper_id,
                    "observation": obs,
                    "error": "Empty page number"
                })
                continue
            
            ocr_key = f"{pdf_path}__page_{page_num}"
            ocr_words = ocr_results.get(ocr_key, [])
            
            if not ocr_words:
                no_ocr_count += 1
                failed_records.append({
                    "paper_id": paper_id,
                    "observation": obs,
                    "error": f"OCR not available for page {page_num}"
                })
                continue
            
            verification = verify_observation(
                obs, 
                ocr_words, 
                ENTITY_THRESHOLD,
                PROPERTY_THRESHOLD
            )
            
            if verification["verified"]:
                verified_records.append({
                    "paper_id": paper_id,
                    "observation": obs,
                    "verification": verification
                })
                logger.debug(f"[Agent 4] PASS: {paper_id} | {obs.get('entity_name')}")
            else:
                verification_failed_count += 1
                failed_records.append({
                    "paper_id": paper_id,
                    "observation": obs,
                    "verification": verification
                })
                entity_score = verification["entity_verification"]["match_score"]
                prop_score = verification["property_verification"]["match_score"]
                logger.debug(f"[Agent 4] FAIL: {paper_id} | "
                           f"entity={entity_score}, property={prop_score}")
    
    total = len(verified_records) + len(failed_records)
    verification_rate = len(verified_records) / total if total > 0 else 0.0
    
    logger.info("=" * 80)
    logger.info("[Agent 4] Validation completed")
    logger.info(f"  - Total observations: {total_obs}")
    logger.info(f"  - Verified PASS: {len(verified_records)}")
    logger.info(f"  - Verification FAIL: {verification_failed_count}")
    logger.info(f"  - No page number: {no_page_count}")
    logger.info(f"  - No OCR data: {no_ocr_count}")
    logger.info(f"  - Total discarded: {len(failed_records)}")
    logger.info(f"  - Verification rate: {verification_rate*100:.1f}%")
    logger.info("=" * 80)
    
    state["verified_records"] = verified_records
    state["failed_records"] = failed_records
    state["verification_rate"] = verification_rate
    
    return state
