"""
_parse_utils.py — field_value 数值解析工具 (V2 可插拔架构)

V2: 从硬编码 if-else 改为解析器注册表 (Parser Registry) 模式。
    支持通过 YAML 配置扩展新格式，无需修改代码。

内置支持:
  - 显式 ±:   "790 ± 3", "0.0802±0.0073"
  - 括号:    "776.2(5)"  → 值=776.2, 不确定度=0.5
             "0.0802(73)" → 值=0.0802, 不确定度=0.0073
  - 前缀:    "~450", "≈0.5", ">5.0", "≤100"
  - 科学记数: "1.2e-5"
  - 范围:    "2.1 <= z <= 3.5"
  - 纯数值:  "375.0", 375.0, 375

向后兼容旧的 int/float 类型。
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ============================================================
# Data Structures
# ============================================================


@dataclass
class ParsedResult:
    """解析后的结构化结果。"""
    numeric_value: float | None = None       # 主数值 (有不确定度时为中心值)
    uncertainty: float | None = None         # 不确定度
    is_range: bool = False                   # 是否为范围表达式
    range_min: float | None = None
    range_max: float | None = None
    matched_parser: str = ""                 # 匹配到的 parser 名称
    original: str = ""                       # 原始输入
    # V2: ambiguity detection
    ambiguous: bool = False                  # 是否存在多义性
    ambiguity_signatures: list[str] = field(default_factory=list)
    """命中的歧义签名: ['paren_as_ref', 'upper_limit', 'approx_value', ...]"""
    disambiguated: bool = False              # 是否已被 LLM 消除歧义


# ============================================================
# Ambiguity Signatures (客观的、可枚举的多义性清单)
# ============================================================

# 签名 1: 数值后的括号 — 可能是不确定度 776.2(5) | 引用编号 776.2 [5]
_PAREN_AMBIGUITY_RE = re.compile(r'^([\d.+-]+)\((\d+)\)$')

# 签名 2: < 前缀 — 可能是上限 | 不等式
_UPPER_LIMIT_RE = re.compile(r'^\s*<\s*([\d.]+)')

# 签名 3: ~ / ≈ 前缀 — 可能是近似值 | 数量级估计
_APPROX_RE = re.compile(r'^\s*[~≈]')

# 签名 4: 数值中出现逗号 — 可能是列表分隔 | 千位分隔
_COMMA_IN_NUMERIC_RE = re.compile(r'[\d.]+,\s*[\d.]+')

# 签名 5: 多个数值 — 可能是范围 | 多值列表
# 排除已被 ± / paren parser 处理的明确格式
_MULTI_VALUE_RE = re.compile(r'[\d.]+[^a-zA-Z*×\d±()]+[\d.]+[^a-zA-Z*×\d±()]+[\d.]+')

# 签名 6: 括号不确定度的小数位数判断 — 括号值≥100可能不同
_LARGE_PAREN_RE = re.compile(r'^([\d.]+)\((\d{3,})\)$')


def detect_ambiguity(raw_value: str) -> list[str]:
    """
    检测 field_value 字符串中客观存在的多义性签名。

    这不是"置信度"判断——而是识别已知的可枚举歧义模式。
    返回命中的签名列表，空列表表示无歧义。
    """
    if not raw_value or not isinstance(raw_value, str):
        return []

    s = raw_value.strip()
    signatures = []

    # 括号: 776.2(5) → 可能是不确定度 or 引用编号
    if _PAREN_AMBIGUITY_RE.match(s):
        signatures.append("paren_as_ref_or_uncertainty")
        # 大括号值 (>100) 更可能是引用
        if _LARGE_PAREN_RE.match(s):
            signatures.append("large_paren_value")

    # 前缀 < → 上限 or 不等式 (排除已处理的 ±/() 格式)
    if _UPPER_LIMIT_RE.match(s) and '±' not in s and '(' not in s:
        signatures.append("upper_limit")

    # 前缀 ~≈ → 近似值 or 数量级
    if _APPROX_RE.match(s) and '±' not in s:
        signatures.append("approx_value")

    # 逗号 → 分隔 or 千位 (排除已处理的 ±/() 格式)
    if _COMMA_IN_NUMERIC_RE.search(s) and '±' not in s and '(' not in s:
        signatures.append("comma_ambiguous")

    # 多数值 → 范围 or 列表 (排除已处理的 ±/() 格式)
    if _MULTI_VALUE_RE.search(s) and '±' not in s and '(' not in s:
        signatures.append("multi_value")

    return signatures


def _inject_ambiguity(result: ParsedResult, raw_value: str):
    """为 ParsedResult 注入歧义签名。"""
    sigs = detect_ambiguity(raw_value)
    if sigs:
        result.ambiguous = True
        result.ambiguity_signatures = sigs


# ============================================================
# Parser Registry
# ============================================================


class ValueParser(ABC):
    """解析器基类 — 子类化即可注册新格式。"""
    name: str = ""
    priority: int = 50  # 越小越优先

    @abstractmethod
    def try_parse(self, value: str) -> ParsedResult | None:
        """尝试解析。返回 ParsedResult 表示成功, None 表示不匹配。"""
        ...

    def describe(self) -> dict:
        return {"name": self.name, "priority": self.priority}


class ValueParserRegistry:
    """解析器注册表 — 按优先级链式尝试。"""

    def __init__(self):
        self._parsers: list[ValueParser] = []

    def register(self, parser: ValueParser):
        self._parsers.append(parser)
        self._parsers.sort(key=lambda p: p.priority)

    def parse_full(self, value: Any) -> ParsedResult:
        """尝试所有 parser, 返回第一个匹配的 ParsedResult。"""
        s = _to_str(value)
        if s is None:
            return ParsedResult(original=str(value) if value is not None else "")

        for parser in self._parsers:
            result = parser.try_parse(s)
            if result is not None:
                result.original = s
                _inject_ambiguity(result, s)  # V2: 检测并注入歧义签名
                return result

        # 无匹配
        return ParsedResult(original=s)

    def parse_numeric(self, value: Any) -> float | None:
        """提取数值 — 向后兼容旧 API。"""
        return self.parse_full(value).numeric_value

    def parse_uncertainty(self, value: Any) -> float | None:
        """提取不确定度 — 向后兼容旧 API。"""
        return self.parse_full(value).uncertainty

    def has_uncertainty(self, value: Any) -> bool:
        """判断是否有不确定度 — 向后兼容旧 API。"""
        return self.parse_full(value).uncertainty is not None

    def is_numeric(self, value: Any) -> bool:
        """判断是否可解析为数值 — 向后兼容旧 API。"""
        return self.parse_full(value).numeric_value is not None

    @property
    def parser_names(self) -> list[str]:
        return [p.name for p in self._parsers]


# ============================================================
# Built-in Parsers
# ============================================================

_PREFIX_RE = re.compile(r'^[~≈<>≤≥]\s*')
_UNICODE_MINUS_RE = re.compile(r'[−－]')  # − and －
_EXPLICIT_UNCERTAINTY_RE = re.compile(r'^(.*?)(?:±|\+/-|±\s+)(.*?)$')
_PAREN_UNCERTAINTY_RE = re.compile(r'^(.+?)\((\d+\.?\d*)\)$')
_RANGE_RE = re.compile(r'^([\d.]+)\s*(?:<=|≤|<)\s*\w+\s*(?:<=|≤|<)\s*([\d.]+)$')


def _to_str(value: Any) -> str | None:
    """统一转为字符串。None → None, bool → 跳过"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    return s if s else None


