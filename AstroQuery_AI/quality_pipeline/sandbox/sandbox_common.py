"""sandbox_common.py — 沙箱 SSOT (Single Source of Truth) 共享设施 (P0)

收纳原先散落在 normalization_agent.py 的沙箱常量与函数 (函数名/语义不变,
原样搬迁): _ALLOWED_AST_NODES / _ALLOWED_MODULES / _FORBIDDEN_FUNCTIONS /
_SANDBOX_TIMEOUT_SEC / _SANDBOX_MAX_LOG_ENTRIES / _safe_import / _make_sandbox /
_validate_code_ast, 并新增共享不变量门 _validate_generated_result 与
模块级 _MODULE_GLOBALS 自动注入 (AST 检查 / _safe_import / globals 三处零漂移)。

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(b)(c) (P0)。

──────────────────────────────────────────────────────────────
模块白名单静态审计表 (P0 校验通过, 各模块为纯标准库, 无文件/网络/子进程面)
──────────────────────────────────────────────────────────────
  math        纯数值函数, 无 IO
  re          正则引擎, 无 IO
  json        纯数据序列化, 无 IO
  copy        深拷贝, 无 IO
  datetime    时间对象, 无 IO
  collections 容器类, 无 IO
  itertools   迭代器工具, 无 IO
  functools   高阶函数 (partial/lru_cache), 无 IO
  typing      类型标注, 无 IO
  statistics  统计函数, 无 IO
  decimal     十进制数值, 无 IO
  fractions   分数, 无 IO
  hashlib     哈希摘要 (单向, 无密钥/文件面), 无 IO
  warnings    警告 (无文件写面)
  base64      base64 编解码, 无 IO
  uuid        UUID 生成, 无 IO
  string      字符串常量/工具, 无 IO
  textwrap    文本缩进工具, 无 IO

已移出 (V1 独立验证, 必修):
  operator    operator.attrgetter("__class__.__bases__") 字符串 dunder 路径
              可实现完整任意代码执行 (Popen 子进程实测) — 见
              NORMALIZATION_LAYER3_OPTIMIZATION.md §9.1
  logging     logging.FileHandler 可写任意文件, 违反沙箱"无 IO"声明

新增模块必须: 先通过静态审计 (无文件/网络/子进程/反射逃逸面), 再登记白名单,
并同步更新本审计表与 _ESCAPE_POCS 测试。
"""
from __future__ import annotations
import ast
from typing import Any, Literal
from pydantic import BaseModel, Field, ValidationError
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)

# AST 白名单: 允许的节点类型
_ALLOWED_AST_NODES = {
    ast.Module, ast.FunctionDef, ast.Return, ast.Assign, ast.Expr,
    ast.Call, ast.Name, ast.Load, ast.Store, ast.Constant, ast.arg,
    ast.arguments, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
    ast.If, ast.For, ast.While, ast.Attribute, ast.Subscript, ast.Index,
    ast.List, ast.Dict, ast.Tuple, ast.Set,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.comprehension, ast.Slice, ast.UAdd, ast.USub, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Mod, ast.Pow, ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
    ast.And, ast.Or, ast.Not, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Pass, ast.Break, ast.Continue, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.Assert, ast.Import, ast.ImportFrom, ast.alias,
    ast.JoinedStr, ast.FormattedValue, ast.Lambda, ast.IfExp,
    ast.AugAssign, ast.AnnAssign, ast.keyword, ast.Starred,
    ast.withitem, ast.With, ast.Yield, ast.YieldFrom,
    # V3.1: 常见数据清洗操作符
    ast.FloorDiv, ast.BitAnd, ast.BitOr, ast.LShift, ast.RShift,
    ast.Invert, ast.Del, ast.Delete,
    # P1 (a): 补齐合法现代语法节点 — walrus (NamedExpr) 与 match 语句系
    # (LLM 生成代码可能使用; 安全前提: dunder 属性块/Name 黑名单照常生效,
    #  对应逃逸 PoC walrus_escape/match_escape 仍被拦截 — 见 test_sandbox_security)
    ast.NamedExpr,
    ast.Match, ast.match_case, ast.MatchValue, ast.MatchSingleton,
    ast.MatchSequence, ast.MatchMapping, ast.MatchClass, ast.MatchStar,
    ast.MatchAs, ast.MatchOr,
}
# TryStar 仅 3.11+ 存在 — 3.10 直接写入集合字面量会在 import 期 AttributeError,
# 故用 hasattr 守卫 (P1 a)
if hasattr(ast, "TryStar"):
    _ALLOWED_AST_NODES.add(ast.TryStar)

