"""P2 Layer 3 集成测试 — 反馈闭环 (g) + no-op 检测 (h) — mock LLM 端到端。

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(g)(h):
  (g) 结构化失败对象 + layer3.attempts/repair_left/succeeded + 修复循环
      (≤1+MAX_REPAIR_ROUNDS 次 LLM) + 跨轮 prev_failures + validation 三态门
      + metadata errors_count/errors[:50]
  (h) _deep_equal/_detect_noop + dry-run unverifiable 预检 + 执行端 noop 拒绝
      + 数据变 log 空 → missing_log 非阻断

全部离线: get_llm 固定响应序列 monkeypatch, 0 网络。
"""

import json

import pytest

import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环
from quality_pipeline.quality_state import _merge_dict


# ══════════════════════════════════════════════════════════════
# fixtures — mock LLM 固定响应序列
# ══════════════════════════════════════════════════════════════

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


# ── 固定 LLM 响应 ──

def _tool_response(tool_name, tool_code, confidence=0.9):
    return json.dumps({
        "tool_name": tool_name,
        "tool_code": tool_code,
        "confidence": confidence,
        "self_check": {"assertions": [], "sample_predictions": []},
        "reasoning": "test",
    })


# 合法工具: 填充 None field_value (base tools 不处理的形态)
_GOOD_TOOL_CODE = (
    "for r in records:\n"
    "    v = _safe_get(r, 'field_value')\n"
    "    if v is None or (isinstance(v, str) and v.strip() == ''):\n"
    "        r['field_value'] = '0'\n"
    "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
    "'field': 'field_value', 'action': 'fill', 'before': str(v), 'after': '0'})\n"
)
_GOOD_RESP = _tool_response("fill_missing_values", _GOOD_TOOL_CODE)

# 语法错误工具 (未闭合括号 → compile SyntaxError)
_BAD_SYNTAX_RESP = _tool_response("bad_tool", "for r in records:\n    x = (1\n")

# no-op 工具 (零修改)
_NOOP_RESP = _tool_response("do_nothing", "for r in records:\n    pass\n")

# 非法 JSON (parse_error)
_BAD_JSON_RESP = "this is not json at all"


# ══════════════════════════════════════════════════════════════
# state builders
# ══════════════════════════════════════════════════════════════

_SID = "S1"


def _success_records():
    """4 条记录: r1/r4 field_value=None (工具填充目标), provenance 完整。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "pc",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [
        dict(base, record_id="r1", field_value=None, field_unit=""),
        dict(base, record_id="r2", field_value=5.0),
        dict(base, record_id="r3", field_value=6.0),
        dict(base, record_id="r4", field_value=None, field_unit=""),
    ]


def _noop_records():
    """数值无单位记录 (missing units 目标问题可验证)。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance"}
    return [
        dict(base, record_id="r1", field_value="5", field_unit=""),
        dict(base, record_id="r2", field_value="5", field_unit=""),
        dict(base, record_id="r3", field_value="5", field_unit=""),
    ]


def _issues_src(missing_units=0, missing_prov=4, score=0.6, fmt=0):
    """quality.sources[S1] — 使 _find_unresolved 评分 ≥2 触发 Layer 3。"""
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
    """构造触发 Layer 3 的 normalization state (quality_report 触发)。"""
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


# ══════════════════════════════════════════════════════════════
# (g) 成功路径 — 数据真被修改 (杜绝静默 no-op)
# ══════════════════════════════════════════════════════════════

