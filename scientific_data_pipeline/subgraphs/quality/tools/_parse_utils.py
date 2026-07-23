"""
_parse_utils.py — property_value 数值解析工具 (Schema V1.1.0 适配)

新 schema 中 property_value 永远是 string，且可能含不确定度。
支持多种科学记法中的不确定度表达:
  - 显式 ±:  "790 ± 3", "0.0802±0.0073"
  - 括号:   "776.2(5)"  → 值=776.2, 不确定度=0.5
            "0.0802(73)" → 值=0.0802, 不确定度=0.0073 (括号数字作用于末尾位数)
  - 前缀:   "~450", "≈0.5", ">5.0", "≤100"
  - 科学记数: "1.2e-5"
向后兼容旧的 int/float 类型。
"""
import re
from typing import Any

_UNCERTAINTY_RE = re.compile(r'^(.*?)(?:±|\+/-|±\s+)(.*?)$')
_PAREN_UNCERTAINTY_RE = re.compile(r'^(.+?)\((\d+\.?\d*)\)$')
_PREFIX_CLEAN = re.compile(r'^[~≈<>≤≥]\s*')


def parse_numeric(value: Any) -> float | None:
    """
    从 property_value 提取数值 (适配 V1.1.0 string 类型)。

    支持的格式:
      - "450", "0.438", "1.2e-5"                          (纯数值)
      - "~450", "≈0.5", ">5.0", "≤100"                    (前缀)
      - "0.0802±0.0073", "790 ± 3"                         (显式 ±)
      - "776.2(5)" → 776.2                                  (括号不确定度)
      - "0.0802(73)" → 0.0802                               (括号不确定度)

    向后兼容旧的 int/float 类型。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # 1. 去掉前缀 (~≈<>≤≥)
    s = _PREFIX_CLEAN.sub('', s)
    # 2. 去掉显式 ± 不确定度部分: "790 ± 3" → "790"
    m = _UNCERTAINTY_RE.match(s)
    if m:
        s = m.group(1).strip()
    # 3. 去掉括号不确定度: "776.2(5)" → "776.2"
    m = _PAREN_UNCERTAINTY_RE.match(s)
    if m:
        s = m.group(1).strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_uncertainty(value: Any) -> float | None:
    """
    提取不确定度值。

    支持:
      - 显式 ±:  "0.0802±0.0073" → 0.0073
      - 括号:   "776.2(5)" → 0.5
                "0.0802(73)" → 0.0073 (自动计算小数点位数)
    """
    if value is None:
        return None
    s = str(value).strip()
    # 1. 显式 ±
    m = _UNCERTAINTY_RE.match(s)
    if m and m.group(2):
        try:
            return float(m.group(2).strip().rstrip("%)"))
        except (ValueError, TypeError):
            pass
    # 2. 括号不确定度
    m = _PAREN_UNCERTAINTY_RE.match(s)
    if m:
        base_str = m.group(1).strip()
        paren_str = m.group(2).strip()
        try:
            base = float(base_str)
            paren_val = float(paren_str)
            # 括号中的数字作用于末尾位数: 如 "776.2(5)" → 0.5
            # 即 776.2 + 括号值 × 10^(-小数位数)
            if '.' in base_str:
                decimal_places = len(base_str.split('.')[1])
                uncertainty = paren_val * (10 ** (-decimal_places))
            else:
                uncertainty = paren_val
            return uncertainty
        except (ValueError, TypeError):
            pass
    return None


def is_numeric(value: Any) -> bool:
    """判断是否可解析为数值。"""
    return parse_numeric(value) is not None


def has_uncertainty(value: Any) -> bool:
    """判断是否含不确定度 (± 或括号记法)。"""
    if value is None:
        return False
    s = str(value).strip()
    if _UNCERTAINTY_RE.match(s):
        return True
    if _PAREN_UNCERTAINTY_RE.match(s):
        return True
    return False
