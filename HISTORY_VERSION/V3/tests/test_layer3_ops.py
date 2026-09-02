"""P3 Layer 3 层 A 测试 — 模板驱动 ops 执行器 (op_executor) + ops 优先路径。

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §5 层 A (P3):
  - OpSpec / OpSpecResponse Pydantic 契约 (ops 1-8 条, confidence 必填 0-1)
  - execute_ops 各 op 语义 (复用 _parse_utils / unit_converter):
    strip_prefix / numeric_convert / trim / unit_normalize / drop_suffix /
    replace_substring / mark_missing_unit
  - 每 op 后记录数/键集合不变校验 (违规 → kind=op_invariant_failed 结构化失败终止)
  - planning_agent ops 优先路径 (先试 OpSpecResponse, 失败且有 tool_code 才走
    自由代码路径); ops 注册 {mode:"ops", ops, confidence}, confidence 无 0.7 门槛
  - normalization_agent mode=="ops" 走 execute_ops (不进沙箱) + 共享门

全部离线 (mock LLM, 0 网络)。
"""

import json

import pytest

import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环
from pydantic import ValidationError


# ══════════════════════════════ (OpSpecResponse) 契约校验 ══════════════════════════════

def test_op_spec_response_contract():
    """OpSpecResponse: ops 必填 (1-8 条) + confidence 必填 (0-1)。"""
    from quality_pipeline.tools.normalization.op_executor import OpSpecResponse
    # 合法
    m = OpSpecResponse.model_validate(
        {"ops": [{"op": "strip_prefix", "field": "field_value"}], "confidence": 0.9,
         "reasoning": "strip tilde"})
    assert m.ops[0].op == "strip_prefix"
    assert m.ops[0].field == "field_value"
    assert m.confidence == 0.9 and m.reasoning == "strip tilde"
    # 缺 ops → 校验失败
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate({"confidence": 0.9})
    # 空 ops → 校验失败
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate({"ops": [], "confidence": 0.9})
    # 超过 8 条 → 校验失败
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate(
            {"ops": [{"op": "trim"}] * 9, "confidence": 0.9})
    # 缺 confidence → 校验失败
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate({"ops": [{"op": "trim"}]})
    # confidence 越界 → 校验失败
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate({"ops": [{"op": "trim"}], "confidence": 1.5})
    # 非法 op 名 → 校验失败 (Literal)
    with pytest.raises(ValidationError):
        OpSpecResponse.model_validate({"ops": [{"op": "eval_code"}], "confidence": 0.9})


def test_op_spec_defaults():
    """OpSpec 字段默认值: field=field_value, unit_field=field_unit, 其余 None。"""
    from quality_pipeline.tools.normalization.op_executor import OpSpec
    s = OpSpec(op="trim")
    assert s.field == "field_value"
    assert s.unit_field == "field_unit"
    assert s.to is None and s.prefixes is None and s.old is None


# ══════════════════════════════ execute_ops 各 op 语义 ══════════════════════════════

def _rec(rid, val, unit="pc", field="field_value"):
    # field_name 与 op.field 对齐 — unit_converter 按 rec.field_name 匹配转换目标
    return {"record_id": rid, "field_name": field, "field": field,
            "field_value": val, "field_unit": unit}


def _exec(records, ops, **ctx):
    from quality_pipeline.tools.normalization.op_executor import (
        OpSpec, execute_ops,
    )
    specs = [o if isinstance(o, OpSpec) else OpSpec.model_validate(o) for o in ops]
    return execute_ops(records, specs, **ctx)