# 允许的模块白名单 (Import/ImportFrom 只能白名单)
# P0 (b): operator/logging 已移出 (见模块 docstring 审计表)
_ALLOWED_MODULES = {"math", "re", "json", "copy", "datetime", "collections", "itertools",
                    "functools", "typing", "statistics", "decimal", "fractions", "hashlib",
                    "warnings",
                    "base64", "uuid", "string", "textwrap"}

# P0 (b): 模块级自动注入 — AST 检查 / _safe_import / 沙箱 globals 三处零漂移
_MODULE_GLOBALS = {name: __import__(name) for name in sorted(_ALLOWED_MODULES)}

# H-12 fix: 沙箱硬超时 (秒) 与输出大小上限 — LLM 生成的 while True 死循环
# 不再挂死整条管线; 超时/超限判生成失败, 回退 Base Tools。
_SANDBOX_TIMEOUT_SEC = 8.0
_SANDBOX_MAX_LOG_ENTRIES = 50000

# P1 (f): 生成工具执行置信度阈值 — planning (effective confidence 计算) 与
# exec (M-16 低置信跳过) 同源, 禁止任一侧硬编码漂移 (identity 测试守护)
_CONFIDENCE_EXEC_THRESHOLD = 0.7

# ══════════════════════════════════════════════════════════════
# P2 (g)(h): 反馈闭环 — 结构化错误 kind 枚举 / 修复预算 / no-op 检测
# 对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(g)(h)
# ══════════════════════════════════════════════════════════════

# Layer 3 结构化失败 kind 枚举 — 统一错误对象 {source_id, tool, kind, error, line?}
_LAYER3_KINDS = frozenset({
    "ast_blocked", "syntax_error", "dry_run_failed", "exec_timeout", "exec_error",
    "low_confidence", "noop", "key_set_changed", "record_count_changed",
    "log_too_large", "invalid_format", "parse_error", "confidence_invalid",
    "self_check_failed", "self_check_invalid", "unsupported_assert",
})

# 修复预算: 每 source 最多 1 + MAX_REPAIR_ROUNDS 次 LLM 调用 (1 初始 + 2 修复),
# 与 graph Retry (≤2) 叠加仍有限终止 (docs §9.3)
_MAX_REPAIR_ROUNDS = 2

# 可修复 kind — 修复轮重试 / validation 三态门判 Retry 的判据。
# low_confidence → 人工审核 (不可重试); missing_log → 非阻断 (数据已改, 缺审计轨迹)
_REPAIRABLE_KINDS = frozenset(_LAYER3_KINDS - {"low_confidence"})

# 仅允许一次修复轮 (重试一次即止) 的 kind — 结构性缺陷, 再修无益
_KIND_RETRY_ONCE = frozenset({
    "noop", "key_set_changed", "record_count_changed",
    "log_too_large", "self_check_failed",
})

# 不可重试 kind (0 次) — 仅在合法自评 < 阈值时出现, 转人工审核
_KIND_NO_RETRY = frozenset({"low_confidence"})


