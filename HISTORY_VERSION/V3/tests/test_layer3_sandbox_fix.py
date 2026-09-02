"""P0 沙箱加固单元测试 — builtins 扩充 / SSOT 沙箱同一性 / 后处理管线修复。

对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(b)(c)(e) (P0):
  (b) safe_builtins 追加 18 内置 + 6 异常类; operator/logging 移出白名单
  (c) sandbox_common SSOT: _MODULE_GLOBALS 自动注入; planning dry-run 不再
      手写沙箱 dict; _validate_generated_result 共享不变量门
  (e) 锚定 JSON 提取 / marker 分割 / AST 手术 / 缩进降级
全部离线 (0 LLM 0 网络)。
"""

import ast
import inspect
import pytest
import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环


# ─────────────────────────────── (b) builtins ───────────────────────────────

_NEW_BUILTINS = [
    "reversed", "next", "iter", "type", "repr", "format", "issubclass",
    "callable", "id", "hash", "frozenset", "bytes", "bytearray", "complex",
    "divmod", "pow", "ord", "chr",
]

_NEW_EXCEPTIONS = [
    "StopIteration", "RuntimeError", "ZeroDivisionError",
    "OverflowError", "ArithmeticError", "LookupError",
]


@pytest.mark.parametrize("name", _NEW_BUILTINS + _NEW_EXCEPTIONS)
def test_sandbox_builtins_available(name):
    """逐名断言: 新增 18 builtins + 6 异常类在沙箱 builtins 中可用。"""
    from quality_pipeline.sandbox.sandbox_common import _make_sandbox
    sb = _make_sandbox()
    assert name in sb["__builtins__"], f"沙箱 builtins 缺少 {name}"
    assert callable(sb["__builtins__"][name]), f"{name} 应可调用"


def test_sandbox_forbidden_names_not_added():
    """逃逸相关名字不放 builtins; __import__ 必须是 _safe_import 包装器。"""
    from quality_pipeline.sandbox.sandbox_common import _make_sandbox, _safe_import
    blt = _make_sandbox()["__builtins__"]
    for name in ("open", "eval", "exec", "compile", "getattr", "setattr",
                 "delattr", "input"):
        assert name not in blt, f"逃逸名字 {name} 不应出现在 builtins"
    assert blt["__import__"] is _safe_import  # 白名单包装器, 不可为裸 __import__


# ─────────────────────────────── (c) SSOT ───────────────────────────────

def test_module_globals_keys_match_allowlist():
    """_MODULE_GLOBALS 键集合 == _ALLOWED_MODULES, 且全量注入沙箱 globals。"""
    from quality_pipeline.sandbox.sandbox_common import (
        _ALLOWED_MODULES, _MODULE_GLOBALS, _make_sandbox,
    )
    assert set(_MODULE_GLOBALS.keys()) == set(_ALLOWED_MODULES)
    sb = _make_sandbox()
    for m in _ALLOWED_MODULES:
        assert sb[m] is _MODULE_GLOBALS[m], f"沙箱 globals 缺少模块 {m}"


def test_sandbox_factory_shared_between_agents():
    """两处沙箱同一性: normalization 与 planning 使用同一 SSOT 工厂。"""
    from subgraphs.data_normalization.agents.normalization_agent import (
        _make_sandbox as na_make, _validate_code_ast as na_validate,
        _ALLOWED_MODULES as na_mods, _safe_import as na_safe_import,
    )
    from quality_pipeline.sandbox.sandbox_common import (
        _make_sandbox as sc_make, _validate_code_ast as sc_validate,
        _ALLOWED_MODULES as sc_mods, _safe_import as sc_safe_import,
    )
    assert na_make is sc_make
    assert na_validate is sc_validate
    assert na_mods is sc_mods
    assert na_safe_import is sc_safe_import


