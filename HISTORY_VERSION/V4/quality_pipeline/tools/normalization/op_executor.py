"""op_executor.py — Layer A: 模板驱动 ops 执行器 (P3)

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §5 层 A (§6 附录 A ops 路径段):
LLM 输出结构化操作规格 ({op, field, params}), 由本确定性执行器逐 op 应用。
消除自由 Python 生成模式 8 根因中 7 个 (无沙箱/无逃逸面/无死循环面) —
exec 与 fn 调用在线程中执行并设硬超时。

设计要点:
- OpSpec / OpSpecResponse 为 Pydantic 严格契约 (LLM 输出先经此校验)
- execute_ops 在深拷贝副本上执行, 逐 op 顺序应用; 每 op 后校验
  记录数/键集合不变 — 违规即终止返回 kind=op_invariant_failed 结构化失败
- 逐 record 错误收集不中断 (errors 含 record_id/field/reason)
- log 条目复用 Base Tool schema (record_id/field/action/before/after)
- 各 op 语义复用 quality_pipeline/tools/_parse_utils.py 的
  is_numeric/parse_numeric 与 unit_converter (单位转换委托)

op 目录 (可扩展):
  strip_prefix / numeric_convert / trim / unit_normalize /
  drop_suffix / replace_substring / mark_missing_unit
"""
from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field

from quality_pipeline.tools._parse_utils import is_numeric, parse_numeric

# 默认数值前缀 (strip_prefix 未显式指定 prefixes 时)
_DEFAULT_PREFIXES = ["~", "≈", "<", ">", "≤", "≥"]

# 单位缺失标签 (mark_missing_unit 未显式指定 unit 时)
_DEFAULT_MISSING_UNIT_LABEL = "unknown"

# ── Pydantic 契约 ──

_OpNames = Literal[
    "strip_prefix", "numeric_convert", "trim", "unit_normalize",
    "drop_suffix", "replace_substring", "mark_missing_unit",
]


class OpSpec(BaseModel):
    """单条操作规格。字段默认值面向规范记录形态 (field_value/field_unit)。"""

    op: _OpNames
    field: str = "field_value"
    unit_field: str | None = "field_unit"
    to: str | None = None          # unit_normalize: 目标单位
    prefixes: list[str] | None = None   # strip_prefix: 自定义前缀表
    suffix: str | None = None      # drop_suffix: 要剥离的末尾子串
    old: str | None = None         # replace_substring: 被替换子串
    new: str | None = None         # replace_substring: 替换结果 (None → "")
    unit: str | None = None        # mark_missing_unit: 补的标签


class OpSpecResponse(BaseModel):
    """LLM ops 路径输出的严格 JSON 契约 — ops 必填 (1-8 条) + confidence 必填。"""

    ops: list[OpSpec] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0, description="必填 0-1, 自评信号")
    reasoning: str = ""


# ── 数值辅助 (复用 _parse_utils, _to_number 语义) ──

