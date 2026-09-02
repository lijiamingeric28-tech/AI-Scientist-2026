"""P3 Layer 3 golden corpus + 指标装置 (docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §8)。

Corpus 构成:
  - 17 实验片段 (按期望 stage_expected 归档 — 全部应为 effective, 其中 15 个
    pass@1、2 个 pass@3: 首轮失败经修复循环 (≤3 次 LLM) 后成功) — 对应
    附录 C 实验 17 片段的 8 根因失败模式, 经 P0/P1/P2/P3 修复后全部可达
    有效成功 (通过且真实修改数据且 log 非空)
  - 18 回归片段 (≥12, §8 清单全覆盖): 6 个放行类 (有界 while/tab/8 空格/
    嵌套 helper+顶层 return/itertools/黑名单撞名 Store) + 12 个拒绝类
    (walrus 逃逸/match 逃逸/try-except* (3.10 syntax_error)/无界 while/
    dunder/__import__ 别名/缺 confidence/no-op/键集合变/记录数变/log 爆/
    运行时死循环 slow 组) — 各自按期望 kind 断言

指标装置 (runner): 三层漏斗统计 (AST 通过率 / dry-run 通过率 / 执行接受率 /
有效成功率) + pass@1 / pass@3, 全部离线 mock LLM (PlanningAgent +
NormalizationAgent 真实管线)。

断言: 全 corpus 中 expect_success 片段的有效成功率 ≥ 85% (pass@3 口径,
阈值参数化 EFFECTIVE_SUCCESS_THRESHOLD)。
"""

import json

import pytest

import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环
from quality_pipeline.quality_state import _merge_dict

# 有效成功率阈值 (pass@3 口径, 参数化)
EFFECTIVE_SUCCESS_THRESHOLD = 0.85

_SID = "S1"


# ══════════════════════════════ mock LLM ══════════════════════════════

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


def _tool_response(tool_name, tool_code, confidence=0.9):
    return json.dumps({
        "tool_name": tool_name,
        "tool_code": tool_code,
        "confidence": confidence,
        "self_check": {"assertions": [], "sample_predictions": []},
        "reasoning": "golden",
    })


# ══════════════════════════════ state builders ══════════════════════════════

def _tilde_records():
    """3 条 ~ 前缀记录 (format 目标问题可验证)。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "pc",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [dict(base, record_id=f"r{i}", field_value=f"~{770 + i}") for i in (1, 2, 3)]


def _plain_str_records(unit=""):
    """3 条纯字符串数值记录 (无 ~ 前缀, 缺单位可验证)。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": unit,
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [dict(base, record_id=f"r{i}", field_value=str(770 + i)) for i in (1, 2, 3)]


def _trim_records():
    """3 条带首尾空白的字符串记录。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "pc",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [dict(base, record_id=f"r{i}", field_value=f"  {770 + i}  ") for i in (1, 2, 3)]


def _fill_records():
    """3 条记录: r1/r3 field_value=None (填充目标), r2 正常。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "pc",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [dict(base, record_id="r1", field_value=None),
            dict(base, record_id="r2", field_value=5.0),
            dict(base, record_id="r3", field_value=None)]


def _no_unit_records():
    """3 条缺单位数值记录 (missing units 目标问题可验证)。"""
    base = {"source_id": _SID, "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_unit": "",
            "provenance": {"page": 12, "bbox": [1, 2, 3, 4]}}
    return [dict(base, record_id=f"r{i}", field_value=f"~{770 + i}") for i in (1, 2, 3)]


def _issues_src(missing_units=4, missing_prov=4, score=0.6, fmt=3):
    """使 _find_unresolved 评分 ≥2 触发 Layer 3 (多维度叠加)。"""
    return {
        "completeness": {"present_fields": ["distance"], "expected_fields": ["distance"],
                         "records_missing_unit": missing_units,
                         "records_missing_provenance": missing_prov,
                         "score": score, "missing_expected_fields": []},
        "format": {"total_issues": fmt},
        "consistency": {"unit_consistency": {}},
        "conflict_risk": {"conflict_count": 0},
    }