def test_op_strip_prefix():
    """"~770" → 770 (int); 自定义 prefixes; 剥离后剩余非数值 → 逐 record 错误不中断。"""
    recs = [_rec("r1", "~770"), _rec("r2", "≈ 45.5"), _rec("r3", "770")]
    r = _exec(recs, [{"op": "strip_prefix", "field": "field_value"}])
    assert r["data"][0]["field_value"] == 770
    assert r["data"][1]["field_value"] == 45.5
    assert r["data"][2]["field_value"] == "770"   # 无前缀 → 不变
    assert len(r["log"]) == 2
    assert r["log"][0]["action"] == "strip_prefix"
    assert r["log"][0]["record_id"] == "r1" and r["log"][0]["before"] == "~770"
    assert r["log"][0]["after"] == 770
    assert r["errors"] == []
    # 自定义 prefixes
    r2 = _exec([_rec("r1", "ppx770")],
               [{"op": "strip_prefix", "field": "field_value", "prefixes": ["ppx"]}])
    assert r2["data"][0]["field_value"] == 770
    # 非数值剩余 → 错误收集, 不中断
    r3 = _exec([_rec("r1", "~abc"), _rec("r2", "~771")],
               [{"op": "strip_prefix", "field": "field_value"}])
    assert r3["data"][1]["field_value"] == 771
    assert len(r3["errors"]) == 1
    assert r3["errors"][0]["record_id"] == "r1"
    assert "not numeric" in r3["errors"][0]["reason"]


def test_op_numeric_convert_idempotent():
    """numeric_convert: 字符串数值转 int/float (_to_number 语义); 幂等 (二次执行零修改)。"""
    recs = [_rec("r1", "770"), _rec("r2", "45.5"), _rec("r3", "1e3"), _rec("r4", 5.0)]
    r = _exec(recs, [{"op": "numeric_convert", "field": "field_value"}])
    assert r["data"][0]["field_value"] == 770        # 整数形态 → int
    assert r["data"][1]["field_value"] == 45.5       # 小数 → float
    assert r["data"][2]["field_value"] == 1000.0     # 指数 → float
    assert r["data"][3]["field_value"] == 5.0        # 已数值 → 不变
    assert len(r["log"]) == 3
    # 幂等: 再执行一次 → 零修改 (log 空)
    r2 = _exec(r["data"], [{"op": "numeric_convert", "field": "field_value"}])
    assert r2["log"] == []
    assert r2["data"] == r["data"]
    # 非数值字符串 → 跳过 (与 _to_number 语义一致, 无错误)
    r3 = _exec([_rec("r1", "abc")], [{"op": "numeric_convert", "field": "field_value"}])
    assert r3["data"][0]["field_value"] == "abc" and r3["errors"] == []


def test_op_trim():
    """trim: 去首尾空白 (仅字符串, 变化才写回才记 log)。"""
    recs = [_rec("r1", "  770  "), _rec("r2", "770"), _rec("r3", None)]
    r = _exec(recs, [{"op": "trim", "field": "field_value"}])
    assert r["data"][0]["field_value"] == "770"
    assert r["data"][1]["field_value"] == "770"
    assert r["data"][2]["field_value"] is None
    assert len(r["log"]) == 1 and r["log"][0]["action"] == "trim"


def test_op_unit_normalize_value_and_unit_sync():
    """unit_normalize: 值+单位同步换算 25°C → 298.15 K (委托 unit_converter)。"""
    recs = [_rec("r1", 25.0, "°C", "temperature"), _rec("r2", 25.0, "°C", "temperature")]
    r = _exec(recs, [{"op": "unit_normalize", "field": "temperature",
                      "to": "K"}], research_domain="materials")
    assert r["data"][0]["field_value"] == pytest.approx(298.15)
    assert r["data"][0]["field_unit"] == "K"
    assert r["data"][1]["field_value"] == pytest.approx(298.15)
    assert len(r["log"]) == 2
    assert r["log"][0]["action"] == "unit_normalize"
    assert r["log"][0]["before"] == "25.0" and r["log"][0]["after"] == "298.15"
    assert r["errors"] == []
    # 无换算规则 → unconverted 逐条转 errors (record_id/field/reason), 不中断
    r2 = _exec([_rec("r1", 25.0, "zzz", "temperature")],
               [{"op": "unit_normalize", "field": "temperature", "to": "K"}],
               research_domain="materials")
    assert len(r2["errors"]) == 1
    assert r2["errors"][0]["record_id"] == "r1"
    assert r2["data"][0]["field_value"] == 25.0 and r2["data"][0]["field_unit"] == "zzz"
    # to 缺失 → op 级错误, 跳过本 op
    r3 = _exec([_rec("r1", 25.0, "°C", "temperature")],
               [{"op": "unit_normalize", "field": "temperature"}])
    assert len(r3["errors"]) == 1 and "requires 'to'" in r3["errors"][0]["reason"]


