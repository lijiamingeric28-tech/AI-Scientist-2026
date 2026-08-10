"""审计修复回归测试（由 test_audit_fixes_g*.py 合并，测试函数与辅助逻辑全部保留）"""

import pytest
import astroquery_ai.adapters as adapters
import astroquery_ai.main_graph as main_graph_module
import astroquery_ai.property_standardization as ps
from astroquery_ai.aggregator import final_aggregator
from astroquery_ai.state import MainGraphState
import importlib
import astroquery_ai  # noqa: F401
import subgraphs.subgraph2.graph as sg2_graph
import subgraphs.subgraph3.graph as sg3_graph
from subgraphs.subgraph1.utils import llm_utils
import json
import astroquery_ai  # noqa: F401  先导入以解循环依赖
import os
from PIL import Image
from subgraphs.subgraph3.utils.image_cache import ImageCache
import importlib.util
import sys
import yaml
from quality_pipeline.configs import (
    load_domain_config,
    load_quality_scoring_runtime,
    load_yaml,
    set_research_domain,
)
from quality_pipeline.tools.normalization.unit_converter import convert_units

# ==========================================================
# 来源: test_audit_fixes_g1.py
# ==========================================================
"""G1 组审计修复回归测试（docs/AUDIT_REPORT.md: H-01/H-05/M-01/L-01/L-02/L-03）

纯离线：禁网络、禁 LLM —— 所有外部依赖（子图 subgraph、OpenAI 客户端）在
fixture 层 monkeypatch 掉。只验证缺陷点的修复行为与正常路径不回归。
"""




# ══════════════════════════════════════════════════════════════
# H-01: MainGraphState 声明 figure_evidence 通道
# ══════════════════════════════════════════════════════════════

def test_state_declares_figure_evidence():
    """figure_evidence 必须在 MainGraphState 声明（否则 LangGraph 静默丢弃）

    注：py3.10 下 stdlib TypedDict 无法识别 typing_extensions.NotRequired 标记
    （所有键都落进 __required_keys__，与既有 NotRequired 字段一致），
    因此从注解本身验证"保持 NotRequired"。
    """
    import typing
    import typing_extensions

    assert "figure_evidence" in MainGraphState.__annotations__
    hint = MainGraphState.__annotations__["figure_evidence"]
    assert typing.get_origin(hint) is typing_extensions.NotRequired
    assert typing.get_args(hint) == (typing.List[typing.Dict],)


def test_aggregator_passes_figure_evidence():
    """aggregator 把 state.figure_evidence 写入 final_output（独立通路）"""
    evidence = [{"page": 1, "path": "/tmp/fig1.png", "caption": "图1"}]
    out = final_aggregator({"figure_evidence": evidence})
    assert out["final_output"]["figure_evidence"] == evidence


def test_extraction_node_passes_figure_evidence(monkeypatch):
    """extraction_node 上浮子图 3 的 figure_evidence（生产者侧通道）"""

    class _FakeSubgraph:
        def invoke(self, *args, **kwargs):
            return {
                "paper_records": [],
                "processing_summary": {"total_papers": 0},
                "figure_evidence": [{"page": 1, "path": "/tmp/fig1.png"}],
            }

    monkeypatch.setattr(
        sg3_graph, "create_extraction_subgraph",
        lambda checkpointer=None: _FakeSubgraph(),
    )
    out = adapters.extraction_node({
        "query_id": "q1",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "paper_results": {"download_paths": [], "sources": []},
    })
    assert out["figure_evidence"] == [{"page": 1, "path": "/tmp/fig1.png"}]


# ══════════════════════════════════════════════════════════════
# H-05: P1 requested_properties 条目形状校验
# ══════════════════════════════════════════════════════════════

def _make_fake_openai(content: str):
    """构造返回固定 content 的假 OpenAI 客户端（离线替身）"""

    class _FakeMessage:
        def __init__(self):
            self.content = content

    class _FakeChoice:
        def __init__(self):
            self.message = _FakeMessage()

    class _FakeResponse:
        def __init__(self):
            self.choices = [_FakeChoice()]

    class _FakeCompletions:
        def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = _FakeChat()

    return _FakeOpenAI


def _call_select_with_llm(monkeypatch, content: str):
    monkeypatch.setattr(ps, "OpenAI", _make_fake_openai(content))
    rag = {"otype": "G", "name_cn": "星系", "description": "", "properties": []}
    return ps.select_properties_with_llm(rag, "M31", "M31 的金属丰度")


def test_h05_filter_non_dict_entries(monkeypatch):
    """非 dict / 缺 property_id 条目被过滤（记 warning），合法条目保留"""
    selected, err = _call_select_with_llm(
        monkeypatch,
        '{"requested_properties": ['
        '{"property_id": "fe_h", "reason": "用户要求"}, '
        '"distance", '
        '{"foo": 1}, '
        '{"property_id": ""}'
        ']}',
    )
    assert err is None
    assert selected == [{"property_id": "fe_h", "reason": "用户要求"}]


def test_h05_all_invalid_returns_error(monkeypatch):
    """全部非法 → (None, err)，走既有错误路径，不再 TypeError"""
    selected, err = _call_select_with_llm(
        monkeypatch,
        '{"requested_properties": ["fe_h", "distance"]}',
    )
    assert selected is None
    assert err is not None
    assert "全部非法" in err


def test_h05_valid_entries_unchanged(monkeypatch):
    """合法 dict 列表原样透传（正常路径不回归）"""
    content = (
        '{"requested_properties": ['
        '{"property_id": "fe_h", "reason": "a"}, '
        '{"property_id": "distance", "reason": "b"}]}'
    )
    selected, err = _call_select_with_llm(monkeypatch, content)
    assert err is None
    assert [s["property_id"] for s in selected] == ["fe_h", "distance"]


# ══════════════════════════════════════════════════════════════
# M-01: retrieval_node 异常路径保留 P1 simbad_info
# ══════════════════════════════════════════════════════════════

def test_retrieval_node_exception_keeps_p1_simbad(monkeypatch):
    """子图 2 抛异常时 fallback 合并 P1 simbad_info（与成功路径 B3 fix 语义一致）"""

    def _boom_subgraph(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sg2_graph, "create_retrieval_subgraph", _boom_subgraph)

    state = {
        "query_id": "q1",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "simbad_info": {
            "main_id": "M31", "otype": "G", "ra": 10.0, "dec": 41.0,
            "sp_type": "S", "ALIASES": ["NGC 224"],
        },
    }
    out = adapters.retrieval_node(state)

    # P1 字段保留，仅 status 标注检索失败
    assert out["simbad_info"]["main_id"] == "M31"
    assert out["simbad_info"]["otype"] == "G"
    assert out["simbad_info"]["ra"] == 10.0
    assert out["simbad_info"]["status"] == "failed"
    # 错误日志 + 空壳检索结构仍存在（契约不变）
    assert out["error_log"][0]["error"].startswith("RuntimeError")
    assert out["database_results"]["records"] == []
    assert out["paper_results"]["download_paths"] == []


def test_retrieval_node_exception_without_p1_simbad(monkeypatch):
    """无 P1 simbad_info 时异常路径仍产出合法 simbad_info 空壳（正常路径不回归）"""

    def _boom_subgraph(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sg2_graph, "create_retrieval_subgraph", _boom_subgraph)

    out = adapters.retrieval_node({
        "query_id": "q1",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
    })
    assert out["simbad_info"]["status"] == "failed"
    assert out["simbad_info"]["main_id"] is None
    assert out["simbad_info"]["aliases"] == []


# ══════════════════════════════════════════════════════════════
# L-01: 删除 _timed/_stage_times 死代码
# ══════════════════════════════════════════════════════════════

def test_no_timed_dead_code():
    """_timed/_stage_times 已删除（零调用点死代码）"""
    assert not hasattr(adapters, "_timed")
    assert not hasattr(adapters, "_stage_times")


# ══════════════════════════════════════════════════════════════
# L-02: 消除 generate_target_schema 双实现漂移
# ══════════════════════════════════════════════════════════════

def test_p1_no_generate_target_schema():
    """P1 的 generate_target_schema 已删除，quality_adapter 为唯一实现"""
    assert not hasattr(ps, "generate_target_schema")