def test_success_path_data_really_modified(monkeypatch):
    """成功路径端到端: 注册 → 执行 → 数据真被修改 (log 非空 + 值变化)。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_GOOD_RESP])
    state = _planning_state(_success_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]

    # 注册成功 + 无失败 attempt + 修复预算未消耗
    assert norm["layer3"]["succeeded"][_SID] == "fill_missing_values"
    assert norm["layer3"]["attempts"] == []
    assert norm["layer3"]["repair_left"][_SID] == 2
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert len(gen) == 1 and gen[0]["tool_name"] == "fill_missing_values"
    assert fake.calls == 1

    # 执行端: 数据真被修改 (generated log 非空 + 值变化)
    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    data = out2["data_state"]["current_data"]
    by_id = {r["record_id"]: r for r in data["records"]}
    assert by_id["r1"]["field_value"] == "0"
    assert by_id["r4"]["field_value"] == "0"
    assert by_id["r2"]["field_value"] == 5.0  # 未受影响记录不变
    mods = out2["report_state"]["normalization"]["modifications"]
    assert mods["details"]["generated"], "generated log 应为非空 (逐条修改均有 log)"
    assert mods["total"] >= 2

    # (g)2/7: layer3.attempts 不被 modifications 覆盖
    norm2 = out2["report_state"]["normalization"]
    assert norm2["layer3"]["succeeded"][_SID] == "fill_missing_values"
    assert not any(e.get("kind") == "parse_error" for e in mods["errors"])


# ══════════════════════════════════════════════════════════════
# (h) no-op 检测 — dry-run 不注册 + errors kind=noop
# ══════════════════════════════════════════════════════════════

def test_noop_not_registered_kind_noop(monkeypatch):
    """dry-run: 样本有目标问题且零修改 → kind=noop 拒绝; noop 重试一次即止。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_NOOP_RESP])
    state = _planning_state(_noop_records(), [{"condition": "missing_units"}],
                            _issues_src(missing_units=4))
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]

    attempts = norm["layer3"]["attempts"]
    assert attempts, "noop 应产生失败对象"
    assert all(a["kind"] == "noop" for a in attempts)
    assert len(attempts) == 2           # noop → 重试一次即止 (共 2 次 LLM)
    assert fake.calls == 2
    assert norm["layer3"]["succeeded"] == {}
    assert norm["layer3"]["repair_left"][_SID] == 1  # 消耗 1 修复轮
    assert norm["tool_registry"]["by_source"][_SID]["generated"] == []
    # 结构化失败对象字段完整
    for a in attempts:
        assert a["source_id"] == _SID and a["kind"] == "noop"
        assert a["error"] and "code" in a


# ══════════════════════════════════════════════════════════════
# (g) 修复循环 — 第 1 次错第 2 次对 → attempts 记录 + 成功注册
# ══════════════════════════════════════════════════════════════

def test_repair_loop_attempts_then_success(monkeypatch):
    """修复循环: [非法 JSON, 语法错, 合法] → attempts 2 条 + 成功注册, 3 次 LLM。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_BAD_JSON_RESP, _BAD_SYNTAX_RESP, _GOOD_RESP])
    state = _planning_state(_success_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]

    assert [a["kind"] for a in norm["layer3"]["attempts"]] == ["parse_error", "syntax_error"]
    assert fake.calls == 3
    assert norm["layer3"]["succeeded"][_SID] == "fill_missing_values"
    assert norm["tool_registry"]["by_source"][_SID]["generated"]
    assert norm["layer3"]["repair_left"][_SID] == 0  # 1 初始 + 2 修复 = 预算耗尽
    # 失败对象带 line 与 error (供修复轮渲染 {kind} @ line {line}: {error})
    se = [a for a in norm["layer3"]["attempts"] if a["kind"] == "syntax_error"][0]
    assert se["line"] is not None and se["error"]


# ══════════════════════════════════════════════════════════════
# (g) 预算耗尽 — 恒错 → 每 source ≤3 次 LLM 调用后回退 + Success
# ══════════════════════════════════════════════════════════════

def test_budget_exhausted_rollback(monkeypatch):
    """恒错: ≤3 次 LLM 调用 (1+2) → attempts 3 条 → 回退 Base Tools → Success。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent

    fake = _mock_llm(monkeypatch, [_BAD_SYNTAX_RESP])
    state = _planning_state(_success_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]

    assert fake.calls == 3                       # 预算封顶: 每 source ≤3 次 LLM
    assert len(norm["layer3"]["attempts"]) == 3
    assert all(a["kind"] == "syntax_error" for a in norm["layer3"]["attempts"])
    assert norm["layer3"]["repair_left"][_SID] == 0
    assert norm["layer3"]["succeeded"] == {}
    assert norm["tool_registry"]["by_source"][_SID]["generated"] == []

    # 回退 Base Tools + validation Success (预算耗尽不 Retry)
    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    out3 = ValidationAgent().run(_merge_dict(merged, out2))
    assert out3["workflow_state"]["execution_status"] == "Success"

    # (g)2/7: layer3.attempts 持久且不被 modifications 覆盖
    norm3 = out3["report_state"]["normalization"]
    assert len(norm3["layer3"]["attempts"]) == 3
    assert not any(e.get("kind") == "syntax_error" for e in norm3["modifications"]["errors"])