def test_op_drop_suffix():
    """drop_suffix: 去除值末尾 suffix; suffix 缺失 → op 级错误不中断。"""
    recs = [_rec("r1", "770 K"), _rec("r2", "45.5 K"), _rec("r3", "770")]
    r = _exec(recs, [{"op": "drop_suffix", "field": "field_value", "suffix": " K"}])
    assert r["data"][0]["field_value"] == "770"
    assert r["data"][1]["field_value"] == "45.5"
    assert r["data"][2]["field_value"] == "770"   # 无后缀 → 不变
    assert len(r["log"]) == 2
    r2 = _exec([_rec("r1", "770 K")], [{"op": "drop_suffix", "field": "field_value"}])
    assert len(r2["errors"]) == 1 and "requires 'suffix'" in r2["errors"][0]["reason"]


def test_op_replace_substring():
    """replace_substring: old → new 替换; old 缺失 → op 级错误。"""
    recs = [_rec("r1", "abc-770"), _rec("r2", "abc-771")]
    r = _exec(recs, [{"op": "replace_substring", "field": "field_value",
                      "old": "abc-", "new": ""}])
    assert r["data"][0]["field_value"] == "770"
    assert r["data"][1]["field_value"] == "771"
    assert len(r["log"]) == 2
    r2 = _exec([_rec("r1", "abc-770")],
               [{"op": "replace_substring", "field": "field_value", "new": "x"}])
    assert len(r2["errors"]) == 1 and "requires 'old'" in r2["errors"][0]["reason"]


def test_op_mark_missing_unit():
    """mark_missing_unit: 仅为缺单位的数值记录补标签 (unit 或默认 unknown)。"""
    recs = [_rec("r1", "770", ""), _rec("r2", 45.5, None), _rec("r3", "770", "pc"),
            _rec("r4", "abc", "")]
    r = _exec(recs, [{"op": "mark_missing_unit", "field": "field_value"}])
    assert r["data"][0]["field_unit"] == "unknown"
    assert r["data"][1]["field_unit"] == "unknown"
    assert r["data"][2]["field_unit"] == "pc"       # 有单位 → 不变
    assert r["data"][3]["field_unit"] == ""         # 非数值 → 不补
    assert len(r["log"]) == 2
    r2 = _exec([_rec("r1", "770", "")],
               [{"op": "mark_missing_unit", "field": "field_value", "unit": "pc?"}])
    assert r2["data"][0]["field_unit"] == "pc?"


def test_op_sequential_application_and_invariants():
    """逐 op 顺序应用 (strip→convert→mark unit); 每 op 后记录数/键集合不变。"""
    recs = [_rec("r1", "~770", ""), _rec("r2", "~45.5", "")]
    r = _exec(recs, [
        {"op": "strip_prefix", "field": "field_value"},
        {"op": "numeric_convert", "field": "field_value"},
        {"op": "mark_missing_unit", "field": "field_value"},
    ])
    assert r["data"][0]["field_value"] == 770 and r["data"][0]["field_unit"] == "unknown"
    assert r["data"][1]["field_value"] == 45.5 and r["data"][1]["field_unit"] == "unknown"
    assert len(r["log"]) == 4  # strip ×2 + mark_missing_unit ×2 (numeric_convert 幂等)

    # 不变量违规终止: 非 dict 记录 → kind=op_invariant_failed (结构化失败, 无 data/log 采纳)
    bad = [dict(recs[0]), "not a dict"]
    r2 = _exec(bad, [{"op": "trim", "field": "field_value"}])
    assert r2.get("kind") == "op_invariant_failed"
    assert "record" in r2.get("message", "") and "dict" in r2.get("message", "")
    assert "op" in r2


