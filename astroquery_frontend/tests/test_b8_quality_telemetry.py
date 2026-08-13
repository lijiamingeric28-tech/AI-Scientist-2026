"""批次 B8「质量管线埋点」回归测试 — 全 mock 离线，零 LLM/网络。

覆盖（对应 docs/web_audit_findings.json）：
  - H-10: HITL 澄清 question 恒空 — interrupt payload 补 question / web_runner
    兜底 question=text / options 透传
  - M-13: flow_started/flow_completed 发送方 + clean/deliver 出口 stage_completed
    + pdf_converter 'paper' step_progress
  - M-16: HumanReviewAgent 节点 agent 事件（interrupt 挂起不掩异常）

事件捕获：events.configure 单例重绑（同 test_web_offline client fixture 思路），
测试后恢复原发布函数，不污染真实总线。
"""

from __future__ import annotations

import pytest

from langgraph.errors import GraphInterrupt


@pytest.fixture
def ev_events(monkeypatch):
    """重绑 events 发射器到本地收集器；结束后恢复原配置。"""
    import events as _ev

    prev = _ev._emit_fn
    out = []
    _ev.configure(lambda tid, ev: out.append({"task_id": tid, **ev}))
    yield out
    _ev.configure(prev)


# ══════════════════════════════════════════════════════════
# H-10: 澄清 question 恒空
# ══════════════════════════════════════════════════════════

def test_web_runner_clarification_question_fallback_and_options():
    """web_runner._clarification_payload：无 question 键 → 兜底取 text；options 透传。"""
    from astroquery_ai.web_runner import _clarification_payload

    # human_review_next 旧 payload 只有 text + options → question 不再恒空
    raw = {
        "type": "human_review_next",
        "text": "\n  ------\n  请选择下一步:\n    [1] 提交裁决\n  ------\n  请输入选项 [1-3]: ",
        "options": ["1", "2", "3"],
    }
    ev = _clarification_payload(raw)
    assert ev["question"] == raw["text"], "无 question 键必须兜底 text"
    assert ev["options"] == ["1", "2", "3"], "human_review 候选选项必须透传"

    # 有 question 键 → 优先使用（生产端补键后不再退化为原始文本）
    raw2 = {"type": "human_review_verdict", "question": "请选择裁决方式：[1] 采用 Source A",
            "text": "  请输入选项 [1-5]: "}
    ev2 = _clarification_payload(raw2)
    assert ev2["question"] == "请选择裁决方式：[1] 采用 Source A"
    assert "options" not in ev2


