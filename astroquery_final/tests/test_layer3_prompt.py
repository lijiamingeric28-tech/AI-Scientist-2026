"""P1 Layer 3 优化测试 — confidence 契约 (f) + AST 白名单修复 (a) + schema prompt (d)。

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(a)(d)(f) (P1):
  (a) NamedExpr/Match 节点放行 + while 三档判定 + Name 黑名单仅 Load + 结构化返回
  (d) _build_schema_block + golden few-shot 选取
  (f) ToolGenResponse Pydantic 契约 + _verify_self_check 矩阵 + effective confidence
全部离线 (0 LLM 0 网络)。
"""

import math
import pytest
import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环
from pydantic import ValidationError


# ═════════════════════════════════ (f) Pydantic 契约 ═════════════════════════════

def _tool_response_model():
    from quality_pipeline.sandbox.sandbox_common import ToolGenResponse
    return ToolGenResponse


def test_toolgen_response_missing_confidence_fails():
    """缺 confidence → Pydantic 校验失败 (不再默认 0.5)。"""
    ToolGenResponse = _tool_response_model()
    with pytest.raises(ValidationError):
        ToolGenResponse.model_validate({
            "tool_name": "t", "tool_code": "for r in records:\n    pass" * 2,
        })


def test_toolgen_response_string_confidence_fails():
    """confidence="high" → 校验失败。"""
    ToolGenResponse = _tool_response_model()
    with pytest.raises(ValidationError):
        ToolGenResponse.model_validate({
            "tool_name": "t", "tool_code": "for r in records:\n    pass" * 2,
            "confidence": "high",
        })


def test_toolgen_response_out_of_range_confidence_fails():
    ToolGenResponse = _tool_response_model()
    with pytest.raises(ValidationError):
        ToolGenResponse.model_validate({
            "tool_name": "t", "tool_code": "for r in records:\n    pass" * 2,
            "confidence": 1.5,
        })


def test_toolgen_response_valid_passes():
    """合法响应 → 校验通过, self_check 契约 (assert alias) 正确解析。"""
    ToolGenResponse = _tool_response_model()
    m = ToolGenResponse.model_validate({
        "tool_name": "strip_prefix",
        "tool_code": "for r in records:\n    pass" * 2,
        "confidence": 0.9,
        "self_check": {
            "assertions": [
                {"field": "field_value", "assert": "no_tilde_prefix"},
                {"field": "field_value", "assert": "changed", "expected": None},
            ],
            "sample_predictions": [
                {"record_id": "r1", "field": "field_value", "before": "~5", "after": "5"},
            ],
        },
        "reasoning": "strip tilde",
    })
    assert m.tool_name == "strip_prefix"
    assert m.confidence == 0.9
    assert len(m.self_check.assertions) == 2
    assert m.self_check.assertions[0].assert_ == "no_tilde_prefix"  # alias 填充
    assert m.self_check.sample_predictions[0].before == "~5"


def test_toolgen_response_short_tool_code_fails():
    """tool_code 长度 < 10 → 校验失败 (parse_error 语义)。"""
    ToolGenResponse = _tool_response_model()
    with pytest.raises(ValidationError):
        ToolGenResponse.model_validate({
            "tool_name": "t", "tool_code": "x = 1", "confidence": 0.9,
        })


def test_parse_tool_response_kind_mapping():
    """_parse_tool_response kind 映射: confidence→confidence_invalid / self_check→
    self_check_invalid / 缺关键键→parse_error。"""
    from quality_pipeline.sandbox.sandbox_common import _parse_tool_response
    # 缺 confidence
    r = _parse_tool_response({"tool_name": "t", "tool_code": "x" * 20})
    assert not r["ok"] and r["kind"] == "confidence_invalid"
    # 非数值 confidence
    r = _parse_tool_response({"tool_name": "t", "tool_code": "x" * 20, "confidence": "high"})
    assert not r["ok"] and r["kind"] == "confidence_invalid"
    # 非法 self_check (断言类型不在枚举)
    r = _parse_tool_response({"tool_name": "t", "tool_code": "x" * 20, "confidence": 0.9,
                              "self_check": {"assertions": [{"field": "f", "assert": "bogus"}]}})
    assert not r["ok"] and r["kind"] == "self_check_invalid"
    # 缺 tool_name
    r = _parse_tool_response({"tool_code": "x" * 20, "confidence": 0.9})
    assert not r["ok"] and r["kind"] == "parse_error"
    # 非 dict
    r = _parse_tool_response("not a dict")
    assert not r["ok"] and r["kind"] == "parse_error"
    # 合法
    r = _parse_tool_response({"tool_name": "t", "tool_code": "x" * 20, "confidence": 0.9})
    assert r["ok"] and r["model"].confidence == 0.9


