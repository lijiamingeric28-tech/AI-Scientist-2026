"""VLM batch extractor node (streaming version with JSON repair)."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from json_repair import repair_json
from typing import Dict, List
from ..schemas.state import ExtractionState
from ..utils.logger import get_logger
from ..utils.vlm_client import call_qwen_vlm, build_extraction_prompt
from ..utils.image_cache import image_cache
from ..config.settings import settings


logger = get_logger(__name__)


def vlm_batch_extractor(state: ExtractionState) -> ExtractionState:
    """
    VLM batch extraction node (streaming version).

    Steps:
    1. Prepare extraction task list with image paths
    2. Call Qwen3.7-Plus concurrently (max_workers=15)
    3. Load images on-demand for each task (reduces memory usage)
    4. Show progress
    5. Record failed papers
    6. Update state

    Args:
        state: Current extraction state

    Returns:
        Updated state with raw_extractions and extraction_failed
    """
    paper_image_paths = state["paper_image_paths"]
    target_entity = state["target_entity"]
    requested_properties = state.get("requested_properties", [])
    property_spec = state.get("property_spec", [])
    query_id = state["query_id"]

    logger.info(f"[VLM Extractor] Query ID: {query_id}")
    logger.info(f"[VLM Extractor] Extracting from {len(paper_image_paths)} papers (streaming mode)...")
    logger.debug(f"[VLM Extractor]   Target entity: {target_entity}")
    logger.debug(f"[VLM Extractor]   Requested properties: {requested_properties}")
    logger.debug(f"[VLM Extractor]   PropertySpec: {len(property_spec)} 个标准性质")
    logger.debug(f"[VLM Extractor]   Concurrency: {settings.concurrency.max_workers}")

    state["extraction_status"] = "running"

    # Prepare task list with image paths (not loaded yet)
    tasks = []
    for bibcode, image_paths in paper_image_paths.items():
        tasks.append({
            "bibcode": bibcode,
            "image_paths": image_paths,  # Paths, not images
            "target_entity": target_entity,
            "requested_properties": requested_properties,
            "property_spec": property_spec,  # 新增
        })

    raw_extractions = {}
    extraction_failed = []

    total = len(tasks)
    completed = 0

    # Concurrent processing (max_workers from settings, default 15)
    with ThreadPoolExecutor(max_workers=settings.concurrency.max_workers) as executor:
        futures = {executor.submit(process_single_paper_vlm, task): task for task in tasks}

        for future in as_completed(futures):
            task = futures[future]
            bibcode = task["bibcode"]

            try:
                result = future.result()

                completed += 1

                # Update progress
                state["extraction_progress"] = {
                    "completed": completed,
                    "total": total,
                    "current_paper": bibcode
                }

                if result["success"]:
                    raw_extractions[bibcode] = result["data"]
                    logger.info(f"[VLM Extractor] [{completed}/{total}] ✓ {bibcode}: {len(result['data']['extractions'])} records")
                else:
                    extraction_failed.append({
                        "bibcode": bibcode,
                        "reason": result.get("error", "Unknown error"),
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.warning(f"[VLM Extractor] [{completed}/{total}] ✗ {bibcode}: {result.get('error')}")

            except Exception as e:
                completed += 1
                extraction_failed.append({
                    "bibcode": bibcode,
                    "reason": str(e),
                    "timestamp": datetime.now().isoformat()
                })
                logger.error(f"[VLM Extractor] [{completed}/{total}] ✗ {bibcode}: {e}")

    # Update state
    state["extraction_status"] = "completed"
    state["raw_extractions"] = raw_extractions
    state["extraction_failed"] = extraction_failed

    state["extraction_progress"] = {
        "completed": total,
        "total": total,
        "current_paper": "Completed"
    }

    logger.info(f"[VLM Extractor] Completed!")
    logger.info(f"[VLM Extractor]   Success: {len(raw_extractions)}")
    logger.info(f"[VLM Extractor]   Failed: {len(extraction_failed)}")

    if extraction_failed:
        logger.warning(f"[VLM Extractor]   Failed papers:")
        for failed in extraction_failed:
            logger.warning(f"[VLM Extractor]     - {failed['bibcode']}: {failed['reason']}")

    return state


def process_single_paper_vlm(task: dict) -> dict:
    """
    Process a single paper (VLM extraction, streaming version).

    Args:
        task: {
            "bibcode": "...",
            "image_paths": ["/path/to/page1.png", ...],
            "target_entity": "M31",
            "requested_properties": ["distance", "metallicity"]
        }

    Returns:
        {
            "success": True/False,
            "data": {"extractions": [...]},
            "error": "..."
        }
    """
    bibcode = task["bibcode"]
    image_paths = task["image_paths"]
    target_entity = task["target_entity"]
    requested_properties = task["requested_properties"]
    property_spec = task.get("property_spec", [])

    logger.debug(f"[VLM Worker] Processing {bibcode} ({len(image_paths)} pages)")

    # Load images on-demand (only for this task)
    try:
        images = image_cache.load_images(image_paths)
        logger.debug(f"[VLM Worker] Loaded {len(images)} images from cache for {bibcode}")
    except Exception as e:
        logger.error(f"[VLM Worker] Failed to load images for {bibcode}: {e}")
        return {
            "success": False,
            "data": None,
            "error": f"Failed to load images: {e}"
        }

    max_retries = settings.quality.max_retries

    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n{'='*60}")
            print(f"📄 处理论文: {bibcode} (attempt {attempt}/{max_retries})")
            print(f"   图片数: {len(images)} 页")
            print(f"   目标天体: {target_entity}")
            print(f"   提取性质: {requested_properties}")
            print(f"{'='*60}")

            # Build prompt with explicit page mapping
            prompt = build_extraction_prompt(
                target_entity,
                requested_properties,
                num_images=len(images),
                property_spec=property_spec
            )

            # Call Qwen3.7-Plus
            print(f"🤖 正在调用VLM分析论文...")
            raw_result = call_qwen_vlm(images, prompt)

            # Debug: Check for truncation
            if len(raw_result) >= settings.vlm.max_tokens * 4:  # Rough estimate: 1 token ≈ 4 chars
                logger.warning(
                    f"[VLM Worker] {bibcode} - Response length ({len(raw_result)} chars) "
                    f"approaches max_tokens limit ({settings.vlm.max_tokens}). Possible truncation!"
                )
                print(f"⚠️  响应长度接近限制，可能被截断！")

            print(f"📊 解析JSON响应...")

            # Try to parse JSON directly
            try:
                data = json.loads(raw_result)
                logger.debug(f"[VLM Worker] {bibcode} - JSON parsed successfully (attempt {attempt})")
                print(f"✓ JSON解析成功")

                # Handle DashScope API's response format
                # The API may return: [{"text": "actual_json_string"}]
                if isinstance(data, list) and len(data) > 0:
                    logger.debug(f"[VLM Worker] {bibcode} - JSON is a list with {len(data)} items")
                    print(f"   检测到list格式，提取内层JSON...")

                    # Check if first item has 'text' field
                    if isinstance(data[0], dict) and "text" in data[0]:
                        logger.debug(f"[VLM Worker] {bibcode} - Extracting JSON from 'text' field")
                        text_content = data[0]["text"]
                        print(f"   从'text'字段提取JSON...")

                        # Parse the inner JSON string
                        try:
                            data = json.loads(text_content)
                            logger.debug(f"[VLM Worker] {bibcode} - Successfully parsed inner JSON from 'text' field")
                            print(f"   ✓ 内层JSON解析成功")
                        except json.JSONDecodeError as inner_error:
                            logger.warning(f"[VLM Worker] {bibcode} - Failed to parse inner JSON: {inner_error}")
                            print(f"   ❌ 内层JSON解析失败，尝试修复...")
                            # Try json_repair on the text content
                            try:
                                repaired_text = repair_json(text_content)
                                data = json.loads(repaired_text)
                                logger.info(f"[VLM Worker] {bibcode} - Inner JSON repaired successfully!")
                                print(f"   ✓ JSON修复成功！")
                            except Exception as repair_error:
                                logger.warning(f"[VLM Worker] {bibcode} - Inner JSON repair failed: {repair_error}")
                                print(f"   ❌ JSON修复失败: {repair_error}")
                                if attempt < max_retries:
                                    continue
                                else:
                                    return {
                                        "success": False,
                                        "data": None,
                                        "error": f"Failed to parse inner JSON after {max_retries} attempts"
                                    }

            except json.JSONDecodeError as json_error:
                # Try JSON repair first
                logger.warning(
                    f"[VLM Worker] {bibcode} - JSON parse failed (attempt {attempt}/{max_retries}), "
                    f"trying json_repair: {json_error}"
                )
                print(f"❌ JSON解析失败，尝试自动修复...")

                try:
                    repaired_result = repair_json(raw_result)
                    data = json.loads(repaired_result)
                    logger.info(f"[VLM Worker] {bibcode} - JSON repaired successfully!")
                    print(f"✓ JSON修复成功！")

                except Exception as repair_error:
                    logger.warning(
                        f"[VLM Worker] {bibcode} - json_repair failed: {repair_error}"
                    )
                    print(f"❌ JSON修复失败: {repair_error}")

                    if attempt < max_retries:
                        logger.info(f"[VLM Worker] {bibcode} - Retrying VLM call (attempt {attempt + 1}/{max_retries})")
                        print(f"🔄 将重新调用VLM...")
                        continue  # Retry by calling VLM again
                    else:
                        return {
                            "success": False,
                            "data": None,
                            "error": f"JSON parse error after {max_retries} attempts and repair failed: {json_error}"
                        }

            # Validate format
            if "extractions" not in data:
                raise ValueError("Invalid JSON format: missing 'extractions' field")

            extractions = data.get("extractions", [])
            logger.debug(f"[VLM Worker] {bibcode} extraction successful: {len(extractions)} records")
            print(f"✅ 提取成功！共 {len(extractions)} 条记录")

            return {
                "success": True,
                "data": data,
                "error": None
            }

        except json.JSONDecodeError as e:
            # Should not reach here (already handled above)
            error_msg = f"JSON parse error (attempt {attempt}/{max_retries}): {e}"
            logger.warning(f"[VLM Worker] {bibcode} - {error_msg}")

            if attempt == max_retries:
                return {
                    "success": False,
                    "data": None,
                    "error": f"JSON parse error after {max_retries} attempts: {e}"
                }
            # Continue to next retry

        except Exception as e:
            error_msg = f"Unexpected error (attempt {attempt}/{max_retries}): {e}"
            logger.warning(f"[VLM Worker] {bibcode} - {error_msg}")

            if attempt == max_retries:
                return {
                    "success": False,
                    "data": None,
                    "error": str(e)
                }
            # Continue to next retry

    # Should not reach here
    return {
        "success": False,
        "data": None,
        "error": "Max retries exceeded"
    }
