"""
PDF处理工具函数
"""

import fitz
from PIL import Image
import base64
from io import BytesIO
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str, max_pages=None, dpi=150):
    """
    将PDF转换为图像列表
    
    Args:
        pdf_path: PDF文件路径
        max_pages: 最大页数（None表示处理所有页）
        dpi: 图像分辨率
    
    Returns:
        List[PIL.Image]: 图像列表
    """
    try:
        doc = fitz.open(pdf_path)
        images = []
        
        # 确定处理页数
        total_pages = len(doc)
        pages_to_process = total_pages if max_pages is None else min(total_pages, max_pages)
        
        for page_num in range(pages_to_process):
            page = doc[page_num]
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        
        doc.close()
        logger.debug(f"PDF转换成功: {pdf_path}, {len(images)}页")
        return images
        
    except Exception as e:
        logger.error(f"PDF转换失败 {pdf_path}: {e}")
        return []


def image_to_base64(image: Image.Image) -> str:
    """
    将PIL Image转换为base64字符串
    
    Args:
        image: PIL Image对象
    
    Returns:
        base64编码的字符串
    """
    buffered = BytesIO()
    image.save(buffered, format="PNG", optimize=True, quality=85)
    return base64.b64encode(buffered.getvalue()).decode()


def pdf_to_base64_page(pdf_path: str, page_num: int, dpi=150):
    """
    将PDF指定页转为base64
    
    Args:
        pdf_path: PDF文件路径
        page_num: 页码（0-based）
        dpi: 图像分辨率
    
    Returns:
        base64字符串或None
    """
    try:
        doc = fitz.open(pdf_path)
        
        if page_num >= len(doc):
            doc.close()
            return None
        
        page = doc[page_num]
        mat = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()
        
    except Exception as e:
        logger.error(f"PDF页转换失败 {pdf_path} 第{page_num+1}页: {e}")
        return None