def _planning_state(records, issues_src):
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
                        _SID: {"conditions": [{"condition": "completeness_low"}],
                               "conflict_ctions": []}},
                    "errors": [],
                },
            },
        },
    }


# ══════════════════════════════ check predicates (有效成功判定) ══════════════════════════════

def _check_no_tilde(data):
    return all(not (isinstance(r.get("field_value"), str)
                    and r.get("field_value", "").strip().startswith("~")) for r in data)


def _check_all_numeric(data):
    return all(isinstance(r.get("field_value"), (int, float)) for r in data)


def _check_trimmed(data):
    return all(not (isinstance(r.get("field_value"), str)
                    and r.get("field_value", "").strip() != r.get("field_value")) for r in data)


def _check_filled(data):
    return all(r.get("field_value") is not None for r in data)


def _check_units_present(data):
    return all(r.get("field_unit") for r in data)


# ══════════════════════════════ 17 实验片段 ══════════════════════════════

_STRIP_TILDE_LOGIC = (
    "for r in records:\n"
    "    v = _safe_get(r, 'field_value')\n"
    "    if isinstance(v, str) and v.strip().startswith('~'):\n"
    "        r['field_value'] = v.strip()[1:]\n"
    "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
    "'field': 'field_value',\n"
    "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"
)

_EXPERIMENTAL = [
    {"id": "exp_strip_tilde", "desc": "剥离 ~ 前缀 (根因5 schema 修复)",
     "tool_code": _STRIP_TILDE_LOGIC, "records": _tilde_records,
     "check": _check_no_tilde},
    {"id": "exp_numeric_convert", "desc": "字符串数值转数值 (_to_number)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if _is_numeric(v):\n"
         "        r['field_value'] = _to_number(v)\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'convert', 'before': str(v), "
         "'after': str(_to_number(v))})\n"),
     "records": lambda: _plain_str_records(), "check": _check_all_numeric},
    {"id": "exp_trim_whitespace", "desc": "去首尾空白",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip() != v:\n"
         "        r['field_value'] = v.strip()\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'trim', 'before': v, 'after': v.strip()})\n"),
     "records": _trim_records, "check": _check_trimmed},
    {"id": "exp_guard_isinstance", "desc": "isinstance 守卫 (根因1 类型错)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if not isinstance(v, str):\n"
         "        continue\n"
         "    s = v.strip()\n"
         "    if not s:\n"
         "        continue\n"
         "    if s.startswith(('~', '≈')):\n"
         "        r['field_value'] = s[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': s[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_fstring_log", "desc": "f-string 日志 (P0 a 节点)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        new = v.strip()[1:]\n"
         "        r['field_value'] = new\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': f'{v!r}', "
         "'after': f'{new!r}'})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_walrus_positive", "desc": "walrus 表达式 (P1 a 放行)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and (n := len(v)) > 1 and v.startswith('~'):\n"
         "        r['field_value'] = v[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde,
     "bad_first": True,   # pass@3: 首轮猜错字段名 → noop → 修复
     "bad_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_valuex')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n")},
    {"id": "exp_match_positive", "desc": "match 语句 (P1 a 放行)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    match v:\n"
         "        case str(s) if s.startswith('~'):\n"
         "            r['field_value'] = s[1:]\n"
         "            _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                         'action': 'strip', 'before': v, 'after': s[1:]})\n"
         "        case _:\n"
         "            pass\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_nested_helper", "desc": "嵌套 helper def (P0 e 不再删行)",
     "tool_code": (
         "def _strip(v):\n"
         "    return v[1:] if isinstance(v, str) and v.startswith('~') else v\n"
         "\n"
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    new = _strip(v)\n"
         "    if new != v:\n"
         "        r['field_value'] = new\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': str(v), 'after': str(new)})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_try_except", "desc": "try/except + 异常类 (P0 b builtins)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str):\n"
         "        try:\n"
         "            f = float(v)\n"
         "        except ValueError:\n"
         "            continue\n"
         "        r['field_value'] = f\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'convert', 'before': v, 'after': f})\n"),
     "records": lambda: _plain_str_records(), "check": _check_all_numeric},
    {"id": "exp_itertools", "desc": "itertools 模块注入 (P0 b 对称化)",
     "tool_code": (
         "for r in chain(records):\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_regex", "desc": "re.match 模式匹配",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str):\n"
         "        m = re.match(r'^[~≈]\\s*(.+)$', v.strip())\n"
         "        if m:\n"
         "            r['field_value'] = m.group(1)\n"
         "            _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                         'action': 'strip', 'before': v, 'after': m.group(1)})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_early_return", "desc": "逻辑内顶层 return (P0 e 缩进降级)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"
         "return {'data': records, 'log': _log, 'summary': 'done'}\n"),
     "records": _tilde_records, "check": _check_no_tilde,
     "bad_first": True,   # pass@3: 首轮语法错误 → 修复
     "bad_code": "for r in records:\n    x = (1\n"},
    {"id": "exp_safe_get_fill", "desc": "_safe_get 防御取值 + None 填充",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if v is None or (isinstance(v, str) and v.strip() == ''):\n"
         "        r['field_value'] = '0'\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'fill', 'before': str(v), 'after': '0'})\n"),
     "records": _fill_records, "check": _check_filled},
    {"id": "exp_multi_field", "desc": "field_value + field_unit 多字段联动",
     "tool_code": (
         "for r in records:\n"
         "    if not _safe_get(r, 'field_unit') and _is_numeric(_safe_get(r, 'field_value')):\n"
         "        r['field_unit'] = 'pc'\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_unit',\n"
         "                     'action': 'fill_unit', 'before': '', 'after': 'pc'})\n"),
     "records": lambda: _plain_str_records(), "check": _check_units_present},
    {"id": "exp_mapping_dict", "desc": "映射 dict 变换",
     "tool_code": (
         "mapping = {'~': '', '≈': ''}\n"
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str):\n"
         "        s = v.strip()\n"
         "        for pre, rep in mapping.items():\n"
         "            if s.startswith(pre):\n"
         "                r['field_value'] = s[len(pre):]\n"
         "                _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                             'action': 'strip', 'before': v, "
         "'after': s[len(pre):]})\n"
         "                break\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_bounded_for", "desc": "有界 for + range 循环",
     "tool_code": (
         "for i in range(len(records)):\n"
         "    r = records[i]\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "exp_log_after_only", "desc": "逐条修改均有 log (根因5/7 可见性)",
     "tool_code": (
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        new = v.strip()[1:]\n"
         "        r['field_value'] = new\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': new})\n"
         "_summary = 'stripped tilde prefixes'\n"),
     "records": _tilde_records, "check": _check_no_tilde},
]

