"""
Agent 3: OCR_Extract_Node
OCR按需提取
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from subgraphs.extraction.state import ExtractionState
from subgraphs.extraction.tools import pdf_to_base64_page, call_ocr_api
from config.constants import OCR_CONCURRENCY, OCR_MAX_RETRIES

logger = logging.getLogger(__name__)


def ocr_extract_node(state: ExtractionState) -> ExtractionState:
    logger.info("=" * 80)
    logger.info("[Agent 3] OCR_Extract_Node started")
    logger.info("=" * 80)

    vlm_results = state["vlm_results"]

    # Step 1: 分析哪些页面需要OCR
    logger.info("[Agent 3][Step 1] Analyzing VLM results to determine pages for OCR")
    pages_to_ocr = {}

    for result in vlm_results:
        if result["status"] != "success":
            continue

        pdf_path = result["pdf_path"]
        observations = result.get("observations", [])

        if pdf_path not in pages_to_ocr:
            pages_to_ocr[pdf_path] = set()

        for obs in observations:
            page_str = obs.get("source_page", "")
            if page_str:
                try:
                    page_num = int(page_str)
                    pages_to_ocr[pdf_path].add(page_num)
                except ValueError:
                    logger.warning(f"[Agent 3] Invalid page number: {page_str}")

    total_pages = sum(len(pages) for pages in pages_to_ocr.values())
    logger.info(f"[Agent 3][Step 1] Analysis completed:")
    logger.info(f"  - PDFs with data: {len(pages_to_ocr)}")
    logger.info(f"  - Total pages to OCR: {total_pages}")

    for pdf_path, page_set in list(pages_to_ocr.items())[:3]:
        logger.debug(f"  - {pdf_path}: pages {sorted(page_set)[:5]}...")

    # Step 2: 并发OCR处理
    logger.info(f"[Agent 3][Step 2] Starting concurrent OCR ({OCR_CONCURRENCY} threads)")

    ocr_results = {}
    tasks = []
    for pdf_path, page_set in pages_to_ocr.items():
        for page_num in page_set:
            tasks.append((pdf_path, page_num))

    start_time = time.time()
    success_count = 0
    failed_count = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=OCR_CONCURRENCY) as executor:
        futures = {
            executor.submit(ocr_single_page, pdf, page): (pdf, page)
            for pdf, page in tasks
        }

        for future in as_completed(futures):
            pdf_path, page_num = futures[future]
            completed += 1

            try:
                ocr_data = future.result()
                if ocr_data:
                    key = f"{pdf_path}__page_{page_num}"
                    ocr_results[key] = ocr_data["words_info"]
                    success_count += 1
                    logger.debug(f"[Agent 3] Progress: {completed}/{total_pages} | "
                               f"Page {page_num} | {len(ocr_data['words_info'])} words")
                else:
                    failed_count += 1
                    logger.warning(f"[Agent 3] Page {page_num} OCR failed")
            except Exception as e:
                logger.error(f"[Agent 3] Page {page_num} exception: {e}")
                failed_count += 1

    elapsed = time.time() - start_time

    ocr_stats = {
        "total_pages": total_pages,
        "success_pages": success_count,
        "failed_pages": failed_count,
        "elapsed_time": elapsed
    }

    logger.info("=" * 80)
    logger.info("[Agent 3] OCR extraction completed")
    logger.info(f"  - Success: {success_count}/{total_pages}")
    logger.info(f"  - Failed: {failed_count}")
    logger.info(f"  - Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    logger.info(f"  - Average: {elapsed/total_pages:.2f}s per page" if total_pages > 0 else "  - Average: N/A")
    logger.info("=" * 80)

    state["ocr_results"] = ocr_results
    state["ocr_stats"] = ocr_stats

    return state


def ocr_single_page(pdf_path: str, page_num: int) -> dict:
    for attempt in range(OCR_MAX_RETRIES):
        try:
            image_base64 = pdf_to_base64_page(pdf_path, page_num - 1)
            if not image_base64:
                return None

            ocr_data = call_ocr_api(image_base64)

            if ocr_data:
                return ocr_data

            if attempt < OCR_MAX_RETRIES - 1:
                time.sleep(1)

        except Exception as e:
            if attempt < OCR_MAX_RETRIES - 1:
                time.sleep(1)
                continue
            else:
                logger.error(f"[OCR] Page {page_num} failed: {e}")
                return None

    return None