# ══════════════════════════════════════════════════════════════
# (g) validation 三态重试门
# ══════════════════════════════════════════════════════════════

def _val_state(gen_errors, repair_left, retry_count=0, layer3_attempts=()):
    return {
        "data_state": {"current_data": {"records": [
            {"record_id": "r1", "source_id": _SID, "field_name": "f",
             "field_value": "5", "field_unit": "pc"},
        ]}},
        "report_state": {"normalization": {
            "layer3": {"attempts": list(layer3_attempts), "repair_left": repair_left,
                       "succeeded": {}},
            "modifications": {"errors": gen_errors},
            "validation": {"retry_count": retry_count},
        }},
        "workflow_state": {},
        "context_state": {},
    }


def test_validation_gate_retry_repairable():
    """gen_errors 含可修复 kind 且 repair_left>0 且 retry<2 → status=Retry。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    st = _val_state([{"source_id": _SID, "tool": "t", "kind": "noop", "error": "noop"}],
                    {_SID: 1})
    out = ValidationAgent().run(st)
    assert out["workflow_state"]["execution_status"] == "Retry"
    assert out["report_state"]["normalization"]["validation"]["retry_count"] == 1


def test_validation_gate_budget_exhausted_success_note():
    """repair_left 耗尽 (0) → 预算耗尽 → Success + note (errors_count 引用)。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    st = _val_state([{"source_id": _SID, "tool": "t", "kind": "noop", "error": "noop"}],
                    {_SID: 0})
    out = ValidationAgent().run(st)
    assert out["workflow_state"]["execution_status"] == "Success"
    notes = [r for r in out["report_state"]["normalization"]["validation"]
             ["remaining_issues"] if r.startswith("Note:")]
    assert notes and "1 generated tool(s)" in notes[0]


def test_validation_gate_low_confidence_no_retry():
    """不可修复 kind (low_confidence → 人工审核) → Success, 不 Retry。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    st = _val_state([{"source_id": _SID, "tool": "t", "kind": "low_confidence",
                      "error": "requires human review"}], {_SID: 2})
    out = ValidationAgent().run(st)
    assert out["workflow_state"]["execution_status"] == "Success"
    assert out["report_state"]["normalization"]["validation"]["retry_count"] == 0


def test_validation_gate_no_gen_errors_unchanged():
    """无 gen_errors → 现状 (Success, 无 note)。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    st = _val_state([], {_SID: 2})
    out = ValidationAgent().run(st)
    assert out["workflow_state"]["execution_status"] == "Success"
    assert not any(r.startswith("Note:") for r in
                   out["report_state"]["normalization"]["validation"]["remaining_issues"])


# ══════════════════════════════════════════════════════════════
# (g) 错误逐条进 metadata (errors_count + errors[:50])
# ══════════════════════════════════════════════════════════════