def _deep_equal(a, b) -> bool:
    """递归深度相等 (P2 h) — no-op 检测的判据。

    - float NaN: 双侧 isnan 特判 (NaN == NaN 判等)
    - None 与缺失等价: 两侧均 None 判等
    - int/float 跨型相等 (1 == 1.0)
    - dict: 键集合不一致 → False
    - bool 与 int 不跨型混判 (True != 1)
    """
    if isinstance(a, float) and a != a:  # NaN
        return isinstance(b, float) and b != b
    if isinstance(b, float) and b != b:
        return False
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a == b


def _detect_noop(records_before, result) -> dict:
    """(h) no-op 检测: 执行后所有记录深度相等 → {"noop": True}。

    调用前提: result 已通过 _validate_generated_result (记录数/键集合一致),
    故仅需逐条比较值; 记录数不等视为数据已变 (正常不会到达 — 门先拦)。
    """
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list) or not isinstance(records_before, list):
        return {"noop": True}
    if len(data) != len(records_before):
        return {"noop": False}
    for orig, new in zip(records_before, data):
        if not _deep_equal(orig, new):
            return {"noop": False}
    return {"noop": True}


def _sample_has_target_issue(issues_text, sample_records) -> bool:
    """(h) dry-run unverifiable 预检: 样本是否真实存在 issues 描述的目标问题。

    探针规则 (按 issues 文本关键词, 逐条记录检查):
      "~prefix"/"format"   → str 值以 ~≈<>≤≥ 开头
      "non-numeric"/"NaN"  → 非数值 str 或 NaN 值
      "missing units"      → 数值值且无 unit
      "missing provenance" → provenance 不完整

    返回 True = 目标问题在样本中可验证; False = 无法验证 (unverifiable → 放行,
    不判 noop — 避免样本形态与全量数据的差异导致误拒)。
    """
    text = (issues_text or "").lower()
    if not text or not sample_records:
        return False
    from quality_pipeline.tools.assessment.source_utils import provenance_is_complete
    for rec in sample_records:
        if not isinstance(rec, dict):
            continue
        val = rec.get("field_value")
        unit = rec.get("field_unit")
        if ("~prefix" in text or "format" in text) \
                and isinstance(val, str) \
                and val.strip().startswith(("~", "≈", "<", ">", "≤", "≥")):
            return True
        if "non-numeric" in text or "nan" in text:
            if isinstance(val, str) and not _is_numeric_like(val):
                return True
            if isinstance(val, float) and val != val:
                return True
        if "missing units" in text and _is_numeric_like(val) \
                and (unit is None or unit == ""):
            return True
        if "provenance" in text and not provenance_is_complete(rec):
            return True
    return False


def _safe_import(name, *args, **kwargs):
    """受限 import 包装器 (C1 fix): 仅允许白名单模块, 防沙箱逃逸。

    exec 的 import 语句经 __builtins__['__import__'] 解析, 直接删除会让
    `import math` 等报错; 此包装器是 AST 白名单之外的第二道运行时防线。
    """
    base = name.split(".")[0]
    if base not in _ALLOWED_MODULES:
        raise ImportError(f"[Sandbox] Module '{name}' not allowed")
    return __import__(name, *args, **kwargs)


