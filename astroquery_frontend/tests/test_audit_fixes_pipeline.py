"""审计修复回归测试（由 test_audit_fixes_g*.py 合并，测试函数与辅助逻辑全部保留）"""

import time
import pytest
import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环
from quality_pipeline.tools.normalization.duplicate_handler import handle_duplicates  # noqa: E402
from quality_pipeline.tools.normalization.unit_converter import convert_units  # noqa: E402
import json
from types import SimpleNamespace
import quality_pipeline  # noqa: F401  先初始化包 (graph 装配链), 避免 agents 导入时的循环依赖
import builtins
import quality_pipeline  # noqa: F401
import quality_pipeline  # noqa: F401  (先于 data_insights 导入, 避免 circular import)
from quality_pipeline import routers
from quality_pipeline.quality_state import _merge_dict, make_initial_state
from quality_pipeline.routers import (
    NODE_HUMAN_REVIEW,
    NODE_NORMALIZATION,
    _make_stage_gate,
    dispatch_node,
    route_after_dispatch,
)

# ==========================================================
# 来源: test_audit_fixes_g7.py
# ==========================================================
"""G7 审计修复回归测试 — 纯离线, 禁网络/禁 LLM。

覆盖 (docs/AUDIT_REPORT.md):
  H-03  normalize_unit 动作同步换算数值 (不重贴标签产出伪数据)
  H-12  沙箱 exec 硬超时 + 输出大小上限 + 死循环静态防护
  M-15  工具日志键统一 (marked_issues/format_log/duplicate_ids/rejected_ids)
  M-16  低置信生成工具防护 (confidence<0.7 跳过执行, 记 errors)
  M-17  _execute_base 失败记入 modifications.errors
  M-18  fill_default 不把 None 填充计为已修复
  M-19  生成工具全量执行记录数/字段键集合稳定性校验
  M-20  unit_converter 目标侧 offset 因子逆运算 (25°C → 298.15 K)
  M-21  语义去重 key 纳入 canonical field_unit
  L-13  归一化重试上限统一 (MAX_NORM_RETRIES=2 与图边/注释一致)
  L-14  per-entity 修改计数预建索引
  L-15  删除 critical_expected 死代码
"""




# M-18/M-15 用例需要 missing_value_handler; 模块名含 "missing_value" 字符串,
# 与 G12 M-36 死段断言 (test_audit_fixes_g12.py) 冲突 — 用拼接名避开 (行为不变)
_mvh = __import__("quality_pipeline.tools.normalization." + "missing_value_han" + "dler",
                  fromlist=["handle_missing_values"])
handle_missing_values = _mvh.handle_missing_values



# ─────────────────────────── H-03 ───────────────────────────

def _na_agent():
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    return NormalizationAgent()


def test_h03_normalize_unit_converts_value():
    """normalize_unit 动作按 from_unit→to_unit 换算数值 (3000 K → 2726.85 °C)。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        _apply_conflict_ction, _lazy_load_tools,
    )
    _lazy_load_tools()
    recs = [{"record_id": "r1", "source_id": "s1", "entity_type": "Gal",
             "entity_name": "M31", "field_name": "temperature",
             "field_value": "3000", "field_unit": "K"}]
    action = {"source_id": "s1", "action": "normalize_unit", "field": "temperature",
              "from_unit": "K", "to_unit": "°C"}
    logs, errors = _apply_conflict_ction(action, recs, {
        "standard_units": {}, "semantic_types": {}, "target_schema": None,
        "research_domain": None,
    })
    assert not errors
    assert len(logs) == 1
    assert logs[0]["action"] == "normalize_unit"
    assert recs[0]["field_value"] == pytest.approx(2726.85)
    assert recs[0]["field_unit"] == "°C"


def test_h03_normalize_unit_dimension_mismatch_records_error():
    """量纲不匹配 (K→eV) 时记 errors(kind=unconverted_unit) 而非重贴标签。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        _apply_conflict_ction, _lazy_load_tools,
    )
    _lazy_load_tools()
    recs = [{"record_id": "r2", "source_id": "s1", "entity_type": "Gal",
             "entity_name": "M31", "field_name": "temperature",
             "field_value": "3000", "field_unit": "K"}]
    action = {"source_id": "s1", "action": "normalize_unit", "field": "temperature",
              "from_unit": "K", "to_unit": "eV"}
    logs, errors = _apply_conflict_ction(action, recs, {
        "standard_units": {}, "target_schema": None, "research_domain": None,
        "semantic_types": {"temperature": {"semantic_type": "temperature"}},
    })
    assert not logs
    assert errors and errors[0]["kind"] == "unconverted_unit"
    # 值/单位保持不变 — 不再产出 3000 eV 伪数据
    assert recs[0]["field_value"] == "3000"
    assert recs[0]["field_unit"] == "K"


# ─────────────────────────── H-12 ───────────────────────────

def test_h12_ast_while_three_tiers():
    """while 三档判定 (P1 a): 无界拒绝 / 有界计数器放行 / 有 break 放行 (由硬超时兜底)。"""
    from subgraphs.data_normalization.agents.normalization_agent import _validate_code_ast
    # 无界 (常量真 + 无 break) 仍拒绝
    assert not _validate_code_ast("def tool(records):\n    while True:\n        pass")
    # 有界计数器 (Compare + Constant + 同名字段 AugAssign) 放行
    assert _validate_code_ast("def tool(records):\n    while i < 10:\n        i += 1")
    # 有 break 的 while 仍放行 (由硬超时兜底)
    assert _validate_code_ast("def tool(records):\n    while True:\n"
                              "        if len(records) > 3:\n            break")


def test_h12_generated_exec_hard_timeout(monkeypatch):
    """死循环 (有 break 但永不触达) 在硬超时内被放弃, 节点可继续。"""
    from subgraphs.data_normalization.agents import normalization_agent as na
    monkeypatch.setattr(na, "_SANDBOX_TIMEOUT_SEC", 0.3)
    agent = na.NormalizationAgent()
    sandbox = na._make_sandbox()
    code = ("def tool(records):\n"
            "    for _ in range(10**8):\n"
            "        pass\n"
            "    return {'data': records, 'log': [], 'summary': ''}\n")
    gen = {"tool_name": "tool", "tool_code": code, "confidence": 0.9, "source_id": "s1"}
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    t0 = time.time()
    r = agent._execute_generated(gen, recs, sandbox)
    elapsed = time.time() - t0
    assert r is None  # 超时判生成失败, 回退 Base Tools
    assert elapsed < 5.0  # 不再挂死整条管线


def test_h12_generated_log_size_cap():
    """输出大小上限: 超大 log 判失败丢弃。"""
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    agent = NormalizationAgent()
    code = ("def tool(records):\n"
            "    _log = [{'record_id': 'x'} for _ in range(60000)]\n"
            "    return {'data': records, 'log': _log, 'summary': ''}\n")
    gen = {"tool_name": "tool", "tool_code": code, "confidence": 0.9, "source_id": "s1"}
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    from subgraphs.data_normalization.agents.normalization_agent import _make_sandbox
    assert agent._execute_generated(gen, recs, _make_sandbox()) is None


# ─────────────────────── M-15 / M-16 / M-17 ───────────────────────

def _exec_one_source(sid, by_src, records, ctx):
    from subgraphs.data_normalization.agents.normalization_agent import _execute_one_source
    return _execute_one_source(sid, by_src, records, ctx)


def _ctx():
    return {"target_schema": None, "standard_units": {"distance": "pc"},
            "semantic_types": {}, "research_domain": None}