def test_errors_into_metadata():
    """metadata: all_errors = modifications.errors + layer3.attempts;
    errors_count = N; errors 逐条 {source, tool, kind, error 截断 200}[:50]。"""
    from quality_pipeline.tools.export.metadata_generator import generate_metadata

    long_err = "e" * 250
    report_state = {"normalization": {
        "normalization_status": "Completed",
        "modifications": {"total": 0, "by_layer": {}, "errors": [
            {"source_id": _SID, "tool": "t1", "kind": "noop", "error": long_err}]},
        "layer3": {"attempts": [
            {"source_id": "S2", "tool": "t2", "kind": "parse_error", "error": "bad json"},
            {"source_id": "S2", "tool": "t2", "kind": "syntax_error", "error": "bad code"}],
            "repair_left": {}, "succeeded": {}},
    }}
    md = generate_metadata(current_data={"sources": [], "records": []},
                           target_schema=None, report_state=report_state,
                           context_state={}, run_id="t")
    proc = md["processing_record"]["normalization"]
    assert proc["errors_count"] == 3
    assert len(proc["errors"]) == 3
    assert proc["errors"][0]["source"] == _SID   # 键对齐 source_id → source
    assert proc["errors"][0]["tool"] == "t1"
    assert proc["errors"][0]["kind"] == "noop"
    assert len(proc["errors"][0]["error"]) == 200  # 截断 200
    assert proc["errors"][1]["source"] == "S2" and proc["errors"][1]["kind"] == "parse_error"
    assert proc["errors"][2]["kind"] == "syntax_error"


# ══════════════════════════════════════════════════════════════
# (g)5 已注册工具决策 — 致命失败重生成 / succeeded 复用 / 非致命保留
# ══════════════════════════════════════════════════════════════

def _state_with_registry(prev_generated, prev_errors, layer3):
    state = _planning_state(_success_records(), [{"condition": "completeness_low"}],
                            _issues_src())
    state["report_state"]["normalization"]["tool_registry"] = {
        "by_source": {_SID: {"generated": prev_generated}}}
    state["report_state"]["normalization"]["modifications"] = {"errors": prev_errors}
    state["report_state"]["normalization"]["layer3"] = layer3
    return state


def test_fatal_failure_regenerates_registered_tool(monkeypatch):
    """已注册工具 exec 失败 (fatal kind: noop) 且 repair_left>0 → 清空重新生成。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_GOOD_RESP])
    state = _state_with_registry(
        [{"tool_name": "old_broken", "tool_code": "code", "confidence": 0.9,
          "source_id": _SID}],
        [{"source_id": _SID, "tool": "old_broken", "kind": "noop", "error": "noop"}],
        {"attempts": [], "repair_left": {_SID: 2}, "succeeded": {}})
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert [g["tool_name"] for g in gen] == ["fill_missing_values"]  # 新工具替换
    assert norm["layer3"]["succeeded"][_SID] == "fill_missing_values"
    assert fake.calls == 1


def test_succeeded_tool_reused_on_retry(monkeypatch):
    """layer3.succeeded 命中 → 复用已注册工具, 不调 LLM。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_GOOD_RESP])
    state = _state_with_registry(
        [{"tool_name": "old_ok", "tool_code": "code", "confidence": 0.9,
          "source_id": _SID}],
        [],
        {"attempts": [], "repair_left": {_SID: 2}, "succeeded": {_SID: "old_ok"}})
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert [g["tool_name"] for g in gen] == ["old_ok"]
    assert fake.calls == 0