def _make_sandbox() -> dict:
    """创建独立的安全沙箱 (V3.1 fix: 每 source 一个, 避免并发共享污染)。

    C1 fix: 不再裸暴露 __import__ 与 type (逃逸链: __import__→os.system /
    type.__subclasses__→任意类); __import__ 由 _safe_import 白名单包装器接管。
    P0 (b): builtins 扩充 (reversed/next/iter/type/repr/format/issubclass/
    callable/id/hash/frozenset/bytes/bytearray/complex/divmod/pow/ord/chr +
    6 异常类); type 放行的安全前提是 _validate_code_ast 的 dunder 属性块
    (type.__subclasses__/__mro__ 均被拦); 不放 open/eval/exec/compile/
    getattr/setattr/delattr/input。模块 globals 由 _MODULE_GLOBALS 全量注入
    (含 itertools/statistics — dry-run 与执行端自动一致)。
    """
    safe_builtins = {
        "True": True, "False": False, "None": None,
        "__import__": _safe_import,  # C1 fix: 白名单包装器 (第二道防线)
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "filter": filter, "float": float, "int": int,
        "isinstance": isinstance, "len": len, "list": list, "map": map,
        "max": max, "min": min, "print": print, "range": range,
        "round": round, "set": set, "sorted": sorted, "str": str,
        "sum": sum, "tuple": tuple, "zip": zip,
        # P0 (b): 常见数据清洗操作/类型/异常类 (见模块 docstring 审计表)
        "reversed": reversed, "next": next, "iter": iter, "type": type,
        "repr": repr, "format": format, "issubclass": issubclass,
        "callable": callable, "id": id, "hash": hash, "frozenset": frozenset,
        "bytes": bytes, "bytearray": bytearray, "complex": complex,
        "divmod": divmod, "pow": pow, "ord": ord, "chr": chr,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
        "StopIteration": StopIteration, "RuntimeError": RuntimeError,
        "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
        "ArithmeticError": ArithmeticError, "LookupError": LookupError,
    }
    return {
        "__builtins__": safe_builtins,
        **_MODULE_GLOBALS,
    }


def _validate_generated_result(records_before, result, max_logs):
    """共享不变量门 (M-19): Normalization 工具只允许修改, 禁止增删记录/增删字段键。

    dry-run 与全量执行共用同一门 (P0 (c) SSOT), 保证两侧判定一致。

    Args:
        records_before: 执行前记录列表。
        result:        工具返回 (应为 {"data": [...], "log": [...], ...})。
        max_logs:      log 条数上限 (_SANDBOX_MAX_LOG_ENTRIES)。

    Returns:
        {"ok": True, "kind": None, "message": ""} 或
        {"ok": False, "kind": <kind>, "message": <说明>}
        kind ∈ {invalid_format, record_count_changed, key_set_changed, log_too_large}
    """
    if not isinstance(result, dict) or "data" not in result:
        return {"ok": False, "kind": "invalid_format",
                "message": "invalid return format (expected dict with 'data')"}
    data = result.get("data")
    if not isinstance(data, list):
        return {"ok": False, "kind": "invalid_format", "message": "'data' is not a list"}
    # M-19 fix: 记录数一致性 — 禁止增删记录
    if len(data) != len(records_before):
        return {"ok": False, "kind": "record_count_changed",
                "message": f"record count changed {len(records_before)} -> {len(data)}"}
    # M-19 fix: 字段键集合校验 — 禁止新增/删除字段键
    for orig, new in zip(records_before, data):
        if not isinstance(new, dict) or set(new.keys()) != set(orig.keys()):
            return {"ok": False, "kind": "key_set_changed",
                    "message": "field key set changed (tools must not add/remove keys)"}
    # H-12 fix: 输出大小上限 (log 条数)
    logs = result.get("log") or []
    if not isinstance(logs, list):
        logs = []
    if len(logs) > max_logs:
        return {"ok": False, "kind": "log_too_large",
                "message": f"log too large ({len(logs)} entries, max {max_logs})"}
    return {"ok": True, "kind": None, "message": ""}


# ══════════════════════════════════════════════════════════════
# P1 (f): confidence 契约 — LLM 输出结构化自检规格 (Pydantic 校验)
# 对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(f) (§5 层 B 契约块)
# ══════════════════════════════════════════════════════════════

# self_check.assertions 的断言类型枚举 (确定性逐条验证)
_ASSERT_TYPES = Literal[
    "no_tilde_prefix", "all_numeric", "no_nan", "all_str", "trimmed",
    "no_empty_str", "unit_present", "unit_equals", "value_equals",
    "changed", "record_count_unchanged", "key_set_unchanged",
]


