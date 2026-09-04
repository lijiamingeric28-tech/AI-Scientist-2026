"""子图1（意图澄清）characterization 测试 — 全 mock 离线

锁定：图装配 + 状态契约 + 天文/寒暄两条流程的最终状态。
"""

import pytest

from subgraphs.subgraph1.graph import create_intent_clarification_subgraph


def test_subgraph1_compiles():
    """图可编译，节点集合完整"""
    graph = create_intent_clarification_subgraph()
    # get_graph() 含 __start__/__end__ 伪节点，过滤
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "initial_parse",
        "polite_reject",
        "greeting_handler",
        "ask_entity",
        "handle_failure",
        "ask_properties",
        "final_confirm",
    }


def test_astronomical_query_confirmed(mock_sg1_llm, mock_stdin):
    """天文查询完整流：M31 + distance → final_confirm('y') → confirmed"""
    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "M31 的距离",
        "query_id": "test-1",
    })

    assert result["query_type"] == "astronomical"
    assert result["target_entity"] == "M31"
    assert result["requested_properties"] == ["distance"]
    assert result["clarification_status"] == "confirmed"
    assert result["user_confirmed"] is True
    # 对话历史包含追问与确认（至少 2 条：assistant + user）
    assert len(result.get("chat_history", [])) >= 2


def test_greeting_then_astronomical(monkeypatch):
    """寒暄 → 引导输入 → 二次解析为天文查询 → confirmed"""
    import importlib

    def _mod(name):
        return importlib.import_module(f"subgraphs.subgraph1.nodes.{name}")

    init_mod = _mod("initial_parse")
    query_types = iter(["greeting", "astronomical"])
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: next(query_types))
    monkeypatch.setattr(
        init_mod,
        "extract_entity_and_properties",
        lambda user_input, chat_history: {
            "target_entity": "M31",
            "requested_properties": ["distance"],
        },
    )
    # greeting_handler 的 interrupt → 新查询；final_confirm 的 interrupt → 确认
    interrupt_values = iter(["M31 的距离", "y"])
    for mod_name in ("greeting_handler", "final_confirm"):
        monkeypatch.setattr(_mod(mod_name), "interrupt", lambda *a, **k: next(interrupt_values))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "你好",
        "query_id": "test-2",
    })

    assert result["target_entity"] == "M31"
    assert result["clarification_status"] == "confirmed"


def test_invalid_query_polite_reject(monkeypatch):
    """无效查询 → polite_reject → END，不进入交互节点"""
    import importlib
    init_mod = importlib.import_module("subgraphs.subgraph1.nodes.initial_parse")
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: "invalid")

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "asdfg!@#$",
        "query_id": "test-3",
    })

    assert result["query_type"] == "invalid"
    # polite_reject 后无 target_entity
    assert result.get("target_entity") is None


# ══════════════════════════════════════════════════════════════
# 2026-09-03 方向1：ask_properties 答复就地解读（M45 实测 bug 回归集）
# 回归对象：答复"全部"/性质列表被 classify_query_type 误判 invalid
# → polite_reject 整次查询失败（0 来源 0 记录）
# ══════════════════════════════════════════════════════════════

def _mock_first_parse(monkeypatch, entity="M45", properties=None):
    """首轮 initial_parse 固定：天文查询 + entity 无性质 → 触发 ask_properties"""
    import importlib
    init_mod = importlib.import_module("subgraphs.subgraph1.nodes.initial_parse")
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: "astronomical")
    monkeypatch.setattr(
        init_mod,
        "extract_entity_and_properties",
        lambda user_input, chat_history: {
            "target_entity": entity,
            "requested_properties": properties or [],
        },
    )


def _mock_node_interrupt(monkeypatch, node, answers):
    """按调用顺序喂 interrupt 返回值（节点模块 import 时绑定属性）"""
    import importlib
    mod = importlib.import_module(f"subgraphs.subgraph1.nodes.{node}")
    it = iter(answers)
    monkeypatch.setattr(mod, "interrupt", lambda *a, **k: next(it))


def _mock_ask_properties_extract(monkeypatch, calls_out=None, empty_for=()):
    """ask_properties 答复解读用的 extract（仅具体性质分支会调用）

    简化语义（对应真实 llm_utils 的 LLM 判定）：
    - empty_for 中的噪音应答（天气句/寒暄等）→ 解析不出性质 → []
    - 其余按 、/和 等分隔符拆成性质原文列表
    """
    import importlib
    mod = importlib.import_module("subgraphs.subgraph1.nodes.ask_properties")

    def _fake(user_input, chat_history):
        if calls_out is not None:
            calls_out.append(user_input)
        import re
        text = str(user_input).strip()
        if any(m in text for m in empty_for):
            return {"target_entity": None, "requested_properties": []}
        parts = re.split(r"[、，,和及\s]+", text)
        props = [p for p in parts if p]
        return {"target_entity": None, "requested_properties": props}

    monkeypatch.setattr(mod, "extract_entity_and_properties", _fake)