def test_human_review_agent_interrupts_carry_question(monkeypatch):
    """6 个 human_review interrupt 全部带 question 键（去分隔符指引）+ options。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent

    payloads = []
    answers = iter(["1", "42", "test reason", "1"])  # verdict → custom_value → reason → next

    def fake_interrupt(payload):
        payloads.append(payload)
        return next(answers)

    monkeypatch.setattr(hra, "interrupt", fake_interrupt)

    state = {
        "workflow_state": {"pending_sources": {"HumanReview": []}, "__human_review_decision__": None},
        "report_state": {
            "quality": {"per_source_routes": {}, "sources": {}},
            "conflict": {"resolution_report": {"resolution_plan": {
                "human_review_items": [{
                    "conflict_d": "CF-001", "field_name": "distance",
                    "entity_name": "M31", "source_ids": ["SRC_A"],
                }],
            }}},
        },
        "data_state": {},
    }
    result = HumanReviewAgent().run(state)
    assert result["workflow_state"]["route_decision"] == "Normalization"

    assert len(payloads) == 4, payloads
    by_type = {p["type"]: p for p in payloads}
    for p in payloads:
        assert p.get("question"), f"{p['type']} 缺 question 键"
    assert "请选择裁决方式" in by_type["human_review_verdict"]["question"]
    assert "请输入理由" in by_type["human_review_reason"]["question"]
    assert by_type["human_review_next"]["options"] == ["1", "2", "3"]
    assert "提交裁决" in by_type["human_review_next"]["question"]


def test_final_confirm_modify_interrupt_carries_question(monkeypatch):
    """final_confirm_modify 补 question 键（Web 重新输入指引）。"""
    import importlib
    # nodes/__init__.py 把 final_confirm 函数再导出，包属性遮蔽子模块 → 用 importlib
    fc = importlib.import_module("subgraphs.subgraph1.nodes.final_confirm")

    payloads = []
    answers = iter(["m", "M31 的距离"])

    def fake_interrupt(payload):
        payloads.append(payload)
        return next(answers)

    monkeypatch.setattr(fc, "interrupt", fake_interrupt)

    out = fc.final_confirm({
        "target_entity": "M31",
        "requested_properties": ["distance"],
        "chat_history": [],
    })
    assert out["clarification_status"] == "modified"

    mod = [p for p in payloads if p.get("type") == "final_confirm_modify"]
    assert len(mod) == 1
    assert mod[0]["question"], "final_confirm_modify 必须带 question 键"
    assert "重新输入" in mod[0]["question"]


# ══════════════════════════════════════════════════════════
# M-13: flow 事件 + clean/deliver 出口 stage_completed
# ══════════════════════════════════════════════════════════

def test_quality_flow_events_paired_and_exit_stage_completed(ev_events):
    """flow_started/flow_completed 配对（flow_id=轮次、round=loop_round、stage_id）；
    管线出口（insights 后）补发 clean/deliver 卡 stage_completed。"""
    from quality_pipeline.graph import _flow_wrap, _pipeline_exit_wrap

    calls = []

    def fake_fn(state):
        calls.append(state)
        return {"workflow_state": {"phase": "done"}}

    state = {
        "context_state": {"query_id": "test-flow-1"},
        "workflow_state": {"loop_round": 2, "phase": "normalization"},
    }

    out = _flow_wrap("normalization", "clean", fake_fn)(state)
    assert out == {"workflow_state": {"phase": "done"}}
    assert calls == [state]

    flows = [e for e in ev_events if e["type"] in ("flow_started", "flow_completed")]
    assert [e["type"] for e in flows] == ["flow_started", "flow_completed"], "flow 事件必须配对"
    assert flows[0]["flow_id"] == "normalization" and flows[0]["round"] == 2
    assert flows[0]["stage_id"] == "clean"
    assert flows[1]["flow_id"] == "normalization" and flows[1]["round"] == 2
    assert flows[0]["task_id"] == "test-flow-1"

    # 出口：clean/deliver 卡 stage_completed（前端卡 5/6 不再永久进行中）
    ev_events.clear()
    _pipeline_exit_wrap(fake_fn)(state)
    stages = [e for e in ev_events if e["type"] == "stage_completed"]
    assert [(s["stage_id"], s["status"]) for s in stages] == [
        ("clean", "completed"), ("deliver", "completed"),
    ]


def test_quality_flow_round_reads_loop_round(ev_events):
    """round 取 workflow_state.loop_round（dispatch 清零 / C→B 递增的轮次语义）。"""
    from quality_pipeline.graph import _flow_wrap

    _flow_wrap("conflict", "clean", lambda s: {"ok": True})({
        "context_state": {"query_id": "q"},
        "workflow_state": {"loop_round": 1},
    })
    flows = [e for e in ev_events if e["type"] == "flow_started"]
    assert flows[0]["flow_id"] == "conflict" and flows[0]["round"] == 1


def test_pdf_converter_emits_paper_progress(monkeypatch, ev_events):
    """pdf_converter 循环内 'paper' step_progress（成功/失败都计数），结束时 completed。"""
    import subgraphs.subgraph3.nodes.pdf_converter as pc

    def fake_pdf_to_images(path, dpi=None):
        if "FAIL" in path:
            raise RuntimeError("boom")
        return ["page1", "page2"]

    monkeypatch.setattr(pc, "pdf_to_images", fake_pdf_to_images)
    monkeypatch.setattr(pc.image_cache, "save_images",
                        lambda bibcode, images: [f"/cache/{bibcode}_p{i}.png" for i in range(len(images))])
    monkeypatch.setattr(pc.image_cache, "get_cache_size", lambda: 1.2)

    state = {
        "query_id": "test-pdf-1",
        "download_paths": [
            {"bibcode": "AAA", "local_path": "/x/aaa.pdf"},
            {"bibcode": "BBB", "local_path": "/x/FAIL_bbb.pdf"},
        ],
    }
    out = pc.pdf_batch_converter(state)
    assert out["conversion_status"] == "completed"
    assert "AAA" in out["paper_image_paths"] and "BBB" not in out["paper_image_paths"]
    assert len(out["conversion_failed"]) == 1

    papers = [e for e in ev_events if e["type"] == "step_progress" and e["step"] == "paper"]
    assert len(papers) == 3, papers
    assert [p["status"] for p in papers] == ["running", "running", "completed"]
    assert papers[0]["stage_id"] == "extraction"
    assert papers[0]["progress"] == {"completed": 1, "total": 2, "current": "AAA"}
    assert papers[1]["progress"] == {"completed": 2, "total": 2, "current": "BBB"}
    assert papers[2]["progress"] == {"completed": 2, "total": 2, "current": None}


# ══════════════════════════════════════════════════════════
# M-16: HumanReviewAgent 节点 agent 事件
# ══════════════════════════════════════════════════════════

def test_human_review_node_emits_agent_events(ev_events):
    """触发 HumanReview（已有决策，无 interrupt）→ agent_started/completed 配对。"""
    from quality_pipeline.graph import human_review_node

    state = {
        "context_state": {"query_id": "test-hr-1"},
        "workflow_state": {
            "__human_review_decision__": {"route_decision": "Normalization"},
            "pending_sources": {"HumanReview": []},
        },
        "report_state": {"quality": {"per_source_routes": {}, "sources": {}}},
        "data_state": {},
    }
    result = human_review_node(state)
    assert result["workflow_state"]["route_decision"] == "Normalization"

    agents = [(e["type"], e.get("agent"), e.get("stage_id")) for e in ev_events
              if e["type"] in ("agent_started", "agent_completed")]
    assert ("agent_started", "HumanReviewAgent", "clean") in agents, agents
    assert ("agent_completed", "HumanReviewAgent", "clean") in agents, agents


def test_human_review_node_interrupt_propagates(monkeypatch, ev_events):
    """interrupt 挂起时 GraphInterrupt 原样上浮（不被 wrapper 的 finally 掩成
    NameError），且不发 agent_completed（挂起中）。"""
    import subgraphs.data_human_review.human_review_agent as hra
    from quality_pipeline.graph import human_review_node

    class _FakeAgent:
        def run(self, state):
            raise GraphInterrupt("human review pending")

    monkeypatch.setattr(hra, "HumanReviewAgent", _FakeAgent)

    with pytest.raises(GraphInterrupt):
        human_review_node({
            "context_state": {"query_id": "q"},
            "workflow_state": {},
            "report_state": {},
            "data_state": {},
        })

    types = [e["type"] for e in ev_events]
    assert types.count("agent_started") == 1
    assert "agent_completed" not in types
