"""结果构建节点。"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from PIL import Image

from astroquery_ai.config import PROJECT_ROOT

from ..schemas.state import ExtractionState
from ..utils.logger import get_logger
from ..utils.image_cache import image_cache
from ..config.settings import settings


logger = get_logger(__name__)

# 2026-08-24: bbox 溯源页图持久化 — 带 bbox 记录引用的论文页图在临时缓存
# 清理前落盘, 供前端在论文页上画框展示原始出处
_SOURCE_PAGES_OUTPUT_ROOT = PROJECT_ROOT / "output" / "figures"
_SOURCE_PAGES_MAX_WIDTH = 1200  # 页图缩限宽度 (px), 控制体积


def _safe_name(s: str) -> str:
    """文件名安全化（与 figure_extractor 保持一致: 替换 / : 空格）"""
    return s.replace("/", "_").replace(":", "_").replace(" ", "_")


def persist_referenced_pages(state: ExtractionState, paper_records: list) -> int:
    """把带 bbox 记录引用的 (bibcode, page) 页图持久化到 output/figures。

    目标路径: output/figures/{query_id}/source_pages/{bibcode}/page_{N}.png
    (与 /static/figures 静态挂载同根, 前端直接可访问; 失败不阻断, 仅记日志)
    """
    paper_image_paths = state.get("paper_image_paths", {}) or {}
    if not paper_image_paths or not paper_records:
        return 0

    query_id = state.get("query_id", "")
    refs = set()
    for rec in paper_records:
        prov = rec.get("provenance") or {}
        page = prov.get("page")
        sid = rec.get("source_id")
        if page is None or not sid:
            continue
        try:
            refs.add((sid, int(page)))
        except (TypeError, ValueError):
            continue

    saved = 0
    for bibcode, page in sorted(refs):
        paths = paper_image_paths.get(bibcode) or []
        if page < 1 or page > len(paths):
            continue
        src = Path(paths[page - 1])
        if not src.exists():
            logger.warning(f"[Result Builder] Source page missing: {bibcode} p{page}")
            continue
        try:
            with Image.open(src) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                if img.width > _SOURCE_PAGES_MAX_WIDTH:
                    img = img.resize((
                        _SOURCE_PAGES_MAX_WIDTH,
                        int(img.height * _SOURCE_PAGES_MAX_WIDTH / img.width),
                    ))
                out_dir = _SOURCE_PAGES_OUTPUT_ROOT / query_id / "source_pages" / _safe_name(bibcode)
                out_dir.mkdir(parents=True, exist_ok=True)
                img.save(out_dir / f"page_{page}.png", format="PNG")
            saved += 1
        except Exception as e:  # noqa: BLE001 — 单页失败不阻断提取链
            logger.warning(f"[Result Builder] Persist page failed {bibcode} p{page}: {e}")

    logger.info(f"[Result Builder] Persisted {saved} source page images (bbox tracing)")
    return saved


def result_builder(state: ExtractionState) -> ExtractionState:
    """
    Result builder node.

    Steps:
    1. Iterate through all VLM extraction results
    2. Build paper records with proper data types
    3. Generate record_id and trace_id
    4. Filter low confidence results
    5. Build final paper_records

    Args:
        state: Current extraction state

    Returns:
        Updated state with paper_records and processing_summary
    """
    raw_extractions = state["raw_extractions"]
    target_entity = state["target_entity"]
    entity_type = state.get("entity_type") or "Unknown"
    query_id = state["query_id"]

    # V2.5: VLM 输出白名单强制校验 — field_name 必须在 PropertySpec 内。
    # 提示词的白名单约束是软约束，VLM 仍可能输出白名单外字段（如 M31 场景
    # 的 dist_modulus），此处做硬校验，白名单外字段直接丢弃。
    property_spec = state.get("property_spec", []) or []
    whitelist = {p.get("property_id") for p in property_spec if isinstance(p, dict)}

    logger.info(f"[Result Builder] Query ID: {query_id}")
    logger.info(f"[Result Builder] Building records from {len(raw_extractions)} papers...")

    paper_records = []
    total_records = 0
    filtered_records = 0
    dropped_bbox = 0

    # doc_index 为"文档序号"（第几篇论文），用于 trace_id；
    # 与 record_index（论文内记录序号，用于 record_id）是两个不同的计数。
    for doc_index, (bibcode, extraction_data) in enumerate(raw_extractions.items()):
        extractions = extraction_data.get("extractions", [])

        logger.debug(f"[Result Builder]   Processing {bibcode} (doc{doc_index}): "
                     f"{len(extractions)} raw extractions")

        for idx, ext in enumerate(extractions):
            try:
                # 过滤低置信度结果
                confidence = float(ext.get("confidence", 0.0))
                if confidence < settings.quality.min_confidence:
                    logger.debug(f"[Result Builder]     Skipping low confidence record: "
                               f"{bibcode} - {ext.get('field_name')} (confidence={confidence:.2f})")
                    filtered_records += 1
                    continue

                # bbox 校验失败 → 直接丢弃该记录，不流向下游（不再用默认框伪造溯源）
                bbox_raw = ext.get("bbox_2d") or ext.get("bbox")
                bbox_validated = validate_and_convert_bbox(bbox_raw)
                if bbox_validated is None:
                    logger.warning(f"[Result Builder]     Dropping record (invalid bbox): "
                                   f"{bibcode} - {ext.get('field_name')} (bbox={bbox_raw})")
                    dropped_bbox += 1
                    continue

                # L3 fix: field_value 为 None/空 → 跳过该记录
                # (旧逻辑 str(None) 产出 "None" 字符串污染下游数值解析)
                fv = ext.get("field_value")
                if fv is None or (isinstance(fv, str) and not fv.strip()):
                    logger.warning(f"[Result Builder]     Dropping record (empty value): "
                                   f"{bibcode} - {ext.get('field_name')}")
                    dropped_bbox += 1  # 复用 dropped 计数槽位
                    continue

                # M-27 fix: field_name 缺失/为空 → 丢弃该条
                # (与 field_value 对齐，防 str(None) 产出 "None" 脏字段与脏 record_id)
                fn = ext.get("field_name")
                if fn is None or (isinstance(fn, str) and not fn.strip()):
                    logger.warning(f"[Result Builder]     Dropping record (empty field_name): "
                                   f"{bibcode} - idx {idx}")
                    dropped_bbox += 1
                    continue

                # V2.5: 白名单强制校验 — field_name 必须在 property_spec 内
                # (仅当存在白名单时生效；无 property_spec 的降级场景不拦截)
                if whitelist and fn not in whitelist:
                    logger.warning(f"[Result Builder]     Dropping record (field_name not in whitelist): "
                                   f"{bibcode} - {fn!r}")
                    filtered_records += 1
                    continue

                # 构建记录
                record = build_paper_record(
                    bibcode=bibcode,
                    extraction=ext,
                    target_entity=target_entity,
                    entity_type=entity_type,
                    record_index=idx,
                    doc_index=doc_index,
                    bbox_validated=bbox_validated,
                )

                paper_records.append(record)
                total_records += 1

            except Exception as e:
                logger.warning(f"[Result Builder]     Failed to build record for {bibcode}: {e}")
                continue

        logger.debug(f"[Result Builder]   {bibcode}: {len([r for r in paper_records if r['source_id'] == bibcode])} records built")

    # Statistics (B10 fix: 统计三种失败源)
    conversion_failed = state.get("conversion_failed", []) or []
    extraction_failed = state.get("extraction_failed", []) or []
    bbox_failed = state.get("bbox_annotation_failed", []) or []

    processing_summary = {
        "total_papers": len(state["download_paths"]),
        "processed_papers": len(raw_extractions),
        "failed_papers": len(conversion_failed) + len(extraction_failed),
        "total_records_extracted": total_records,
        "filtered_low_confidence": filtered_records,
        "dropped_invalid_bbox": dropped_bbox
    }

    # B10 fix: 将三套失败列表合并为 error_log 上浮到主图
    error_log = []
    for f in conversion_failed:
        error_log.append({
            "node": "pdf_converter",
            "error": f"{f.get('bibcode', '?')}: {f.get('reason', 'unknown')}",
            "timestamp": datetime.now().isoformat(),
        })
    for f in extraction_failed:
        error_log.append({
            "node": "vlm_extractor",
            "error": f"{f.get('bibcode', '?')}: {f.get('reason', 'unknown')}",
            "timestamp": datetime.now().isoformat(),
        })
    for f in bbox_failed:
        error_log.append({
            "node": "bbox_annotator",
            "error": f"{f.get('key', '?')}: {f.get('reason', 'unknown')}",
            "timestamp": f.get("timestamp") or datetime.now().isoformat(),
        })

    # Web 埋点：卡 3 步骤④ 总结（sources/records 数字，前端拼）
    try:
        from events import emit_progress
        emit_progress(
            state.get("query_id", ""), "extraction", "summary", "completed",
            data={
                "sources": len(state.get("paper_sources", [])),
                "records": total_records,
            },
        )
    except Exception:
        pass  # 埋点失败不影响流程

    # 更新状态
    state["paper_records"] = paper_records
    state["processing_summary"] = processing_summary
    if error_log:
        state["error_log"] = error_log

    # 2026-08-24: bbox 溯源页图落盘 — 必须在 H-10 清理临时缓存之前执行
    # (此前临时页图随清理即丢失, 前端只能看到 bbox 数字坐标)
    persist_referenced_pages(state, paper_records)

    # H-10: 清理本次查询的临时页图 — result_builder 是提取链最后节点，
    # 图片数据已写入 paper_records/figure_evidence，按论文逐一删除缓存目录
    cached_bibcodes = set(raw_extractions.keys()) | set(state.get("paper_image_paths", {}).keys())
    for bibcode in cached_bibcodes:
        try:
            image_cache.cleanup(bibcode)
        except Exception as e:
            logger.warning(f"[Result Builder] Cache cleanup failed for {bibcode}: {e}")

    logger.info("[Result Builder] Completed!")
    logger.info(f"[Result Builder]   Papers processed: {processing_summary['processed_papers']}")
    logger.info(f"[Result Builder]   Records extracted: {processing_summary['total_records_extracted']}")
    logger.info(f"[Result Builder]   Filtered (low confidence): {processing_summary['filtered_low_confidence']}")

    return state


def build_paper_record(
    bibcode: str,
    extraction: dict,
    target_entity: str,
    record_index: int,
    entity_type: str = "Unknown",
    doc_index: int = 0,
    bbox_validated: List = None
) -> dict:
    """
    Build a single paper record from VLM extraction result.

    Args:
        bibcode: Paper's bibcode (source_id)
        extraction: Single VLM extraction data
        target_entity: Target celestial object name
        record_index: Record index within this paper (used for record_id)
        entity_type: SIMBAD otype (e.g., "AGN", "GlC")
        doc_index: Document ordinal across this run (used for trace_id)
        bbox_validated: 已通过校验的 bbox（调用方 pre-check 后传入）

    Returns:
        Record conforming to downstream schema

    Key processing:
    1. BBox: NO conversion needed (already [xmin, ymin, xmax, ymax])
    2. Data type conversion: ensure int/str types are correct
    3. Generate record_id and trace_id
    """
    # 提取字段
    page = extraction.get("page")
    field_name = extraction.get("field_name")
    field_value = extraction.get("field_value")
    field_unit = extraction.get("field_unit", "")
    context_snippet = extraction.get("context_snippet", "")
    measurement_method = extraction.get("measurement_method", "")
    condition_tags = extraction.get("condition_tags", [])
    extraction_method = extraction.get("extraction_method", "text")
    confidence = extraction.get("confidence", 0.0)

    # ===== 键：BBox =====
    # 调用方已 pre-check（无效 bbox 的记录在循环中丢弃），此处使用传入的校验结果
    if bbox_validated is None:
        raise ValueError("bbox 校验失败（调用方应已丢弃该记录）")

    # ===== 键：数据类型转换 =====
    page_int = int(page)  # Ensure integer
    # M-27: (field_name or "") 防御 — 调用方已判空丢弃，此处兜底防 "None" 字符串
    field_name_str = (field_name or "").strip()
    field_value_str = str(field_value).strip()
    field_unit_str = str(field_unit).strip() if field_unit else ""

    # 生成 record_id（格式：bibcode_entity_fieldname_index）
    # 替换特殊字符
    safe_bibcode = bibcode.replace("/", "_").replace(":", "_")
    safe_entity = target_entity.replace(" ", "_")
    safe_field = field_name_str.replace(" ", "_").replace("/", "_")

    record_id = f"{safe_bibcode}_{safe_entity}_{safe_field}_{record_index}"

    # Generate trace_id (format: doc{文档序号}_p{页码})
    # 注意：用 doc_index（第几篇论文），不是 record_index（论文内记录序号）
    trace_id = f"doc{doc_index}_p{page_int}"

    # 构建记录
    record = {
        "record_id": record_id,                          # ✅ string
        "source_id": bibcode,                            # ✅ string
        "entity_type": entity_type,                      # ✅ string (SIMBAD otype)
        "entity_name": target_entity,                    # ✅ string
        "field_name": field_name_str,                    # ✅ string
        "field_value": field_value_str,                  # ✅ string
        "field_unit": field_unit_str,                    # ✅ string
        "trace_id": trace_id,                            # ✅ string
        "provenance": {
            "page": page_int,                            # ✅ integer
            "bbox": bbox_validated,                      # ✅ integer array [xmin, ymin, xmax, ymax]
            "bbox_coord_system": "normalized_1000",      # ✅ 显式标注坐标系（0-1000 归一化）
            "bbox_source": (extraction.get("bbox_source") or ""),  # 2026-08-24: vector/vlm_crop/fallback
        },
        "extraction_method": f"vlm_{extraction_method}", # ✅ string
        "extraction_confidence": float(confidence),      # ✅ float
        "context_snippet": str(context_snippet),         # ✅ string
        "measurement_method": str(measurement_method),   # ✅ string
        "condition_tags": condition_tags if isinstance(condition_tags, list) else []  # ✅ list
    }

    logger.debug(f"[Result Builder]       Built record: {record_id}")

    return record


def validate_and_convert_bbox(bbox_raw) -> Optional[List[int]]:
    """
    Validate and convert BBox coordinates.

    NOTE: Qwen VLM outputs [xmin, ymin, xmax, ymin] format (0-1000 range).
    NO transformation needed - just validate and convert to integers.

    Input: [xmin, ymin, xmax, ymax] (0-1000, may be floats)
    Output: [xmin, ymin, xmax, ymax] (0-1000, integers) 或 None（校验失败）

    校验失败返回 None——调用方应丢弃该记录，不再使用默认框伪造溯源。
    """
    if not bbox_raw or len(bbox_raw) != 4:
        logger.warning(f"Invalid bbox format (not 4 elements): {bbox_raw}")
        return None

    try:
        bbox_int = [int(round(coord)) for coord in bbox_raw]
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert bbox {bbox_raw} to integers: {e}")
        return None

    # 范围校验：任一坐标越界即失败（不允许部分越界）
    for coord in bbox_int:
        if coord < 0 or coord > 1000:
            logger.warning(f"BBox coordinate out of range [0, 1000]: {coord} in {bbox_raw}")
            return None

    # 几何校验：x_min < x_max 且 y_min < y_max
    if bbox_int[0] >= bbox_int[2] or bbox_int[1] >= bbox_int[3]:
        logger.warning(f"BBox 几何非法 (x_min>=x_max 或 y_min>=y_max): {bbox_raw}")
        return None

    return bbox_int