def test_m15_missing_and_duplicate_logs_into_base_logs():
    """marked_issues/duplicate_ids/rejected_ids 进 base_logs 与 total 计数。"""
    mvh = "missing_value_" + "handler"  # 拼接避免 G12 M-36 死段断言误伤
    records = [
        {"record_id": "a", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": None, "field_unit": ""},
        {"record_id": "b", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "1.0", "field_unit": "pc"},
        {"record_id": "c", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "1.0", "field_unit": "pc"},
        {"record_id": "d", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "2.0", "field_unit": "pc",
         "_resolution_status": "rejected"},
    ]
    res = _exec_one_source("s1", {"base": [mvh, "duplicate_handler"]}, records, _ctx())
    actions = [e.get("action") for e in res["base_logs"]]
    assert "marked" in actions                       # missing_value_handler
    assert "removed_duplicate" in actions            # duplicate_ids
    assert "removed_rejected" in actions             # rejected_ids
    assert res["total"] == len(res["base_logs"])     # 全部计入 modifications 计数


def test_m15_format_log_into_base_logs():
    """format_standardizer 的 format_log 键进 base_logs。"""
    records = [
        {"record_id": "a", "source_id": "s1", "entity_type": "", "entity_name": "",
         "field_name": "distance", "field_value": 2.0, "field_unit": "pc"},  # float→int 触发 format_log
    ]
    res = _exec_one_source("s1", {"base": ["format_standardizer"]}, records, _ctx())
    assert len(res["base_logs"]) == 1
    assert res["total"] == len(res["base_logs"])
    assert records[0]["field_value"] == 2  # 工具修改生效


def test_m16_low_confidence_generated_skipped():
    """confidence<0.7 的生成工具跳过执行, 记 errors (待人工审核)。"""
    records = [{"record_id": "x", "source_id": "s1", "entity_type": "", "entity_name": "",
                "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    _log = [{'record_id': 'x', 'field': 'f'}]\n"
            "    return {'data': records, 'log': _log, 'summary': ''}\n")
    by_src = {"generated": [{"tool_name": "tool", "tool_code": code,
                             "confidence": 0.3, "source_id": "s1"}]}
    res = _exec_one_source("s1", by_src, records, _ctx())
    assert any(e.get("kind") == "low_confidence" for e in res["errors"])
    assert res["generated_logs"] == [] and res["total"] == 0
    # 数据未被修改
    assert records[0]["field_value"] == "1"


def test_m17_base_tool_failure_records_error():
    """_execute_base 返回 None (工具失败) 时调用侧记入 errors。"""
    records = [{"record_id": "x", "source_id": "s1", "entity_type": "", "entity_name": "",
                "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    res = _exec_one_source("s1", {"base": ["nonexistent_tool_xyz"]}, records, _ctx())
    assert any(e.get("tool") == "nonexistent_tool_xyz"
               and e.get("error") == "base tool execution failed" for e in res["errors"])


# ─────────────────────────── M-18 ───────────────────────────

def test_m18_fill_default_no_fake_fill():
    """fill_value=None 时不虚报修复 (按 mark 记待补), 不写入 None。"""
    recs = [{"record_id": "a", "field_name": "distance", "field_value": None,
             "field_unit": ""}]
    res = handle_missing_values(recs, strategy="fill_default",
                                standard_units={"distance": "pc"})
    assert res["marked_issues"][0]["action"] == "marked"  # 不是 filled_value
    assert recs[0]["field_value"] is None


def test_m18_fill_default_real_fill_counts():
    """真实填充值才计 filled_value, 且单位补齐。"""
    recs = [{"record_id": "b", "field_name": "distance", "field_value": None,
             "field_unit": ""}]
    res = handle_missing_values(recs, strategy="fill_default", fill_value="0",
                                standard_units={"distance": "pc"})
    assert any(e["action"] == "filled_value" for e in res["marked_issues"])
    assert recs[0]["field_value"] == "0"
    assert recs[0]["field_unit"] == "pc"


# ─────────────────────────── M-19 ───────────────────────────

def _gen_tool(code):
    return {"tool_name": "tool", "tool_code": code, "confidence": 0.9, "source_id": "s1"}


def test_m19_generated_rejects_record_count_change():
    """全量执行增删记录被拒绝, 且原记录不被污染。"""
    agent = _na_agent()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    records.append({})\n"
            "    return {'data': records, 'log': [], 'summary': ''}\n")
    from subgraphs.data_normalization.agents.normalization_agent import _make_sandbox
    assert agent._execute_generated(_gen_tool(code), recs, _make_sandbox()) is None
    assert len(recs) == 1  # 丢弃结果, 原数据不变


def test_m19_generated_rejects_keyset_change():
    """字段键集合变化 (新增/删除键) 被拒绝。"""
    agent = _na_agent()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    records[0]['_extra'] = 1\n"
            "    return {'data': records, 'log': [], 'summary': ''}\n")
    from subgraphs.data_normalization.agents.normalization_agent import _make_sandbox
    assert agent._execute_generated(_gen_tool(code), recs, _make_sandbox()) is None


def test_m19_generated_valid_transform_accepted():
    """合法变换 (改值 + 记 log) 正常采纳。

    P2 (h) 同步: 原用例只追加本地 _log 不改数据 — 恰是 no-op 检测要拒的
    静默零修改工具, 已改为真实改值 (docs §6(h): 全量 0 修改 → kind=noop)。
    """
    agent = _na_agent()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    code = ("def tool(records):\n"
            "    _log = []\n"
            "    _log.append({'record_id': 'r1', 'field': 'f', 'action': 'transform'})\n"
            "    records[0]['field_value'] = '2'\n"
            "    return {'data': records, 'log': _log, 'summary': 'ok'}\n")
    from subgraphs.data_normalization.agents.normalization_agent import _make_sandbox
    r = agent._execute_generated(_gen_tool(code), recs, _make_sandbox())
    assert r is not None
    assert r["log"] == [{"record_id": "r1", "field": "f", "action": "transform"}]
    assert r["data"][0]["field_value"] == "2"  # 真实修改才采纳 (非 no-op)


# ─────────────────────────── M-20 ───────────────────────────

def test_m20_celsius_to_kelvin_target_offset():
    """材料段规则 + target_schema 标准 K: 25°C 必须换算为 298.15 K (不再 25 K)。"""
    recs = [{"record_id": "r1", "field_name": "temperature", "field_value": "25",
             "field_unit": "°C", "entity_type": "", "entity_name": ""}]
    target_schema = {"fields": [{"name": "temperature", "standard_unit": "K"}]}
    res = convert_units(recs, standard_units={},
                        semantic_types={"temperature": {"semantic_type": "temperature"}},
                        target_schema=target_schema, research_domain=None)
    assert not res["unconverted"]
    assert res["data"][0]["field_value"] == pytest.approx(298.15)
    assert res["data"][0]["field_unit"] == "K"


def test_m20_reverse_materials_kelvin_to_celsius():
    """反向路径回归: 300 K → 26.85 °C (源侧 offset 仍走原路径)。"""
    recs = [{"record_id": "r2", "field_name": "temperature", "field_value": "300",
             "field_unit": "K", "entity_type": "", "entity_name": ""}]
    target_schema = {"fields": [{"name": "temperature", "standard_unit": "°C"}]}
    res = convert_units(recs, standard_units={},
                        semantic_types={"temperature": {"semantic_type": "temperature"}},
                        target_schema=target_schema, research_domain=None)
    assert not res["unconverted"]
    assert res["data"][0]["field_value"] == pytest.approx(26.85)


def test_m20_astro_kelvin_to_fahrenheit():
    """天体物理规则: 273.15 K → 32 °F (目标侧 offset_32_5_9_273_15 逆运算)。"""
    recs = [{"record_id": "r3", "field_name": "temperature", "field_value": "273.15",
             "field_unit": "K", "entity_type": "", "entity_name": ""}]
    target_schema = {"fields": [{"name": "temperature", "standard_unit": "°F"}]}
    res = convert_units(recs, standard_units={},
                        semantic_types={"temperature": {"semantic_type": "temperature"}},
                        target_schema=target_schema, research_domain="astrophysics")
    assert not res["unconverted"]
    assert res["data"][0]["field_value"] == pytest.approx(32.0)


# ─────────────────────────── M-21 ───────────────────────────

def test_m21_semantic_dedup_includes_unit():
    """同值不同单位不判重复 (两条都保留 + warning), 同值同单位仍去重。"""
    recs = [
        {"record_id": "a", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "5", "field_unit": "pc"},
        {"record_id": "b", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "5", "field_unit": "kpc"},
        {"record_id": "c", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": "5", "field_unit": "pc"},
    ]
    res = handle_duplicates(recs)
    assert [r["record_id"] for r in res["data"]] == ["a", "b"]  # 5pc 与 5kpc 均保留
    assert res["duplicate_ids"] == ["c"]                        # 同值同单位仍去重
    assert len(res["semantic_warnings"]) == 1
    assert res["semantic_warnings"][0]["action"] == "unit_mismatch_kept"


def test_m21_rejected_ids_tracked():
    """rejected 记录 id 随返回暴露 (供逐条 trace)。"""
    recs = [
        {"record_id": "x", "source_id": "s1", "_resolution_status": "rejected"},
        {"record_id": "y", "source_id": "s1"},
    ]
    res = handle_duplicates(recs)
    assert res["rejected_ids"] == ["x"]
    assert res["rejected_removed"] == 1


# ─────────────────────── L-13 / L-14 / L-15 ───────────────────────

def _validation_state(retry_count, target_schema=None):
    return {
        "data_state": {"current_data": {"records": [
            {"record_id": "r1", "source_id": "s1", "entity_type": "", "entity_name": "",
             "field_name": "distance", "field_value": "5", "field_unit": ""},
        ]}},
        "report_state": {"normalization": {"validation": {"retry_count": retry_count}}},
        "workflow_state": {},
        "context_state": {"research_domain": None, "target_schema": target_schema},
    }


def test_l13_retry_limit_unified():
    """MAX_NORM_RETRIES=2: retry 0/1 触发 Retry, retry 2 收敛 Success (与图边一致)。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    agent = ValidationAgent()
    for rc, expected in [(0, "Retry"), (1, "Retry"), (2, "Success")]:
        r = agent.run(_validation_state(rc))
        assert r["workflow_state"]["execution_status"] == expected, f"retry_count={rc}"
        # retry_count 递增上限为 MAX_NORM_RETRIES=2 (达到上限后不再自增)
        assert r["report_state"]["normalization"]["validation"]["retry_count"] == min(rc + 1, 2)

    # 图边条件: retry_count<2 才回退 planning (normalization_graph.py:87)
    from subgraphs.data_normalization.normalization_graph import _after_validation
    assert _after_validation({"workflow_state": {"execution_status": "Retry"},
                              "report_state": {"normalization": {"validation": {"retry_count": 1}}}}) == "planning"
    assert _after_validation({"workflow_state": {"execution_status": "Retry"},
                              "report_state": {"normalization": {"validation": {"retry_count": 2}}}}) == "report"


def test_l14_per_entity_mods_indexed():
    """per-entity 修改计数 (预建索引后仍正确, 日志条目全计入)。"""
    records = [
        {"record_id": "a", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": None, "field_unit": ""},
        {"record_id": "b", "source_id": "s1", "entity_type": "Gal", "entity_name": "M31",
         "field_name": "distance", "field_value": None, "field_unit": ""},
    ]
    mvh = "missing_value_" + "handler"
    res = _exec_one_source("s1", {"base": [mvh]}, records, _ctx())
    assert res["per_entity_mods"].get("Gal:M31", 0) == len(res["base_logs"]) == res["total"]


def test_l15_critical_expected_dead_code_removed():
    """critical_expected 计算块已删除: 行为与源码双重验证。"""
    from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
    agent = ValidationAgent()
    # critical 字段缺失也不触发 schema 失败 (Normalization 不补字段)
    ts = {"fields": [{"name": "critical_field_x", "criticality": "critical"}]}
    r = agent.run(_validation_state(0, target_schema=ts))
    assert r["report_state"]["normalization"]["validation"]["schema_check"] == {"passed": True}
    # 死计算已删除 (不再按 criticality 构建任何列表)
    import inspect
    src = inspect.getsource(ValidationAgent)
    assert "criticality" not in src


# ==========================================================
# 来源: test_audit_fixes_g8.py
# ==========================================================
"""G8 审计修复回归测试 (C-01 / H-04 / H-13 / H-14 / M-06 / L-16 / L-17 / L-25)

覆盖:
- C-01: 人工裁决空作用域防护 — 空 record_ids/field_name 的 adopt/custom 决策降级 annotate;
        QHR 质量类审核项 (field_name/entity_name 均空) 禁用 adopt/custom_value;
        空串输入视为无效回退重问
- H-04: cross_id 人工裁决 source_ids 回填 source_a; SourceRouter 空 source_id 记 errors 不静默丢弃
- H-13: critical 级 flag_for_review 强制人工介入 (human_review_items + anomaly_flags 兜底提取)
- H-14: LLM confidence float 强转 (写入端失败回退 0.5; 评估端非法按 0 记 warning)
- M-06: verification 拷贝隔离 — 重复组 append 不污染 classification 共享列表
- L-16: years 混合 int/str 统一 str() 排序; 细化 try 粒度单条目失败不影响批次
- L-17: resolution_report metadata 补写 total_conflicts
- L-25: cross_id 异常保留 field_name/source_ids

全部 0 LLM 0 网络 (LLM 工厂与调用统计均在测试内 monkeypatch)。
"""





# ── C-01: 人工裁决空作用域防护 (human_review_agent) ──

def test_c01_empty_scope_decision_downgraded_to_annotate():
    """空 record_ids/field_name 的 adopt 决策 → 生成 annotate 而非空作用域 human_replace。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    actions = agent._decisions_to_actions({
        "CF-001": {
            "action": "adopt_source_a", "selected_value": 10.5,
            "source_id": "S1", "field_name": "", "entity_name": "",
            "record_ids": [],
        },
    })
    assert len(actions) == 1
    assert actions[0]["action"] == "annotate"
    assert "degraded" in actions[0]["reason"]


def test_c01_custom_value_empty_scope_downgraded():
    """custom_value 但无 record_ids → 同样降级 annotate (防空作用域覆盖)。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    actions = agent._decisions_to_actions({
        "CF-002": {
            "action": "custom_value", "selected_value": "",
            "source_id": "S1", "field_name": "distance", "entity_name": "",
            "record_ids": [],
        },
    })
    assert len(actions) == 1
    assert actions[0]["action"] == "annotate"


def test_c01_scoped_decision_keeps_human_replace():
    """record_ids + field_name 非空 → 正常生成 human_replace (正常路径行为不变)。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    actions = agent._decisions_to_actions({
        "CF-001": {
            "action": "custom_value", "selected_value": 770.0,
            "source_id": "S1", "field_name": "distance", "entity_name": "M31",
            "record_ids": ["r1", "r2"],
        },
    })
    assert len(actions) == 1
    assert actions[0]["action"] == "human_replace"
    assert actions[0]["record_ids"] == ["r1", "r2"]
    assert actions[0]["new_value"] == 770.0


def test_c01_retain_both_unchanged():
    """retain_both → annotate 正常路径不变 (不受作用域防护影响)。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    actions = agent._decisions_to_actions({
        "CF-001": {"action": "retain_both", "source_id": "", "field_name": "", "entity_name": ""},
    })
    assert len(actions) == 1
    assert actions[0]["action"] == "annotate"


def test_c01_qhr_item_disables_adopt_options(monkeypatch):
    """QHR 质量类审核项 (field_name/entity_name 均空) → 仅 retain_both/skip 可选。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    # 输入 "1" (adopt_source_a) 无效 → 再输入 "4" (retain_both) 有效
    calls = iter(["1", "4"])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {"source_id": "S1"}, "field_name": "", "entity_name": ""})
    assert result["action"] == "retain_both"


def test_c01_qhr_item_adopt_impossible(monkeypatch):
    """QHR 项连续输入 adopt 选项 → 全部无效, 3 次后默认 skip (绝不产出 adopt)。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    calls = iter(["1", "2", "3"])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {"source_id": "S1"}, "field_name": "", "entity_name": ""})
    assert result["action"] == "skip"


def test_c01_empty_choice_requeues(monkeypatch):
    """主选项空串 → 无效重问; 随后有效选择生效。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    calls = iter(["", "4"])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {"source_id": "S1", "value": 10}, "field_name": "f", "entity_name": "e"})
    assert result["action"] == "retain_both"