def test_ask_properties_answer_all_confirms(monkeypatch):
    """回归：M45 无性质 → ask_properties 答"全部" → 查全部 → confirmed（不再 polite_reject）"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["全部"])
    _mock_node_interrupt(monkeypatch, "final_confirm", ["y"])
    extract_calls = []
    _mock_ask_properties_extract(monkeypatch, extract_calls)

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "帮我查询M45", "query_id": "t-all"})

    assert result["clarification_status"] == "confirmed"
    assert result["user_confirmed"] is True
    assert result["target_entity"] == "M45"
    # 查全部 = 空性质列表（语义由 P1 兜底默认性质集），且不触发 LLM 提取
    assert result["requested_properties"] == []
    assert extract_calls == []


def test_ask_properties_answer_property_list(monkeypatch):
    """回归：答具体性质列表 → 就地提取 → confirmed with props"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["距离、年龄和金属丰度"])
    _mock_node_interrupt(monkeypatch, "final_confirm", ["y"])

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M45", "query_id": "t-props"})

    assert result["clarification_status"] == "confirmed"
    # mock extract 按 、/和 分词："距离、年龄和金属丰度" → 3 项
    assert result["requested_properties"] == ["距离", "年龄", "金属丰度"]
    assert result["target_entity"] == "M45"


def test_ask_properties_unparsed_reasks_then_all(monkeypatch):
    """答非所问（非性质内容）→ 礼貌重问一轮 → 答"全部" → confirmed（任务不被杀死）"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["今天天气怎么样", "全部"])
    _mock_node_interrupt(monkeypatch, "final_confirm", ["y"])
    extract_calls = []
    _mock_ask_properties_extract(monkeypatch, extract_calls, empty_for=("今天天气怎么样",))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M45", "query_id": "t-reask"})

    assert result["clarification_status"] == "confirmed"
    assert result["target_entity"] == "M45"
    assert result["requested_properties"] == []
    # 第一轮答复确实走了 LLM 提取（天气句解析不出性质）→ 触发重问
    assert len(extract_calls) == 1


def test_ask_properties_greeting_reasks(monkeypatch):
    """澄清轮内寒暄（M7 历史场景）→ 不吞掉也不终止 → 重问"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["你好", "距离"])
    _mock_node_interrupt(monkeypatch, "final_confirm", ["y"])
    extract_calls = []
    _mock_ask_properties_extract(monkeypatch, extract_calls, empty_for=("你好",))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M45", "query_id": "t-greet"})

    assert result["clarification_status"] == "confirmed"
    assert result["target_entity"] == "M45"
    assert result["requested_properties"] == ["距离"]
    assert len(extract_calls) == 2  # 你好 + 距离 各解析一次


def test_ask_properties_exit_cancels(monkeypatch):
    """澄清轮内答"不查了" → cancelled 优雅终止（final_confirm 不再触发）"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["不查了"])
    import importlib
    fc_mod = importlib.import_module("subgraphs.subgraph1.nodes.final_confirm")
    monkeypatch.setattr(fc_mod, "interrupt", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应进入 final_confirm")))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M45", "query_id": "t-exit"})

    assert result["clarification_status"] == "cancelled"
    assert result["user_confirmed"] is False
    assert result["exit_intent_detected"] is True


def test_ask_properties_reask_exhausted_falls_back_all(monkeypatch):
    """重问超限（max_turns=3）→ 回退查全部 → final_confirm 用户可再改/取消"""
    _mock_first_parse(monkeypatch)
    _mock_node_interrupt(monkeypatch, "ask_properties", ["天气", "天气", "天气"])
    _mock_node_interrupt(monkeypatch, "final_confirm", ["y"])
    extract_calls = []
    _mock_ask_properties_extract(monkeypatch, extract_calls, empty_for=("天气",))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({"user_query": "M45", "query_id": "t-exhaust"})

    assert result["clarification_status"] == "confirmed"
    assert result["requested_properties"] == []
    # 三次询问：首问 + 两次重问，全部解析失败后第 3 轮回退全部
    assert len(extract_calls) == 3