# ══════════════════════════════ 18 回归片段 (§8 清单全覆盖) ══════════════════════════════

_REGRESSION = [
    {"id": "reg_walrus_escape", "desc": "walrus 内 dunder 逃逸 (拒)",
     "tool_code": "if (t := type.__subclasses__):\n    pass\n",
     "records": _tilde_records, "expect_kind": "ast_blocked"},
    {"id": "reg_match_escape", "desc": "match 内 dunder 逃逸 (拒)",
     "tool_code": "match x:\n    case _:\n        type.__subclasses__\n",
     "records": _tilde_records, "expect_kind": "ast_blocked"},
    {"id": "reg_try_except_star_py310", "desc": "try-except* (3.10 期望 syntax_error)",
     "tool_code": "try:\n    x = 1\nexcept* ValueError:\n    pass\n",
     "records": _tilde_records, "expect_kind": "syntax_error"},
    {"id": "reg_bounded_while", "desc": "有界 while 计数器 (放行)",
     "tool_code": (
         "i = 0\n"
         "while i < 3:\n"
         "    r = records[i]\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip() != v:\n"
         "        r['field_value'] = v.strip()\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'trim', 'before': v, 'after': v.strip()})\n"
         "    i += 1\n"),
     "records": _trim_records, "check": _check_trimmed},
    {"id": "reg_unbounded_while", "desc": "无界 while (拒 + 行号消息)",
     "tool_code": "while True:\n    pass\n",
     "records": _tilde_records, "expect_kind": "ast_blocked",
     "expect_line": True},
    {"id": "reg_tab_indent", "desc": "tab 缩进 (放行, P0 e expandtabs)",
     "tool_code": (
         "for r in records:\n"
         "\tv = _safe_get(r, 'field_value')\n"
         "\tif isinstance(v, str) and v.strip().startswith('~'):\n"
         "\t\tr['field_value'] = v.strip()[1:]\n"
         "\t\t_log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "\t\t             'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "reg_8_space_indent", "desc": "8 空格缩进 (放行, AST unparse 归一)",
     "tool_code": (
         "for r in records:\n"
         "        v = _safe_get(r, 'field_value')\n"
         "        if isinstance(v, str) and v.strip().startswith('~'):\n"
         "            r['field_value'] = v.strip()[1:]\n"
         "            _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                         'action': 'strip', 'before': v, "
         "'after': v.strip()[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "reg_nested_helper_top_return", "desc": "嵌套 helper + 顶层 return (放行)",
     "tool_code": (
         "def _helper(v):\n"
         "    return v[1:] if isinstance(v, str) and v.startswith('~') else v\n"
         "\n"
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    new = _helper(v)\n"
         "    if new != v:\n"
         "        r['field_value'] = new\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': str(v), 'after': str(new)})\n"
         "return {'data': records, 'log': _log, 'summary': 'done'}\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "reg_itertools_use", "desc": "逻辑级 import 白名单模块 (放行)",
     "tool_code": (
         "import statistics\n"
         "vals = []\n"
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        vals.append(float(v.strip()[1:]))\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"
         "_summary = 'mean=' + str(statistics.mean(vals)) if vals else 'noop'\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "reg_blacklist_name_store", "desc": "黑名单名 Store 撞名 (放行, P1 a Load 限定)",
     "tool_code": (
         "eval = 5\n"
         "for r in records:\n"
         "    v = _safe_get(r, 'field_value')\n"
         "    if isinstance(v, str) and v.strip().startswith('~'):\n"
         "        r['field_value'] = v.strip()[1:]\n"
         "        _log.append({'record_id': _safe_get(r, 'record_id', '?'), "
         "'field': 'field_value',\n"
         "                     'action': 'strip', 'before': v, 'after': v.strip()[1:]})\n"),
     "records": _tilde_records, "check": _check_no_tilde},
    {"id": "reg_dunder", "desc": "dunder 属性链 (拒)",
     "tool_code": "x = 1\ny = x.__class__.__mro__\n",
     "records": _tilde_records, "expect_kind": "ast_blocked"},
    {"id": "reg_import_alias", "desc": "__import__ 别名 (拒, Name Load)",
     "tool_code": "_imp = __import__\n",
     "records": _tilde_records, "expect_kind": "ast_blocked"},
    {"id": "reg_missing_confidence", "desc": "缺 confidence (拒, 契约校验)",
     "no_confidence": True,   # LLM 响应缺 confidence 键
     "tool_code": "for r in records:\n    pass\n",
     "records": _tilde_records, "expect_kind": "confidence_invalid"},
    {"id": "reg_noop", "desc": "零修改 no-op (拒, dry-run)",
     "tool_code": "for r in records:\n    pass\n",
     "records": _no_unit_records, "expect_kind": "noop"},
    {"id": "reg_key_set_change", "desc": "键集合变 (拒)",
     "tool_code": "for r in records:\n    r['new_key'] = 1\n",
     "records": _tilde_records, "expect_kind": "key_set_changed"},
    {"id": "reg_record_count_change", "desc": "记录数变 (拒)",
     "tool_code": "records.append({'record_id': 'x'})\n",
     "records": _tilde_records, "expect_kind": "record_count_changed"},
    {"id": "reg_log_burst", "desc": "log 爆量 (拒, 上限 50000)",
     "tool_code": ("for i in range(60000):\n"
                   "    _log.append({'record_id': 'x', 'field': 'f', 'action': 'spam'})\n"),
     "records": _tilde_records, "expect_kind": "log_too_large"},
    {"id": "reg_runtime_deadlock", "desc": "运行时死循环 (拒, slow 组 exec_timeout)",
     "tool_code": ("flag = False\n"
                   "i = 0\n"
                   "while i < 10:\n"
                   "    if flag:\n"
                   "        i += 1\n"),
     "records": _tilde_records, "expect_kind": "exec_timeout",
     "slow": True},
]


def _normalize_fragment(frag):
    """补齐默认键: expect_success / stage / bad_first / resp。"""
    f = dict(frag)
    f.setdefault("expect_success", "check" in f)   # 有 check 谓词 = 期望有效成功
    f.setdefault("bad_first", False)
    f.setdefault("issues", _issues_src())
    return f


# ══════════════════════════════ 指标装置 runner ══════════════════════════════

def _run_fragment(monkeypatch, frag):
    """单片段过真实管线 (PlanningAgent + NormalizationAgent, mock LLM)。

    Returns:
        {"effective": bool, "registered": bool, "ast_ok": bool,
         "exec_ok": bool, "kind": <首个失败 kind|None>, "calls": int,
         "errors": <执行期错误数>}
    """
    from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
    from subgraphs.data_normalization.agents.planning_agent import PlanningAgent

    if frag.get("slow"):
        # 死循环片段: 缩短沙箱超时 (仅本片段, _run_with_timeout 调用时读全局)
        import subgraphs.data_normalization.agents.normalization_agent as na_mod
        monkeypatch.setattr(na_mod, "_SANDBOX_TIMEOUT_SEC", 1.0)

    resp = _tool_response(frag["id"], frag["tool_code"])
    if frag.get("no_confidence"):
        resp = json.dumps({
            "tool_name": frag["id"], "tool_code": frag["tool_code"],
            "self_check": {"assertions": [], "sample_predictions": []},
            "reasoning": "golden"})
    if frag.get("bad_first"):
        bad = _tool_response(frag["id"], frag["bad_code"])
        seq = [bad, resp, resp]
    else:
        seq = [resp]
    fake = _mock_llm(monkeypatch, seq)

    state = _planning_state(frag["records"](), frag["issues"])
    out = PlanningAgent().run(state)
    norm = out["report_state"]["normalization"]
    attempts = norm["layer3"]["attempts"]
    first_kind = attempts[0].get("kind") if attempts else None
    gen = norm["tool_registry"]["by_source"][_SID]["generated"]

    result = {"effective": False, "registered": bool(gen),
              "ast_ok": first_kind not in ("ast_blocked", "syntax_error"),
              "exec_ok": False, "kind": first_kind, "calls": fake.calls,
              "errors": 0,
              "line": attempts[0].get("line") if attempts else None}
    if not gen:
        return result

    merged = _merge_dict(state, out)
    out2 = NormalizationAgent().run(merged)
    mods = out2["report_state"]["normalization"]["modifications"]
    data = out2["data_state"]["current_data"]["records"]
    generated_logs = mods["details"]["generated"]
    result["errors"] = len(mods["errors"])
    result["exec_ok"] = True
    # 有效成功: 执行接受 且 数据真实修改 (check 谓词) 且 log 非空
    check = frag.get("check")
    if check is not None and check(data) and generated_logs:
        result["effective"] = True
    return result


def _funnel_summary(results):
    """三层漏斗 + pass@1/pass@3 统计 (全 corpus 口径)。"""
    total = len(results)
    ast_pass = sum(1 for r in results.values() if r["ast_ok"])
    dry_run_pass = sum(1 for r in results.values() if r["registered"])
    exec_accept = sum(1 for r in results.values() if r["exec_ok"])
    effective = sum(1 for r in results.values() if r["effective"])
    pass1 = sum(1 for r in results.values() if r["effective"] and r["calls"] == 1)
    pass3 = sum(1 for r in results.values() if r["effective"] and r["calls"] <= 3)
    return (
        f"corpus={total}  AST 通过率={ast_pass}/{total} ({ast_pass / total:.1%})  "
        f"dry-run 通过率={dry_run_pass}/{total} ({dry_run_pass / total:.1%})  "
        f"执行接受率={exec_accept}/{total} ({exec_accept / total:.1%})  "
        f"有效成功率={effective}/{total} ({effective / total:.1%})  "
        f"pass@1={pass1}/{total} ({pass1 / total:.1%})  "
        f"pass@3={pass3}/{total} ({pass3 / total:.1%})"
    )


def _success_set_summary(results, corpus):
    """expect_success 子集的有效成功率 (pass@3 口径, 断言对象)。"""
    working = [f["id"] for f in corpus if f["expect_success"]]
    eff = sum(1 for fid in working if results[fid]["effective"])
    return eff, len(working), working


# ══════════════════════════════ 测试 ══════════════════════════════

_CORPUS = [_normalize_fragment(f) for f in _EXPERIMENTAL + _REGRESSION]


def test_golden_corpus_funnel_and_effective_success(monkeypatch):
    """全 corpus 跑指标装置: 漏斗统计 + 有效成功率 ≥85% (pass@3, 阈值参数化)。

    - expect_success 片段 (17 实验 + 6 放行回归) 全部达到有效成功
    - 拒绝类回归片段按期望 kind 拒绝 (含行号消息断言)
    """
    results = {}
    failures = []
    for frag in _CORPUS:
        r = _run_fragment(monkeypatch, frag)
        results[frag["id"]] = r
        if frag["expect_success"] and not r["effective"]:
            failures.append(
                f"{frag['id']}: expected effective, got stage={r['kind']} "
                f"registered={r['registered']} exec_ok={r['exec_ok']} "
                f"errors={r['errors']} calls={r['calls']}")
        if not frag["expect_success"]:
            got_kind = r["kind"]
            if got_kind != frag["expect_kind"]:
                failures.append(
                    f"{frag['id']}: expected kind={frag['expect_kind']}, "
                    f"got {got_kind}")
            elif frag.get("expect_line"):
                # 无界 while 拒绝必须带行号 (修复循环定位依据)
                if r["line"] is None:
                    failures.append(
                        f"{frag['id']}: ast_blocked 应带 line (修复循环定位), got None")

    # 拒绝类片段至少覆盖 §8 清单: 每种期望 kind 都出现
    rejected_kinds = sorted({f["expect_kind"] for f in _CORPUS if not f["expect_success"]})
    assert rejected_kinds == sorted(["ast_blocked", "syntax_error", "confidence_invalid",
                                     "noop", "key_set_changed", "record_count_changed",
                                     "log_too_large", "exec_timeout"]), rejected_kinds

    # 有效成功率 ≥85% (pass@3 口径, expect_success 子集)
    eff, total_working, working = _success_set_summary(results, _CORPUS)
    rate = eff / total_working
    summary = _funnel_summary(results)
    detail = "; ".join(failures) if failures else "all expect_success fragments effective"
    assert not failures, f"corpus failures: {detail}\n{summary}"
    assert rate >= EFFECTIVE_SUCCESS_THRESHOLD, (
        f"effective success rate {rate:.1%} < {EFFECTIVE_SUCCESS_THRESHOLD:.0%} "
        f"(pass@3) over working corpus {working}\n{summary}")

    # pass@1 / pass@3 报告 (全 corpus)
    pass1 = sum(1 for r in results.values() if r["effective"] and r["calls"] == 1)
    pass3 = sum(1 for r in results.values() if r["effective"] and r["calls"] <= 3)
    print(f"[golden] {summary} | success-set={eff}/{total_working} "
          f"({rate:.1%}) pass@1={pass1} pass@3={pass3}")


def test_corpus_composition():
    """corpus 构成断言: 17 实验片段 + ≥12 回归片段; 实验片段全含 check 谓词。"""
    exp = [f for f in _CORPUS if f["id"].startswith("exp_")]
    reg = [f for f in _CORPUS if f["id"].startswith("reg_")]
    assert len(exp) == 17, f"实验片段应为 17, got {len(exp)}"
    assert len(reg) >= 12, f"回归片段应 ≥12, got {len(reg)}"
    assert all(f["expect_success"] for f in exp)
    # §8 回归清单关键类别全覆盖 (放行类 6 + 拒绝类 12)
    allowed_reg = [f["id"] for f in reg if f["expect_success"]]
    assert len(allowed_reg) == 6, allowed_reg
    assert "reg_bounded_while" in allowed_reg and "reg_tab_indent" in allowed_reg
    assert "reg_8_space_indent" in allowed_reg
    assert "reg_nested_helper_top_return" in allowed_reg
    assert "reg_itertools_use" in allowed_reg
    assert "reg_blacklist_name_store" in allowed_reg