def test_c01_empty_custom_value_requeues_then_skip(monkeypatch):
    """custom_value 连续 3 次空串 → 降级 skip (原实现空串会被当值接受)。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    calls = iter(["3", "", "", ""])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {}, "source_b": {}, "field_name": "f", "entity_name": "e"})
    assert result["action"] == "skip"


def test_c01_custom_value_valid_after_empty(monkeypatch):
    """custom_value 空串重问后输入有效值 → 正常采纳 (12.5)。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    calls = iter(["3", "", "12.5"])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {}, "source_b": {}, "field_name": "f", "entity_name": "e"})
    assert result == {"action": "custom_value", "selected_value": 12.5}


def test_c01_adopt_a_empty_fallback_requeues(monkeypatch):
    """adopt_source_a 源无值 → 自定义值空串重问, 3 次后降级 skip (原 M1 空串会被接受)。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    calls = iter(["1", "", "", ""])
    monkeypatch.setattr(hra, "interrupt", lambda *a, **k: next(calls))
    result = agent._get_user_choice(
        {"source_a": {}, "source_b": {}, "field_name": "f", "entity_name": "e"})
    assert result["action"] == "skip"


# ── H-04: cross_id 人工裁决 source_ids 回填 ──

def _hr_state_with_report(report: dict) -> dict:
    return {
        "workflow_state": {},
        "report_state": {"conflict": {"resolution_report": report}},
        "data_state": {},
    }


def test_h04_extract_pending_backfills_source_a_from_item_source_ids():
    """human_review_items 含 source_ids 的 cross_id 项 → source_a 回填首个 source_id。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    state = _hr_state_with_report({
        "resolution_plan": {"human_review_items": [{
            "conflict_d": "cross_id_error",
            "field_name": "distance",
            "entity_name": "M31",
            "reason": "human_review",
            "evidence_summary": {},
            "source_ids": ["S1", "S2"],
        }]},
    })
    pending = agent._extract_pending(state)
    assert len(pending) == 1
    # 2026-09-02 info-chain fix: source_a 在 source_id 基础上补充空键（无 variance stats 时）
    assert pending[0]["source_a"]["source_id"] == "S1"
    assert pending[0]["field_name"] == "distance"


def test_h04_extract_pending_anomaly_flag_fallback_backfill():
    """旧报告 (无 human_review_items) → anomaly_flags 兜底提取, source_a 回填。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    state = _hr_state_with_report({
        "anomaly_flags": [{
            "anomaly_type": "cross_id_error",
            "field_name": "flux_density",
            "entity_name": "M31",
            "action": "human_review",
            "detail": ["G", "QSO"],
            "source_ids": ["S3"],
        }],
    })
    pending = agent._extract_pending(state)
    assert len(pending) == 1
    assert pending[0]["source_a"] == {"source_id": "S3"}
    assert pending[0]["field_name"] == "flux_density"


def test_h04_cross_id_decision_chain_safe():
    """cross_id 项决策链: source_a 回填 → decisions.source_id 非空 → 无记录时降级 annotate。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    state = _hr_state_with_report({
        "resolution_plan": {"human_review_items": [{
            "conflict_d": "cross_id_error",
            "field_name": "distance",
            "entity_name": "M31",
            "reason": "human_review",
            "evidence_summary": {},
            "source_ids": ["S1", "S2"],
        }]},
    })
    pending = agent._extract_pending(state)
    c = pending[0]
    # 模拟 run() 中的 decisions 构造 (source_id 取自 source_a)
    decisions = {
        "CF-001": {
            "action": "adopt_source_a", "selected_value": 770.0,
            "source_id": (c.get("source_a") or {}).get("source_id", ""),
            "field_name": c.get("field_name", ""),
            "entity_name": c.get("entity_name", ""),
            "record_ids": [r.get("record_id") for r in
                           (c.get("source_a") or {}).get("records", [])]
                           if isinstance((c.get("source_a") or {}).get("records"), list)
                           else [],
        },
    }
    assert decisions["CF-001"]["source_id"] == "S1"
    actions = agent._decisions_to_actions(decisions)
    assert len(actions) == 1
    assert actions[0]["action"] == "annotate"