def test_invariant_gate_direct():
    """_invariant_violated 直接测试: 记录数变 / 键集合变 → 结构化失败。"""
    from quality_pipeline.tools.normalization.op_executor import _invariant_violated
    recs = [{"record_id": "r1", "a": 1}]
    # 记录数变
    v = _invariant_violated([{"record_id": "r1", "a": 1}, {"record_id": "r2", "a": 2}],
                            1, [frozenset({"record_id", "a"})])
    assert v and v["kind"] == "op_invariant_failed" and "record count" in v["message"]
    # 键集合变
    v2 = _invariant_violated([{"record_id": "r1", "a": 1, "b": 2}], 1,
                             [frozenset({"record_id", "a"})])
    assert v2 and v2["kind"] == "op_invariant_failed" and "key set" in v2["message"]
    # 不变 → None
    assert _invariant_violated(recs, 1, [frozenset({"record_id", "a"})]) is None


def test_execute_ops_does_not_mutate_input():
    """execute_ops 在深拷贝上执行 — 原始 records 不被修改。"""
    recs = [_rec("r1", "~770")]
    r = _exec(recs, [{"op": "strip_prefix", "field": "field_value"}])
    assert recs[0]["field_value"] == "~770"    # 原始未动
    assert r["data"][0]["field_value"] == 770


# ══════════════════════════════ ops 优先路径 (planning + exec 集成) ══════════════════════════════

class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """可控假 LLM — 按序返回响应, 耗尽后循环最后一个。"""

    def __init__(self, sequence):
        self.sequence = sequence
        self.calls = 0

    def invoke(self, messages):
        content = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        return _Resp(content)


def _mock_llm(monkeypatch, sequence):
    import quality_pipeline.utils.llm as qllm
    fake = _FakeLLM(sequence)
    monkeypatch.setattr(qllm, "get_llm", lambda temperature=0.0: fake)
    return fake


_SID = "S1"


def _ops_records():
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "pc",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [
        dict(base, record_id="r1", field_value="~770", field_unit=""),
        dict(base, record_id="r2", field_value="~771", field_unit=""),
        dict(base, record_id="r3", field_value="~772", field_unit=""),
    ]


def _issues_src(missing_units=4, missing_prov=4, score=0.6, fmt=0):
    return {
        "completeness": {"present_fields": ["distance"], "expected_fields": ["distance"],
                         "records_missing_unit": missing_units,
                         "records_missing_provenance": missing_prov,
                         "score": score, "missing_expected_fields": []},
        "format": {"total_issues": fmt},
        "consistency": {"unit_consistency": {}},
        "conflict_risk": {"conflict_count": 0},
    }


def _planning_state(records, conditions, issues_src):
    return {
        "data_state": {"current_data": {"records": records,
                                        "sources": [{"source_id": _SID}]}},
        "context_state": {"research_domain": "astrophysics", "target_schema": None},
        "workflow_state": {"llm_call_count": 0},
        "report_state": {
            "quality": {
                "per_source_routes": {_SID: "Normalization"},
                "conditional_routes": [],
                "sources": {_SID: issues_src},
                "quality_scoring": {},
                "profile": {},
            },
            "normalization": {
                "source_plan": {
                    "trigger_source": "quality_report",
                    "sources_to_normalize": {
                        _SID: {"conditions": conditions, "conflict_ctions": []}},
                    "errors": [],
                },
            },
        },
    }


def _ops_response(ops, confidence=0.9, reasoning="ops test"):
    return json.dumps({"ops": ops, "confidence": confidence, "reasoning": reasoning})


