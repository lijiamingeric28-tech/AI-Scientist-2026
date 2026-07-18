"""
忠实度验证工具（TheFuzz模糊匹配）
"""

from thefuzz import fuzz
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def verify_field(target_value: str, ocr_words_info: List[Dict], threshold: int) -> Dict:
    """
    在OCR结果中查找目标值（模糊匹配）
    
    Args:
        target_value: 目标值
        ocr_words_info: OCR结果的words_info列表
        threshold: 匹配阈值
    
    Returns:
        {
            "found": bool,
            "match_score": int,
            "matched_text": str,
            "bbox": list
        }
    """
    if not target_value or not ocr_words_info:
        return {"found": False, "match_score": 0, "matched_text": None, "bbox": None}
    
    target_value = str(target_value).strip()
    
    # 方法1: 精确子串匹配（优先）
    for word in ocr_words_info:
        ocr_text = word.get("text", "")
        if target_value.lower() in ocr_text.lower():
            return {
                "found": True,
                "match_score": 100,
                "matched_text": ocr_text,
                "bbox": word.get("location")
            }
    
    # 方法2: 模糊子串匹配（容错）
    best_match = {
        "found": False,
        "match_score": 0,
        "matched_text": None,
        "bbox": None
    }
    
    for word in ocr_words_info:
        ocr_text = word.get("text", "")
        # 使用partial_ratio在长文本中查找短文本
        score = fuzz.partial_ratio(target_value, ocr_text)
        
        if score > best_match["match_score"]:
            best_match = {
                "found": score >= threshold,
                "match_score": score,
                "matched_text": ocr_text,
                "bbox": word.get("location")
            }
    
    return best_match


def verify_observation(
    observation: Dict, 
    ocr_words_info: List[Dict],
    entity_threshold: int,
    property_threshold: int
) -> Dict:
    """
    验证单条观测记录（双阈值策略）
    
    Args:
        observation: VLM提取的观测记录
        ocr_words_info: OCR结果
        entity_threshold: entity验证阈值
        property_threshold: property验证阈值
    
    Returns:
        {
            "verified": bool,
            "entity_verification": {...},
            "property_verification": {...}
        }
    """
    entity_name = observation.get("entity_name", "")
    property_value = observation.get("property_value", "")
    
    # 验证实体名称（阈值90）
    entity_result = verify_field(entity_name, ocr_words_info, entity_threshold)
    
    # 验证属性值（阈值95）
    property_result = verify_field(property_value, ocr_words_info, property_threshold)
    
    # 综合判断：两者都找到才算验证通过
    verified = entity_result["found"] and property_result["found"]
    
    return {
        "verified": verified,
        "entity_verification": entity_result,
        "property_verification": property_result
    }