def test_quality_adapter_single_impl_keeps_criticality():
    """唯一实现（quality_adapter）保留 criticality 字段（原漂移点）"""
    from astroquery_ai.quality_adapter import generate_target_schema

    ts = generate_target_schema([{
        "property_id": "fe_h", "unit": "dex", "category": "physical",
        "ucd": "phys.abund.Fe", "description": "铁丰度",
    }])
    field = ts["fields"][0]
    assert field["name"] == "fe_h"
    assert field["standard_unit"] == "dex"
    assert field["semantic_type"] == "physical"
    assert field["criticality"] == "important"


def test_p1_node_no_target_schema_write(monkeypatch):
    """property_standardization_node 不再写入 state.target_schema（仅 simbad+spec）"""
    monkeypatch.setattr(ps, "query_simbad", lambda name: (
        {"main_id": "M31", "otype": "G"}, None
    ))
    monkeypatch.setattr(ps, "load_rag_properties", lambda r: {
        "otype": "G", "name_cn": "星系", "description": "",
        "properties": [{
            "property_id": "fe_h", "name_cn": "铁丰度", "unit": "dex",
            "category": "physical", "ucd": "u", "description": "d",
        }],
    })
    monkeypatch.setattr(ps, "select_properties_with_llm", lambda *a, **k: (
        [{"property_id": "fe_h", "reason": "x"}], None
    ))

    out = ps.property_standardization_node({
        "target_entity": "M31",
        "user_query": "M31 的金属丰度",
        "requested_properties": [],
    })
    assert "target_schema" not in out
    assert out["simbad_info"]["main_id"] == "M31"
    assert out["property_spec"][0]["property_id"] == "fe_h"


# ══════════════════════════════════════════════════════════════
# L-03: HITL input EOFError 捕获
# ══════════════════════════════════════════════════════════════

def test_run_pipeline_eof_cancels(monkeypatch):
    """HITL 循环 input() EOF → 视为取消，返回当前 state 而非抛栈"""
    class _FakeApp:
        def __init__(self):
            self.invocations = []

        def invoke(self, *args, **kwargs):
            self.invocations.append((args, kwargs))
            return {"__interrupt__": [{"text": "确认检索?"}]}

    fake = _FakeApp()
    monkeypatch.setattr(main_graph_module, "create_main_graph",
                        lambda checkpointer=None: fake)
    monkeypatch.setattr(
        main_graph_module, "_prompt_for_interrupt",
        lambda payloads: (_ for _ in ()).throw(EOFError("EOF")),
    )

    result = main_graph_module.run_pipeline("M31 距离")
    # 返回带 __interrupt__ 的当前 state，且没有 resume 第二次 invoke
    assert result.get("__interrupt__") == [{"text": "确认检索?"}]
    assert len(fake.invocations) == 1


def test_cli_eof_returns_0(monkeypatch, tmp_path):
    """cli 层补 EOFError 分支：输入流关闭按取消处理，退出码 0"""
    import astroquery_ai.cli as cli_mod

    class _Args:
        query = "M31 距离"
        pdf = []
        output = str(tmp_path / "out.json")
        verbose = False

    monkeypatch.setattr(cli_mod, "parse_args", lambda: _Args())
    monkeypatch.setattr(
        cli_mod, "run_pipeline",
        lambda **kw: (_ for _ in ()).throw(EOFError("EOF")),
    )

    assert cli_mod.main() == 0
    # 取消后不写输出文件
    assert not (tmp_path / "out.json").exists()


# ==========================================================
# 来源: test_audit_fixes_g2.py
# ==========================================================
"""G2 组审计缺陷回归测试 — subgraph1 意图澄清（纯离线，禁网络/禁 LLM）

覆盖（docs/AUDIT_REPORT.md 已确认缺陷）：
- H-06: classify/extract 的 LLM 调用指数退避重试（2 次 0.5s/1s），重试耗尽
        classify 回退 "astronomical"、extract 返回空 dict，initial_parse 降级而非 raise
- H-07: extract JSON 多层解析回退（剥 fence/前后空白 → json.loads →
        raw_decode 定位首个完整对象 → 严格 JSON prompt 重试 → 空响应直接返回空）
- M-07: classify_query_type 判空（None/空串回退 astronomical）与合法值白名单
- M-08: extract 输出类型校验（requested_properties 必须 list 且元素 str，
        target_entity 必须 str，不符置默认值记 warning）
- M-09: final_confirm 空输入/未识别输入重发 interrupt 追问，仅显式 "n"/"取消" 才 cancelled
- L-04: greeting 判定改精确门限（整句等于关键词或仅剩语气词/标点，而非 len<15 前缀命中）
"""



# 前置完整导入主包：subgraphs.subgraph1.config ←→ astroquery_ai 存在循环导入，
# 与生产入口（cli/run）一致地先导入 astroquery_ai 即可解开（基线既有行为）。


# 注意: nodes/__init__.py 会把节点函数 re-export, `from ...nodes import X` 绑定的是
# 函数而非模块, 无法 patch 其模块属性 — 与 conftest 一致用 importlib 取模块。
FINAL_CONFIRM_MOD = importlib.import_module("subgraphs.subgraph1.nodes.final_confirm")