def _parse_float(s: str) -> float | None:
    """安全 float() 解析。"""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _normalize(s: str) -> str:
    """统一 Unicode 减号、去除多余空白。"""
    return _UNICODE_MINUS_RE.sub('-', s).strip()


class PrefixCleaner(ValueParser):
    """优先级 1: 去除 ~≈<>≤≥ 前缀。"""
    name = "prefix_cleaner"
    priority = 1

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        v = _PREFIX_RE.sub('', v).strip()
        if not v:
            return None
        n = _parse_float(v)
        if n is not None:
            return ParsedResult(numeric_value=n, matched_parser=self.name)
        return None  # 不是纯数值, 交给后续 parser


class ExplicitUncertaintyParser(ValueParser):
    """优先级 2: 处理显式 ± 不确定度。

    V4 fix: 容忍尾随括号换算 — "24.47 ± 0.12 (= 783 ± 43 kpc)"
    此前 uncert_str 整段 float 失败导致不确定度丢失、换算信息静默丢弃;
    现提取前导浮点数, 并标注 parenthetical_conversion 歧义签名。
    """
    name = "explicit_uncertainty"
    priority = 2

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        # 先去掉前缀
        prefix_cleaned = _PREFIX_RE.sub('', v).strip()
        m = _EXPLICIT_UNCERTAINTY_RE.match(prefix_cleaned)
        if not m:
            return None

        base_str = m.group(1).strip()
        uncert_str = m.group(2).strip().rstrip("%)")

        base = _parse_float(base_str)
        if base is None:
            return None

        # V4 fix: 提取前导浮点数 (容忍尾随括号换算/单位, 如 "0.12 (= 783 ± 43 kpc)")
        uncert = None
        mm = re.match(r'^([+-]?[\d.]+(?:[eE][+-]?\d+)?)', uncert_str)
        if mm:
            uncert = _parse_float(mm.group(1))

        result = ParsedResult(
            numeric_value=base,
            uncertainty=uncert,
            matched_parser=self.name,
        )
        # V4 fix: 检测括号换算 " (= 783 ± 43 kpc)" — 保留换算信息而非静默丢弃
        conv = re.search(r'\(=\s*([^)]+)\)', uncert_str)
        if conv:
            result.ambiguous = True
            result.ambiguity_signatures.append(
                f"parenthetical_conversion: {conv.group(1).strip()}")
        return result