def test_non_fatal_failure_keeps_registered_tool(monkeypatch):
    """非致命失败 (low_confidence → 人工审核) → 保留已注册工具, 不重生成。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    fake = _mock_llm(monkeypatch, [_GOOD_RESP])
    state = _state_with_registry(
        [{"tool_name": "old_ok", "tool_code": "code", "confidence": 0.9,
          "source_id": _SID}],
        [{"source_id": _SID, "tool": "old_ok", "kind": "low_confidence",
          "error": "human review"}],
        {"attempts": [], "repair_left": {_SID: 2}, "succeeded": {}})
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]
    assert [g["tool_name"] for g in gen] == ["old_ok"]
    assert fake.calls == 0


# ══════════════════════════════════════════════════════════════
# (h) _deep_equal / _detect_noop 单元
# ══════════════════════════════════════════════════════════════

def test_deep_equal_semantics():
    """_deep_equal: NaN 双侧 / None / int-float 跨型 / dict 键集合 / bool 不跨型。"""
    from quality_pipeline.sandbox.sandbox_common import _deep_equal
    assert _deep_equal(1, 1.0)                              # int/float 跨型相等
    assert _deep_equal(float("nan"), float("nan"))          # NaN 双侧 isnan
    assert not _deep_equal(float("nan"), 1.0)
    assert not _deep_equal(1.0, float("nan"))
    assert _deep_equal(None, None)
    assert not _deep_equal(None, 0)
    assert _deep_equal({"a": 1, "b": None}, {"a": 1.0, "b": None})
    assert not _deep_equal({"a": 1}, {"a": 1, "b": 2})      # dict 键集合不一致 False
    assert not _deep_equal({"a": 1}, {"a": 2})
    assert _deep_equal([1, "x"], [1.0, "x"])
    assert not _deep_equal([1], [1, 2])
    assert not _deep_equal(True, 1)                         # bool 不跨型
    assert _deep_equal("5", "5") and not _deep_equal("5", 5)


def test_detect_noop():
    """_detect_noop: 零修改 → noop=True; 任一记录变化 → False。"""
    from quality_pipeline.sandbox.sandbox_common import _detect_noop
    recs = [{"record_id": "r1", "field_value": "1", "field_unit": "pc"},
            {"record_id": "r2", "field_value": 2.0, "field_unit": "pc"}]
    assert _detect_noop(recs, {"data": [dict(recs[0]), dict(recs[1])], "log": []})["noop"] is True
    changed = [dict(recs[0], field_value="2"), dict(recs[1])]
    assert _detect_noop(recs, {"data": changed, "log": []})["noop"] is False


# ══════════════════════════════════════════════════════════════
# (h) 执行端 no-op 拒绝 + missing_log 边界
# ══════════════════════════════════════════════════════════════

def test_exec_noop_rejected_and_missing_log():
    """执行端: 全量 0 修改 → kind=noop 失败对象 (丢弃);
    数据变但 log 空 → 采纳 + kind=missing_log 非阻断错误。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        NormalizationAgent, _make_sandbox,
    )
    agent = NormalizationAgent()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]

    # no-op → 拒绝 + 结构化失败对象
    noop_code = ("def tool(records):\n"
                 "    return {'data': records, 'log': [], 'summary': 'noop'}\n")
    sink = []
    r = agent._execute_generated({"tool_name": "tool", "tool_code": noop_code,
                                  "confidence": 0.9, "source_id": _SID},
                                 recs, _make_sandbox(), sink)
    assert r is None
    assert sink and sink[0]["kind"] == "noop"
    assert sink[0]["source_id"] == _SID and sink[0]["tool"] == "tool"

    # 数据变但 log 空 → 采纳 + missing_log
    silent_code = ("def tool(records):\n"
                   "    records[0]['field_value'] = '2'\n"
                   "    return {'data': records, 'log': [], 'summary': 'silent'}\n")
    sink2 = []
    r2 = agent._execute_generated({"tool_name": "tool", "tool_code": silent_code,
                                   "confidence": 0.9, "source_id": _SID},
                                  recs, _make_sandbox(), sink2)
    assert r2 is not None
    assert r2["data"][0]["field_value"] == "2"
    assert sink2 and sink2[0]["kind"] == "missing_log"


def test_exec_one_source_records_structured_noop_error():
    """_execute_one_source: 执行期 noop → errors 含 kind=noop, 无重复通用错误。"""
    from subgraphs.data_normalization.agents.normalization_agent import _execute_one_source
    recs = [{"record_id": "r1", "source_id": _SID, "entity_type": "", "entity_name": "",
             "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    return {'data': records, 'log': [], 'summary': 'noop'}\n")
    by_src = {"base": [], "adapted": [], "generated": [
        {"tool_name": "tool", "tool_code": code, "confidence": 0.9, "source_id": _SID}]}
    res = _execute_one_source(_SID, by_src, recs, {})
    noop_errors = [e for e in res["errors"] if e.get("kind") == "noop"]
    assert len(noop_errors) == 1
    assert noop_errors[0]["error"]
    # 无通用 fallback 重复 (len == 具体 kind 数)
    assert len(res["errors"]) == 1
    assert res["generated_logs"] == [] and res["total"] == 0