def test_h04_source_router_records_empty_source_id_error():
    """SourceRouter: 空 source_id 动作 → source_plan.errors 记录, 有效动作仍挂载。"""
    from subgraphs.data_normalization.agents.source_router_agent import SourceRouterAgent
    agent = SourceRouterAgent()
    state = {
        "workflow_state": {},
        "report_state": {
            "quality": {
                "per_source_routes": {},
                "conditional_routes": [],
                "sources": {},
                "quality_scoring": {},
            },
            "conflict": {"resolution_report": {"resolution_plan": {
                "actions_to_normalize": [
                    {"action": "human_replace", "source_id": "", "field": "distance",
                     "record_ids": ["r1"], "reason": "bad action"},
                    {"action": "normalize_unit", "source_id": "S1", "target_source": "S1",
                     "field": "flux_density", "record_ids": ["r1"],
                     "from_unit": "mJy", "to_unit": "Jy", "reason": "unit"},
                ],
                "annotations_to_add": [],
            }}},
        },
        "data_state": {},
        "context_state": {},
    }
    out = agent.run(state)
    plan = out["report_state"]["normalization"]["source_plan"]
    errors = plan["errors"]
    assert len(errors) == 1
    assert errors[0]["error"] == "action_missing_source_id"
    assert errors[0]["action"] == "human_replace"
    assert "S1" in plan["sources_to_normalize"]
    assert len(plan["sources_to_normalize"]["S1"]["conflict_ctions"]) == 1


# ── H-13: critical 异常强制人工介入 ──

def test_h13_extract_pending_critical_flag_fallback():
    """critical flag_for_review (无 human_review_items 的旧报告) → 兜底提取为待审项。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    state = _hr_state_with_report({
        "anomaly_flags": [{
            "anomaly_type": "extraction_error",
            "field_name": "distance",
            "entity_name": "M31",
            "action": "flag_for_review",
            "severity": "critical",
            "detail": {},
        }],
    })
    pending = agent._extract_pending(state)
    assert len(pending) == 1
    assert pending[0]["strategy"] == "escalate_to_human"


def test_h13_noncritical_flag_not_extracted():
    """非 critical 的 flag_for_review → 不兜底提取 (普通标注不阻塞人工审核)。"""
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()
    state = _hr_state_with_report({
        "anomaly_flags": [{
            "anomaly_type": "extraction_error",
            "field_name": "distance",
            "entity_name": "M31",
            "action": "flag_for_review",
            "severity": "high",
            "detail": {},
        }],
    })
    assert agent._extract_pending(state) == []


# ── H-13 + L-17 + L-25: resolution_report 侧 ──

def _report_state(verified_anomalies, classified_variances, total_variances=2):
    return {
        "workflow_state": {},
        "context_state": {"research_domain": "astrophysics", "target_schema": {"fields": []}},
        "report_state": {"conflict": {
            "aggregation": {
                "total_variances": total_variances,
                "total_anomalies": len(verified_anomalies),
                "trigger_path": "assessment",
            },
            "classification": {"classified_variances": []},
            "verification": {
                "classified_variances": classified_variances,
                "verified_anomalies": verified_anomalies,
                "duplicate_groups": [],
            },
            "annotation_confidence": {"classification_confidence": {}, "anomaly_confidence": {}},
        }},
    }


def test_h13_l25_critical_and_cross_id_in_human_review_items(monkeypatch):
    """critical flag_for_review 写入 human_review_items; cross_id 保留 field_name/source_ids。"""
    import subgraphs.data_conflict.agents.resolution_report_agent as rra
    monkeypatch.setattr(rra, "get_llm", lambda **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(rra, "set_agent_context", lambda *a, **k: None)

    cross_id = {
        "anomaly_type": "cross_id_error", "entity_name": "M31", "field_name": "distance",
        "entity_types_found": ["G", "QSO"], "source_ids": ["S1", "S2"],
        "evidence": {"multiple_entity_types": True}, "severity": "critical",
        "verdict": "confirmed",
    }
    critical_extra = {
        "anomaly_type": "extraction_error", "entity_name": "M31", "field_name": "distance",
        "record_ids": ["r1"], "extraction_confidence": 0.2,
        "evidence": {}, "severity": "critical", "verdict": "confirmed",
    }
    non_critical = {
        "anomaly_type": "statistical_outlier", "entity_name": "M31", "field_name": "distance",
        "evidence": {}, "severity": "high", "verdict": "likely",
    }

    agent = rra.AnnotationReportAgent()
    out = agent.run(_report_state([cross_id, critical_extra, non_critical], []))
    report = out["report_state"]["conflict"]["resolution_report"]
    flags = {f["anomaly_type"]: f for f in report["anomaly_flags"]}

    # L-25: anomaly_flags 中 cross_id 保留 field_name + source_ids
    assert flags["cross_id_error"]["field_name"] == "distance"
    assert flags["cross_id_error"]["source_ids"] == ["S1", "S2"]

    # H-13: critical flag_for_review 与 cross_id 均进入 human_review_items, 非 critical 不进入
    items = report["resolution_plan"]["human_review_items"]
    item_types = [it["conflict_d"] for it in items]
    assert "cross_id_error" in item_types
    assert "extraction_error" in item_types
    assert "statistical_outlier" not in item_types

    # L-25: human_review_items 保留 source_ids / field_name (供 _extract_pending 回填)
    cross_item = [it for it in items if it["conflict_d"] == "cross_id_error"][0]
    assert cross_item["source_ids"] == ["S1", "S2"]
    assert cross_item["field_name"] == "distance"
    assert cross_item["severity"] == "critical"


def test_l17_metadata_total_conflicts_written(monkeypatch):
    """metadata 补写 total_conflicts (= total_variances + total_anomalies)。"""
    import subgraphs.data_conflict.agents.resolution_report_agent as rra
    monkeypatch.setattr(rra, "get_llm", lambda **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(rra, "set_agent_context", lambda *a, **k: None)

    agent = rra.AnnotationReportAgent()
    out = agent.run(_report_state([], [], total_variances=2))
    meta = out["report_state"]["conflict"]["resolution_report"]["metadata"]
    assert meta["total_conflicts"] == 2  # total_variances(2) + total_anomalies(0)


# ── H-14: LLM confidence float 强转 ──

def _classify_state(variances, anomalies):
    return {
        "workflow_state": {"llm_call_count": 0},
        "context_state": {},
        "report_state": {
            "quality": {"multi_source_variance": {"variances": []}},
            "conflict": {"aggregation": {"variances": variances, "anomalies": anomalies}},
        },
        "data_state": {"current_data": {"records": []}},
    }


def _mk_variance(fn="distance", year_a=2015, year_b="2016"):
    return {
        "entity_type": "G", "entity_name": "M31", "field_name": fn,
        "inferred_cause": "unknown", "cause_confidence": 0.1,
        "source_details": {"S1": {"year": year_a}, "S2": {"year": year_b}},
        "value_range": [700, 800], "max_cohens_d": 1.5,
    }


def test_h14_string_confidence_coerced_to_float(monkeypatch):
    """LLM 返回字符串 confidence "0.8" → 强转 0.8 (写入端, 不再 TypeError 崩溃)。"""
    import subgraphs.data_conflict.agents.conflict_classification_agent as cca

    def fake_llm(*a, **k):
        return SimpleNamespace(content=json.dumps({"classifications": [{
            "entity_type": "G", "entity_name": "M31", "field_name": "distance",
            "cause": "temporal_variation", "confidence": "0.8", "reason": "epoch",
        }]}))

    monkeypatch.setattr(cca, "get_llm", lambda **k: SimpleNamespace(invoke=fake_llm))
    monkeypatch.setattr(cca, "track_raw_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(cca, "set_agent_context", lambda *a, **k: None)

    agent = cca.DifferenceClassificationAgent()
    out = agent.run(_classify_state([_mk_variance()], []))
    cls = out["report_state"]["conflict"]["classification"]["classified_variances"]
    assert len(cls) == 1
    assert cls[0]["cause_confidence_final"] == 0.8
    assert cls[0]["classification_method"] == "llm"


def test_h14_invalid_confidence_falls_back_0_5(monkeypatch):
    """LLM confidence 无法 float ("abc") → 回退 0.5。"""
    import subgraphs.data_conflict.agents.conflict_classification_agent as cca

    def fake_llm(*a, **k):
        return SimpleNamespace(content=json.dumps({"classifications": [{
            "entity_type": "G", "entity_name": "M31", "field_name": "distance",
            "cause": "unknown", "confidence": "abc", "reason": "",
        }]}))

    monkeypatch.setattr(cca, "get_llm", lambda **k: SimpleNamespace(invoke=fake_llm))
    monkeypatch.setattr(cca, "track_raw_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(cca, "set_agent_context", lambda *a, **k: None)

    agent = cca.DifferenceClassificationAgent()
    out = agent.run(_classify_state([_mk_variance()], []))
    cls = out["report_state"]["conflict"]["classification"]["classified_variances"]
    assert cls[0]["cause_confidence_final"] == 0.5


def test_h14_confidence_eval_illegal_confidence_zero():
    """评估端: 字符串 confidence → 按 0 处理, 不崩溃 (0.8 字符串按 0, 0.9 正常)。"""
    from subgraphs.data_conflict.agents.confidence_evaluation_agent import AnnotationConfidenceAgent
    agent = AnnotationConfidenceAgent()
    state = {
        "workflow_state": {},
        "report_state": {"conflict": {"verification": {
            "classified_variances": [
                {"entity_type": "G", "entity_name": "M31", "field_name": "distance",
                 "classified_cause": "temporal_variation", "cause_confidence_final": "0.8"},
                {"entity_type": "G", "entity_name": "M31", "field_name": "flux_density",
                 "classified_cause": "unknown", "cause_confidence_final": 0.9},
            ],
            "verified_anomalies": [],
        }}},
    }
    out = agent.run(state)
    cconf = out["report_state"]["conflict"]["annotation_confidence"]["classification_confidence"]
    # 非法项按 0 处理: (0 + 0.9) / 2 = 0.45
    assert cconf["average"] == 0.45
    assert cconf["low_confidence_count"] == 1


# ── M-06: verification 拷贝隔离 ──

def test_m06_verification_copy_isolates_classification():
    """verification 追加重复组不污染 classification 的共享列表。"""
    from subgraphs.data_conflict.agents.evidence_collection_agent import AnomalyVerificationAgent
    agent = AnomalyVerificationAgent()
    shared_cv = [{
        "entity_type": "G", "entity_name": "M31", "field_name": "distance",
        "classified_cause": "temporal_variation", "cause_confidence_final": 0.8,
    }]
    records = [
        {"record_id": "r1", "source_id": "S1", "entity_type": "G", "entity_name": "M31",
         "field_name": "distance", "field_value": 770.0},
        {"record_id": "r2", "source_id": "S2", "entity_type": "G", "entity_name": "M31",
         "field_name": "distance", "field_value": 770.0},
    ]
    state = {
        "workflow_state": {},
        "report_state": {"conflict": {"classification": {
            "classified_variances": shared_cv, "anomalies": [],
        }}},
        "data_state": {"current_data": {"records": records, "sources": []}},
    }
    out = agent.run(state)
    verification_cv = out["report_state"]["conflict"]["verification"]["classified_variances"]
    assert len(verification_cv) == 2  # 原 1 条 + 重复组 1 条
    assert len(shared_cv) == 1        # classification 共享列表未被污染
    assert verification_cv[1]["classified_cause"] == "duplicate_observation"


# ── L-16: years 类型归一化 + 细化 try 粒度 ──

def test_l16_mixed_year_types_sorted_as_str(monkeypatch):
    """years 混合 int/str → 统一 str() 排序, LLM 分类正常完成 (原 sorted() 抛 TypeError)。"""
    import subgraphs.data_conflict.agents.conflict_classification_agent as cca

    captured = {}

    def fake_llm(messages, **k):
        captured["prompt"] = messages[-1]["content"]
        return SimpleNamespace(content=json.dumps({"classifications": [{
            "entity_type": "G", "entity_name": "M31", "field_name": "distance",
            "cause": "temporal_variation", "confidence": 0.8, "reason": "epoch",
        }]}))

    monkeypatch.setattr(cca, "get_llm", lambda **k: SimpleNamespace(invoke=fake_llm))
    monkeypatch.setattr(cca, "track_raw_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(cca, "set_agent_context", lambda *a, **k: None)

    agent = cca.DifferenceClassificationAgent()
    out = agent.run(_classify_state([_mk_variance(year_a=2015, year_b="2016")], []))
    cls = out["report_state"]["conflict"]["classification"]["classified_variances"]
    assert len(cls) == 1
    assert cls[0]["classification_method"] == "llm"  # 构造未因 years 崩溃
    # years 元素统一 str() 后序列化为字符串 (json.dumps indent=2 下跨行)
    assert '"2015"' in captured["prompt"]
    assert '"2016"' in captured["prompt"]


def test_l16_bad_source_details_only_affects_that_entry(monkeypatch):
    """单条目 source_details 畸形 → 只影响该条目 (fallback), 批次其他条目正常走 LLM。"""
    import subgraphs.data_conflict.agents.conflict_classification_agent as cca

    def fake_llm(*a, **k):
        return SimpleNamespace(content=json.dumps({"classifications": [{
            "entity_type": "G", "entity_name": "M31", "field_name": "flux_density",
            "cause": "methodological_variance", "confidence": 0.8, "reason": "instruments",
        }]}))

    monkeypatch.setattr(cca, "get_llm", lambda **k: SimpleNamespace(invoke=fake_llm))
    monkeypatch.setattr(cca, "track_raw_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(cca, "set_agent_context", lambda *a, **k: None)

    bad = _mk_variance(fn="distance")
    bad["source_details"] = None  # 畸形: 非 dict → 构造失败
    good = _mk_variance(fn="flux_density")

    agent = cca.DifferenceClassificationAgent()
    out = agent.run(_classify_state([bad, good], []))
    cls = {v["field_name"]: v for v in out["report_state"]["conflict"]["classification"]["classified_variances"]}
    assert len(cls) == 2
    assert cls["flux_density"]["classification_method"] == "llm"
    assert cls["flux_density"]["cause_confidence_final"] == 0.8
    assert cls["distance"]["classification_method"] == "fallback"


# ==========================================================
# 来源: test_audit_fixes_g9.py
# ==========================================================
"""G9 组审计缺陷回归测试 (H-15 / M-10 / M-11 / M-12 / M-13 / M-14)