class ParenUncertaintyParser(ValueParser):
    """优先级 3: 处理括号不确定度。

    "776.2(5)" → 值=776.2, 不确定度=0.5
    "0.0802(73)" → 值=0.0802, 不确定度=0.0073
    "790(3)" → 值=790, 不确定度=3
    """
    name = "paren_uncertainty"
    priority = 3

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        # 去掉前缀
        v = _PREFIX_RE.sub('', v).strip()
        m = _PAREN_UNCERTAINTY_RE.match(v)
        if not m:
            return None

        base_str = m.group(1).strip()
        paren_str = m.group(2).strip()

        base = _parse_float(base_str)
        if base is None:
            return None

        paren_val = _parse_float(paren_str)
        if paren_val is None:
            return None

        # 括号中的数字作用于末尾位数:
        #   "776.2(5)" → 776.2, 括号值=5, 小数位=1 → 不确定度 = 5 × 10^(-1) = 0.5
        #   "0.0802(73)" → 0.0802, 括号值=73, 小数位=4 → 不确定度 = 73 × 10^(-4) = 0.0073
        #   "790(3)" → 790, 括号值=3, 无小数点 → 不确定度 = 3
        if '.' in base_str:
            decimal_places = len(base_str.split('.')[1])
            uncertainty = paren_val * (10 ** (-decimal_places))
        else:
            uncertainty = paren_val

        return ParsedResult(
            numeric_value=base,
            uncertainty=uncertainty,
            matched_parser=self.name,
        )


class RangeExpressionParser(ValueParser):
    """优先级 4: 处理范围/不等式表达式。

    "2.1 <= z <= 3.5" → range_min=2.1, range_max=3.5, is_range=True
    """
    name = "range_expression"
    priority = 4

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        m = _RANGE_RE.match(v)
        if not m:
            return None

        lo = _parse_float(m.group(1))
        hi = _parse_float(m.group(2))
        if lo is None or hi is None:
            return None

        return ParsedResult(
            numeric_value=(lo + hi) / 2.0,  # 取中点作为代表值
            is_range=True,
            range_min=lo,
            range_max=hi,
            matched_parser=self.name,
        )


class NumericFallbackParser(ValueParser):
    """优先级 99: 纯数值兜底。"""
    name = "numeric_fallback"
    priority = 99

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        # 去掉前缀
        v = _PREFIX_RE.sub('', v).strip()
        n = _parse_float(v)
        if n is not None:
            return ParsedResult(numeric_value=n, matched_parser=self.name)
        return None


# ============================================================
# Singleton Registry (模块级)
# ============================================================

_registry: ValueParserRegistry | None = None


def _get_registry() -> ValueParserRegistry:
    global _registry
    if _registry is None:
        _registry = ValueParserRegistry()
        _registry.register(PrefixCleaner())
        _registry.register(ExplicitUncertaintyParser())
        _registry.register(ParenUncertaintyParser())
        _registry.register(RangeExpressionParser())
        _registry.register(NumericFallbackParser())
        _load_custom_parsers(_registry)
    return _registry


