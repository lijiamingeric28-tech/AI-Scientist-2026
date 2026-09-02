"""PDF processing utilities."""

import fitz  # PyMuPDF
from PIL import Image
from typing import List
from .logger import get_logger


logger = get_logger(__name__)


def pdf_to_images(pdf_path: str, dpi: int = 150) -> List[Image.Image]:
    """
    Convert PDF to a list of images (one per page).

    Args:
        pdf_path: Path to PDF file
        dpi: Resolution (default 150, balances quality and performance)

    Returns:
        List of PIL Image objects

    Raises:
        Exception: If PDF cannot be opened or converted
    """
    logger.debug(f"Opening PDF: {pdf_path}")

    try:
        doc = fitz.open(pdf_path)
        images = []

        # Calculate zoom matrix (300 DPI)
        zoom = dpi / 72.0  # 72 is PDF's default DPI
        matrix = fitz.Matrix(zoom, zoom)

        logger.debug(f"PDF has {len(doc)} pages, converting at {dpi} DPI")

        for page_num in range(len(doc)):
            logger.debug(f"  Converting page {page_num + 1}/{len(doc)}")
            page = doc[page_num]

            # Render page as image
            pix = page.get_pixmap(matrix=matrix)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)

        doc.close()

        logger.debug(f"Successfully converted {len(images)} pages")
        return images

    except Exception as e:
        logger.error(f"Failed to convert PDF {pdf_path}: {e}")
        raise