def test_planning_dry_run_no_handwritten_sandbox():
    """planning dry-run 不再构造手写沙箱 dict (改用 _make_sandbox())。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    src = inspect.getsource(PlanningAgent._llm_generate_tool)
    assert "_make_sandbox()" in src
    assert '"__import__": _safe_import' not in src
    # 旧手写 dict 的两侧不一致注入 (itertools/statistics 手写行) 已删除
    assert '"itertools": __import__("itertools")' not in src
    assert '"statistics": __import__("statistics")' not in src


def test_dry_run_input_uses_l1l2_processed_samples():
    """dry-run 输入 = L1/L2 处理后样本形态 (执行端真实输入)。"""
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
    src = inspect.getsource(PlanningAgent._llm_generate_tool)
    assert "agent._execute_base" in src
    assert "agent._execute_adapted" in src
    assert 'test_records = r["data"]' in src


def test_operator_logging_removed_from_allowlist():
    """operator/logging 不在 _ALLOWED_MODULES, import operator 被 AST 拒。"""
    from quality_pipeline.sandbox.sandbox_common import _ALLOWED_MODULES, _validate_code_ast
    assert "operator" not in _ALLOWED_MODULES
    assert "logging" not in _ALLOWED_MODULES
    assert not _validate_code_ast('import operator\nb = operator.attrgetter("x")')
    assert not _validate_code_ast('import logging')
    # 白名单内模块 import 仍放行 (含 itertools/statistics)
    assert _validate_code_ast("import math\nimport itertools\nimport statistics")


# ─────────────────── (c) 共享不变量门 _validate_generated_result ───────────────────

def _validate_generated_result_matrix():
    from quality_pipeline.sandbox.sandbox_common import _validate_generated_result
    return _validate_generated_result


def test_validate_generated_result_ok():
    v = _validate_generated_result_matrix()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    r = v(recs, {"data": [dict(recs[0])], "log": [{"record_id": "r1"}]}, 100)
    assert r == {"ok": True, "kind": None, "message": ""}


def test_validate_generated_result_invalid_format():
    v = _validate_generated_result_matrix()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    assert v(recs, "not a dict", 100)["kind"] == "invalid_format"
    assert v(recs, {"x": 1}, 100)["kind"] == "invalid_format"
    assert v(recs, {"data": 5, "log": []}, 100)["kind"] == "invalid_format"
    assert v(recs, None, 100)["kind"] == "invalid_format"


def test_validate_generated_result_record_count_changed():
    v = _validate_generated_result_matrix()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    r = v(recs, {"data": [dict(recs[0]), {"record_id": "r2"}], "log": []}, 100)
    assert r["ok"] is False and r["kind"] == "record_count_changed"


def test_validate_generated_result_key_set_changed():
    v = _validate_generated_result_matrix()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    extra = {"data": [dict(recs[0], _extra=1)], "log": []}
    r = v(recs, extra, 100)
    assert r["ok"] is False and r["kind"] == "key_set_changed"
    missing = {"data": [{"record_id": "r1", "field_name": "f"}], "log": []}
    assert v(recs, missing, 100)["kind"] == "key_set_changed"


def test_validate_generated_result_log_too_large():
    v = _validate_generated_result_matrix()
    recs = [{"record_id": "r1", "field_name": "f", "field_value": "1", "field_unit": "pc"}]
    r = v(recs, {"data": [dict(recs[0])], "log": list(range(101))}, 100)
    assert r["ok"] is False and r["kind"] == "log_too_large"


# ─────────────────────────────── (e) 后处理管线 ───────────────────────────────

def test_extract_json_object_anchored():
    """锚定提取: fence 剥离 + 首个完整对象, 尾随文本自然丢弃。"""
    from subgraphs.data_normalization.agents.planning_agent import _extract_json_object
    # fence + 尾随 prose
    obj, err = _extract_json_object(
        '```json\n{"tool_name": "t", "tool_code": "x = 1", "confidence": 0.9}\n```\nHope this helps!')
    assert err is None and obj["tool_name"] == "t"
    # 字符串内 } 不截断
    obj, err = _extract_json_object(
        'Return {"tool_code": "rec[\\"field_value\\"] = str(v)", "tool_name": "t", "confidence": 0.9} and more')
    assert err is None and obj["tool_code"] == 'rec["field_value"] = str(v)'
    # 多个对象取首个
    obj, err = _extract_json_object('{"a": 1} {"b": 2}')
    assert err is None and obj == {"a": 1}
    # 失败路径返回结构化错误信息
    assert _extract_json_object("no json here")[0] is None
    assert _extract_json_object("")[0] is None
    assert _extract_json_object('{"a": }')[0] is None


def test_extract_business_logic_markers():
    """marker 分割: START/END 之间取逻辑; END 缺失到串尾。"""
    from subgraphs.data_normalization.agents.planning_agent import _extract_business_logic
    code = ("prefix\n# LLM_GENERATED_LOGIC_START\nx = 1\ny = 2\n"
            "# LLM_GENERATED_LOGIC_END\nsuffix")
    assert _extract_business_logic(code).strip() == "x = 1\ny = 2"
    no_end = "# LLM_GENERATED_LOGIC_START\nx = 1\ny = 2"
    assert _extract_business_logic(no_end).strip() == "x = 1\ny = 2"


def test_extract_business_logic_def_tool():
    """无 marker 但有 def tool( → 取首个 FunctionDef.body。"""
    from subgraphs.data_normalization.agents.planning_agent import _extract_business_logic
    code = 'def tool(records):\n    x = 1\n    return records\n'
    out = _extract_business_logic(code)
    assert "x = 1" in out and "return records" in out


def _compile_in_func(code):
    """清洗后逻辑带 4 空格基准缩进 (供模板注入), 需在函数上下文内 compile。"""
    return compile("def _wrapper():\n" + code, "<test>", "exec")


def test_surgery_removes_top_return_keeps_nested_def():
    """AST 手术后: 顶层 return 删除, 嵌套 helper def 与其 return 保留。"""
    import textwrap
    from subgraphs.data_normalization.agents.planning_agent import (
        _TOOL_CODE_TEMPLATE, _surgical_clean_logic,
    )
    from quality_pipeline.sandbox.sandbox_common import _validate_code_ast
    code = ('def _helper(x):\n'
            '    return x * 2\n'
            'for r in records:\n'
            '    r["field_value"] = str(_helper(2))\n'
            'return {"data": records}')
    cleaned = _surgical_clean_logic(code)
    assert "def _helper" in cleaned and "return x * 2" in cleaned
    assert "return {" not in cleaned
    tree = ast.parse(textwrap.dedent(cleaned))
    assert not any(isinstance(n, ast.Return) for n in tree.body)  # 仅删模块级 return
    _compile_in_func(cleaned)
    # 生产路径: 注入模板后的 full_code 仍过 AST 白名单
    assert _validate_code_ast(_TOOL_CODE_TEMPLATE.replace("{LLM_CODE}", cleaned))


def test_indent_boundary_8spaces_and_tabs_compile():
    """缩进边界: 8 空格深缩进 / tab 混用 → AST 手术后注入模板可 compile。"""
    from subgraphs.data_normalization.agents.planning_agent import (
        _TOOL_CODE_TEMPLATE, _surgical_clean_logic,
    )
    deep8 = ('        for r in records:\n'
             '            r["field_value"] = str(r["field_value"])\n'
             '        return {"data": records}')
    cleaned8 = _surgical_clean_logic(deep8)
    _compile_in_func(cleaned8)
    compile(_TOOL_CODE_TEMPLATE.replace("{LLM_CODE}", cleaned8), "<full8>", "exec")

    tabbed = ('for r in records:\n'
              '\tr["field_value"] = str(r["field_value"])\n'
              'return {"data": records}')
    cleaned_tab = _surgical_clean_logic(tabbed)
    _compile_in_func(cleaned_tab)
    compile(_TOOL_CODE_TEMPLATE.replace("{LLM_CODE}", cleaned_tab), "<fulltab>", "exec")
    # 8 空格深缩进必须被归一为 4 空格基准 (旧实现负 delta 保留 8 空格)
    assert cleaned8.startswith("    for r in records:")


def test_indent_fallback_dedent_compiles():
    """缩进降级路径: dedent + 非空行统一 4 空格前缀 → 可 compile。"""
    from subgraphs.data_normalization.agents.planning_agent import _indent_fallback_logic
    deep = ('    for r in records:\n'
            '        r["field_value"] = str(r["field_value"])')
    out = _indent_fallback_logic(deep)
    assert out.startswith("    for r in records:")
    _compile_in_func(out)