class SelfCheckAssertion(BaseModel):
    """单条自检断言。assert 是 Python 关键字, 用 assert_ + Field(alias='assert')。

    field 允许空串 — record_count_unchanged / key_set_unchanged 为全局断言,
    无特定字段。
    """

    model_config = {"populate_by_name": True}
    field: str = Field(default="", description="断言针对的字段名 (全局断言可为空)")
    assert_: _ASSERT_TYPES = Field(alias="assert", description="断言类型枚举")
    expected: Any = None


class SamplePrediction(BaseModel):
    """LLM 对单条记录的 before/after 预测 — 程序化比对防止幻觉 (IEEE TSE 2024)。"""

    record_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    before: Any = None
    after: Any = None


class SelfCheck(BaseModel):
    """LLM 生成工具的自检契约 (max 12 断言 + max 3 样本预测)。"""

    assertions: list[SelfCheckAssertion] = Field(default_factory=list, max_length=12)
    sample_predictions: list[SamplePrediction] = Field(default_factory=list, max_length=3)


class ToolGenResponse(BaseModel):
    """Layer 3 LLM 输出的严格 JSON 契约 — 缺 confidence 即校验失败 (不再默认 0.5)。"""

    tool_name: str = Field(min_length=1)
    tool_code: str = Field(min_length=10)
    confidence: float = Field(ge=0.0, le=1.0, description="必填 0-1, 自评信号不是考试分数")
    self_check: SelfCheck | None = None
    reasoning: str | None = None


def _parse_tool_response(llm_data) -> dict:
    """Pydantic 校验 LLM 工具生成响应 → 结构化结果。

    Returns:
        成功: {"ok": True, "model": ToolGenResponse}
        失败: {"ok": False, "kind": <kind>, "message": <说明>}
        kind 映射: 非 dict/缺 tool_name/tool_code 等关键字段 → parse_error;
                   confidence 缺失/非数值/越界 → confidence_invalid;
                   self_check 结构非法 → self_check_invalid。
    """
    if not isinstance(llm_data, dict):
        return {"ok": False, "kind": "parse_error",
                "message": "LLM response is not a JSON object"}
    try:
        model = ToolGenResponse.model_validate(llm_data)
    except ValidationError as e:
        root_locs = {err.get("loc")[0] for err in e.errors() if err.get("loc")}
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in e.errors()[:3])
        if "confidence" in root_locs:
            return {"ok": False, "kind": "confidence_invalid",
                    "message": f"invalid confidence: {detail}"}
        if "self_check" in root_locs:
            return {"ok": False, "kind": "self_check_invalid",
                    "message": f"invalid self_check: {detail}"}
        return {"ok": False, "kind": "parse_error",
                "message": f"invalid tool response: {detail}"}
    return {"ok": True, "model": model}


def _self_check_values_equal(a, b) -> bool:
    """自检值比对: None 等值 / NaN 特判 / 数值跨型 (str "770" == 770) / 否则字符串比对。"""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and a != a:  # NaN
        return isinstance(b, float) and b != b
    if isinstance(b, float) and b != b:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    # L3 实测修正: LLM 常把 before 写成数值化后的值 ('~770'→770、'1,200'→1200),
    # 逐字 str 比较会误拒合法工具 → 用 parse_numeric 做数值等价 (含逗号剥离兜底)。
    try:
        from ..tools._parse_utils import parse_numeric
        a_n, b_n = parse_numeric(str(a)), parse_numeric(str(b))
        if a_n is None or b_n is None:
            # 千分位逗号剥离后再试 ('1,200' → 1200)
            a_n = parse_numeric(str(a).replace(",", "").replace(" ", ""))
            b_n = parse_numeric(str(b).replace(",", "").replace(" ", ""))
        if a_n is not None and b_n is not None:
            return a_n == b_n
    except Exception:
        pass
    return str(a) == str(b)


def _is_numeric_like(val) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        try:
            float(val.strip())
            return True
        except (TypeError, ValueError):
            return False
    return False