def test_ops_path_registers_and_executes(monkeypatch):
    """ops 优先路径端到端: LLM 输出 ops 规格 → 注册 {mode:"ops"} → 执行 (不进沙箱)。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    from quality_pipeline.quality_state import _merge_dict

    fake = _mock_llm(monkeypatch, [
        _ops_response([{"op": "strip_prefix", "field": "field_value"}])])
    state = _planning_state(_ops_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]

    # 注册 mode=="ops" + succeeded + 无失败 attempt
    assert norm["layer3"]["succeeded"][_SID] == "ops_strip_prefix"
    assert norm["layer3"]["attempts"] == []
    assert fake.calls == 1
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert len(gen) == 1
    assert gen[0]["mode"] == "ops"
    assert gen[0]["ops"] == [{"op": "strip_prefix", "field": "field_value",
                              "unit_field": "field_unit", "to": None, "prefixes": None,
                              "suffix": None, "old": None, "new": None, "unit": None}]
    assert gen[0]["confidence"] == 0.9

    # 执行端: 数据真被修改 + generated log 非空 + 无错误
    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    data = out2["data_state"]["current_data"]
    by_id = {r["record_id"]: r for r in data["records"]}
    assert by_id["r1"]["field_value"] == 770
    assert by_id["r2"]["field_value"] == 771
    assert by_id["r3"]["field_value"] == 772
    mods = out2["report_state"]["normalization"]["modifications"]
    assert mods["details"]["generated"], "ops 执行必须有 generated log"
    assert mods["errors"] == []


def test_ops_path_no_confidence_threshold(monkeypatch):
    """ops 路径 confidence <0.7 不设门槛 — 0.5 仍执行 (确定性执行器)。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    from quality_pipeline.quality_state import _merge_dict

    fake = _mock_llm(monkeypatch, [
        _ops_response([{"op": "strip_prefix", "field": "field_value"}], confidence=0.5)])
    state = _planning_state(_ops_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert gen and gen[0]["mode"] == "ops" and gen[0]["confidence"] == 0.5

    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    mods = out2["report_state"]["normalization"]["modifications"]
    by_id = {r["record_id"]: r for r in out2["data_state"]["current_data"]["records"]}
    assert by_id["r1"]["field_value"] == 770       # 低置信 ops 仍执行
    assert not any(e.get("kind") == "low_confidence" for e in mods["errors"])


def test_ops_spec_invalid_no_tool_code_fails(monkeypatch):
    """ops 校验失败且响应无 tool_code → 结构化失败 (parse_error, 可修复)。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [
        json.dumps({"ops": [], "confidence": 0.9})])   # 空 ops → OpSpecResponse 校验失败
    state = _planning_state(_ops_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    attempts = norm["layer3"]["attempts"]
    assert attempts and attempts[0]["kind"] == "parse_error"
    assert norm["layer3"]["succeeded"] == {}
    assert norm["tool_registry"]["by_source"][_SID]["generated"] == []


def test_ops_path_low_conf_but_valid_free_code_still_gated(monkeypatch):
    """自由代码路径 (非 ops) 的 M-16 门槛不受影响 — 低置信 code 工具仍跳过。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    from quality_pipeline.quality_state import _merge_dict

    code = ("for r in records:\n"
            "    v = r.get('field_value')\n"
            "    if isinstance(v, str) and v.startswith('~'):\n"
            "        r['field_value'] = v[1:]\n"
            "        _log.append({'record_id': r.get('record_id'), 'field': 'field_value',\n"
            "                     'action': 'strip', 'before': v, 'after': v[1:]})\n")
    resp = json.dumps({"tool_name": "strip", "tool_code": code, "confidence": 0.5,
                       "self_check": {"assertions": [], "sample_predictions": []},
                       "reasoning": "t"})
    fake = _mock_llm(monkeypatch, [resp])
    state = _planning_state(_ops_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert gen and gen[0].get("mode") != "ops"      # 走自由代码路径
    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    mods = out2["report_state"]["normalization"]["modifications"]
    low_conf = [e for e in mods["errors"] if e.get("kind") == "low_confidence"]
    assert low_conf, "自由代码路径低置信必须被 M-16 门槛拦截 (回归)"
