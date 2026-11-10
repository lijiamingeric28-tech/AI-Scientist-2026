"""自动化回归测试：验证科研问答智能体 (Agent Harness 2.0) 全链路真实性与去硬编码特性。
测试覆盖：
1. TaskDataBundle 2.0 数据装载与全要素真实索引
2. 7 大领域只读工具的无网高精度调阅
3. GroundingVerifier 2.0 的防幻觉校验、非真实 ID 安全降级与 Emoji 清洗
4. AgentStore 多轮交互 SQLite 持久化
5. AgentController ReAct 编排循环与离线真实数据合成保底
"""

import asyncio
import pytest
from pathlib import Path

from astroquery_ai.agent_harness import (
    AgentController,
    AgentMemory,
    AgentStore,
    DomainTools,
    GroundingVerifier,
    TaskDataBundle,
    load_task_bundle,
)
from astroquery_ai.runtime.paths import data_root
from astroquery_ai.runtime.application import Application

SAMPLE_TASK_ID = "e030fefb-3db1-479e-af8b-eb710233e539"


@pytest.fixture(scope="module")
def app():
    root = data_root()
    return Application(root)


@pytest.fixture(scope="module")
def bundle(app):
    return load_task_bundle(SAMPLE_TASK_ID, app)


def test_bundle_loader_truth_anchoring(bundle):
    """验证数据加载器对真实交付快照的解构与实体完整性。"""
    assert bundle.task_id == SAMPLE_TASK_ID
    assert "J0437" in bundle.target_name or "PSR" in bundle.target_name
    assert len(bundle.measurements) > 0
    assert len(bundle.definitions_list) > 0
    assert len(bundle.sources) > 0

    # 验证内存索引
    assert len(bundle.measurements_by_id) == len(bundle.measurements)
    assert len(bundle.definitions_by_id) == len(bundle.definitions_list)

    # 验证事实摘要文本
    summary = bundle.get_grounded_summary()
    assert "当前任务事实基底" in summary
    assert bundle.target_name in summary


def test_domain_tools_read_only(bundle):
    """验证 7 大领域只读工具在无外部网络依赖下的检索与学术表达。"""
    tools = DomainTools(bundle)

    # 1. query_measurements
    res_m = tools.execute_tool("query_measurements", {"property_name": "色散量", "limit": 4})
    assert "[REC:" in res_m
    assert "[SOURCE:" in res_m

    # 2. get_measurement_provenance
    mid = bundle.measurements[0]["measurement_id"]
    res_prov = tools.execute_tool("get_measurement_provenance", {"measurement_id": mid})
    assert f"[REC:{mid}]" in res_prov
    assert "底层溯源链" in res_prov

    # 3. get_property_definition
    res_def = tools.execute_tool("get_property_definition", {"property_name": "色散量"})
    assert "[DEF:" in res_def
    assert "物理量约定与量纲定义" in res_def

    # 4. search_literature
    res_lit = tools.execute_tool("search_literature", {"query_terms": "pulsar"})
    assert "[SOURCE:" in res_lit

    # 5. inspect_differences_and_arbitration
    res_diff = tools.execute_tool("inspect_differences_and_arbitration", {"property_name": "色散量"})
    assert "多源测定分歧案卷" in res_diff or "一致性" in res_diff

    # 6. get_figure_evidence
    res_fig = tools.execute_tool("get_figure_evidence", {"property_keyword": "dispersion"})
    assert "科学图表切片" in res_fig

    # 7. get_scientific_theory
    res_theory = tools.execute_tool("get_scientific_theory", {"property_name": "色散"})
    assert "理论底座" in res_theory


def test_grounding_verifier_strictness(bundle):
    """验证防幻觉校验器：过滤非真实伪造 ID、抽取合法引用元数据、剔除全部 Emoji。"""
    verifier = GroundingVerifier(bundle)

    real_mid = bundle.measurements[0]["measurement_id"]
    real_src = bundle.sources[0]["source_id"]

    # 构造混合测试文本：包含真实 ID、伪造 ID、Emoji 表情、LaTeX
    raw_text = (
        f"💡 发现科学规律！测定值符合 [REC:{real_mid}]，出处参考 [SOURCE:{real_src}]。\n"
        f"同时存在虚构引用 [REC:fake_invented_id_999] 和未知图证 [FIG:fake_fig_888] 🚀✨。"
    )

    clean_text, citations = verifier.verify_and_clean(raw_text)

    # 1. 严格断言：杜绝任何 Emoji
    assert "💡" not in clean_text
    assert "🚀" not in clean_text
    assert "✨" not in clean_text

    # 2. 真实 ID 获得保留并挂载 payload
    assert f"[REC:{real_mid}]" in clean_text
    found_types = {c["type"] for c in citations}
    assert "record" in found_types

    # 3. 虚构 ID 必须被降级为纯文本，防止前端 404
    assert "[REC:fake_invented_id_999]" not in clean_text
    assert "测定记录 fake_invented_id_999" in clean_text
    assert "[FIG:fake_fig_888]" not in clean_text
    assert "图证 fake_fig_888" in clean_text


def test_agent_store_persistence(app):
    """验证智能体多轮历史在 SQLite 中的增删查改。"""
    store = AgentStore(app.repository)
    test_task = SAMPLE_TASK_ID

    # 清理初始测试数据
    store.delete_messages(test_task)
    assert len(store.get_messages(test_task)) == 0

    # 写入用户消息
    store.add_message(test_task, "user", "请问该天体的自转周期是多少？")
    msgs = store.get_messages(test_task)
    assert len(msgs) == 1
    assert msgs[0]["content"] == "请问该天体的自转周期是多少？"

    # 写入助手消息（带思考步骤与引用）
    steps = [{"step": 1, "thought": "正在检索测定记录..."}]
    cites = [{"type": "record", "id": "rec-1", "label": "REC-01"}]
    store.add_message(test_task, "assistant", "根据测定，其值为 5.74 ms。", steps, cites)

    msgs2 = store.get_messages(test_task)
    assert len(msgs2) == 2
    assert msgs2[1]["thought_steps"] == steps
    assert msgs2[1]["citations"] == cites

    # 再次清理还原
    store.delete_messages(test_task)
    assert len(store.get_messages(test_task)) == 0


def test_agent_controller_react_stream(bundle, app):
    """验证 ReAct 控制器全流程流式交互与确定性学术保底。"""
    async def _run():
        ctrl = AgentController(bundle, application=app)

        events = []
        async for ev in ctrl.run_react_stream([], "核查该天体的色散量与轨道周期测定值"):
            events.append(ev)

        event_types = [e["event"] for e in events]
        assert "agent_thought" in event_types
        assert "agent_tool_call" in event_types
        assert "agent_tool_result" in event_types
        assert "agent_token" in event_types
        assert "agent_done" in event_types

        done_ev = next(e for e in events if e["event"] == "agent_done")
        data = done_ev["data"]

        content = data["content"]
        citations = data["citations"]

        # 严格校验：内容不得包含任何 Emoji
        for char in content:
            code = ord(char)
            assert not (0x1F600 <= code <= 0x1F64F or 0x1F300 <= code <= 0x1F5FF or 0x2700 <= code <= 0x27BF)

        # 真实性检验：必须包含目标天体名称与实际引用
        assert "J0437" in content or "PSR" in content
        assert len(citations) > 0

    asyncio.run(_run())