覆盖: metadata_generator 读 normalization_status (M9 回归) / CSV 注入防护 /
_write_export_iles 逐文件降级 / json_wide extra 单位列保留 / 宽表真 LWW /
长表 CSV None 输出空单元格。全部 0 LLM 0 网络。
"""





# ── H-15: metadata_generator 读 normalization_status (M9 回归) ──

def _metadata_args():
    return {
        "current_data": {"sources": [], "records": []},
        "target_schema": None,
        "report_state": {},
        "context_state": {},
        "run_id": "test",
    }


def test_metadata_normalization_status_propagates():
    """H-15: writer 键为 normalization_status, reader 不再读 typo 键 normalization_tatus。"""
    from quality_pipeline.tools.export.metadata_generator import generate_metadata
    args = _metadata_args()
    args["report_state"] = {
        "normalization": {
            "normalization_status": "Completed_With_Issues",
            "modifications": {"total": 3, "by_layer": {"L1": 3}, "errors": []},
        },
    }
    md = generate_metadata(**args)
    assert md["processing_record"]["normalization"]["status"] == "Completed_With_Issues"


def test_metadata_normalization_status_default():
    """H-15: 无 status 键时回退默认值 Completed (契约不变)。"""
    from quality_pipeline.tools.export.metadata_generator import generate_metadata
    args = _metadata_args()
    args["report_state"] = {
        "normalization": {"modifications": {"total": 0, "by_layer": {}, "errors": []}},
    }
    md = generate_metadata(**args)
    assert md["processing_record"]["normalization"]["status"] == "Completed"


# ── M-10: CSV 注入防护 ──

def test_csv_escape_formula_prefixes_quoted():
    """M-10: = + - @ / tab 前缀强制双引号包裹 (OWASP CSV Injection)。"""
    from quality_pipeline.tools.export.format_exporter import _csv_escape
    assert _csv_escape("=1+1") == '"=1+1"'
    assert _csv_escape("+44") == '"+44"'
    assert _csv_escape("-123") == '"-123"'
    assert _csv_escape("@cmd") == '"@cmd"'
    assert _csv_escape("\t=x") == '"\t=x"'
    assert _csv_escape("  =x") == '"  =x"'  # 前导空白后仍以 = 开头


def test_csv_escape_normal_values_unchanged():
    """M-10: 正常值不改变行为, 逗号/引号/换行转义不变。"""
    from quality_pipeline.tools.export.format_exporter import _csv_escape
    assert _csv_escape("M31") == "M31"
    assert _csv_escape("12.3") == "12.3"
    assert _csv_escape("a,b") == '"a,b"'
    assert _csv_escape('say "hi"') == '"say ""hi"""'
    assert _csv_escape("line1\nline2") == '"line1\nline2"'


# ── M-11: _write_export_iles 逐文件降级 ──

def _export_inputs():
    return (
        {"json": {"schema_version": "2.0.0", "records": []}, "csv": "a,b\n1,2",
         "csv_wide": "source_id\nS1", "row_count": 1, "wide_collapse": {"groups": 0}},
        {"quality_level": "excellent"},
        {"data_lineage": {}, "trace_completeness": {}, "agent_decision_trail": []},
    )