# ── 假 LLM 客户端（离线）──
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """按队列依次弹出响应；元素为 Exception 时抛出（模拟瞬时 429/超时）"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0) if self.responses else _FakeResponse(None)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("_FakeChat", (), {"completions": completions})()


def _patch_client(monkeypatch, responses):
    """安装假 LLM 客户端，返回 _FakeCompletions 供断言调用次数/消息"""
    completions = _FakeCompletions(responses)
    monkeypatch.setattr(llm_utils, "get_llm_client", lambda: _FakeClient(completions))
    return completions


def _patch_sleep(monkeypatch):
    """记录 time.sleep 的延迟参数（不真正等待）"""
    slept = []
    monkeypatch.setattr(llm_utils.time, "sleep", lambda s: slept.append(s))
    return slept


# ── H-06: LLM 调用重试与降级 ──

def test_classify_retry_exhausted_falls_back_astronomical(monkeypatch):
    """H-06: classify 调用连续失败 → 2 次指数退避重试 → 回退 astronomical 不抛异常"""
    completions = _patch_client(
        monkeypatch,
        [Exception("429"), Exception("timeout"), Exception("boom")],
    )
    slept = _patch_sleep(monkeypatch)

    result = llm_utils.classify_query_type("M31 的距离")

    assert result == "astronomical"
    assert len(completions.calls) == 3
    assert slept == [0.5, 1.0]  # 指数退避延迟


def test_classify_retry_succeeds_after_failure(monkeypatch):
    """H-06: 首次瞬时失败后重试成功 → 返回 LLM 判定"""
    completions = _patch_client(monkeypatch, [Exception("429"), _FakeResponse("yes")])
    slept = _patch_sleep(monkeypatch)

    assert llm_utils.classify_query_type("M31 的距离") == "astronomical"
    assert len(completions.calls) == 2
    assert slept == [0.5]


def test_extract_retry_exhausted_returns_empty(monkeypatch):
    """H-06: extract 重试耗尽 → 返回空 dict 而非 raise（走 ask_entity 追问）"""
    completions = _patch_client(
        monkeypatch,
        [Exception("timeout"), Exception("429"), _FakeResponse("完全不是 JSON")],
    )
    slept = _patch_sleep(monkeypatch)

    result = llm_utils.extract_entity_and_properties("M31 的距离", [])

    assert result == {"target_entity": None, "requested_properties": []}
    assert len(completions.calls) == 3
    assert slept == [0.5, 1.0]


def test_initial_parse_degrades_instead_of_raise(monkeypatch):
    """H-06: initial_parse 异常时降级返回（保持天文分类走 ask_entity 追问）而非 raise"""
    init_mod = importlib.import_module("subgraphs.subgraph1.nodes.initial_parse")

    def _boom(*args, **kwargs):
        raise RuntimeError("LLM 爆炸")

    monkeypatch.setattr(init_mod, "classify_query_type", lambda u: "astronomical")
    monkeypatch.setattr(init_mod, "extract_entity_and_properties", _boom)

    state = {"user_query": "M31 的距离", "chat_history": []}
    result = init_mod.initial_parse(state)

    assert result["query_type"] == "astronomical"
    assert result["is_clear"] is False


# ── H-07: extract JSON 多层解析回退 ──

def test_extract_multi_layer_json_parse(monkeypatch):
    """H-07: markdown fence / 尾随花括号解释文本 / 前导文本 / BOM 均能解析"""
    cases = [
        # markdown fence
        ('```json\n{"target_entity": "M31", "requested_properties": ["距离"]}\n```',
         {"target_entity": "M31", "requested_properties": ["距离"]}),
        # 尾随花括号解释文本（旧 greedy 正则吞到最后一个 } 的失败场景）
        ('{"target_entity": "M31", "requested_properties": []}\n（M31 即{梅西耶编号}）',
         {"target_entity": "M31", "requested_properties": []}),
        # 前导文本
        ('好的，结果如下：{"target_entity": "M31", "requested_properties": []}',
         {"target_entity": "M31", "requested_properties": []}),
        # BOM 前缀
        ('{"target_entity": "M31", "requested_properties": []}',
         {"target_entity": "M31", "requested_properties": []}),
    ]
    for text, expected in cases:
        _patch_client(monkeypatch, [_FakeResponse(text)])
        result = llm_utils.extract_entity_and_properties("M31", [])
        assert result == expected, text


def test_extract_parse_fail_retries_with_strict_prompt(monkeypatch):
    """H-07: 首次输出无法解析 → 重试一次 LLM（强调严格 JSON）→ 成功"""
    completions = _patch_client(
        monkeypatch,
        [
            _FakeResponse('{"target_entity": "M31", "requested_properties": [}'),
            _FakeResponse('{"target_entity": "M31", "requested_properties": ["距离"]}'),
        ],
    )
    slept = _patch_sleep(monkeypatch)

    result = llm_utils.extract_entity_and_properties("M31 的距离", [])

    assert result == {"target_entity": "M31", "requested_properties": ["距离"]}
    assert len(completions.calls) == 2
    assert slept == [0.5]
    # 重试时使用强调严格 JSON 的 prompt
    assert "只输出 JSON 对象本身" in completions.calls[1]["messages"][0]["content"]


def test_extract_none_response_returns_empty(monkeypatch):
    """H-07: response_text 为 None → 直接返回空 dict，不抛错"""
    completions = _patch_client(monkeypatch, [_FakeResponse(None)])

    result = llm_utils.extract_entity_and_properties("M31", [])

    assert result == {"target_entity": None, "requested_properties": []}
    assert len(completions.calls) == 1  # 空响应直接回退，不重试


# ── M-07: classify_query_type 判空与白名单 ──

def test_classify_empty_content_falls_back_astronomical(monkeypatch):
    """M-07: content None/空串 → 回退 astronomical（走 ask_entity 追问）而非 invalid/崩溃"""
    for content in (None, "", "   "):
        _patch_client(monkeypatch, [_FakeResponse(content)])
        assert llm_utils.classify_query_type("M31 的距离") == "astronomical", repr(content)


def test_classify_whitelist_yes_no(monkeypatch):
    """M-07: 显式枚举合法值 — yes → astronomical，no → invalid，无法识别 → 保守 astronomical"""
    _patch_client(monkeypatch, [_FakeResponse("yes")])
    assert llm_utils.classify_query_type("M31 的距离") == "astronomical"

    _patch_client(monkeypatch, [_FakeResponse("No.")])
    assert llm_utils.classify_query_type("今天天气怎么样") == "invalid"

    # "不确定" 等截断/异常输出不再一律判 invalid 误拒
    _patch_client(monkeypatch, [_FakeResponse("不确定")])
    assert llm_utils.classify_query_type("今天天气怎么样") == "astronomical"


# ── M-08: extract 输出类型校验 ──

def test_extract_output_type_validation(monkeypatch):
    """M-08: requested_properties 非 list/含非 str 元素 → 置 []; target_entity 非 str → None"""
    # 字符串性质（旧缺陷：join 逐字符拼接出乱码）
    _patch_client(
        monkeypatch,
        [_FakeResponse('{"target_entity": "M31", "requested_properties": "distance"}')],
    )
    result = llm_utils.extract_entity_and_properties("M31 的距离", [])
    assert result == {"target_entity": "M31", "requested_properties": []}

    # 含数值元素（旧缺陷：join 抛 TypeError 整图降级）
    _patch_client(
        monkeypatch,
        [_FakeResponse('{"target_entity": "M31", "requested_properties": ["距离", 42]}')],
    )
    result = llm_utils.extract_entity_and_properties("M31 的距离", [])
    assert result == {"target_entity": "M31", "requested_properties": []}

    # target_entity 数值
    _patch_client(
        monkeypatch,
        [_FakeResponse('{"target_entity": 12345, "requested_properties": ["距离"]}')],
    )
    result = llm_utils.extract_entity_and_properties("M31 的距离", [])
    assert result == {"target_entity": None, "requested_properties": ["距离"]}

    # 正常路径不受影响
    _patch_client(
        monkeypatch,
        [_FakeResponse('{"target_entity": "M31", "requested_properties": ["距离"]}')],
    )
    result = llm_utils.extract_entity_and_properties("M31 的距离", [])
    assert result == {"target_entity": "M31", "requested_properties": ["距离"]}


# ── L-04: greeting 判定精确门限 ──

def test_greeting_precise_threshold(monkeypatch):
    """L-04: 纯寒暄（精确等于关键词或仅剩语气词/标点）判 greeting"""
    for text in ["你好", "您好", "你好！", "你好呀", "hi", "hello!", "在吗？"]:
        assert llm_utils.classify_query_type(text) == "greeting", repr(text)


def test_greeting_with_entity_content_goes_to_llm(monkeypatch):
    """L-04: 含实体特征的输入（如 "你好 M31 的距离是多少"）不再误判寒暄，交 LLM 分类"""
    _patch_client(monkeypatch, [_FakeResponse("yes")])
    assert llm_utils.classify_query_type("你好 M31 的距离是多少") == "astronomical"

    # 含实义内容的英文输入同样不判寒暄
    _patch_client(monkeypatch, [_FakeResponse("yes")])
    assert llm_utils.classify_query_type("hello what is the distance of M31") == "astronomical"


# ── M-09: final_confirm 空输入/未识别输入重问 ──

def _confirm_state():
    return {
        "target_entity": "M31",
        "requested_properties": ["distance"],
        "chat_history": [],
    }


def test_final_confirm_empty_input_reasks_then_confirmed(monkeypatch):
    """M-09: 空回车 → 重发 interrupt 追问 → 再次输入 y → confirmed（旧行为误取消）"""
    values = iter(["", "y"])
    monkeypatch.setattr(FINAL_CONFIRM_MOD, "interrupt", lambda *a, **k: next(values))

    result = FINAL_CONFIRM_MOD.final_confirm(_confirm_state())

    assert result["user_confirmed"] is True
    assert result["clarification_status"] == "confirmed"


def test_final_confirm_unrecognized_reasks_then_cancel(monkeypatch):
    """M-09: 未识别输入 → 重问；仅显式 n → cancelled"""
    values = iter(["随便", "n"])
    monkeypatch.setattr(FINAL_CONFIRM_MOD, "interrupt", lambda *a, **k: next(values))

    result = FINAL_CONFIRM_MOD.final_confirm(_confirm_state())

    assert result["user_confirmed"] is False
    assert result["clarification_status"] == "cancelled"


def test_final_confirm_explicit_cancel_no_reask(monkeypatch):
    """M-09: 显式 n/取消 → 直接 cancelled，不重问"""
    for cancel_word in ("n", "取消"):
        calls = []

        def _fake_interrupt(*a, **k):
            calls.append(a)
            return cancel_word

        monkeypatch.setattr(FINAL_CONFIRM_MOD, "interrupt", _fake_interrupt)
        result = FINAL_CONFIRM_MOD.final_confirm(_confirm_state())
        assert result["clarification_status"] == "cancelled"
        assert len(calls) == 1


def test_final_confirm_lookalike_inputs_never_cancel(monkeypatch):
    """M-09: "是的"/"对" 等非白名单输入均重问而非误取消，最终确认生效"""
    values = iter(["是的", "对", "y"])
    monkeypatch.setattr(FINAL_CONFIRM_MOD, "interrupt", lambda *a, **k: next(values))

    result = FINAL_CONFIRM_MOD.final_confirm(_confirm_state())

    assert result["clarification_status"] == "confirmed"
    assert result["user_confirmed"] is True


def test_final_confirm_modify_still_works(monkeypatch):
    """M-09 回归: m → 修改分支不受影响"""
    values = iter(["m", "M31 的距离"])
    monkeypatch.setattr(FINAL_CONFIRM_MOD, "interrupt", lambda *a, **k: next(values))

    result = FINAL_CONFIRM_MOD.final_confirm(_confirm_state())

    assert result["clarification_status"] == "modified"
    assert result["user_confirmed"] is False


# ── M-09 + H-06: 子图端到端 ──

def test_e2e_final_confirm_empty_then_confirm(monkeypatch):
    """端到端: final_confirm 空输入重问后确认 → confirmed（真实图装配）"""
    from subgraphs.subgraph1.graph import create_intent_clarification_subgraph

    init_mod = importlib.import_module("subgraphs.subgraph1.nodes.initial_parse")
    # initial_parse 以关键字参数调用 (user_input=..., chat_history=...), lambda 形参须同名
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: "astronomical")
    monkeypatch.setattr(
        init_mod,
        "extract_entity_and_properties",
        lambda user_input, chat_history: {"target_entity": "M31", "requested_properties": ["distance"]},
    )
    values = iter(["", "y"])
    for mod_name in ("ask_entity", "ask_properties", "greeting_handler", "final_confirm"):
        mod = importlib.import_module(f"subgraphs.subgraph1.nodes.{mod_name}")
        monkeypatch.setattr(mod, "interrupt", lambda *a, **k: next(values))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M31 的距离", "query_id": "g2-e2e"})

    assert result["target_entity"] == "M31"
    assert result["clarification_status"] == "confirmed"
    assert result["user_confirmed"] is True


# ==========================================================
# 来源: test_audit_fixes_g3.py
# ==========================================================
"""G3 组审计修复回归测试（docs/AUDIT_REPORT.md: H-08/M-22/M-23/M-24/M-25/L-05/L-06/L-07）

