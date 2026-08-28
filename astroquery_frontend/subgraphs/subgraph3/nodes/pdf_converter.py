"""PDF batch converter node (streaming version)."""

from datetime import datetime
from ..schemas.state import ExtractionState
from ..utils.logger import get_logger
from ..utils.pdf_utils import pdf_to_images
from ..utils.image_cache import image_cache
from ..config.settings import settings


logger = get_logger(__name__)


def pdf_batch_converter(state: ExtractionState) -> ExtractionState:
    """
    PDF batch conversion node (streaming version).

    Steps:
    1. Iterate through all downloaded PDFs
    2. Convert each PDF to an image sequence
    3. Save images to disk (not memory) for streaming processing
    4. Record image file paths instead of Image objects
    5. Record conversion failures

    This approach dramatically reduces memory usage for large batches.

    Args:
        state: Current extraction state

    Returns:
        Updated state with paper_image_paths and conversion_failed
    """
    download_paths = state["download_paths"]
    query_id = state["query_id"]

    logger.info(f"[PDF Converter] Query ID: {query_id}")
    logger.info(f"[PDF Converter] Converting {len(download_paths)} PDFs to images (streaming mode)...")

    # M-13: Web 事件埋点（离线 no-op）—— 多篇大 PDF 转换耗时，前端卡3 步骤① paper 需进度
    from events import emit_progress

    state["conversion_status"] = "running"

    paper_image_paths = {}
    conversion_failed = []

    total = len(download_paths)
    for idx, paper_info in enumerate(download_paths, 1):
        bibcode = paper_info["bibcode"]
        pdf_path = paper_info["local_path"]

        logger.info(f"[PDF Converter] [{idx}/{total}] Converting {bibcode}...")
        logger.debug(f"[PDF Converter]   PDF path: {pdf_path}")

        try:
            # Convert PDF to images (in memory)
            # L-08: 显式透传配置 DPI（原为 pdf_to_images 默认值 150，配置恒不生效）
            images = pdf_to_images(pdf_path, dpi=settings.pdf.dpi)

            # Save images to disk and get paths
            image_paths = image_cache.save_images(bibcode, images)
            paper_image_paths[bibcode] = image_paths

            logger.info(f"[PDF Converter]   [OK] Success: {len(images)} pages converted and cached")
            logger.debug(f"[PDF Converter]   Cache paths: {len(image_paths)} files")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[PDF Converter]   [FAIL] Failed: {error_msg}")
            conversion_failed.append({
                "bibcode": bibcode,
                "pdf_path": pdf_path,
                "reason": error_msg,
                "timestamp": datetime.now().isoformat()
            })

        # M-13: 每篇转换完成（含失败）即报进度
        # 2026-08-27: data.phase='convert' —— 前端卡3 步骤①"论文提取"分段展示：
        # pdf→图片 与 VLM 文本提取各一段（此前两节点共用 step='paper' 跑两遍，
        # 用户误判"已完成"；旧任务事件无该字段 → 前端按单段降级）
        emit_progress(
            query_id, "extraction", "paper", "running",
            progress={"completed": idx, "total": total, "current": bibcode},
            data={"phase": "convert"},
        )

    # Update state
    state["conversion_status"] = "completed"
    state["paper_image_paths"] = paper_image_paths
    state["conversion_failed"] = conversion_failed

    # M-13: 转换阶段完成（成功/失败均发，前端 'paper' 步不再无信号）
    emit_progress(
        query_id, "extraction", "paper", "completed",
        progress={"completed": total, "total": total, "current": None},
        data={"phase": "convert"},
    )

    # Log cache statistics
    cache_size_mb = image_cache.get_cache_size()
    logger.info("[PDF Converter] Completed!")
    logger.info(f"[PDF Converter]   Success: {len(paper_image_paths)}")
    logger.info(f"[PDF Converter]   Failed: {len(conversion_failed)}")
    logger.info(f"[PDF Converter]   Cache size: {cache_size_mb:.2f} MB")

    if conversion_failed:
        logger.warning("[PDF Converter]   Failed papers:")
        for failed in conversion_failed:
            logger.warning(f"[PDF Converter]     - {failed['bibcode']}: {failed['reason']}")

    return state