def _to_number(val: Any):
    """_to_number 语义: 字符串数值 → int/float; 已是数值 → 幂等返回; 否则 None。

    与模板内 _to_number 对齐: 整数形态字符串转 int, 含小数点/指数转 float
    (parse_numeric 兜底处理 ±/括号/前缀等扩展形态)。
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return val  # 幂等 — 已是数值
    if isinstance(val, str):
        n = parse_numeric(val)
        if n is None:
            return None
        s = val.strip()
        if "." not in s and "e" not in s.lower():
            return int(n)
        return n
    return None


# ── 各 op 实现 ──

def _apply_strip_prefix(data, op, log, errors):
    """剥离数值前缀 (prefixes 或默认 ~≈<>≤≥) + 数值化剩余。

    "~770" → 770; 剥离后剩余非数值 → 逐 record 错误 (不中断)。
    """
    prefixes = op.prefixes if op.prefixes else _DEFAULT_PREFIXES
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        val = rec.get(op.field)
        if not isinstance(val, str):
            continue  # 非字符串 (已数值化) 无前缀可剥
        s = val.strip()
        stripped = s
        for p in prefixes:
            if p and stripped.startswith(p):
                stripped = stripped[len(p):].lstrip()
                break
        if stripped == s:
            continue  # 无前缀命中
        n = _to_number(stripped)
        if n is None:
            errors.append({"record_id": rec.get("record_id"), "field": op.field,
                           "reason": f"prefix stripped but remainder not numeric: {stripped!r}"})
            continue
        rec[op.field] = n
        log.append({"record_id": rec.get("record_id"), "field": op.field,
                    "action": "strip_prefix", "before": s, "after": n})


def _apply_numeric_convert(data, op, log, errors):
    """字符串数值 → int/float (_to_number 语义, 幂等 — 已数值化记录不变不记 log)。"""
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        val = rec.get(op.field)
        if not isinstance(val, str):
            continue  # 幂等: 非字符串 (数值/None/其它) 不转换
        n = _to_number(val)
        if n is None:
            continue  # 非数值字符串 → 跳过 (与 _to_number 语义一致, 不记错误)
        rec[op.field] = n
        log.append({"record_id": rec.get("record_id"), "field": op.field,
                    "action": "numeric_convert", "before": val, "after": n})


def _apply_trim(data, op, log, errors):
    """去首尾空白 (仅字符串值; 变化才写回才记 log)。"""
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        val = rec.get(op.field)
        if not isinstance(val, str):
            continue
        stripped = val.strip()
        if stripped == val:
            continue
        rec[op.field] = stripped
        log.append({"record_id": rec.get("record_id"), "field": op.field,
                    "action": "trim", "before": val, "after": stripped})


def _apply_drop_suffix(data, op, log, errors):
    """去除值末尾的 suffix 子串 (suffix 缺失 → op 级错误, 跳过本 op 不中断)。"""
    suffix = op.suffix
    if not suffix:
        errors.append({"record_id": None, "field": op.field,
                       "reason": "drop_suffix requires 'suffix' parameter"})
        return
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        val = rec.get(op.field)
        if not isinstance(val, str):
            continue
        if val.endswith(suffix):
            new_val = val[:-len(suffix)]
            rec[op.field] = new_val
            log.append({"record_id": rec.get("record_id"), "field": op.field,
                        "action": "drop_suffix", "before": val, "after": new_val})


def _apply_replace_substring(data, op, log, errors):
    """将值中的 old 子串替换为 new (old 缺失 → op 级错误, 跳过本 op 不中断)。"""
    old = op.old
    if not old:
        errors.append({"record_id": None, "field": op.field,
                       "reason": "replace_substring requires 'old' parameter"})
        return
    new = op.new or ""
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        val = rec.get(op.field)
        if not isinstance(val, str):
            continue
        if old in val:
            new_val = val.replace(old, new)
            rec[op.field] = new_val
            log.append({"record_id": rec.get("record_id"), "field": op.field,
                        "action": "replace_substring", "before": val, "after": new_val})


def _apply_unit_normalize(data, op, log, errors, ctx):
    """单位转换 (委托 unit_converter): 值 + 单位同步换算。

    to 缺失 → op 级错误; 无换算规则/量纲不匹配 → unconverted 逐条转 errors
    (record_id/field/reason), 不中断。
    """
    target = op.to
    if not target:
        errors.append({"record_id": None, "field": op.field,
                       "reason": "unit_normalize requires 'to' parameter"})
        return
    from quality_pipeline.tools.normalization.unit_converter import convert_units
    conv = convert_units(
        data,
        unit_conversions=[{"field": op.field, "to": target}],
        standard_units=(ctx or {}).get("standard_units") or {},
        semantic_types=(ctx or {}).get("semantic_types") or {},
        target_schema=(ctx or {}).get("target_schema"),
        research_domain=(ctx or {}).get("research_domain"),
    )
    # 转换日志 → Base Tool schema (record_id/field/action/before/after, 保留 from/to)
    for cl in conv.get("conversion_log", []) or []:
        if not isinstance(cl, dict):
            continue
        log.append({
            "record_id": cl.get("record_id"), "field": cl.get("field"),
            "action": "unit_normalize",
            "before": str(cl.get("original_value")), "after": str(cl.get("new_value")),
            "from": cl.get("from"), "to": cl.get("to"),
        })
    for uc in conv.get("unconverted", []) or []:
        if isinstance(uc, dict):
            errors.append({"record_id": uc.get("record_id"), "field": uc.get("field"),
                           "reason": uc.get("reason", "no conversion rule")})


def _apply_mark_missing_unit(data, op, log, errors):
    """仅为缺单位的数值记录补标签 (unit 或默认 unknown)。"""
    label = op.unit or _DEFAULT_MISSING_UNIT_LABEL
    unit_field = op.unit_field or "field_unit"
    for rec in data:
        if not isinstance(rec, dict):
            errors.append({"record_id": None, "field": op.field, "reason": "record is not a dict"})
            continue
        unit = rec.get(unit_field)
        if (unit is None or unit == "") and is_numeric(rec.get(op.field)):
            rec[unit_field] = label
            log.append({"record_id": rec.get("record_id"), "field": op.field,
                        "action": "mark_missing_unit", "before": str(unit), "after": label})


# ── op 分发表 ──

_OP_APPLIERS = {
    "strip_prefix": _apply_strip_prefix,
    "numeric_convert": _apply_numeric_convert,
    "trim": _apply_trim,
    "unit_normalize": _apply_unit_normalize,
    "drop_suffix": _apply_drop_suffix,
    "replace_substring": _apply_replace_substring,
    "mark_missing_unit": _apply_mark_missing_unit,
}


# ── 执行入口 ──

def _invariant_violated(data, n_records, key_sets) -> dict | None:
    """每 op 后校验记录数/键集合不变 — 违规返回结构化失败 (调用方终止)。"""
    if len(data) != n_records:
        return {"kind": "op_invariant_failed",
                "message": f"record count changed {n_records} -> {len(data)}"}
    for i, rec in enumerate(data):
        if not isinstance(rec, dict):
            return {"kind": "op_invariant_failed",
                    "message": f"record {i} is not a dict"}
        if frozenset(rec.keys()) != key_sets[i]:
            return {"kind": "op_invariant_failed",
                    "message": f"field key set changed at index {i} (ops must not add/remove keys)"}
    return None


def execute_ops(records: list[dict], ops: list[OpSpec], **ctx) -> dict:
    """在深拷贝副本上逐 op 顺序应用模板驱动变换 (确定性执行器)。

    Args:
        records: 执行前记录列表 (调用方持有的原始列表不被修改)。
        ops:     操作规格序列 (1-8 条, OpSpec 或可被 OpSpec.model_validate 的 dict)。
        **ctx:   可选执行上下文 (research_domain/semantic_types/target_schema/
                 standard_units — 供 unit_normalize 委托 unit_converter)。

    Returns:
        成功: {"data": [...], "log": [...], "errors": [...], "summary": "..."}
              (与生成工具 result 同形, 可直接过 _validate_generated_result /
               _detect_noop 共享门)
        不变量违规: {"kind": "op_invariant_failed", "op": <op>, "message": "..."}
              (终止, 不再应用后续 op)
    """
    data = copy.deepcopy(records)
    log: list[dict] = []
    errors: list[dict] = []
    n_records = len(data)
    key_sets = [frozenset(r.keys()) if isinstance(r, dict) else frozenset()
                for r in data]

    for op in ops:
        spec = op if isinstance(op, OpSpec) else OpSpec.model_validate(op)
        applier = _OP_APPLIERS.get(spec.op)
        if applier is None:
            # 未知 op (正常不会到达 — Literal 已约束; 防御性兜底)
            errors.append({"record_id": None, "field": spec.field,
                           "reason": f"unknown op: {spec.op}"})
            continue
        if spec.op == "unit_normalize":
            applier(data, spec, log, errors, ctx)
        else:
            applier(data, spec, log, errors)
        # 每 op 后不变量门 — 违规即终止 (结构化失败)
        violation = _invariant_violated(data, n_records, key_sets)
        if violation is not None:
            violation["op"] = spec.op
            violation["data"] = data
            violation["log"] = log
            violation["errors"] = errors
            return violation

    return {"data": data, "log": log, "errors": errors,
            "summary": f"Applied {len(ops)} op(s), {len(log)} modification(s), "
                       f"{len(errors)} error(s)"}
