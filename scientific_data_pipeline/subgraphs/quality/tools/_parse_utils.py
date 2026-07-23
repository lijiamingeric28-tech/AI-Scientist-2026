"""
_parse_utils.py — property_value 数值解析工具 (Schema V1.1.0 适配)

新 schema 中 property_value 永远是 string，且可能含 +/- 不确定度。
此模块提供统一的数值解析函数，向后兼容旧的 number 类型。
"""
import re
from typing import Any

_UNCERTAINTY_RE = re.compile(r'^(.*?)(?:±|\+/-|±\s+)(.*?)$')
_PREFIX_CLEAN = re.compile(r'^[~≈<>≤≥]\s*')


def parse_numeric(value: Any) -> float | None:
    """
    从 property_value 提取数值 (适配 V1.1.0 string 类型)。
    支持: "450", "~450", "0.438", "0.0802±0.0073", ">5.0", "1.2e-5"
    向后兼容旧的 int/float 类型。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = _PREFIX_CLEAN.sub('', s)
    # 去除 +/- 不确定度部分
    m = _UNCERTAINTY_RE.match(s)
    if m:
        s = m.group(1).strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_uncertainty(value: Any) -> float | None:
    """提取 +/- 不确定度。"""
    if value is None:
        return None
    s = str(value).strip()
    m = _UNCERTAINTY_RE.match(s)
    if m and m.group(2):
        try:
            return float(m.group(2).strip().rstrip("%)"))
        except (ValueError, TypeError):
            pass
    return None


def is_numeric(value: Any) -> bool:
    """判断是否可解析为数值。"""
    return parse_numeric(value) is not None


def has_uncertainty(value: Any) -> bool:
    """判断是否含 +/- 不确定度。"""
    return parse_uncertainty(value) is not None