纯离线：禁网络、禁 LLM —— 所有外部依赖在 monkeypatch 层 mock。
只验证缺陷点的修复行为与正常路径不回归。
"""



# 先导入 astroquery_ai 完成 adapters → subgraphs.* 导入链，
# 否则直接 import subgraphs.subgraph2.* 会与 astroquery_ai/__init__ 循环导入。


# ══════════════════════════════════════════════════════════════
# H-08: table_meta_cache 键并入 target_entity + 失败兜底不缓存
# ══════════════════════════════════════════════════════════════

def _suppl_table_mock():
    """supplementary_query 用的假 VizieR 表（列 Name+Dist，一行 M31）"""

    class _Col:
        def __init__(self, unit):
            self.unit = unit

    class _Table:
        colnames = ["Name", "Dist"]
        _units = {"Name": "", "Dist": "Mpc"}
        _rows = [{"Name": "M31", "Dist": "0.77"}]

        def __iter__(self):
            return iter(self._rows)

        def __getitem__(self, key):
            return _Col(self._units.get(key, ""))

    class _FakeVizier:
        def find_catalogs(self, bibcode):
            return {}

        def get_catalogs(self, table_id):
            return [_Table()]

    return _FakeVizier


def _run_suppl(monkeypatch, tmp_path, target_entity, fake_judge, cache_payload=None):
    """跑一次 supplementary_query（全 mock），返回 (模块, 输出)"""
    sq_mod = importlib.import_module("subgraphs.subgraph2.nodes.supplementary_query")
    _FakeVizier = _suppl_table_mock()

    if cache_payload is not None:
        (tmp_path / "cache.json").write_text(
            json.dumps(cache_payload), encoding="utf-8")

    monkeypatch.setattr(sq_mod, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(sq_mod, "_CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(sq_mod, "_catalog_real_exists", lambda cid: True)
    monkeypatch.setattr(sq_mod, "_load_table_meta", lambda tid: {
        "title": "t", "description": "d", "columns": ["Name", "Dist [Mpc] distance"]})
    monkeypatch.setattr(sq_mod, "_llm_judge_table", fake_judge)
    monkeypatch.setattr(sq_mod, "query_with_fallback",
                        lambda fn, **kw: fn(_FakeVizier()))
    monkeypatch.setattr(sq_mod, "map_columns_to_properties",
                        lambda **kw: {"Dist": "distance"})
    monkeypatch.setattr(sq_mod.time, "sleep", lambda *a: None)

    out = sq_mod.supplementary_query({
        "query_id": "test-suppl",
        "target_entity": target_entity,
        "simbad_aliases": ["M31", "NGC 224"],
        "simbad_object_type": "G",
        "property_spec": [{"property_id": "distance", "unit": "Mpc"}],
        "paper_sources": [{
            "source_id": "2018A&A...616A...1G",
            "title": "Test Paper",
        }],
    })
    return sq_mod, out


def test_suppl_cache_key_isolated_by_entity(monkeypatch, tmp_path):
    """H-08: 缓存键并入 target_entity——不同天体不共用判断结果，相同天体命中缓存"""
    calls = []

    def fake_judge(meta, ent):
        calls.append(ent)
        return {"table_class": "whole_entity", "entity_column": "Name",
                "property_columns": [{"column": "Dist", "standard_name": "distance"}]}

    _, out1 = _run_suppl(monkeypatch, tmp_path, "M31", fake_judge)
    assert len(out1["supplementary_records"]) == 1
    assert calls == ["M31"]

    # 换一个天体（同表）：缓存键含 target_entity，必须重新 LLM 判断
    _, out2 = _run_suppl(monkeypatch, tmp_path, "M32", fake_judge)
    assert calls == ["M31", "M32"], "不同天体必须重新 LLM 判断"

    # 再查 M31：命中缓存，不再调 LLM
    _, out3 = _run_suppl(monkeypatch, tmp_path, "M31", fake_judge)
    assert calls == ["M31", "M32"], "相同天体应命中缓存"
    assert len(out3["supplementary_records"]) == 1

    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert "J/A+A/616/A1#M31" in cache
    assert "J/A+A/616/A1#M32" in cache
    # 不再出现旧的无天体指纹键
    assert "J/A+A/616/A1" not in cache


def test_suppl_llm_failure_not_cached(monkeypatch, tmp_path):
    """H-08: LLM 失败/解析失败兜底不写缓存——避免失败结果被永久缓存"""
    def fake_judge(meta, ent):
        return None  # 模拟 LLM 异常/解析失败

    _, out = _run_suppl(monkeypatch, tmp_path, "M31", fake_judge)
    assert out["supplementary_records"] == []
    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert cache == {}, "失败兜底不得写入缓存"


@pytest.mark.parametrize("bad_entry", [
    {"table_class": "bogus"},   # table_class 不在四枚举内
    "garbage",                  # 非 dict
])
def test_suppl_invalid_cache_entry_rejudged(monkeypatch, tmp_path, bad_entry):
    """H-08: 命中缓存时校验 judgment 结构——非法条目视为未命中重新判断"""
    calls = []

    def fake_judge(meta, ent):
        calls.append(ent)
        return {"table_class": "whole_entity", "entity_column": "Name",
                "property_columns": [{"column": "Dist", "standard_name": "distance"}]}

    _, out = _run_suppl(
        monkeypatch, tmp_path, "M31", fake_judge,
        cache_payload={"J/A+A/616/A1#M31": bad_entry},
    )
    assert calls == ["M31"], "非法缓存条目应触发重新判断"
    assert len(out["supplementary_records"]) == 1
    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert cache["J/A+A/616/A1#M31"]["table_class"] == "whole_entity"


# ══════════════════════════════════════════════════════════════
# M-22: DB 浮点值全精度序列化
# ══════════════════════════════════════════════════════════════

def test_db_float_full_precision():
    """M-22: np.floating 用 .17g 保留全精度（不再 6 位截断），大整数路径不变"""
    import numpy as np
    from subgraphs.subgraph2.utils.database_utils import build_database_records

    class _Table:
        colnames = ["F", "I"]

        def __iter__(self):
            yield {"F": np.float64(1234.56789), "I": np.int64(5000000000000000000)}

        def __len__(self):
            return 1

    records = build_database_records(
        _Table(),
        "SRC_DB_T",
        "M31",
        {"vizier_table": "J/A+A/616/A1", "key_column": "ID", "id": "1"},
        {"F": "mag", "I": ""},
        "G",
        {"F": "flux", "I": "count"},
    )
    assert len(records) == 2
    by_name = {r["field_name"]: r for r in records}

    fv = by_name["flux"]["field_value"]
    assert fv != "1234.57", "6 位有效数字截断已移除"
    assert float(fv) == 1234.56789, "浮点全精度往返"

    assert by_name["count"]["field_value"] == "5000000000000000000", "大整数保留精度"


# ══════════════════════════════════════════════════════════════
# M-23: vizier _is_retryable 识别 5xx/429
# ══════════════════════════════════════════════════════════════

def test_vizier_retryable_5xx_and_429():
    """M-23: HTTPError 5xx/429 判可重试（切换镜像），4xx 仍直接抛"""
    from requests.exceptions import HTTPError
    from subgraphs.subgraph2.utils.vizier_client import _is_retryable

    def _http_err(status):
        err = HTTPError(f"HTTP {status}")

        class _Resp:
            status_code = status

        err.response = _Resp()
        return err

    for status in (500, 502, 503, 504, 429):
        assert _is_retryable(_http_err(status)) is True, f"{status} 应判可重试"
    for status in (400, 403, 404, 422):
        assert _is_retryable(_http_err(status)) is False, f"{status} 应直接抛"

    # 无 response 的 HTTPError：无法判断状态码，不重试
    assert _is_retryable(HTTPError("no response")) is False


# ══════════════════════════════════════════════════════════════
# M-24: Unpaywall DOI/email 百分号编码 + DOI 前缀校验
# ══════════════════════════════════════════════════════════════

def test_unpaywall_doi_email_encoded(monkeypatch):
    """M-24: DOI/email 特殊字符百分号编码后进 URL，不破坏 query 结构"""
    uq_mod = importlib.import_module("subgraphs.subgraph2.nodes.unpaywall_query")

    captured = {}

    class _Resp:
        status_code = 404

    def fake_get(url, timeout=30):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(uq_mod.requests, "get", fake_get)

    uq_mod.get_unpaywall_urls("10.1000/abc+def(x)&y;z", "a.b+c@example.com")

    assert captured["url"].startswith("https://api.unpaywall.org/v2/")
    # DOI: '/' '+' '(' ')' '&' ';' 全部编码
    assert "10.1000%2Fabc%2Bdef%28x%29%26y%3Bz" in captured["url"]
    # email: '+' '@' 编码，'?' 只能出现一次（query 分隔符）
    assert "email=a.b%2Bc%40example.com" in captured["url"]
    assert captured["url"].count("?") == 1, "DOI 内 '?' 必须编码，不得破坏 query 结构"


def test_unpaywall_invalid_doi_skipped(monkeypatch):
    """M-24: 非 '10.' 前缀的 DOI 请求前拦截，不发请求"""
    uq_mod = importlib.import_module("subgraphs.subgraph2.nodes.unpaywall_query")

    calls = []

    class _Resp:
        status_code = 404

    def fake_get(url, timeout=30):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(uq_mod.requests, "get", fake_get)

    res = uq_mod.get_unpaywall_urls("not-a-doi", "a@b.com")
    assert res == []
    assert calls == [], "非法 DOI 不应发起请求"


# ══════════════════════════════════════════════════════════════
# M-25: PDF 流式字节限流 + .part 清理
# ══════════════════════════════════════════════════════════════

def test_pdf_stream_limit_aborts_and_cleans_part(monkeypatch, tmp_path):
    """M-25: 无 Content-Length 时写循环内限流——超限中断、删 .part、不落正式文件"""
    pdf_mod = importlib.import_module("subgraphs.subgraph2.nodes.pdf_download")

    class _Resp:
        status_code = 200
        headers = {}  # 无 Content-Length（chunked 场景）

        def iter_content(self, chunk_size=8192):
            yield b"x" * (2 * 1024 * 1024)  # 单块 2MB > max_size_mb=1

    monkeypatch.setattr(pdf_mod.requests, "get",
                        lambda url, headers=None, timeout=0, stream=False: _Resp())

    target = tmp_path / "paper.pdf"
    res = pdf_mod.download_from_url("http://example.com/x.pdf", str(target),
                                    max_size_mb=1)

    assert res["success"] is False
    assert "too large" in res["error"].lower()
    assert not (tmp_path / "paper.pdf").exists(), "超限不得落正式文件"
    assert not (tmp_path / "paper.pdf.part").exists(), ".part 残留必须删除"


def test_pdf_exception_cleans_part(monkeypatch, tmp_path):
    """M-25: 下载异常路径删除 .part 残留（瀑布流不续写脏文件）"""
    import requests
    pdf_mod = importlib.import_module("subgraphs.subgraph2.nodes.pdf_download")

    def fake_get(url, headers=None, timeout=0, stream=False):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(pdf_mod.requests, "get", fake_get)

    target = tmp_path / "paper.pdf"
    part = tmp_path / "paper.pdf.part"
    part.write_bytes(b"partial")
    res = pdf_mod.download_from_url("http://example.com/x.pdf", str(target))

    assert res["success"] is False
    assert not part.exists(), "异常路径必须清理 .part"


# ══════════════════════════════════════════════════════════════
# L-05: 移除 simbad_resolver 死导出
# ══════════════════════════════════════════════════════════════

def test_simbad_resolver_not_exported():
    """L-05: nodes 包不再导出 simbad_resolver（文件留档但不参与包导入链）"""
    import sys
    import subgraphs.subgraph2.nodes as nodes_pkg

    assert "simbad_resolver" not in nodes_pkg.__all__
    assert not hasattr(nodes_pkg, "simbad_resolver"), "包命名空间不得暴露 simbad_resolver"
    assert "subgraphs.subgraph2.nodes.simbad_resolver" not in sys.modules, \
        "包导入不得连带加载 simbad_resolver 模块（旧行为会连带 import astroquery.simbad）"


# ══════════════════════════════════════════════════════════════
# L-06: A&A 字母文章 J/ 表号推导
# ══════════════════════════════════════════════════════════════

def test_guess_j_tables_aa_letter_article():
    """L-06: A&A 字母文章拼回卷尾字母（616A → J/A+A/616/A1）；其余期刊路径不变"""
    from subgraphs.subgraph2.nodes.supplementary_query import guess_j_tables

    assert guess_j_tables("2018A&A...616A...1G") == ["J/A+A/616/A1"]
    assert guess_j_tables("2012MNRAS.427.1463Z") == ["J/MNRAS/427/1463"]
    assert guess_j_tables("2014ApJ...780..128I") == ["J/ApJ/780/128"]
    assert guess_j_tables("2001AJ....121.2557D") == ["J/AJ/121/2557"]


# ══════════════════════════════════════════════════════════════
# L-07: retrieval_priority 动态年份 + age 钳制
# ══════════════════════════════════════════════════════════════

def test_retrieval_priority_dynamic_year():
    """L-07: 当前年份动态取值；未来年份 age 钳制 0（time_factor 不反超 1）"""
    from datetime import datetime
    from subgraphs.subgraph2.utils.paper_utils import calculate_retrieval_priority

    # 未来年份：age 钳制为 0 → time_factor = 1.0，不被 min 截断
    p_future = calculate_retrieval_priority(score=1000, citation_count=1000, year=9999)
    assert p_future == 1.0

    # 当前年份：同样 age=0
    p_now = calculate_retrieval_priority(
        score=1000, citation_count=1000, year=datetime.now().year)
    assert p_now == 1.0

    # 正常历史论文不回归（time_factor 随 age 递减）
    p_old = calculate_retrieval_priority(score=1000, citation_count=1000, year=2000)
    assert p_old < p_now


# ==========================================================
# 来源: test_audit_fixes_g4.py
# ==========================================================
"""G4 组审计修复回归测试 — H-09 / H-10 / M-26 / M-27 / L-08（全 mock 离线）