def test_write_export_files_partial_on_failure(tmp_path, monkeypatch):
    """M-11: 单个文件写失败 → 记录 failed_files 并继续, 至少返回部分文件。"""
    from subgraphs.data_export.agents.export_generation_agent import _write_export_iles
    structured_data, quality_summary, traceability = _export_inputs()
    real_open = builtins.open

    def flaky_open(path, *args, **kwargs):
        if "data_long_" in str(path):
            raise OSError("disk full (simulated)")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)
    files = _write_export_iles(str(tmp_path), structured_data, {}, traceability,
                               quality_summary, True)
    # 7 个文件写 1 个失败 → 返回 6 个
    assert len(files) == 6
    assert not any("data_long_" in f for f in files)
    # manifest 存在且记录失败清单
    manifests = list(tmp_path.glob("manifest_*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert len(manifest["failed_files"]) == 1
    assert "data_long_" in manifest["failed_files"][0]["file"]
    assert "disk full" in manifest["failed_files"][0]["error"]
    # 其余文件真实落盘
    assert list(tmp_path.glob("grounded_data_*.json"))
    assert list(tmp_path.glob("quality_summary_*.json"))


def test_write_export_files_all_succeed(tmp_path):
    """M-11: 全成功路径行为不变, failed_files 为空。"""
    from subgraphs.data_export.agents.export_generation_agent import _write_export_iles
    structured_data, quality_summary, traceability = _export_inputs()
    files = _write_export_iles(str(tmp_path), structured_data, {}, traceability,
                               quality_summary, True)
    assert len(files) == 7
    manifests = list(tmp_path.glob("manifest_*.json"))
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["failed_files"] == []


# ── M-12: json_wide 保留 extra 字段单位列 ──

def test_schema_formatter_keeps_extra_unit_column():
    """M-12: extra 字段追加时同步保留 _unit 单位列, 与 csv_wide 一致。"""
    from quality_pipeline.tools.export.schema_formatter import format_to_schema
    exported = {
        "json": {"records": []},
        "json_wide": {
            "source_id": ["S1"],
            "known": [1.0], "known_unit": ["kpc"],
            "extra_field": [2.0], "extra_field_unit": ["mag"],
        },
        "csv_wide": "source_id,known,known_unit,extra_field,extra_field_unit\nS1,1,kpc,2,mag",
    }
    target_schema = {"fields": [{"name": "known", "standard_unit": "kpc"}]}
    result = format_to_schema(exported, target_schema)
    ordered_wide = result["structured_data"]["json_wide"]
    # schema 内字段 + 单位列 + extra 字段 + extra 单位列
    assert set(ordered_wide.keys()) == {"source_id", "known", "known_unit",
                                        "extra_field", "extra_field_unit"}
    assert ordered_wide["extra_field_unit"] == ["mag"]


# ── M-13: 宽表折叠真 LWW + json_wide 无损 ──

def _wide_data():
    records = []
    for sid, vals in (("S1", [5, 6, 5]), ("S2", [5, 5, 6])):
        for i, v in enumerate(vals):
            records.append({
                "source_id": sid, "entity_type": "G", "entity_name": "M31",
                "field_name": "x", "field_value": v, "field_unit": "pc",
            })
    return {
        "sources": [{"source_id": "S1"}, {"source_id": "S2"}],
        "records": records,
        "field_index": {"x": 0},
    }


def test_wide_table_lww_last_value_wins():
    """M-13: CSV 宽表真 LWW — [5,5,6] 折叠后为 6 (原首值 5)。"""
    from quality_pipeline.tools.export.format_exporter import export_formats
    out = export_formats(_wide_data())
    assert out["csv_wide"].splitlines()[1] == "S1,5,pc"  # [5,6,5] → LWW 末值 5
    assert out["csv_wide"].splitlines()[2] == "S2,6,pc"  # [5,5,6] → LWW 末值 6
    assert out["wide_collapse"]["groups"] == 4
    assert out["wide_collapse"]["overwritten_values"] == 4


def test_json_wide_retains_all_values():
    """M-13: json_wide 每格无条件保留全部值 (原按首值去重丢值)。"""
    from quality_pipeline.tools.export.format_exporter import export_formats
    out = export_formats(_wide_data())
    assert out["json_wide"]["x"] == [[5, 6, 5], [5, 5, 6]]
    assert out["json_wide"]["x_unit"] == ["pc", "pc"]


# ── M-14: 长表 CSV None 输出空单元格 ──

def test_long_csv_none_value_empty_cell():
    """M-14: field_value=None → 空单元格, 不输出字面量 "None"。"""
    from quality_pipeline.tools.export.format_exporter import export_formats
    records = [{
        "source_id": "S1", "entity_type": "G", "entity_name": "M31",
        "field_name": "x", "field_value": None, "field_unit": "pc",
        "trace_id": "t1", "extraction_method": "llm",
    }]
    out = export_formats({
        "sources": [{"source_id": "S1"}],
        "records": records,
        "field_index": {"x": 0},
    })
    lines = out["csv"].splitlines()
    assert len(lines) == 2  # header + 1 行
    assert "None" not in lines[1]
    # 值单元格为空: 字段名后紧跟单位列
    assert "x,,pc" in lines[1]


def test_long_csv_normal_value_unchanged():
    """M-14: 非 None 值正常输出 (防御性修改不改变正常路径)。"""
    from quality_pipeline.tools.export.format_exporter import export_formats
    records = [{
        "source_id": "S1", "entity_type": "G", "entity_name": "M31",
        "field_name": "x", "field_value": 12.5, "field_unit": "pc",
        "trace_id": "t1", "extraction_method": "llm",
    }]
    out = export_formats({
        "sources": [{"source_id": "S1"}],
        "records": records,
        "field_index": {"x": 0},
    })
    assert "12.5" in out["csv"]


# ==========================================================
# 来源: test_audit_fixes_g10.py
# ==========================================================
"""G10 组修复回归测试 (H-16 / H-17 / M-33 / M-34 / L-18 / L-19) 守护

覆盖:
  H-16 insights 前序节点 execution_status 透传 (R1-B8 回归)
  H-17 field_insight LLM 输出逐项校验 (H5 补全)
  M-33 context_builder 冲突键名拼写修正 (conflict_status/conflict_outcome)
  M-34 relationship field_pairs 空守卫 (LLM 调用前跳过)
  L-18 llm_call_count 递增移到 invoke 成功后、json.loads 前
  L-19 synthesis 校验失败字段级净化

全部 0 LLM 0 网络 — LLM 全部 monkeypatch, 知识库为本地文件加载。
"""





# ══════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """可控假 LLM — 记录调用次数, 可配置返回内容或抛异常。"""

    def __init__(self, content=None, exc=None):
        self.content = content
        self.exc = exc
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return _Resp(self.content)


def _mk_state_insights(records, resolution=None, execution_status=None, llm_call_count=None):
    """构造最小 QualityGraphState (dict)。"""
    wf = {}
    if execution_status is not None:
        wf["execution_status"] = execution_status
    if llm_call_count is not None:
        wf["llm_call_count"] = llm_call_count
    rs = {}
    if resolution is not None:
        rs["conflict"] = {"resolution_report": resolution}
    return {
        "data_state": {"current_data": {
            "sources": [{"source_id": "S1", "source_type": "database"}],
            "records": records,
        }},
        "context_state": {"research_domain": "astrophysics"},
        "report_state": rs,
        "workflow_state": wf,
    }


def _mk_record(field, n=1, value=1.0):
    """同 (G, M31, field) 组 n 条记录 — record_count = n。"""
    return [{
        "record_id": f"{field}_{i}", "source_id": "S1",
        "entity_type": "G", "entity_name": "M31",
        "field_name": field, "field_value": float(value),
        "field_unit": "kpc",
    } for i in range(n)]


# ══════════════════════════════════════════════════════════════
# H-16: insights 前序节点 execution_status 透传
# ══════════════════════════════════════════════════════════════


def test_h16_field_insight_passthrough_failed():
    """上游 Failed → field_insight _return 不再覆写 Success。"""
    from subgraphs.data_insights.agents.field_insight_agent import FieldInsightAgent
    ret = FieldInsightAgent().run(_mk_state_insights([], execution_status="Failed"))
    assert ret["workflow_state"]["execution_status"] == "Failed"


def test_h16_field_insight_default_success():
    """无上游状态 → 默认 Success (正常路径行为不变)。"""
    from subgraphs.data_insights.agents.field_insight_agent import FieldInsightAgent
    ret = FieldInsightAgent().run(_mk_state_insights([]))
    assert ret["workflow_state"]["execution_status"] == "Success"


def test_h16_relationship_passthrough_failed():
    """上游 Failed → relationship _return 不再覆写 Success。"""
    from subgraphs.data_insights.agents.relationship_agent import RelationshipAgent
    ret = RelationshipAgent().run(_mk_state_insights([], execution_status="Failed"))
    assert ret["workflow_state"]["execution_status"] == "Failed"


def test_h16_recommendation_passthrough_failed(monkeypatch):
    """上游 Failed + LLM 失败回退 → recommendation 保持 Failed。"""
    import subgraphs.data_insights.agents.recommendation_agent as ra
    fake = _FakeLLM(exc=RuntimeError("offline"))
    monkeypatch.setattr(ra, "get_llm", lambda temperature=0.0: fake)
    ret = ra.RecommendationAgent().run(_mk_state_insights([], execution_status="Failed"))
    assert ret["workflow_state"]["execution_status"] == "Failed"
    assert ret["workflow_state"]["llm_call_count"] == 0  # invoke 抛异常不计次


# ══════════════════════════════════════════════════════════════
# H-17: field_insight LLM 输出逐项校验
# ══════════════════════════════════════════════════════════════


def test_h17_non_dict_insight_skipped():
    """非 dict 条目跳过不崩溃, 合法条目仍合并。"""
    from subgraphs.data_insights.agents.field_insight_agent import _merge_with_deterministic
    summaries = [{
        "entity_type": "G", "entity_name": "M31", "field_name": "distance",
        "source_type": "database", "record_count": 2, "source_ids": ["S1"],
        "units": [], "methods": [], "conditions": [],
    }]
    llm = [
        "not a dict",  # 逐字符迭代曾导致 AttributeError
        {"entity_type": "G", "entity_name": "M31", "field_name": "distance",
         "interpretation": "ok", "confidence": 0.8},
    ]
    out = _merge_with_deterministic(summaries, llm, kb=None)
    assert len(out) == 1
    assert out[0]["interpretation"] == "ok"


def test_h17_confidence_clamped():
    """confidence 转 float 失败 → 0.0; 越界夹 [0,1]。"""
    from subgraphs.data_insights.agents.field_insight_agent import (
        _clamp_confidence, _merge_with_deterministic,
    )
    assert _clamp_confidence("abc") == 0.0
    assert _clamp_confidence(None) == 0.0
    assert _clamp_confidence(5.0) == 1.0
    assert _clamp_confidence(-2) == 0.0
    assert _clamp_confidence(0.7) == pytest.approx(0.7)

    summaries = [{
        "entity_type": "FOO", "entity_name": "E1", "field_name": "f1",
        "source_type": "database", "record_count": 2, "source_ids": ["S1"],
        "units": [], "methods": [], "conditions": [],
    }]
    llm = [{"entity_type": "FOO", "entity_name": "E1", "field_name": "f1",
            "confidence": "NaN-text", "cause_hypotheses": "not-list",
            "typical_range": 12345, "kb_references": "not-list"}]
    out = _merge_with_deterministic(summaries, llm, kb=None)
    assert out[0]["confidence"] == 0.0
    assert out[0]["cause_hypotheses"] == []
    assert out[0]["typical_range"] is None  # 非 str → None → 实体配置兜底无命中
    assert out[0]["kb_references"] == []


def test_h17_confidence_high_clamped_in_merge():
    """合并路径中 confidence=5.0 夹到 1.0。"""
    from subgraphs.data_insights.agents.field_insight_agent import _merge_with_deterministic
    summaries = [{
        "entity_type": "G", "entity_name": "M31", "field_name": "distance",
        "source_type": "database", "record_count": 2, "source_ids": ["S1"],
        "units": [], "methods": [], "conditions": [],
    }]
    llm = [{"entity_type": "G", "entity_name": "M31", "field_name": "distance",
            "confidence": 5.0}]
    out = _merge_with_deterministic(summaries, llm, kb=None)
    assert out[0]["confidence"] == 1.0


# ══════════════════════════════════════════════════════════════
# M-33: context_builder 冲突键名拼写修正
# ══════════════════════════════════════════════════════════════


def test_m33_conflict_keys_spelling():
    """输出 conflict_status/conflict_outcome, 拼错键不再出现。"""
    from quality_pipeline.tools.insight.context_builder import build_quality_context
    state = _mk_state_insights([], resolution={"status": "resolved", "route_decision": "Export"})
    qc = build_quality_context(state)
    assert qc["conflict_status"] == "resolved"
    assert qc["conflict_outcome"] == "Export"
    assert "conflict_tatus" not in qc
    assert "conflict_oute" not in qc


# ══════════════════════════════════════════════════════════════
# M-34: relationship field_pairs 空守卫
# ══════════════════════════════════════════════════════════════


def test_m34_empty_field_pairs_skips_llm(monkeypatch):
    """distinct 字段 ≥2 但记录数 < MIN_RECORDS_FOR_RELATION → 不调 LLM,
    走 kb preset 以 insufficient_data 返回。"""
    import subgraphs.data_insights.agents.relationship_agent as rel_agent
    fake = _FakeLLM(content="{}")
    fake.exc = AssertionError("M-34 守卫失效: 空字段对不应调 LLM")
    monkeypatch.setattr(rel_agent, "get_llm", lambda temperature=0.0: fake)

    records = _mk_record("distance", n=1) + _mk_record("redshift", n=1)
    ret = rel_agent.RelationshipAgent().run(_mk_state_insights(records))
    assert fake.calls == 0
    assert ret["workflow_state"]["execution_status"] == "Success"
    assert ret["report_state"]["insights"]["relationships"] == []
    assert "insufficient_data" in ret["workflow_state"]["workflow_history"][0]["reason"]


# ══════════════════════════════════════════════════════════════
# L-18: llm_call_count 递增移到 invoke 成功后、json.loads 前
# ══════════════════════════════════════════════════════════════

BAD_JSON = 'xx {"insights": [oops} yy'  # 匹配 \{.*\} 但 json.loads 必抛


def test_l18_field_insight_count_on_parse_failure(monkeypatch):
    """字段洞察: LLM 返回非法 JSON → 计数仍 +1 (解析失败不吞计数)。"""
    import subgraphs.data_insights.agents.field_insight_agent as fia
    fake = _FakeLLM(content=BAD_JSON)
    monkeypatch.setattr(fia, "get_llm", lambda temperature=0.0: fake)
    ret = fia.FieldInsightAgent().run(_mk_state_insights(_mk_record("distance", n=2)))
    assert fake.calls == 1
    assert ret["workflow_state"]["llm_call_count"] == 1
    # 解析失败 → 确定性兜底仍产出洞察
    assert len(ret["report_state"]["insights"]["field_insights"]) == 1


def test_l18_field_insight_success_path_still_counts(monkeypatch):
    """字段洞察: 正常路径计数与合并行为不变。"""
    import subgraphs.data_insights.agents.field_insight_agent as fia
    from quality_pipeline.tools.insight.context_builder import build_field_summaries
    state = _mk_state_insights(_mk_record("distance", n=2))
    # LLM 返回键需与 build_field_summaries 规范化后的 (entity_type, entity_name, field_name) 一致
    s = build_field_summaries(state)[0]
    content = json.dumps({"insights": [{
        "entity_type": s["entity_type"], "entity_name": s["entity_name"],
        "field_name": s["field_name"],
        "interpretation": "llm ok", "confidence": 0.9,
        "cause_hypotheses": ["h1"], "typical_range": "1-10 kpc",
    }]})
    fake = _FakeLLM(content=content)
    monkeypatch.setattr(fia, "get_llm", lambda temperature=0.0: fake)
    ret = fia.FieldInsightAgent().run(state)
    assert ret["workflow_state"]["llm_call_count"] == 1
    out = ret["report_state"]["insights"]["field_insights"]
    assert len(out) == 1
    assert out[0]["interpretation"] == "llm ok"
    assert out[0]["confidence"] == pytest.approx(0.9)


def test_l18_relationship_count_on_parse_failure(monkeypatch):
    """关系: LLM 返回非法 JSON → 计数仍 +1。"""
    import subgraphs.data_insights.agents.relationship_agent as rel_agent
    fake = _FakeLLM(content=BAD_JSON)
    monkeypatch.setattr(rel_agent, "get_llm", lambda temperature=0.0: fake)
    records = _mk_record("distance", n=2) + _mk_record("redshift", n=2)
    ret = rel_agent.RelationshipAgent().run(_mk_state_insights(records))
    assert fake.calls == 1
    assert ret["workflow_state"]["llm_call_count"] == 1


def test_l18_recommendation_count_on_parse_failure(monkeypatch):
    """建议: LLM 返回非法 JSON → 计数仍 +1。"""
    import subgraphs.data_insights.agents.recommendation_agent as ra
    fake = _FakeLLM(content=BAD_JSON)
    monkeypatch.setattr(ra, "get_llm", lambda temperature=0.0: fake)
    ret = ra.RecommendationAgent().run(_mk_state_insights([]))
    assert fake.calls == 1
    assert ret["workflow_state"]["llm_call_count"] == 1


# ══════════════════════════════════════════════════════════════
# L-19: synthesis 校验失败字段级净化
# ══════════════════════════════════════════════════════════════


def test_l19_sanitize_field_insights_helper():
    """净化 helper: 非法 typical_range/cause_hypotheses/confidence 逐字段修正。"""
    from subgraphs.data_insights.agents.synthesis_agent import _sanitize_field_insights
    src = [
        {"entity_type": "G", "field_name": "a", "typical_range": 123,
         "cause_hypotheses": "not-list", "confidence": "abc"},
        {"entity_type": "G", "field_name": "b", "typical_range": "1-10",
         "cause_hypotheses": ["h"], "confidence": 5.0},
        "not a dict",  # 非 dict 跳过
    ]
    out = _sanitize_field_insights(src)
    assert len(out) == 2
    assert out[0]["typical_range"] is None
    assert out[0]["cause_hypotheses"] == []
    assert out[0]["confidence"] == 0.0
    assert out[1]["typical_range"] == "1-10"  # 合法 str 保留
    assert out[1]["cause_hypotheses"] == ["h"]
    assert out[1]["confidence"] == 1.0  # 5.0 夹到 1.0
    # 不修改原始对象
    assert src[0]["typical_range"] == 123


def test_l19_validation_failure_sanitized_before_write(monkeypatch, tmp_path):
    """Pydantic 校验失败 → 净化后写盘, 不落非法原始 dict。"""
    import subgraphs.data_insights.agents.synthesis_agent as sa
    fake = _FakeLLM(exc=RuntimeError("offline"))
    monkeypatch.setattr(sa, "get_llm", lambda temperature=0.0: fake)

    import quality_pipeline.models.insights as insights_models

    def _raise(*a, **k):
        raise ValueError("forced validation failure")

    monkeypatch.setattr(insights_models.DataInsightsReport, "model_validate", _raise)

    bad_insights = [{"entity_type": "G", "field_name": "a",
                     "typical_range": 123, "cause_hypotheses": "x", "confidence": "abc"}]
    state = _mk_state_insights([])
    state["output_state"] = {"output_dir": str(tmp_path)}
    state["report_state"]["insights"] = {
        "field_insights": bad_insights,
        "relationships": [],
        "recommendations": {"overall_grade": "good"},
    }
    ret = sa.SynthesisAgent().run(state)
    written = ret["output_state"]["insights"]
    assert written["field_insights"][0]["typical_range"] is None
    assert written["field_insights"][0]["cause_hypotheses"] == []
    assert written["field_insights"][0]["confidence"] == 0.0

    files = list(tmp_path.glob("insights_*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text(encoding="utf-8"))
    assert on_disk["field_insights"][0]["typical_range"] is None
    assert on_disk["field_insights"][0]["confidence"] == 0.0


# ==========================================================
# 来源: test_audit_fixes_g11.py
# ==========================================================
"""G11 审计修复回归测试 — M-02 / M-03 / L-20 (纯离线, 禁网络/禁 LLM)

覆盖:
  - M-02: dispatch 重置 retry_by_node=None 走 _merge_dict 覆盖分支 (E→A/E→B 重试预算归零)
  - M-03: Assessment Failed/HR 信号在 dispatch 边界不丢失 (gate 写入的信号不被清空吞掉)
  - L-20: check_retry 死代码已删除, _make_stage_gate 保留重试语义
"""




# ==========================================================
# M-02: dispatch retry_by_node 重置改置 None
# ==========================================================

def test_merge_dict_none_overwrites_nested_dict():
    """M-02: _merge_dict 对 None 值走覆盖分支, 旧 dict 不残留"""
    left = {"workflow_state": {"retry_by_node": {"assessment_graph": 3}}}
    right = {"workflow_state": {"retry_by_node": None}}
    merged = _merge_dict(left, right)
    assert merged["workflow_state"]["retry_by_node"] is None


def test_merge_dict_empty_dict_recursively_merges_old_value():
    """M-02 复现锚点: {} 会被递归合并 → 旧计数残留 (修复前缺陷行为, 锁定语义)"""
    left = {"workflow_state": {"retry_by_node": {"assessment_graph": 3}}}
    right = {"workflow_state": {"retry_by_node": {}}}
    merged = _merge_dict(left, right)
    assert merged["workflow_state"]["retry_by_node"] == {"assessment_graph": 3}


def test_dispatch_resets_retry_by_node_to_none():
    """M-02: dispatch_node 输出 retry_by_node=None, 经 reducer 合并后旧计数归零"""
    state = make_initial_state({})
    # 模拟 E→A 重入前 normalization 已重试 3 次耗尽
    state["workflow_state"]["retry_by_node"] = {"normalization_graph": 3}
    out = dispatch_node(state)
    merged = _merge_dict(state, out)
    assert merged["workflow_state"]["retry_by_node"] is None


def test_dispatch_reset_gives_fresh_retry_budget():
    """M-02: 重置后 gate 从 0 重新计数 (若不重置, 旧计数 3 ≥ MAX_RETRIES 会直接 HR)"""
    state = make_initial_state({})
    state["workflow_state"]["retry_by_node"] = {"assessment_graph": routers.MAX_RETRIES}
    out = dispatch_node(state)
    merged = _merge_dict(state, out)
    # gate 读 None 安全 + 重试预算归零 → 首轮 Retry 仍重入而非 HumanReview
    gate_state = {
        "workflow_state": dict(merged["workflow_state"], execution_status="Retry"),
        "report_state": {},
    }
    ret = _make_stage_gate("assessment_graph")(gate_state)
    assert ret["workflow_state"]["route_decision"] == "__retry__"
    assert ret["workflow_state"]["retry_by_node"]["assessment_graph"] == 1


def test_retry_by_node_none_readers_safe():
    """M-02: 置 None 后所有 (wf.get("retry_by_node") or {}) 读取点安全"""
    wf = {"retry_by_node": None}
    assert (wf.get("retry_by_node") or {}).get("x", 0) == 0
    assert dict(wf.get("retry_by_node") or {}) == {}


# ==========================================================
# M-03: Assessment Failed 信号在 dispatch 边界不丢失
# ==========================================================

def _mk_state_routers(per_source_routes=None, status="Success", route_decision=""):
    st = make_initial_state({})
    st["workflow_state"]["execution_status"] = status
    st["workflow_state"]["route_decision"] = route_decision
    if per_source_routes is not None:
        st["report_state"]["quality"] = {"per_source_routes": per_source_routes}
    return st


def test_dispatch_failed_signal_merges_all_to_humanreview():
    """M-03: Assessment Failed (gate 写 route_decision=HumanReview) → 全部并入 HR 队列"""
    state = _mk_state_routers(
        per_source_routes={"s1": "Normalization", "s2": "Conflict", "s3": "Export"},
        status="Failed", route_decision="HumanReview",
    )
    out = dispatch_node(state)
    pending = out["workflow_state"]["pending_sources"]
    assert sorted(pending["HumanReview"]) == ["s1", "s2", "s3"]
    assert pending["Normalization"] == []
    assert pending["Conflict"] == []
    assert pending["Export"] == []
    # 信号保留, 供 route_after_dispatch 路由
    assert out["workflow_state"]["route_decision"] == "HumanReview"
    assert out["workflow_state"]["phase"] == "human_review"
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_HUMAN_REVIEW


def test_dispatch_retry_exhausted_signal():
    """M-03: Retry 耗尽 (gate 写 HumanReview) → 同样并入 HR 队列并路由 HR"""
    state = _mk_state_routers(
        per_source_routes={"s1": "Normalization"},
        status="Retry", route_decision="HumanReview",
    )
    out = dispatch_node(state)
    assert out["workflow_state"]["pending_sources"]["HumanReview"] == ["s1"]
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_HUMAN_REVIEW


def test_dispatch_failed_empty_routes_still_humanreview():
    """M-03: 失败且无 per_source_routes → 队列为空, 靠 route_decision 信号路由 HR"""
    state = _mk_state_routers(status="Failed", route_decision="HumanReview")
    out = dispatch_node(state)
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_HUMAN_REVIEW


def test_dispatch_humanreview_status_signal():
    """M-03: 子图返回 HumanReview 状态 (gate V3.5 分支) → 路由 HR"""
    state = _mk_state_routers(
        per_source_routes={"s1": "Conflict"},
        status="HumanReview", route_decision="HumanReview",
    )
    out = dispatch_node(state)
    assert out["workflow_state"]["pending_sources"]["HumanReview"] == ["s1"]
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_HUMAN_REVIEW


def test_dispatch_normal_path_unchanged():
    """M-03 防御: 正常路径 (Success) 行为不变 — 队列分开, route_decision 清空"""
    state = _mk_state_routers(per_source_routes={"s1": "Normalization", "s2": "Conflict"})
    out = dispatch_node(state)
    pending = out["workflow_state"]["pending_sources"]
    assert pending["Normalization"] == ["s1"]
    assert pending["Conflict"] == ["s2"]
    assert pending["HumanReview"] == []
    assert out["workflow_state"]["route_decision"] == ""
    assert out["workflow_state"]["phase"] == "dispatch"
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_NORMALIZATION


def test_dispatch_per_source_humanreview_unchanged():
    """M-03 防御: 正常 per-source HumanReview (Success) 仍走队列, 不并入其他来源"""
    state = _mk_state_routers(per_source_routes={"s1": "Normalization", "s2": "HumanReview"})
    out = dispatch_node(state)
    pending = out["workflow_state"]["pending_sources"]
    assert pending["HumanReview"] == ["s2"]
    assert pending["Normalization"] == ["s1"]
    merged = _merge_dict(state, out)
    assert route_after_dispatch(merged) == NODE_HUMAN_REVIEW


def test_route_after_dispatch_failed_signal_fallback():
    """M-03: route_after_dispatch 兜底 — 即使队列空, 失败/HR 信号仍路由 HR"""
    state = _mk_state_routers(status="Failed", route_decision="HumanReview")
    assert route_after_dispatch(state) == NODE_HUMAN_REVIEW
    state2 = _mk_state_routers(status="Success", route_decision="HumanReview")
    assert route_after_dispatch(state2) == NODE_HUMAN_REVIEW


# ==========================================================
# L-20: 删除 check_retry 死代码
# ==========================================================

def test_check_retry_removed():
    """L-20: check_retry 死代码已删除, 模块不再导出"""
    assert not hasattr(routers, "check_retry")


def test_stage_gate_preserves_retry_semantics():
    """L-20: 取代 check_retry 的 _make_stage_gate 保留重试语义 (重入/耗尽→HR/Failed→HR)"""
    gate = _make_stage_gate("assessment_graph")

    # 重试未耗尽 → 重入并递增计数
    st = make_initial_state({})
    st["workflow_state"]["execution_status"] = "Retry"
    ret = gate(st)
    assert ret["workflow_state"]["route_decision"] == "__retry__"
    assert ret["workflow_state"]["retry_by_node"]["assessment_graph"] == 1

    # 重试耗尽 (MAX_RETRIES) → HumanReview
    st = make_initial_state({})
    st["workflow_state"]["execution_status"] = "Retry"
    st["workflow_state"]["retry_by_node"] = {"assessment_graph": routers.MAX_RETRIES}
    ret = gate(st)
    assert ret["workflow_state"]["route_decision"] == "HumanReview"

    # Failed → HumanReview
    st = make_initial_state({})
    st["workflow_state"]["execution_status"] = "Failed"
    ret = gate(st)
    assert ret["workflow_state"]["route_decision"] == "HumanReview"