def _load_custom_parsers(registry: ValueParserRegistry):
    """从 YAML 配置加载自定义 parser。"""
    try:
        from ..configs import load_yaml
        config = load_yaml("value_parser_rules.yaml")
        custom = config.get("custom_parsers", {})
    except Exception:
        return  # config file optional

    for name, cfg in custom.items():
        try:
            pattern = cfg.get("pattern", "")
            value_grp = cfg.get("value_group", 1)
            uncert_grp = cfg.get("uncertainty_group")
            range_max_grp = cfg.get("range_max_group")
            priority = cfg.get("priority", 50)
            desc = cfg.get("description", name)

            regex = re.compile(pattern)
            parser = _ConfigDrivenParser(
                name=name, priority=priority, pattern=regex,
                value_group=value_grp, uncertainty_group=uncert_grp,
                range_max_group=range_max_grp, description=desc,
            )
            registry.register(parser)
        except Exception:
            pass  # skip bad config entries


class _ConfigDrivenParser(ValueParser):
    """从 YAML 配置驱动的 parser。"""

    def __init__(self, name: str, priority: int, pattern: re.Pattern,
                 value_group: int = 1, uncertainty_group: int | None = None,
                 range_max_group: int | None = None, description: str = ""):
        self.name = name
        self.priority = priority
        self._pattern = pattern
        self._value_group = value_group
        self._uncertainty_group = uncertainty_group
        self._range_max_group = range_max_group
        self._description = description

    def try_parse(self, value: str) -> ParsedResult | None:
        v = _normalize(value)
        # 去掉常见前缀
        v = _PREFIX_RE.sub('', v).strip()
        m = self._pattern.match(v)
        if not m:
            return None

        base = _parse_float(m.group(self._value_group))
        if base is None:
            return None

        uncert = None
        if self._uncertainty_group:
            uncert = _parse_float(m.group(self._uncertainty_group))

        rmin, rmax = None, None
        is_range = False
        if self._range_max_group:
            rmax = _parse_float(m.group(self._range_max_group))
            if rmax is not None:
                rmin = base
                is_range = True

        return ParsedResult(
            numeric_value=base if not is_range else (base + (rmax or base)) / 2.0,
            uncertainty=uncert,
            is_range=is_range,
            range_min=rmin,
            range_max=rmax,
            matched_parser=self.name,
        )

    def describe(self) -> dict:
        return {
            "name": self.name, "priority": self.priority,
            "description": self._description, "source": "config",
        }


def register_parser(parser: ValueParser):
    """动态注册自定义 parser (代码级别)。"""
    _get_registry().register(parser)


# ============================================================
# V2: LLM Batch Disambiguator
# ============================================================

_DISAMBIGUATION_SYSTEM = """You are a scientific data parser. For each record below, use the context_snippet
to determine the correct interpretation of the field_value. Return JSON only.

For each record_id, provide:
- resolution: one of ["uncertainty", "reference", "upper_limit", "inequality",
                       "approximate", "exact", "range", "list", "unchanged"]
- explanation: one short sentence

Rules:
- "(N)" after a number in a measurement context → "uncertainty"
- "(N)" after a number when it's a citation/reference → "reference"
- "<" prefix when context says "upper limit" or suggests non-detection → "upper_limit"
- "<" prefix when it's just a mathematical inequality → "inequality"
- "~" or "≈" when it's a rough estimate → "approximate"
- "~" or "≈" when it's just marking approximate equality → "unchanged"
- Multiple numbers separated by spaces/commas → "list" if independent values, "range" if min-max

Return: {"disambiguations": [{"record_id": "...", "resolution": "...", "explanation": "..."}]}"""