def test_confidence_threshold_shared_identity():
    """_CONFIDENCE_EXEC_THRESHOLD planning/exec 同源 (identity 防漂移), 值=0.7。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        _CONFIDENCE_EXEC_THRESHOLD as na_conf,
    )
    from quality_pipeline.sandbox.sandbox_common import (
        _CONFIDENCE_EXEC_THRESHOLD as sc_conf,
    )
    assert na_conf is sc_conf
    assert na_conf == 0.7
    # 执行端 re-export 了共享工厂
    from subgraphs.data_normalization.agents.normalization_agent import _verify_self_check
    from quality_pipeline.sandbox.sandbox_common import _verify_self_check as sc_verify
    assert _verify_self_check is sc_verify


def test_compute_effective_confidence():
    """effective = llm × (通过 1.0 / 失败 0.3)。"""
    from quality_pipeline.sandbox.sandbox_common import _compute_effective_confidence
    assert _compute_effective_confidence(0.9, True) == pytest.approx(0.9)
    assert _compute_effective_confidence(0.9, False) == pytest.approx(0.27)
    assert _compute_effective_confidence(1.0, False) == pytest.approx(0.3)


# ═══════════════════════════ (f) _verify_self_check 断言矩阵 ═══════════════════════════

def _verify(result, self_check, records_before):
    from quality_pipeline.sandbox.sandbox_common import _verify_self_check
    return _verify_self_check(result, self_check, records_before)


def _rec(rid, val, unit=""):
    return {"record_id": rid, "field_name": "f", "field_value": val, "field_unit": unit}


def _assertion(field, assert_type, expected=None):
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SelfCheckAssertion
    return SelfCheck(assertions=[SelfCheckAssertion(field=field, assert_=assert_type,
                                                    expected=expected)])


def test_self_check_assertion_matrix():
    """断言类型矩阵: 每种类型通过/失败路径。"""
    # (assert_type, before_val, after_val, expected, unit, pass_ok)
    cases = [
        ("no_tilde_prefix", "5", "5", None, "", True),
        ("no_tilde_prefix", "~5", "~5", None, "", False),
        ("all_numeric", "5", "5", None, "", True),
        ("all_numeric", "5", "abc", None, "", False),
        ("no_nan", 5.0, 5.0, None, "", True),
        ("no_nan", 5.0, float("nan"), None, "", False),
        ("all_str", "5", "5", None, "", True),
        ("all_str", "5", 5, None, "", False),
        ("trimmed", "a", "a", None, "", True),
        ("trimmed", "a", " a ", None, "", False),
        ("no_empty_str", "a", "a", None, "", True),
        ("no_empty_str", "a", "", None, "", False),
        ("unit_present", "5", "5", None, "pc", True),
        ("unit_present", "5", "5", None, "", False),
        ("unit_equals", "5", "5", "pc", "pc", True),
        ("unit_equals", "5", "5", "kpc", "pc", False),
        ("value_equals", "5", "5", "5", "", True),
        ("value_equals", "5", "5", "10", "", False),
        ("changed", "5", "6", None, "", True),
        ("changed", "5", "5", None, "", False),
    ]
    for atype, before, after, expected, unit, should_pass in cases:
        sc = _assertion("field_value", atype, expected)
        rec_before = _rec("r1", before, unit)
        rec_after = _rec("r1", after, unit)
        result = {"data": [rec_after]}
        if atype == "changed":
            # L3 泛化: changed 判定 = 工具级 log 非空 (不绑定字段值/逐记录比较)
            result["log"] = [{"record_id": "r1", "action": "x"}] if after != before else []
        r = _verify(result, sc, [rec_before])
        assert r["ok"] is should_pass, f"assert={atype} should_pass={should_pass}, got {r}"


def test_self_check_global_assertions():
    """record_count_unchanged / key_set_unchanged 全局断言。"""
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SelfCheckAssertion
    b = [_rec("r1", "5"), _rec("r2", "6")]
    # 记录数变 → 失败
    sc = SelfCheck(assertions=[SelfCheckAssertion(field="", assert_="record_count_unchanged")])
    assert not _verify({"data": [_rec("r1", "5")]}, sc, b)["ok"]
    assert _verify({"data": [dict(x) for x in b]}, sc, b)["ok"]
    # 键集合变 → 失败
    sc = SelfCheck(assertions=[SelfCheckAssertion(field="", assert_="key_set_unchanged")])
    changed = [dict(x, _extra=1) for x in b]
    assert not _verify({"data": changed}, sc, b)["ok"]
    assert _verify({"data": [dict(x) for x in b]}, sc, b)["ok"]


def test_self_check_sample_predictions_before_mismatch():
    """sample_predictions before 与真实输入不一致 → 拦截。"""
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SamplePrediction
    b = [_rec("r1", "5")]
    sc = SelfCheck(sample_predictions=[
        SamplePrediction(record_id="r1", field="field_value", before="99", after="6")])
    r = _verify({"data": [_rec("r1", "6")]}, sc, b)
    assert not r["ok"]
    assert any("before mismatch" in f["message"] for f in r["failed"])


def test_self_check_sample_predictions_after_mismatch():
    """sample_predictions after 与真实输出不符 → 拦截。"""
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SamplePrediction
    b = [_rec("r1", "5")]
    sc = SelfCheck(sample_predictions=[
        SamplePrediction(record_id="r1", field="field_value", before="5", after="99")])
    r = _verify({"data": [_rec("r1", "6")]}, sc, b)
    assert not r["ok"]
    assert any("after mismatch" in f["message"] for f in r["failed"])


def test_self_check_sample_predictions_ok():
    """before/after 均一致 → 通过。"""
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SamplePrediction
    b = [_rec("r1", "5")]
    sc = SelfCheck(sample_predictions=[
        SamplePrediction(record_id="r1", field="field_value", before="5", after="6")])
    assert _verify({"data": [_rec("r1", "6")]}, sc, b)["ok"]


def test_self_check_missing_record_intercepted():
    """prediction 指向不存在的 record_id → 拦截。"""
    from quality_pipeline.sandbox.sandbox_common import SelfCheck, SamplePrediction
    b = [_rec("r1", "5")]
    sc = SelfCheck(sample_predictions=[
        SamplePrediction(record_id="ghost", field="field_value", before="5", after="6")])
    r = _verify({"data": [_rec("r1", "6")]}, sc, b)
    assert not r["ok"] and any("not found" in f["message"] for f in r["failed"])


def test_self_check_none_passes():
    """无 self_check → 恒通过。"""
    assert _verify({"data": []}, None, []) == {"ok": True, "failed": []}


# ═══════════════════════════════ (d) schema prompt ═══════════════════════════════

def test_build_schema_block_structure():
    """_build_schema_block 输出结构: 每字段 12 项 + target_schema 合并 (含别名匹配)。"""
    from subgraphs.data_normalization.agents.planning_agent import _build_schema_block
    target_schema = {"fields": [
        {"name": "yield_strength", "type": "number", "standard_unit": "MPa",
         "criticality": "critical", "aliases": ["YS", "yield_stress"]},
        {"name": "elongation", "type": "number", "standard_unit": "%",
         "criticality": "important", "aliases": ["EL"]},
    ]}
    profile = {
        "YS": {"count": 3, "types": {"numeric": 3}, "sample_values": [450, 460],
               "sample_units": ["MPa"], "null_count": 0,
               "numeric_range": "[450, 460]", "has_provenance": 1.0},
        "elongation": {"count": 2, "types": {"string": 2}, "sample_values": ["12 %", "13 %"],
                       "sample_units": [], "null_count": 1,
                       "numeric_range": None, "has_provenance": 0.5},
        "extra_field": {"count": 1, "types": {"string": 1}, "sample_values": ["x"],
                        "sample_units": [], "null_count": 0,
                        "numeric_range": None, "has_provenance": 0.0},
    }
    import json
    block = json.loads(_build_schema_block(target_schema, profile))
    assert set(block.keys()) == {"YS", "elongation", "extra_field"}
    ys = block["YS"]
    # 12 项结构
    for key in ("inferred_type", "types_seen", "missing_rate", "sample_values",
                "sample_units", "numeric_range", "target_schema_required",
                "schema_type", "standard_unit", "criticality", "aliases"):
        assert key in ys, f"缺少 {key}"
    # 别名匹配 → target_schema 合并
    assert ys["target_schema_required"] is True
    assert ys["schema_type"] == "number" and ys["standard_unit"] == "MPa"
    assert ys["criticality"] == "critical" and ys["aliases"] == ["YS", "yield_stress"]
    assert ys["missing_rate"] == 0.0 and ys["inferred_type"] == "numeric"
    # 直名匹配
    el = block["elongation"]
    assert el["target_schema_required"] is True and el["standard_unit"] == "%"
    assert el["missing_rate"] == 0.5
    # schema 外字段
    ex = block["extra_field"]
    assert ex["target_schema_required"] is False
    assert ex["standard_unit"] is None and ex["criticality"] is None


def test_build_schema_block_none_target_schema():
    """target_schema=None → 不崩溃, 全部 target_schema_required=False。"""
    from subgraphs.data_normalization.agents.planning_agent import _build_schema_block
    import json
    block = json.loads(_build_schema_block(None, {
        "f": {"count": 1, "types": {"numeric": 1}, "sample_values": [1],
              "sample_units": [], "null_count": 0, "numeric_range": "[1, 1]",
              "has_provenance": 0.0},
    }))
    assert block["f"]["target_schema_required"] is False


def test_few_shot_load_and_keyword_selection():
    """tool_examples.yaml 加载 4 条; 按 issue 关键词匹配选取 ≤3 条注入。"""
    import textwrap
    from subgraphs.data_normalization.agents.planning_agent import (
        _load_tool_examples, _render_few_shots,
    )
    examples = _load_tool_examples()
    assert len(examples) >= 4
    for ex in examples:
        code = ex.get("tool_code", "")
        # 模板契约: yaml 解析后顶层语句 0 缩进、嵌套语句恰 4 空格 —
        # 加 4 空格前缀 (与 _indent_into_function 同语义) 后必须是合法函数体
        compile("def _wrapper():\n" + textwrap.indent(code, "    "), "<t>", "exec")
        assert "confidence" in ex and "self_check" in ex
    # 关键词匹配: unit 类问题 → unit_normalize 排最前
    out = _render_few_shots("- 12 numeric records missing units")
    assert "unit_normalize" in out
    assert out.count("示例 ") <= 3
    # 关键词不命中 → 依序取 3 条
    out2 = _render_few_shots("nothing matches here")
    assert out2.count("示例 ") == 3


# ═══════════════════════════════ (a) AST 白名单 ═══════════════════════════════

def _validate(code):
    from quality_pipeline.sandbox.sandbox_common import _validate_code_ast
    return _validate_code_ast(code)


def test_bounded_while_allowed():
    """有界计数器放行: Lt/Add 与 Gt/Sub 两方向。"""
    assert _validate("def tool(records):\n    i = 0\n    while i < 10:\n        i += 1")
    assert _validate("def tool(records):\n    i = 10\n    while i > 0:\n        i -= 1")
    assert _validate("def tool(records):\n    i = 0\n    while i <= 10:\n        i += 1")
    # 条件常量假 → 放行
    assert _validate("def tool(records):\n    while False:\n        pass")


def test_unbounded_while_rejected_with_line():
    """无界 while 拒绝, 结构化结果带 line 与条件摘要消息。"""
    res = _validate("def tool(records):\n    while True:\n        pass")
    assert res["allowed"] is False
    assert res["kind"] == "ast_blocked"
    assert res["line"] == 2
    assert "while" in res["message"] and "True" in res["message"]
    # 真值兼容既有 `if not` 调用方
    assert not res


def test_while_break_allowed():
    """有 break 的 while 放行 (运行时硬超时兜底)。"""
    assert _validate("def tool(records):\n    while True:\n"
                     "        if len(records) > 3:\n            break")


def test_nested_loop_counter_allowed():
    """L3 泛化: 复杂条件 while (非"常量真且无 break") 一律放行, 终止性由
    8s 运行时超时兜底 — 嵌套循环/len() 边界等不再静态误杀。"""
    res = _validate("def tool(records):\n    while i < 10:\n"
                    "        for j in range(5):\n            i += 1")
    assert res["allowed"] is True


def test_store_name_collision_allowed():
    """Store 撞名放行 (黑名单名仅 Load 上下文检查)。"""
    assert _validate("def tool(records):\n    eval = 5\n    return records")
    assert _validate("def tool(records):\n    compile = 1\n    return records")
    # Load 上下文仍拦截 (含 __import__ 别名)
    assert not _validate("_imp = __import__")
    assert not _validate("x = eval\nx('1+1')")


def test_walrus_and_match_nodes_allowed_but_escapes_blocked():
    """NamedExpr/Match 节点放行, 但分支内 dunder 逃逸仍拦截。"""
    assert _validate("def tool(records):\n    if (n := len(records)) > 0:\n        pass")
    assert _validate("def tool(records):\n"
                     "    match records[0].get('field_value'):\n"
                     "        case str(v):\n            pass")
    # 对应逃逸 PoC 仍拦截
    assert not _validate("if (t := type.__subclasses__):\n    pass")
    assert not _validate("match x:\n    case _:\n        type.__subclasses__")


def test_structured_verdict_block_fields():
    """结构化拦截: kind=ast_blocked + line (dunder/import/语法错误)。"""
    res = _validate("x = 1\nx.__class__.__mro__")
    assert res["kind"] == "ast_blocked" and res["line"] == 2
    res = _validate("import os")
    assert res["kind"] == "ast_blocked" and res["line"] == 1
    res = _validate("def tool(records):\n    if True\n        pass")  # 语法错误
    assert res["kind"] == "ast_blocked" and res["line"] == 2


def test_runtime_eval_alias_nameerror():
    """运行时防线: 沙箱 builtins 无 eval → `x = eval` 直接 NameError (即使 AST 放行)。"""
    from quality_pipeline.sandbox.sandbox_common import _make_sandbox
    sb = _make_sandbox()
    with pytest.raises(NameError):
        exec("x = eval", sb)


# ═══════════════════════════ (f) exec 端 self_check 挂接 ═══════════════════════════

def test_execute_generated_self_check_attached():
    """_execute_generated 在 M-19 门后执行 self_check, result 携带 effective_confidence。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        NormalizationAgent, _make_sandbox,
    )
    agent = NormalizationAgent()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "~5", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    _log = []\n"
            "    for r in records:\n"
            "        val = r.get('field_value')\n"
            "        if isinstance(val, str) and val.startswith('~'):\n"
            "            r['field_value'] = val[1:]\n"
            "            _log.append({'record_id': r['record_id'], 'field': 'field_value',\n"
            "                         'action': 'strip', 'before': str(val), 'after': val[1:]})\n"
            "    return {'data': records, 'log': _log, 'summary': 'ok'}\n")
    gen = {"tool_name": "tool", "tool_code": code, "confidence": 0.9,
           "self_check": {"assertions": [{"field": "field_value", "assert": "no_tilde_prefix"}],
                          "sample_predictions": [{"record_id": "r1", "field": "field_value",
                                                  "before": "~5", "after": "5"}]},
           "source_id": "s1"}
    r = agent._execute_generated(gen, recs, _make_sandbox())
    assert r is not None
    assert r["effective_confidence"] == pytest.approx(0.9)
    # self_check 失败 (value_equals 期望 999 ≠ 实际 5) → effective ×0.3
    gen_bad = dict(gen)
    gen_bad["self_check"] = {"assertions": [{"field": "field_value", "assert": "value_equals",
                                             "expected": "999"}],
                             "sample_predictions": []}
    r2 = agent._execute_generated(gen_bad, recs, _make_sandbox())
    assert r2 is not None and r2["effective_confidence"] == pytest.approx(0.27)
