"""
Agent 2: VLM_Extract_Agent
VLM批量提取
"""

import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from state.extraction_state import ExtractionState
from tools.extraction import pdf_to_images, image_to_base64, call_vlm_api
from configs.prompts_extraction import VLM_EXTRACTION_SCHEMA
from configs.constants import VLM_CONCURRENCY, VLM_MAX_RETRIES

logger = logging.getLogger(__name__)


def vlm_extract_agent(state: ExtractionState) -> ExtractionState:
    logger.info("=" * 80)
    logger.info("[Agent 2] VLM_Extract_Agent started")
    logger.info("=" * 80)
    
    tasks = state["extraction_tasks"]
    prompt = state["extraction_prompt"]
    
    logger.info(f"[Agent 2] Configuration:")
    logger.info(f"  - Total PDFs: {len(tasks)}")
    logger.info(f"  - Concurrency: {VLM_CONCURRENCY} threads")
    logger.info(f"  - Max retries per PDF: {VLM_MAX_RETRIES}")
    
    logger.info("[Agent 2] Starting concurrent VLM extraction...")
    start_time = time.time()
    
    results = []
    completed = 0
    
    with ThreadPoolExecutor(max_workers=VLM_CONCURRENCY) as executor:
        futures = {
            executor.submit(extract_single_pdf_vlm, task, prompt): task
            for task in tasks
        }
        
        for future in as_completed(futures):
            task = futures[future]
            completed += 1
            
            try:
                result = future.result()
                results.append(result)
                
                status = result.get("status", "unknown")
                obs_count = len(result.get("observations", []))
                logger.info(f"[Agent 2] Progress: {completed}/{len(tasks)} | "
                           f"Paper: {task['paper_id']} | "
                           f"Status: {status} | Observations: {obs_count}")
                
            except Exception as e:
                logger.error(f"[Agent 2] Exception for PDF {task['paper_id']}: {e}")
                results.append({
                    "paper_id": task["paper_id"],
                    "pdf_path": task["pdf_path"],
                    "status": "error",
                    "error": str(e),
                    "observations": []
                })
    
    elapsed = time.time() - start_time
    
    success_count = sum(1 for r in results if r["status"] == "success")
    total_observations = sum(len(r.get("observations", [])) for r in results if r["status"] == "success")
    
    vlm_stats = {
        "total_pdfs": len(results),
        "success_pdfs": success_count,
        "failed_pdfs": len(results) - success_count,
        "total_observations": total_observations,
        "elapsed_time": elapsed
    }
    
    logger.info("=" * 80)
    logger.info("[Agent 2] VLM extraction completed")
    logger.info(f"  - Success: {success_count}/{len(results)}")
    logger.info(f"  - Total observations: {total_observations}")
    logger.info(f"  - Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    logger.info("=" * 80)
    
    state["vlm_results"] = results
    state["vlm_stats"] = vlm_stats
    
    return state


def extract_single_pdf_vlm(task: dict, prompt: str) -> dict:
    paper_id = task["paper_id"]
    pdf_path = task["pdf_path"]
    
    logger.debug(f"[VLM] Processing {paper_id}")
    
    try:
        images = pdf_to_images(pdf_path, max_pages=task.get("max_pages"))
        if not images:
            return {
                "paper_id": paper_id,
                "pdf_path": pdf_path,
                "status": "error",
                "error": "PDF conversion failed",
                "observations": []
            }
        
        logger.debug(f"[VLM] {paper_id} - {len(images)} pages")
        
        content = []
        for img in images:
            img_base64 = image_to_base64(img)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_base64}"}
            })
        content.append({"type": "text", "text": prompt})
        
        observations = None
        attempts = 0
        
        for attempt in range(1, VLM_MAX_RETRIES + 1):
            logger.debug(f"[VLM] {paper_id} - Attempt {attempt}")
            try:
                result_text = call_vlm_api(content, schema=VLM_EXTRACTION_SCHEMA)
                observations = json.loads(result_text)
                
                if isinstance(observations, list):
                    attempts = attempt
                    if len(observations) > 0 or attempt >= 2:
                        break
                        
            except Exception as e:
                logger.warning(f"[VLM] {paper_id} - Attempt {attempt} failed: {e}")
                if attempt < VLM_MAX_RETRIES:
                    time.sleep(1)
        
        if observations is not None and isinstance(observations, list):
            logger.info(f"[VLM] {paper_id} - SUCCESS: {len(observations)} obs, {attempts} attempts")
            return {
                "paper_id": paper_id,
                "pdf_path": pdf_path,
                "status": "success",
                "attempts": attempts,
                "pages": len(images),
                "observations": observations
            }
        else:
            logger.error(f"[VLM] {paper_id} - FAILED")
            return {
                "paper_id": paper_id,
                "pdf_path": pdf_path,
                "status": "error",
                "error": "VLM failed",
                "observations": []
            }
            
    except Exception as e:
        logger.error(f"[VLM] {paper_id} - EXCEPTION: {e}")
        return {
            "paper_id": paper_id,
            "pdf_path": pdf_path,
            "status": "error",
            "error": str(e),
            "observations": []
        }