覆盖：
- H-09 bbox VLM 输出类型归一化（vlm_extractor 出口 + bbox 任务构建逐条 try）
- H-10 image_cache.cleanup() 接线 + 容量上限保护
- M-26 bbox VLM 解析 repair_json 回退
- M-27 result_builder field_name 空值丢弃
- L-08 subgraph3 死配置接线（pdf.dpi / vlm.timeout / bbox_vlm.max_tokens）

注意：必须先导入 astroquery_ai 以解 subgraph3 与主图的循环依赖
（subgraphs.subgraph3.utils.logger → astroquery_ai.logger → 包 __init__ → adapters → subgraph3.graph）。
"""





# ============================================================
# H-09 bbox VLM 输出类型归一化
# ============================================================

def test_vlm_extractor_normalizes_page_int(monkeypatch):
    """H-09: 出口归一化 — page 字符串/浮点转 int；无效 page/非法条目丢弃"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.vlm_extractor")

    def fake_call_qwen_vlm(images, prompt):
        return json.dumps({"extractions": [
            {"page": "4", "field_name": "distance", "field_value": "24.5"},
            {"page": 2.0, "field_name": "metallicity", "field_value": "-0.4"},
            {"page": "abc", "field_name": "bad", "field_value": "x"},
            {"page": None, "field_name": "bad2", "field_value": "y"},
            "not-a-dict",
        ]})

    monkeypatch.setattr(mod, "call_qwen_vlm", fake_call_qwen_vlm)

    result = mod.process_single_paper_vlm({
        "bibcode": "TEST_BIB",
        "image_paths": ["p1.png"],
        "target_entity": "M31",
        "requested_properties": ["distance"],
        "property_spec": [],
    })

    assert result["success"] is True
    data = result["data"]["extractions"]
    # 只保留 2 条 page 可转 int 的记录
    assert len(data) == 2
    assert data[0]["page"] == 4 and isinstance(data[0]["page"], int)
    assert data[1]["page"] == 2 and isinstance(data[1]["page"], int)


