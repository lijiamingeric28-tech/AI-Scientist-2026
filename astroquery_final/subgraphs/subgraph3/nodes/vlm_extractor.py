"""VLM 批量提取节点（流式版本，带 JSON 修复）。"""

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
    VLM 批量提取节点（流式版本）。

    步骤：
    1. 构建带图片路径的提取任务列表
    2. 并发调用 Qwen3.7-Plus（max_workers=15）
    3. 每个任务按需加载图片（降低内存占用）
    4. 展示进度
    5. 记录失败论文
    6. 更新状态

    Args:
        state: 当前提取状态

    Returns:
        更新后的状态（raw_extractions / extraction_failed）
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

    # 论文级性质子集（2026-08-11）：每篇论文只提取其 ADS 命中的性质（单一性质提取），
    # 无标记（手动上传/单查询回退）→ 全量 spec 兜底
    pids_by_bibcode = {}
    for p in state.get("download_paths", []) or []:
        pids_by_bibcode[p.get("bibcode", "")] = p.get("property_ids", []) or []

    # 构建任务列表（只带路径，不加载图片）
    tasks = []
    for bibcode, image_paths in paper_image_paths.items():
        paper_pids = pids_by_bibcode.get(bibcode, [])
        paper_spec = (
            [p for p in property_spec if p["property_id"] in paper_pids]
            or property_spec
        )
        if paper_pids and len(paper_spec) != len(paper_pids):
            logger.debug(
                f"[VLM Extractor] {bibcode}: 性质交集 {len(paper_spec)}/{len(paper_pids)}"
            )
        tasks.append({
            "bibcode": bibcode,
            "image_paths": image_paths,  # 路径而非图片对象
            "target_entity": target_entity,
            "requested_properties": requested_properties,
            "property_spec": paper_spec,  # 论文级子集（无标记 → 全量）
        })

    raw_extractions = {}
    extraction_failed = []

    total = len(tasks)
    completed = 0

    # 并发处理（max_workers 来自配置，默认 15）
    with ThreadPoolExecutor(max_workers=settings.concurrency.max_workers) as executor:
        futures = {executor.submit(process_single_paper_vlm, task): task for task in tasks}

        for future in as_completed(futures):
            task = futures[future]
            bibcode = task["bibcode"]

            try:
                result = future.result()

                completed += 1

                # 更新进度
                state["extraction_progress"] = {
                    "completed": completed,
                    "total": total,
                    "current_paper": bibcode
                }

                if result["success"]:
                    raw_extractions[bibcode] = result["data"]
                    logger.info(f"[VLM Extractor] [{completed}/{total}] [OK] {bibcode}: {len(result['data']['extractions'])} records")
                else:
                    extraction_failed.append({
                        "bibcode": bibcode,
                        "reason": result.get("error", "Unknown error"),
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.warning(f"[VLM Extractor] [{completed}/{total}] [FAIL] {bibcode}: {result.get('error')}")

            except Exception as e:
                completed += 1
                extraction_failed.append({
                    "bibcode": bibcode,
                    "reason": str(e),
                    "timestamp": datetime.now().isoformat()
                })
                logger.error(f"[VLM Extractor] [{completed}/{total}] [FAIL] {bibcode}: {e}")

    # 更新状态
    state["extraction_status"] = "completed"
    state["raw_extractions"] = raw_extractions
    state["extraction_failed"] = extraction_failed

    state["extraction_progress"] = {
        "completed": total,
        "total": total,
        "current_paper": "Completed"
    }

    logger.info("[VLM Extractor] Completed!")
    logger.info(f"[VLM Extractor]   Success: {len(raw_extractions)}")
    logger.info(f"[VLM Extractor]   Failed: {len(extraction_failed)}")

    if extraction_failed:
        logger.warning("[VLM Extractor]   Failed papers:")
        for failed in extraction_failed:
            logger.warning(f"[VLM Extractor]     - {failed['bibcode']}: {failed['reason']}")

    return state


def process_single_paper_vlm(task: dict) -> dict:
    """
    处理单篇论文（VLM 提取，流式版本）。

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

    # 按需加载图片（仅本任务）
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
            print(f"[PDF] 处理论文: {bibcode} (attempt {attempt}/{max_retries})")
            print(f"   图片数: {len(images)} 页")
            print(f"   目标天体: {target_entity}")
            print(f"   提取性质: {requested_properties}")
            print(f"{'='*60}")

            # 构建带显式页码映射的 prompt
            prompt = build_extraction_prompt(
                target_entity,
                requested_properties,
                num_images=len(images),
                property_spec=property_spec
            )

            # 调用 Qwen3.7-Plus
            print("[AI] 正在调用VLM分析论文...")
            raw_result = call_qwen_vlm(images, prompt)

            # 调试：检查是否截断
            if len(raw_result) >= settings.vlm.max_tokens * 4:  # Rough estimate: 1 token ≈ 4 chars
                logger.warning(
                    f"[VLM Worker] {bibcode} - Response length ({len(raw_result)} chars) "
                    f"approaches max_tokens limit ({settings.vlm.max_tokens}). Possible truncation!"
                )
                print("⚠  响应长度接近限制，可能被截断！")

            print("[CHART] 解析JSON响应...")

            # 直接尝试解析 JSON
            try:
                data = json.loads(raw_result)
                logger.debug(f"[VLM Worker] {bibcode} - JSON parsed successfully (attempt {attempt})")
                print("[OK] JSON解析成功")

                # 处理 DashScope API 的响应格式
                # API 可能返回：[{"text": "实际JSON字符串"}]
                if isinstance(data, list) and len(data) > 0:
                    logger.debug(f"[VLM Worker] {bibcode} - JSON is a list with {len(data)} items")
                    print("   检测到list格式，提取内层JSON...")

                    # Check if first item has 'text' field
                    if isinstance(data[0], dict) and "text" in data[0]:
                        logger.debug(f"[VLM Worker] {bibcode} - Extracting JSON from 'text' field")
                        text_content = data[0]["text"]
                        print("   从'text'字段提取JSON...")

                        # Parse the inner JSON string
                        try:
                            data = json.loads(text_content)
                            logger.debug(f"[VLM Worker] {bibcode} - Successfully parsed inner JSON from 'text' field")
                            print("   [OK] 内层JSON解析成功")
                        except json.JSONDecodeError as inner_error:
                            logger.warning(f"[VLM Worker] {bibcode} - Failed to parse inner JSON: {inner_error}")
                            print("   ❌ 内层JSON解析失败，尝试修复...")
                            # Try json_repair on the text content
                            try:
                                repaired_text = repair_json(text_content)
                                data = json.loads(repaired_text)
                                logger.info(f"[VLM Worker] {bibcode} - Inner JSON repaired successfully!")
                                print("   [OK] JSON修复成功！")
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
                print("❌ JSON解析失败，尝试自动修复...")

                try:
                    repaired_result = repair_json(raw_result)
                    data = json.loads(repaired_result)
                    logger.info(f"[VLM Worker] {bibcode} - JSON repaired successfully!")
                    print("[OK] JSON修复成功！")

                except Exception as repair_error:
                    logger.warning(
                        f"[VLM Worker] {bibcode} - json_repair failed: {repair_error}"
                    )
                    print(f"❌ JSON修复失败: {repair_error}")

                    if attempt < max_retries:
                        logger.info(f"[VLM Worker] {bibcode} - Retrying VLM call (attempt {attempt + 1}/{max_retries})")
                        print("[RETRY] 将重新调用VLM...")
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
            # H-09: 出口逐条归一化 — extractions 非 list 判该论文失败；
            # page 转 int 失败/缺失丢弃该条（防 bbox 节点整篇崩溃）
            if not isinstance(extractions, list):
                logger.warning(
                    f"[VLM Worker] {bibcode} - extractions 非 list ({type(extractions).__name__}), 判论文失败"
                )
                return {
                    "success": False,
                    "data": None,
                    "error": f"extractions 非 list: {type(extractions).__name__}"
                }

            normalized = []
            for ext in extractions:
                if not isinstance(ext, dict):
                    logger.warning(f"[VLM Worker] {bibcode} - 非法 extraction 类型 {type(ext).__name__}, 丢弃该条")
                    continue
                try:
                    ext["page"] = int(ext.get("page"))
                except (TypeError, ValueError):
                    logger.warning(f"[VLM Worker] {bibcode} - page 无法转 int: {ext.get('page')!r}, 丢弃该条")
                    continue
                normalized.append(ext)
            data["extractions"] = normalized
            extractions = normalized

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
