"""PDF batch converter node (streaming version)."""

from datetime import datetime
from ..schemas.state import ExtractionState
from ..utils.logger import get_logger
from ..utils.pdf_utils import pdf_to_images
from ..utils.image_cache import image_cache


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

    state["conversion_status"] = "running"

    paper_image_paths = {}
    conversion_failed = []

    for idx, paper_info in enumerate(download_paths, 1):
        bibcode = paper_info["bibcode"]
        pdf_path = paper_info["local_path"]

        logger.info(f"[PDF Converter] [{idx}/{len(download_paths)}] Converting {bibcode}...")
        logger.debug(f"[PDF Converter]   PDF path: {pdf_path}")

        try:
            # Convert PDF to images (in memory)
            images = pdf_to_images(pdf_path)

            # Save images to disk and get paths
            image_paths = image_cache.save_images(bibcode, images)
            paper_image_paths[bibcode] = image_paths

            logger.info(f"[PDF Converter]   ✓ Success: {len(images)} pages converted and cached")
            logger.debug(f"[PDF Converter]   Cache paths: {len(image_paths)} files")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[PDF Converter]   ✗ Failed: {error_msg}")
            conversion_failed.append({
                "bibcode": bibcode,
                "pdf_path": pdf_path,
                "reason": error_msg,
                "timestamp": datetime.now().isoformat()
            })

    # Update state
    state["conversion_status"] = "completed"
    state["paper_image_paths"] = paper_image_paths
    state["conversion_failed"] = conversion_failed

    # Log cache statistics
    cache_size_mb = image_cache.get_cache_size()
    logger.info(f"[PDF Converter] Completed!")
    logger.info(f"[PDF Converter]   Success: {len(paper_image_paths)}")
    logger.info(f"[PDF Converter]   Failed: {len(conversion_failed)}")
    logger.info(f"[PDF Converter]   Cache size: {cache_size_mb:.2f} MB")

    if conversion_failed:
        logger.warning(f"[PDF Converter]   Failed papers:")
        for failed in conversion_failed:
            logger.warning(f"[PDF Converter]     - {failed['bibcode']}: {failed['reason']}")

    return state
