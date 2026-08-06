"""BBox annotation node (data-point level concurrency)."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict
from ..schemas.state import ExtractionState
from ..utils.logger import get_logger
from ..utils.bbox_vlm_client import call_qwen_flash_bbox
from ..utils.image_cache import image_cache
from ..config.settings import settings


logger = get_logger(__name__)


def bbox_batch_annotator(state: ExtractionState) -> ExtractionState:
    """
    BBox batch annotation node (data-point level concurrency).

    Steps:
    1. Iterate through all raw_extractions
    2. Build task list: each extraction record as an independent task
    3. Call qwen3.7-flash concurrently (max_workers from config)
    4. Track results using (bibcode, index) tuples
    5. Fill bbox_2d back to original extractions
    6. Update state

    Args:
        state: Current extraction state

    Returns:
        Updated state with bbox_2d fields added to raw_extractions
    """
    raw_extractions = state.get("raw_extractions", {})
    paper_image_paths = state.get("paper_image_paths", {})
    target_entity = state["target_entity"]
    query_id = state["query_id"]

    logger.info(f"[BBox Annotator] Query ID: {query_id}")
    logger.info(f"[BBox Annotator] Starting bbox annotation for {len(raw_extractions)} papers...")

    state["bbox_annotation_status"] = "running"

    # Build task list (data-point level)
    tasks = []
    for bibcode, paper_data in raw_extractions.items():
        extractions = paper_data.get("extractions", [])
        for idx, extraction in enumerate(extractions):
            page = extraction.get("page")
            if page is None:
                logger.warning(f"[BBox Annotator] Missing page for {bibcode} extraction {idx}")
                continue

            # Get image path for this page
            if bibcode not in paper_image_paths:
                logger.warning(f"[BBox Annotator] No images found for {bibcode}")
                continue

            image_paths = paper_image_paths[bibcode]
            if page < 1 or page > len(image_paths):
                logger.warning(f"[BBox Annotator] Invalid page {page} for {bibcode}")
                continue

            image_path = image_paths[page - 1]  # page is 1-based

            tasks.append({
                "bibcode": bibcode,
                "index": idx,  # 🔑 Array index for tracking
                "page": page,
                "image_path": image_path,
                "extraction": extraction  # Full extraction data
            })

    total_tasks = len(tasks)
    logger.info(f"[BBox Annotator] Total annotation tasks: {total_tasks}")

    if total_tasks == 0:
        logger.warning("[BBox Annotator] No tasks to process!")
        state["bbox_annotation_status"] = "completed"
        return state

    # Result storage: key = f"{bibcode}_{index}"
    bbox_results = {}
    failed_tasks = []
    completed = 0

    # Get concurrency settings
    max_workers = getattr(settings, 'bbox_concurrency', type('obj', (object,), {
        'max_workers': 100,
        'max_retries': 3
    })()).max_workers

    logger.info(f"[BBox Annotator] Using max_workers={max_workers}")

    # Concurrent processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {}
        for task in tasks:
            key = f"{task['bibcode']}_{task['index']}"
            future = executor.submit(annotate_single_bbox, task, target_entity)
            futures[future] = key

        # Collect results
        for future in as_completed(futures):
            key = futures[future]
            completed += 1

            try:
                result = future.result()
                bbox_results[key] = result

                if result.get("bbox_2d") is not None:
                    logger.debug(f"[BBox Annotator] [{completed}/{total_tasks}] ✓ {key}")
                else:
                    logger.warning(f"[BBox Annotator] [{completed}/{total_tasks}] ✗ {key}: {result.get('error', 'No bbox')}")
                    failed_tasks.append({
                        "key": key,
                        "reason": result.get("error", "No bbox found"),
                        "timestamp": datetime.now().isoformat()
                    })

            except Exception as e:
                completed += 1
                logger.error(f"[BBox Annotator] [{completed}/{total_tasks}] ✗ {key}: {e}")
                bbox_results[key] = {
                    "bbox_2d": None,
                    "confidence": 0.0,
                    "found": False,
                    "error": str(e)
                }
                failed_tasks.append({
                    "key": key,
                    "reason": str(e),
                    "timestamp": datetime.now().isoformat()
                })

            # Update progress
            state["bbox_annotation_progress"] = {
                "completed": completed,
                "total": total_tasks,
                "current_key": key
            }

    # Fill bbox_2d back to original extractions (🔑 Key step: ensure 1-to-1 mapping)
    logger.info("[BBox Annotator] Filling bbox_2d back to extractions...")
    fill_success = 0
    fill_failed = 0

    for bibcode, paper_data in raw_extractions.items():
        for idx, extraction in enumerate(paper_data["extractions"]):
            key = f"{bibcode}_{idx}"

            if key in bbox_results:
                result = bbox_results[key]
                extraction["bbox_2d"] = result.get("bbox_2d", None)

                if extraction["bbox_2d"] is not None:
                    fill_success += 1
                else:
                    fill_failed += 1
            else:
                # Should not happen
                logger.warning(f"[BBox Annotator] Missing result for {key}")
                extraction["bbox_2d"] = None
                fill_failed += 1

    # Update state
    state["raw_extractions"] = raw_extractions
    state["bbox_annotation_status"] = "completed"
    state["bbox_annotation_failed"] = failed_tasks

    state["bbox_annotation_progress"] = {
        "completed": total_tasks,
        "total": total_tasks,
        "current_key": "Completed"
    }

    logger.info(f"[BBox Annotator] Completed!")
    logger.info(f"[BBox Annotator]   Total tasks: {total_tasks}")
    logger.info(f"[BBox Annotator]   Success: {fill_success}")
    logger.info(f"[BBox Annotator]   Failed: {fill_failed}")

    if failed_tasks:
        logger.warning(f"[BBox Annotator]   Failed tasks sample (first 5):")
        for failed in failed_tasks[:5]:
            logger.warning(f"[BBox Annotator]     - {failed['key']}: {failed['reason']}")

    return state


def annotate_single_bbox(task: dict, target_entity: str) -> dict:
    """
    Annotate a single extraction record with bbox.

    Args:
        task: {
            "bibcode": "...",
            "index": 0,
            "page": 4,
            "image_path": "/path/to/page4.png",
            "extraction": {...}
        }
        target_entity: Target celestial object name

    Returns:
        {
            "bbox_2d": [...] or None,
            "confidence": float,
            "found": bool,
            "error": str or None
        }
    """
    bibcode = task["bibcode"]
    index = task["index"]
    image_path = task["image_path"]
    extraction = task["extraction"]

    logger.debug(f"[BBox Worker] Processing {bibcode} extraction {index}")

    # Load image
    try:
        images = image_cache.load_images([image_path])
        if not images or len(images) == 0:
            raise ValueError("Failed to load image")
        image = images[0]
    except Exception as e:
        logger.error(f"[BBox Worker] Failed to load image for {bibcode}_{index}: {e}")
        return {
            "bbox_2d": None,
            "confidence": 0.0,
            "found": False,
            "error": f"Failed to load image: {e}"
        }

    # Get max_retries from settings
    max_retries = getattr(settings, 'bbox_concurrency', type('obj', (object,), {
        'max_retries': 3
    })()).max_retries

    # Call qwen3.7-flash
    try:
        result = call_qwen_flash_bbox(
            image=image,
            extraction=extraction,
            target_entity=target_entity,
            max_retries=max_retries
        )
        return result

    except Exception as e:
        logger.error(f"[BBox Worker] Exception for {bibcode}_{index}: {e}")
        return {
            "bbox_2d": None,
            "confidence": 0.0,
            "found": False,
            "error": str(e)
        }
