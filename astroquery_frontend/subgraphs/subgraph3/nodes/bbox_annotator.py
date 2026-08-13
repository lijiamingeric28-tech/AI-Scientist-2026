"""BBox 标注节点（数据点级并发）。"""

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

    from events import emit_progress  # Web 事件埋点（离线 no-op）

    state["bbox_annotation_status"] = "running"

    # 构建任务列表（数据点级）
    tasks = []
    build_failed = []  # H-09: 任务构建失败的坏记录（不击穿节点）
    for bibcode, paper_data in raw_extractions.items():
        extractions = paper_data.get("extractions", [])
        for idx, extraction in enumerate(extractions):
            try:
                page = extraction.get("page")
                if page is None:
                    logger.warning(f"[BBox Annotator] Missing page for {bibcode} extraction {idx}")
                    continue

                # 获取该页的图片路径
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
                    "index": idx,  # [KEY] Array index for tracking
                    "page": page,
                    "image_path": image_path,
                    "extraction": extraction  # Full extraction data
                })
            except Exception as e:
                # H-09: 单条坏记录不击穿节点 — 记录后跳过
                logger.warning(f"[BBox Annotator] Bad extraction {bibcode} idx {idx}, skipped: {e}")
                build_failed.append({
                    "key": f"{bibcode}_{idx}",
                    "reason": str(e),
                    "timestamp": datetime.now().isoformat()
                })
                continue

    total_tasks = len(tasks)
    logger.info(f"[BBox Annotator] Total annotation tasks: {total_tasks}")

    if total_tasks == 0:
        logger.warning("[BBox Annotator] No tasks to process!")
        # M-15: 空任务早退路径补发 bbox 终止事件——前端子步骤②不再永久 waiting
        emit_progress(
            state.get("query_id", ""), "extraction", "bbox", "skipped",
            data={"success": 0, "failed": len(build_failed)},
        )
        state["bbox_annotation_status"] = "completed"
        state["bbox_annotation_failed"] = build_failed  # H-09: 坏记录仍上报
        return state

    # 结果存储：key = f"{bibcode}_{index}"
    bbox_results = {}
    failed_tasks = []
    completed = 0

    # 获取并发配置
    max_workers = getattr(settings, 'bbox_concurrency', type('obj', (object,), {
        'max_workers': 100,
        'max_retries': 3
    })()).max_workers

    logger.info(f"[BBox Annotator] Using max_workers={max_workers}")

    # 并发处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交全部任务
        futures = {}
        for task in tasks:
            key = f"{task['bibcode']}_{task['index']}"
            future = executor.submit(annotate_single_bbox, task, target_entity)
            futures[future] = key

        # 收集结果
        for future in as_completed(futures):
            key = futures[future]
            completed += 1

            try:
                result = future.result()
                bbox_results[key] = result

                if result.get("bbox_2d") is not None:
                    logger.debug(f"[BBox Annotator] [{completed}/{total_tasks}] [OK] {key}")
                else:
                    logger.warning(f"[BBox Annotator] [{completed}/{total_tasks}] [FAIL] {key}: {result.get('error', 'No bbox')}")
                    failed_tasks.append({
                        "key": key,
                        "reason": result.get("error", "No bbox found"),
                        "timestamp": datetime.now().isoformat()
                    })

            except Exception as e:
                # L2 fix: 删除重复自增 — completed 已在循环开头 +1, 此处再 +1 双计数
                logger.error(f"[BBox Annotator] [{completed}/{total_tasks}] [FAIL] {key}: {e}")
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

            # 更新进度
            state["bbox_annotation_progress"] = {
                "completed": completed,
                "total": total_tasks,
                "current_key": key
            }

            # Web 埋点：bbox 验证进度（前端卡 3 步骤②，current_key=bibcode_idx）
            emit_progress(
                state.get("query_id", ""), "extraction", "bbox", "running",
                progress={"completed": completed, "total": total_tasks, "current": key},
            )

    # Fill bbox_2d back to original extractions ([KEY] Key step: ensure 1-to-1 mapping)
    logger.info("[BBox Annotator] Filling bbox_2d back to extractions...")
    fill_success = 0
    fill_failed = 0

    for bibcode, paper_data in raw_extractions.items():
        for idx, extraction in enumerate(paper_data["extractions"]):
            key = f"{bibcode}_{idx}"

            # H-09: 非 dict 坏记录（构建期已跳过）在此同样跳过，防止击穿节点
            if not isinstance(extraction, dict):
                logger.warning(f"[BBox Annotator] Skipping non-dict extraction for {key}")
                continue

            if key in bbox_results:
                result = bbox_results[key]
                extraction["bbox_2d"] = result.get("bbox_2d", None)

                if extraction["bbox_2d"] is not None:
                    fill_success += 1
                else:
                    fill_failed += 1
            else:
                # 不应发生
                logger.warning(f"[BBox Annotator] Missing result for {key}")
                extraction["bbox_2d"] = None
                fill_failed += 1

    # 更新状态
    state["raw_extractions"] = raw_extractions
    state["bbox_annotation_status"] = "completed"
    # H-09: 任务构建失败 + 执行失败合并上报
    state["bbox_annotation_failed"] = build_failed + failed_tasks

    state["bbox_annotation_progress"] = {
        "completed": total_tasks,
        "total": total_tasks,
        "current_key": "Completed"
    }

    # Web 埋点：验证完成（前端卡 3 步骤②摘要 + 失败原因列表，契约 D6 事件带）
    emit_progress(
        state.get("query_id", ""), "extraction", "bbox", "completed",
        progress={"completed": total_tasks, "total": total_tasks, "current": None},
        data={
            "success": fill_success,
            "failed": fill_failed,
            "failures": [
                {"key": f.get("key", ""), "reason": f.get("reason", "")}
                for f in (build_failed + failed_tasks)
            ],
        },
    )

    logger.info("[BBox Annotator] Completed!")
    logger.info(f"[BBox Annotator]   Total tasks: {total_tasks}")
    logger.info(f"[BBox Annotator]   Success: {fill_success}")
    logger.info(f"[BBox Annotator]   Failed: {fill_failed}")

    if failed_tasks:
        logger.warning("[BBox Annotator]   Failed tasks sample (first 5):")
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

    # 加载图片
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

    # 从配置获取最大重试次数
    max_retries = getattr(settings, 'bbox_concurrency', type('obj', (object,), {
        'max_retries': 3
    })()).max_retries

    # 调用 qwen3.7-flash
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