def _check_single_assertion(rec, field: str, assert_type: str, expected) -> bool:
    """单条断言对单条记录的确定性检查 (断言类型由 _ASSERT_TYPES Literal 约束)。"""
    rec = rec if isinstance(rec, dict) else {}
    val = rec.get(field)
    if assert_type == "no_tilde_prefix":
        return not (isinstance(val, str) and val.strip().startswith("~"))
    if assert_type == "all_numeric":
        return _is_numeric_like(val)
    if assert_type == "no_nan":
        return not (isinstance(val, float) and val != val)
    if assert_type == "all_str":
        return isinstance(val, str)
    if assert_type == "trimmed":
        return not (isinstance(val, str) and val.strip() != val)
    if assert_type == "no_empty_str":
        return not (isinstance(val, str) and val.strip() == "")
    if assert_type == "unit_present":
        u = rec.get("field_unit")
        return u is not None and u != ""
    if assert_type == "unit_equals":
        return _self_check_values_equal(rec.get("field_unit"), expected)
    if assert_type == "value_equals":
        return _self_check_values_equal(val, expected)
    return True  # 未知类型 (正常不会到达 — Pydantic Literal 已约束)


def _find_record(records, record_id):
    for r in records:
        if isinstance(r, dict) and r.get("record_id") == record_id:
            return r
    return None


def _verify_self_check(result, self_check, records_before) -> dict:
    """确定性验证 LLM 自检契约 (P1 f) — dry-run 与 _execute_generated 共用。

    必须在 M-19 键集合检查之后调用 (result 已通过记录数/键集合不变校验,
    与 records_before 同序同长)。断言逐条检查 + sample_predictions
    before/after 比对 (before 与真实输入不符即拦截)。

    Returns:
        {"ok": bool, "failed": [{"assert": <类型>, "field": ..., "message": ...}]}
    """
    if not self_check:
        return {"ok": True, "failed": []}
    if isinstance(self_check, dict):
        try:
            self_check = SelfCheck.model_validate(self_check)
        except ValidationError as e:
            return {"ok": False, "failed": [
                {"assert": "self_check_invalid", "field": "",
                 "message": f"invalid self_check contract: {e}"}]}
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return {"ok": False, "failed": [
            {"assert": "self_check_invalid", "field": "",
             "message": "result has no 'data' list"}]}
    before = list(records_before)
    failed = []

    for a in self_check.assertions:
        atype = a.assert_
        field = a.field
        if atype == "record_count_unchanged":
            if len(data) != len(before):
                failed.append({"assert": atype, "field": field,
                               "message": f"record count {len(before)} -> {len(data)}"})
        elif atype == "key_set_unchanged":
            for idx, (orig, new) in enumerate(zip(before, data)):
                if isinstance(orig, dict) and isinstance(new, dict) \
                        and set(new.keys()) != set(orig.keys()):
                    failed.append({"assert": atype, "field": field,
                                   "message": f"key set changed at index {idx}"})
                    break
        elif atype == "changed":
            # L3 实测修正: LLM 常把 changed 的 field 写成 record_id 等恒不变键 →
            # 逐记录值比较误报。changed 语义放宽为"工具级产生了修改"(log 非空),
            # 不再绑定具体字段值变化。
            log_entries = result.get("log") if isinstance(result, dict) else None
            if not log_entries:
                failed.append({"assert": atype, "field": field or "?",
                               "message": "no modifications recorded (log empty)"})
        else:
            for idx, rec in enumerate(data):
                if not _check_single_assertion(rec, field, atype, a.expected):
                    failed.append({"assert": atype, "field": field,
                                   "message": f"assertion failed at index {idx}"})
                    break  # 每断言只报首条失败, 避免 log 爆炸

    for p in self_check.sample_predictions:
        before_rec = _find_record(before, p.record_id)
        if before_rec is None:
            failed.append({"assert": "sample_prediction", "field": p.field,
                           "message": f"record {p.record_id} not found in input"})
            continue
        actual_before = before_rec.get(p.field) if isinstance(before_rec, dict) else None
        if not _self_check_values_equal(actual_before, p.before):
            failed.append({"assert": "sample_prediction", "field": p.field,
                           "message": f"before mismatch for {p.record_id}: "
                                      f"predicted {p.before!r}, actual {actual_before!r}"})
            continue
        after_rec = _find_record(data, p.record_id)
        if after_rec is None:
            failed.append({"assert": "sample_prediction", "field": p.field,
                           "message": f"record {p.record_id} not found in result"})
            continue
        actual_after = after_rec.get(p.field) if isinstance(after_rec, dict) else None
        if not _self_check_values_equal(actual_after, p.after):
            failed.append({"assert": "sample_prediction", "field": p.field,
                           "message": f"after mismatch for {p.record_id}: "
                                      f"predicted {p.after!r}, actual {actual_after!r}"})
    return {"ok": not failed, "failed": failed}