def test_vlm_extractor_extractions_not_list_fails(monkeypatch):
    """H-09: extractions 非 list → 判该论文失败（不再把坏数据传给下游）"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.vlm_extractor")

    monkeypatch.setattr(
        mod, "call_qwen_vlm",
        lambda images, prompt: json.dumps({"extractions": {"page": 1}}),
    )

    result = mod.process_single_paper_vlm({
        "bibcode": "TEST_BIB",
        "image_paths": ["p1.png"],
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
    })

    assert result["success"] is False
    assert "非 list" in result["error"]


def test_bbox_annotator_bad_record_does_not_crash(monkeypatch):
    """H-09: bbox 任务构建坏记录 → bbox_annotation_failed，不击穿节点"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.bbox_annotator")

    def fake_annotate(task, target_entity):
        return {"bbox_2d": [10, 20, 30, 40], "confidence": 0.95,
                "found": True, "error": None}

    monkeypatch.setattr(mod, "annotate_single_bbox", fake_annotate)

    state = {
        "raw_extractions": {
            # 好记录：page 为合法 int
            "B1": {"extractions": [{"page": 2, "field_name": "distance"}]},
            # 坏记录：page 为字符串（page < 1 抛 TypeError）+ 非 dict 条目
            "B2": {"extractions": [{"page": "4", "field_name": "x"}, 12345]},
        },
        "paper_image_paths": {"B1": ["p1.png", "p2.png", "p3.png"],
                              "B2": ["p1.png"]},
        "target_entity": "M31",
        "query_id": "t1",
    }

    out = mod.bbox_batch_annotator(state)

    assert out["bbox_annotation_status"] == "completed"
    # 好记录正常标注
    assert out["raw_extractions"]["B1"]["extractions"][0]["bbox_2d"] == [10, 20, 30, 40]
    # 坏记录进 failed 列表而非崩溃
    keys = {f["key"] for f in out["bbox_annotation_failed"]}
    assert "B2_0" in keys and "B2_1" in keys


def test_bbox_annotator_all_bad_records_early_return(monkeypatch):
    """H-09: 全部记录坏 → total_tasks==0 早退分支仍上报 bbox_annotation_failed"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.bbox_annotator")

    monkeypatch.setattr(mod, "annotate_single_bbox",
                        lambda task, entity: {"bbox_2d": None, "found": False})

    state = {
        "raw_extractions": {"B1": {"extractions": ["bad-item"]}},
        "paper_image_paths": {"B1": ["p1.png"]},
        "target_entity": "M31",
        "query_id": "t1",
    }

    out = mod.bbox_batch_annotator(state)

    assert out["bbox_annotation_status"] == "completed"
    assert out["bbox_annotation_failed"], "坏记录应仍上报"
    assert out["bbox_annotation_failed"][0]["key"] == "B1_0"


# ============================================================
# H-10 image_cache.cleanup() 接线 + 容量保护
# ============================================================

def test_image_cache_cleanup_per_bibcode(tmp_path):
    """H-10: cleanup(bibcode) 只删该论文目录（含 '/' ':' sanitize）"""
    cache = ImageCache(str(tmp_path))
    img = Image.new("RGB", (10, 10), "white")
    p1 = cache.save_images("BIB/A:1", [img])
    p2 = cache.save_images("BIB2", [img])
    assert os.path.exists(p1[0]) and os.path.exists(p2[0])

    cache.cleanup("BIB/A:1")
    assert not os.path.exists(p1[0]), "应删除 BIB/A:1 的缓存目录"
    assert os.path.exists(p2[0]), "不应误删 BIB2 的缓存目录"

    cache.cleanup("BIB2")
    assert not os.path.exists(p2[0])


def test_image_cache_within_capacity_keeps_files(tmp_path):
    """H-10: 容量未超限时不清理"""
    cache = ImageCache(str(tmp_path), max_size_mb=1024.0)
    img = Image.new("RGB", (10, 10), "white")
    paths = cache.save_images("B1", [img, img])
    assert all(os.path.exists(p) for p in paths)


def test_image_cache_capacity_evicts_oldest(tmp_path):
    """H-10: 超容量上限 → 按 mtime 清理最旧直到回到限内"""
    cache = ImageCache(str(tmp_path), max_size_mb=0.0)  # 上限 0 → 全部淘汰
    img = Image.new("RGB", (10, 10), "white")
    paths = cache.save_images("B1", [img, img, img])
    assert all(not os.path.exists(p) for p in paths)
    assert cache.get_cache_size() == 0.0


# ============================================================
# M-26 bbox VLM 解析 repair_json 回退
# ============================================================

def test_bbox_coerce_repair_json_fallback():
    """M-26: 尾逗号坏 JSON → repair_json 修复后仍能解析"""
    from subgraphs.subgraph3.utils.bbox_vlm_client import _coerce_to_dict

    data = _coerce_to_dict('{"bbox_2d": [10, 20, 30, 40], "found": true, "confidence": 0.95,}')
    assert data is not None
    assert data["bbox_2d"] == [10, 20, 30, 40]
    assert data["found"] is True


def test_bbox_coerce_unrepairable_returns_none():
    """M-26: 完全不可修复的字符串 → 返回 None（不抛异常）"""
    from subgraphs.subgraph3.utils.bbox_vlm_client import _coerce_to_dict

    assert _coerce_to_dict("this is not json at all") is None


# ============================================================
# M-27 result_builder field_name 空值丢弃
# ============================================================

def test_result_builder_drops_empty_field_name():
    """M-27: field_name 缺失/空白 → 丢弃该条，计入 dropped 计数"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.result_builder")

    state = {
        "raw_extractions": {
            "B1": {"extractions": [
                {"page": 1, "field_name": "distance", "field_value": "24.5",
                 "confidence": 0.95, "bbox_2d": [10, 20, 30, 40]},
                {"page": 1, "field_name": None, "field_value": "12.3",
                 "confidence": 0.95, "bbox_2d": [10, 20, 30, 40]},
                {"page": 1, "field_name": "   ", "field_value": "12.3",
                 "confidence": 0.95, "bbox_2d": [10, 20, 30, 40]},
            ]},
        },
        "target_entity": "M31",
        "query_id": "t1",
        "download_paths": [{"bibcode": "B1"}],
    }

    out = mod.result_builder(state)

    records = out["paper_records"]
    assert len(records) == 1
    assert records[0]["field_name"] == "distance"
    # 两条空 field_name 计入丢弃统计（复用 dropped_invalid_bbox 槽位）
    assert out["processing_summary"]["dropped_invalid_bbox"] == 2


