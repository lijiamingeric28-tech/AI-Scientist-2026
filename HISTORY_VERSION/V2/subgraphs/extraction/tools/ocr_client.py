"""
OCR API 客户端
"""

import dashscope
import logging
import os
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


def get_dashscope_api_key():
    """获取DashScope API Key"""
    api_key = os.getenv('DASHSCOPE_API_KEY') or os.getenv('OPENAI_API_KEY') or os.getenv('QWEN_API_KEY')

    if not api_key:
        raise ValueError("API key not found. Please set DASHSCOPE_API_KEY, OPENAI_API_KEY or QWEN_API_KEY")

    return api_key


def call_ocr_api(image_base64: str) -> Optional[Dict]:
    """
    调用OCR API

    Args:
        image_base64: base64编码的图像

    Returns:
        OCR结果字典或None
    """
    from config.constants import OCR_MODEL

    api_key = get_dashscope_api_key()
    dashscope.api_key = api_key
    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

    try:
        response = dashscope.MultiModalConversation.call(
            api_key=api_key,
            model=OCR_MODEL,
            messages=[{
                "role": "user",
                "content": [{
                    "image": f"data:image/png;base64,{image_base64}",
                    "min_pixels": 32 * 32 * 3,
                    "max_pixels": 32 * 32 * 8192,
                    "enable_rotate": False
                }]
            }],
            ocr_options={"task": "advanced_recognition"}
        )

        # 提取OCR结果
        choices = response.get("output", {}).get("choices", [])
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content", [])
        if not content:
            return None

        # 查找ocr_result
        for item in content:
            if "ocr_result" in item:
                ocr_result = item["ocr_result"]
                if "words_info" in ocr_result:
                    return {
                        "ocr_model": OCR_MODEL,
                        "timestamp": datetime.now().isoformat(),
                        "words_count": len(ocr_result["words_info"]),
                        "words_info": ocr_result["words_info"]
                    }

        return None

    except Exception as e:
        logger.error(f"OCR调用失败: {e}")
        return None