def _compute_effective_confidence(llm_confidence: float, self_check_ok: bool) -> float:
    """effective = llm_confidence × (self_check 通过 ? 1.0 : 0.3) — exec 只消费 effective。"""
    return float(llm_confidence) * (1.0 if self_check_ok else 0.3)


# 危险函数名黑名单 (即使 AST 节点在白名单中也拒绝)
_FORBIDDEN_FUNCTIONS = {"eval", "exec", "compile", "open",
                        "getattr", "setattr", "delattr", "globals", "locals",
                        "breakpoint", "input",
                        # 防止沙箱逃逸: 显式调用 __import__ 或 __subclasses__ 链
                        "__import__", "__subclasses__", "__class__",
                        "__bases__", "__mro__", "__subclasshook__",
                        "__init_subclass__"}


class _AstVerdict(dict):
    """AST 校验结构化结果 dict — 真值兼容既有 `if not _validate_code_ast(...)` 判断。

    allowed=False 时 falsy (非空 dict 默认 truthy, 故覆写 __bool__)。
    """

    def __bool__(self):
        return bool(self.get("allowed", False))


def _block(line, message):
    return _AstVerdict({"allowed": False, "kind": "ast_blocked",
                        "line": line, "message": message})


def _allow():
    return _AstVerdict({"allowed": True, "kind": None,
                        "line": None, "message": ""})


def _find_counter_augment(loop_node: ast.While, counter: str, want_add: bool) -> bool:
    """在循环体 (不含嵌套函数/循环) 内查找 counter 的 AugAssign 方向匹配 (P1 a)。

    Lt/LtE 系 (i < N) 需要 AugAssign(Add) 递增逼近上界;
    Gt/GtE 系 (i > 0) 需要 AugAssign(Sub) 递减逼近下界。
    """
    stack = list(loop_node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                          ast.While, ast.For, ast.AsyncFor)):
            continue  # 嵌套函数/循环整体跳过
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) \
                and n.target.id == counter:
            if isinstance(n.op, ast.Add) and want_add:
                return True
            if isinstance(n.op, ast.Sub) and not want_add:
                return True
        stack.extend(ast.iter_child_nodes(n))
    return False


def _check_while_bounded(node: ast.While):
    """while 终止性判定 (泛化版): 返回 None=放行, 否则返回拒绝消息。

    泛化原则 (L3 实测修正): 静态判定只拦截**确定无界**的 while (条件为常量真
    且无 break) —— 这是唯一能静态证伪的情况。其余条件 (有界计数器/len() 边界/
    任意复杂条件) 一律放行, 终止性由运行时 _SANDBOX_TIMEOUT_SEC=8s 硬超时兜底
    (P4 Job Object 可真杀)。此前"无 break 即拒"误杀了 LLM 常见的
    while idx < len(s): idx += 1 写法。
    """
    line = getattr(node, "lineno", None)
    cond_summary = ast.unparse(node.test)[:60]

    # 常量假条件 → 循环体永不执行 → 放行
    if isinstance(node.test, ast.Constant) and not node.test.value:
        return None

    # 常量真条件 (while True / while 1) 且无 break → 确定无界 → 拒绝
    if isinstance(node.test, ast.Constant) and bool(node.test.value):
        if not any(isinstance(n, ast.Break) for n in ast.walk(node)):
            return (f"unbounded while loop at line {line} (condition: {cond_summary}); "
                    f"use a bounded counter (e.g. while i < N: i += 1) or a break")
        return None

    # break 存在 → 放行 (运行时超时兜底)
    if any(isinstance(n, ast.Break) for n in ast.walk(node)):
        return None

    # 其余复杂条件 → 泛化放行, 由运行时超时兜底
    return None