def test_build_paper_record_field_name_none_not_str_none():
    """M-27: build_paper_record 兜底 — field_name=None 不产出 'None' 脏字段"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.result_builder")

    rec = mod.build_paper_record(
        bibcode="B1",
        extraction={"page": 1, "field_name": None, "field_value": "x",
                    "confidence": 0.9},
        target_entity="M31",
        record_index=0,
        bbox_validated=[10, 20, 30, 40],
    )

    assert rec["field_name"] == ""
    assert "None" not in rec["record_id"]


# ============================================================
# L-08 subgraph3 死配置接线
# ============================================================

def test_pdf_converter_passes_config_dpi(monkeypatch):
    """L-08: pdf_converter 显式透传 settings.pdf.dpi"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.pdf_converter")
    captured = {}

    def fake_pdf_to_images(pdf_path, dpi=150):
        captured["dpi"] = dpi
        return []

    monkeypatch.setattr(mod, "pdf_to_images", fake_pdf_to_images)
    monkeypatch.setattr(mod.image_cache, "save_images",
                        lambda bibcode, images: [])  # 不写真实磁盘

    out = mod.pdf_batch_converter({
        "download_paths": [{"bibcode": "B1", "local_path": "x.pdf"}],
        "query_id": "t1",
    })

    assert captured["dpi"] == mod.settings.pdf.dpi
    assert out["paper_image_paths"] == {"B1": []}
    assert out["conversion_status"] == "completed"


def test_bbox_vlm_max_tokens_from_settings(monkeypatch):
    """L-08: bbox VLM max_tokens 读 settings.bbox_vlm.max_tokens"""
    mod = importlib.import_module("subgraphs.subgraph3.utils.bbox_vlm_client")
    captured = {}

    class FakeChoice:
        message = type("M", (), {
            "content": '{"bbox_2d": [10, 20, 30, 40], "found": true, "confidence": 0.95}'
        })

    class FakeOutput:
        choices = [FakeChoice()]

    class FakeResp:
        status_code = 200
        output = FakeOutput()

    def fake_call(**kwargs):
        captured.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(mod.MultiModalConversation, "call", fake_call)

    img = Image.new("RGB", (10, 10), "white")
    result = mod.call_qwen_flash_bbox(
        image=img,
        extraction={"field_name": "distance", "field_value": "24.5"},
        target_entity="M31",
        max_retries=1,
    )

    assert captured["max_tokens"] == mod.settings.bbox_vlm.max_tokens
    assert result["bbox_2d"] == [10, 20, 30, 40]


def test_vlm_client_request_timeout_from_settings(monkeypatch):
    """L-08: vlm_client 透传 request_timeout=settings.vlm.timeout"""
    mod = importlib.import_module("subgraphs.subgraph3.utils.vlm_client")
    captured = {}

    class FakeChoice:
        message = type("M", (), {"content": '{"extractions": []}'})

    class FakeOutput:
        choices = [FakeChoice()]

    class FakeResp:
        status_code = 200
        output = FakeOutput()

    def fake_call(**kwargs):
        captured.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(mod.MultiModalConversation, "call", fake_call)

    img = Image.new("RGB", (10, 10), "white")
    result = mod.call_qwen_vlm([img], "prompt", max_retries=1)

    assert captured.get("request_timeout") == mod.settings.vlm.timeout
    assert "extractions" in result


# ==========================================================
# 来源: test_audit_fixes_g12.py
# ==========================================================
# -*- coding: utf-8 -*-
"""G12 审计修复回归测试 — M-35 / M-36 / M-37 / L-22 / L-23 (纯离线, 禁网络/禁 LLM)

覆盖:
  - M-35: 语义类型 units 与转换组对齐 (metallicity unit_category→abundance + dex 并入
          abundance 组; density.units 移除 pc**-2/mas**-2), unit_converter
          (inferred_cat, unit) 与 (matched_cat, target) 双向可命中
  - M-36: 无消费方配置段已删除, 有消费方段保留, 加载器不回归
  - M-37: gen_catalog_schema 列源并入 catalog_units.json 键集 (5 列逃逸列兜底)
  - L-22: 三个知识库脚本改 Path(__file__) 相对定位
  - L-23: 脚本幂等去重改真实列表过滤 (assert 在 -O 下被剥离)
"""


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS_DIR = os.path.join(REPO_ROOT, "quality_pipeline", "configs")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "quality_pipeline", "scripts")



def _load_quality_rules() -> dict:
    return load_yaml("quality_rules.yaml")


def _load_schema_mapping() -> dict:
    return load_yaml("schema_mapping.yaml")