def disambiguate_batch(
    ambiguous_records: list[dict],
    temperature: float = 0.0,
) -> dict[str, dict]:
    """
    批量 LLM 歧义消除。

    Args:
        ambiguous_records: [{"record_id": str, "field_value": str, "context_snippet": str}, ...]
        temperature: LLM temperature

    Returns:
        {record_id: {"resolution": str, "explanation": str}} 或空 dict (LLM 失败)
    """
    if not ambiguous_records:
        return {}

    try:
        from ..utils.llm import get_llm, set_agent_context
        import json as _json, time as _time

        t0 = _time.time()
        set_agent_context("value_disambiguator")

        # 构建批量 prompt
        items = []
        for rec in ambiguous_records:
            ctx = (rec.get("context_snippet", "") or "")[:300]
            items.append(
                f"record_id: {rec['record_id']}\n"
                f"field_value: {rec['field_value']}\n"
                f"context: {ctx}\n"
            )

        user_msg = "Disambiguate these field_values using context:\n\n" + "\n---\n".join(items)

        llm = get_llm(temperature=temperature)
        resp = llm.invoke([
            {"role": "system", "content": _DISAMBIGUATION_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        content = resp.content if hasattr(resp, "content") else str(resp)

        # 解析 JSON 响应
        import re as _re
        m = _re.search(r'\{.*\}', content, _re.DOTALL)
        if not m:
            return {}

        data = _json.loads(m.group(0))
        disambiguations = {}
        for item in data.get("disambiguations", []):
            rid = item.get("record_id", "")
            if rid:
                disambiguations[rid] = {
                    "resolution": item.get("resolution", "unchanged"),
                    "explanation": item.get("explanation", ""),
                }
        return disambiguations

    except Exception:
        return {}


def apply_disambiguation(results: dict[str, ParsedResult],
                         disambiguations: dict[str, dict]):
    """
    将 LLM 歧义消除结果应用到 ParsedResult。

    根据 resolution 类型选择性覆盖解析结果：
    - "reference": 清除 uncertainty (括号是引用，不是不确定度)
    - "upper_limit": 保留值但标记为上限
    - "list": 标记多值（暂不拆分，保留原值）
    - "unchanged": 不动
    """
    for rid, info in disambiguations.items():
        r = results.get(rid)
        if r is None:
            continue

        resolution = info.get("resolution", "unchanged")

        if resolution == "reference":
            # 括号是引用编号，不是不确定度 → 清除
            r.uncertainty = None

        elif resolution == "upper_limit":
            # < 前缀是上限，标记但不改变数值
            r.ambiguity_signatures.append("resolved_as_upper_limit")

        elif resolution == "approximate":
            r.ambiguity_signatures.append("resolved_as_approximate")

        elif resolution == "inequality":
            # < 只是不等式，保留原值
            r.ambiguity_signatures.append("resolved_as_inequality")

        elif resolution == "range":
            r.is_range = True

        elif resolution == "list":
            # 多值列表，当前保留原值，未来可考虑拆分
            r.ambiguity_signatures.append("resolved_as_list")

        r.disambiguated = True


# ============================================================
# Public API (向后兼容)
# ============================================================


def parse_numeric(value: Any) -> float | None:
    """
    从 field_value 提取数值。

    支持的格式:
      - "450", "0.438", "1.2e-5"                          (纯数值)
      - "~450", "≈0.5", ">5.0", "≤100"                    (前缀)
      - "0.0802±0.0073", "790 ± 3"                         (显式 ±)
      - "776.2(5)" → 776.2                                  (括号不确定度)
      - "0.0802(73)" → 0.0802                               (括号不确定度)
      - "2.1 <= z <= 3.5" → 2.8                             (范围取中点)

    向后兼容旧的 int/float 类型。
    """
    # 特殊处理: 直接的 number 类型 (向后兼容)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return _get_registry().parse_numeric(value)


def parse_uncertainty(value: Any) -> float | None:
    """
    提取不确定度值。

    支持:
      - 显式 ±:  "0.0802±0.0073" → 0.0073
      - 括号:   "776.2(5)" → 0.5
                "0.0802(73)" → 0.0073 (自动计算小数点位数)
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    return _get_registry().parse_uncertainty(value)


def is_numeric(value: Any) -> bool:
    """判断是否可解析为数值。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    return _get_registry().is_numeric(value)


def has_uncertainty(value: Any) -> bool:
    """判断是否含不确定度 (± 或括号记法)。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    return _get_registry().has_uncertainty(value)


def parse_full(value: Any) -> ParsedResult:
    """
    返回完整的 ParsedResult, 含不确定度/范围等元信息。

    V2 新增 API — 供需要结构化信息的调用方使用。
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ParsedResult(
            numeric_value=float(value),
            matched_parser="direct_number",
            original=str(value),
        )
    return _get_registry().parse_full(value)