def _validate_code_ast(code: str):
    """AST 白名单校验 (P1 a 结构化): 拒绝含危险节点的代码 (V2.1)。

    Returns:
        结构化 _AstVerdict: {"allowed": bool, "kind": "ast_blocked"|None,
                             "line": int|None, "message": str}
        — 真值语义: allowed=True 时 truthy, 拒绝时 falsy (兼容既有 `if not` 调用方)。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return _block(getattr(e, "lineno", None), f"syntax error: {e.msg}")

    for node in ast.walk(tree):
        # 拒绝非白名单节点类型
        if type(node) not in _ALLOWED_AST_NODES:
            logger.warning("[Sandbox] Blocked AST node: %s", type(node).__name__)
            return _block(getattr(node, "lineno", None),
                          f"blocked AST node: {type(node).__name__}")

        # 对 Import/ImportFrom 校验模块白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod not in _ALLOWED_MODULES:
                    logger.warning("[Sandbox] Blocked import: %s", alias.name)
                    return _block(getattr(node, "lineno", None),
                                  f"blocked import: {alias.name}")
        if isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod not in _ALLOWED_MODULES:
                    logger.warning("[Sandbox] Blocked import from: %s", node.module)
                    return _block(getattr(node, "lineno", None),
                                  f"blocked import from: {node.module}")

        # P1 (a): Name 黑名单仅 Load 上下文 — 杀死别名赋值逃逸
        # (e.g. `_imp = __import__` 中 __import__ 是 Name Load), 同时 Store/Del
        # 撞名 (如 `eval = 5`) 放行 — 黑名单名不可变绑定本身无逃逸面
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in _FORBIDDEN_FUNCTIONS:
                logger.warning("[Sandbox] Blocked name reference: %s", node.id)
                return _block(getattr(node, "lineno", None),
                              f"blocked name reference: {node.id}")

        # P1 (a): while 三档判定 — 常量假 → 有界计数器 → break → 拒绝 (带行号/条件摘要)
        if isinstance(node, ast.While):
            block_msg = _check_while_bounded(node)
            if block_msg:
                logger.warning("[Sandbox] %s", block_msg)
                return _block(getattr(node, "lineno", None), block_msg)

        # C1 fix: 任何 dunder 属性访问拒绝 — 杀死属性链逃逸
        # (x.__class__.__mro__ / type.__subclasses__ / obj.__getattribute__ 等),
        # 白名单例外: __name__ (模板代码中仅作可读属性使用)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr != "__name__":
                logger.warning("[Sandbox] Blocked dunder attribute: %s", node.attr)
                return _block(getattr(node, "lineno", None),
                              f"blocked dunder attribute: {node.attr}")

        # 对函数调用校验危险函数名 — 仅拦**裸 Name 调用** (compile(...)/eval(...))。
        # L3 实测修正: Attribute 形式 (re.compile(...)) 曾被按 attr 名误杀 —
        # 模块限定调用由 _ALLOWED_MODULES 白名单保证安全 (os/sys 进不来),
        # 记录数据 (dict/list/str) 无危险方法, dunder 属性块已拦 __ 前缀。
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            if func_name and func_name in _FORBIDDEN_FUNCTIONS:
                logger.warning("[Sandbox] Blocked function call: %s()", func_name)
                return _block(getattr(node, "lineno", None),
                              f"blocked function call: {func_name}()")

    return _allow()