def _load_script_module(rel_path: str):
    """从文件路径加载独立脚本模块 (不依赖包路径, 不执行 append 副作用)。"""
    abs_path = os.path.join(REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(
        "g12_tmp_" + os.path.basename(rel_path).replace(".", "_"), abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==========================================================
# M-35: 语义类型 units 与转换组对齐
# ==========================================================

def test_metallicity_unit_category_is_abundance():
    """M-35: metallicity 语义类型 unit_category 改为 abundance (与转换组对齐)"""
    cfg = _load_quality_rules()["semantic_types_astrophysics"]["metallicity"]
    assert cfg["unit_category"] == "abundance"
    assert set(cfg["units"]) == {"dex", "", "Sun", "log(Sun)"}


def test_abundance_group_covers_full_metallicity_unit_set():
    """M-35: abundance 转换组包含 dex/Sun/log(Sun), metallicity.units 全量可命中"""
    conv = _load_schema_mapping()["unit_conversions_astrophysics"]["abundance"]
    assert set(conv.keys()) >= {"dex", "Sun", "log(Sun)"}


def test_metallicity_sun_units_convert_to_dex():
    """M-35 核心: 'Sun'/'log(Sun)' 经 (inferred_cat=abundance, unit) 与
    (matched_cat=abundance, target=dex) 双向查表命中, 转换到标准单位 dex"""
    set_research_domain("astrophysics")
    semantic_types = {"metallicity": "metallicity"}
    records = [
        {"record_id": "r1", "field_name": "metallicity", "field_value": 0.3, "field_unit": "Sun"},
        {"record_id": "r2", "field_name": "metallicity", "field_value": 0.3, "field_unit": "log(Sun)"},
    ]
    res = convert_units(records, semantic_types=semantic_types, research_domain="astrophysics")
    converted = {(c["record_id"], c["from"], c["to"]) for c in res["conversion_log"]}
    assert converted == {("r1", "Sun", "dex"), ("r2", "log(Sun)", "dex")}
    assert res["unconverted"] == []
    assert records[0]["field_unit"] == "dex" and records[1]["field_unit"] == "dex"


def test_dex_units_unaffected_by_abundance_merge():
    """M-35: alpha_abundance (unit_category 仍 metallicity) 与 surface_gravity 的 dex 不受影响"""
    set_research_domain("astrophysics")
    semantic_types = {"alpha_abundance": "alpha_abundance", "surface_gravity": "surface_gravity"}
    records = [
        {"record_id": "r1", "field_name": "alpha_abundance", "field_value": 0.2, "field_unit": "dex"},
        {"record_id": "r2", "field_name": "surface_gravity", "field_value": 4.4, "field_unit": "dex"},
    ]
    res = convert_units(records, semantic_types=semantic_types, research_domain="astrophysics")
    # 已是目标单位 (dex) → 跳过而非误转
    assert res["conversion_log"] == []
    assert records[0]["field_unit"] == "dex" and records[1]["field_unit"] == "dex"


def test_density_units_exclude_surface_density_units():
    """M-35: density.units 移除 pc**-2/mas**-2 (面密度单位属 surface_density 组,
    在 density 组内查表必 miss → 此前被 unit_recognized 后以非标准单位静默导出)"""
    cfg = _load_quality_rules()["semantic_types_astrophysics"]["density"]
    assert "pc**-2" not in cfg["units"]
    assert "mas**-2" not in cfg["units"]
    conv = _load_schema_mapping()["unit_conversions_astrophysics"]["density"]
    assert "pc**-2" not in conv and "mas**-2" not in conv
    # 面密度转换组保留 (gen_catalog_schema UNIT_PATCH 幂等锚点)
    sd = _load_schema_mapping()["unit_conversions_astrophysics"]["surface_density"]
    assert "pc**-2" in sd and "mas**-2" in sd


def test_surface_density_unit_not_silently_converted():
    """M-35: density 语义类型字段上的面密度单位不静默转换 (记入 unconverted)"""
    set_research_domain("astrophysics")
    semantic_types = {"density": "density"}
    records = [
        {"record_id": "r1", "field_name": "density", "field_value": 10.0, "field_unit": "pc**-2"},
    ]
    res = convert_units(records, semantic_types=semantic_types, research_domain="astrophysics")
    assert res["conversion_log"] == []
    assert any(u["field"] == "density" for u in res["unconverted"])


# ==========================================================
# M-36: 清理无消费方配置段
# ==========================================================

# 全仓 grep 确认零读取的段键 (仅出现在注释/字符串)
_DEAD_SECTIONS = [
    "missing_value",
    "duplicate",
    "consistency",
    "format",
    "source_reliability",
    "conflict_detection",
    "outlier_detection",
    "nonlinear_penalties",
    "domain_weights_astrophysics",
    "journal_tiers_astrophysics",
    "resolution_weights_astrophysics",
    "adaptive_thresholds_astrophysics",
    "entity_extraction_astrophysics",
    "measurement_methods_astrophysics",
]

# 有消费方的段 (必须保留)
_KEPT_SECTIONS = [
    "quality_scoring",
    "quality_scoring_runtime",
    "loop_control",
    "adaptive_thresholds",
    "domain_weights",
    "semantic_types",
    "semantic_types_astrophysics",
    "entity_types_astrophysics",
]


def test_dead_config_sections_removed():
    """M-36: 无消费方配置段已从 quality_rules.yaml 删除"""
    cfg = _load_quality_rules()
    for section in _DEAD_SECTIONS:
        assert section not in cfg, f"死段 {section} 应已删除"


def test_kept_config_sections_present():
    """M-36: 有消费方配置段保留"""
    cfg = _load_quality_rules()
    for section in _KEPT_SECTIONS:
        assert section in cfg, f"有消费方段 {section} 不应被删"


def test_dead_sections_not_read_by_any_py_module():
    """M-36: 全仓 .py 不再以配置访问语法读取死段键 (锁定零消费方状态, 防复活)。

    仅匹配键名出现在访问上下文 (get("...") / [...]) 的读取形态;
    注释/数据字段/工具名里的同名字符串 (如 statistical_conflict 输出键
    measurement_methods、missing_value_handler 工具名) 不是配置读取。
    """
    import re
    # 仅无歧义 yaml 段键: 裸键 missing_value/outlier_detection/nonlinear_penalties
    # 与 runtime 报告字典键不重叠, _astrophysics 后缀键不可能出现在运行时数据里;
    # measurement_methods/source_reliability 等裸键是质量报告字典的合法数据键, 不在此列
    dead_keys = ("missing_value", "outlier_detection", "nonlinear_penalties",
                 "domain_weights_astrophysics", "journal_tiers_astrophysics",
                 "resolution_weights_astrophysics", "adaptive_thresholds_astrophysics",
                 "entity_extraction_astrophysics", "measurement_methods_astrophysics")
    pattern = re.compile(r"[\(\[]\s*[\"'](" + "|".join(dead_keys) + r")[\"']")
    hits = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", ".pytest_cache")]
        if "output" in dirnames:
            dirnames.remove("output")
        for fn in filenames:
            if not fn.endswith(".py") or fn.startswith("test_audit_fixes"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if pattern.search(line):
                        hits.append(f"{os.path.relpath(path, REPO_ROOT)}:{lineno}")
    assert hits == [], f"死段键名仍有 .py 读取: {hits}"


def test_config_loaders_after_cleanup():
    """M-36: 删除后加载器不回归 (领域段/运行参数/循环控制均可正常读取)"""
    set_research_domain("materials_science")
    st = load_domain_config("semantic_types", "semantic_types")
    assert "temperature" in st and "material" in st
    set_research_domain("astrophysics")
    st_astro = load_domain_config("semantic_types", "semantic_types")
    assert "redshift" in st_astro and "metallicity" in st_astro
    et = load_domain_config("entity_types", "entity_types")
    assert "types" in et and "typical_ranges" in et
    rt = load_quality_scoring_runtime()
    for key in ("volume_thresholds", "agreement_std_coef", "repair_cost",
                "extraction_human_threshold", "conflict_severity", "level_thresholds"):
        assert key in rt
    lc = load_yaml("quality_rules.yaml").get("loop_control", {})
    assert lc.get("max_loop") == 3 and lc.get("max_iterations") == 8


# ==========================================================
# M-37: gen_catalog_schema 列源并入 catalog_units.json
# ==========================================================

def _load_gen_catalog_schema():
    path = os.path.join(SCRIPTS_DIR, "gen_catalog_schema.py")
    spec = importlib.util.spec_from_file_location("g12_gen_catalog_schema", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gen_catalog_schema_column_source_union():
    """M-37: _load_used_columns 列源并入 catalog_units.json 键集 (与 vizier schema 并集)"""
    mod = _load_gen_catalog_schema()
    used, col_info = mod._load_used_columns()
    # catalog_units.json 独有的 5 列必须进入兜底列源 (audit U12: S159MHz/e_S159MHz
    # 3c、f.mag ucac、AV(HK)/AV(JH) fermi)
    for col in ("S159MHz", "e_S159MHz", "f.mag", "AV(HK)", "AV(JH)"):
        assert col in col_info, f"catalog_units 列 {col} 未并入列源"


def test_gen_catalog_schema_aliases_cover_escaped_columns():
    """M-37: 逃逸列经 build_alias_patch 落入 database_catalog_properties 兜底"""
    mod = _load_gen_catalog_schema()
    used, col_info = mod._load_used_columns()
    patch = mod.build_alias_patch(used, col_info)
    rest = patch.get("database_catalog_properties", [])
    for col in ("S159MHz", "e_S159MHz", "f.mag", "AV(HK)", "AV(JH)"):
        assert col in rest, f"逃逸列 {col} 未进入 database_catalog_properties 兜底"


# ==========================================================
# L-22: 知识库脚本改相对路径
# ==========================================================

_SCRIPT_REL_PATHS = [
    "quality_pipeline/scripts/append_methodology_entries.py",
    # 注: backfill_hq.py / extend_galaxy_catalogs.py 为一次性 KB 维护脚本,
    # 使命完成 (KB 294 条 / HQ 100%) 已删除 (2026-08-10 清理)
]


def test_kb_scripts_no_hardcoded_absolute_paths():
    """L-22: 三个脚本不再硬编码作者机器绝对路径 (C:/Users/...)"""
    for rel in _SCRIPT_REL_PATHS:
        src = open(os.path.join(REPO_ROOT, rel), encoding="utf-8").read()
        assert "C:/Users/" not in src, f"{rel} 仍含硬编码绝对路径"
        assert "C:\\Users\\" not in src, f"{rel} 仍含硬编码绝对路径"
        assert "Path(__file__)" in src, f"{rel} 未用 Path(__file__) 相对定位"


def test_kb_scripts_paths_resolve_to_existing_files():
    """L-22: 相对路径解析后指向真实存在的知识库文件"""
    script_dir = os.path.join(REPO_ROOT, "quality_pipeline", "scripts")
    m1 = os.path.join(script_dir, "append_methodology_entries.py")
    assert os.path.exists(m1)
    # 按脚本的新逻辑推导目标路径
    from pathlib import Path
    p1 = Path(m1).parent.parent / "data" / "insight_knowledge" / "astrophysics" / "methodology.yaml"
    assert os.path.exists(p1)
    p2 = Path(REPO_ROOT) / "quality_pipeline" / "data" / "insight_knowledge" / "astrophysics"
    assert os.path.isdir(p2)
    p3 = p2 / "galaxy_catalogs.yaml"
    assert os.path.exists(p3)


# ==========================================================
# L-23: 脚本幂等去重改真实过滤
# ==========================================================

def test_append_methodology_dedup_is_real_filter():
    """L-23: append_methodology_entries.py 用真实列表过滤替代 assert 去重
    (assert 在 python -O 下被剥离 → 重复执行会产生重复 id)"""
    src = open(os.path.join(SCRIPTS_DIR, "append_methodology_entries.py"), encoding="utf-8").read()
    # 去重是列表过滤: added = [e for e in new_entries if e["id"] not in existing_ids]
    assert "added = [e for e in new_entries if e[\"id\"] not in existing_ids]" in src
    assert 'data["entries"].extend(added)' in src
    # 不再有 assert-based 去重
    assert 'assert e["id"] not in existing_ids' not in src


def test_append_knowledge_dedup_style_matches():
    """L-23: 参照 append_knowledge.py 的真实过滤写法 (风格一致)"""
    src = open(os.path.join(SCRIPTS_DIR, "append_knowledge.py"), encoding="utf-8").read()
    assert "added = [e for e in entries if e.get(\"id\") not in existing]" in src

