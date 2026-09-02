"""
test_main_graph_routing.py — 主图路由专项测试 (V3.3)

直接编译 compile_quality_graph() 并逐节点 invoke, 覆盖:
  1. A→B→D          (全 Normalization → Export)
  2. A→C→D          (全 Conflict → Export)
  4. A→C→E          (Conflict 判 HumanReview)
  5. E→A            (HR 送回 Assessment → dispatch 重新初始化, 无旧报告残留)
  7. 混合 HumanReview + Normalization (HR 优先, 无人丢失)
  8. Retry 超限      (子图 Retry 3 次 → HumanReview)
  9. 循环超限强制 Export
  10. Gate 机制      (Retry 1 次成功重入)

策略: patch 子图决策 agent (DecisionReasoning / AnnotationReport) 控制路由,
      Normalization/Export/HR 真实执行, 只测试主图路由而非评估逻辑。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import unittest
from unittest.mock import patch, MagicMock

# LLM 全 mock
import utils.llm as llm_mod

def _fake_llm(*args, **kwargs):
    m = MagicMock()
    m.content = '{}'
    return m

llm_mod.get_llm = _fake_llm

from quality_state import make_initial_state
from graph import compile_quality_graph


def _base_data(sids):
    sources = [{"source_id": sid, "source_type": "paper", "title": f"Paper {sid}",
                "access_path": "/x.pdf"} for sid in sids]
    records = []
    for i, sid in enumerate(sids):
        records.append({
            "record_id": f"{sid}_field_0", "source_id": sid,
            "field_name": "distance", "field_value": f"{10 + i}", "field_unit": "kpc",
            "trace_id": f"t{i}", "provenance": {"page": i + 1, "bbox": [0, 0, 1, 1]},
            "extraction_method": "llm_text", "extraction_confidence": 0.9,
        })
    return {"schema_version": "2.0.0", "research_domain": "astrophysics",
            "sources": sources, "records": records}


def _fake_decision(routes):
    """控制 Assessment 输出的 per_source_routes。"""
    def fake_run(self, state):
        return {
            "report_state": {"quality": {
                "per_source_routes": routes,
                "route_counts": {r: list(routes.values()).count(r) for r in set(routes.values())},
            }},
            "workflow_state": {"execution_status": "Success", "current_node": "decision"},
        }
    return fake_run


def _fake_annotation_report(route_decision, status="Annotated"):
    """控制 Conflict 子图的 resolution_report。"""
    def fake_run(self, state):
        return {
            "report_state": {"conflict": {
                "resolution_report": {
                    "route_decision": route_decision,
                    "status": status,
                    "summary": "mocked",
                },
                "aggregation": {"involved_sources": ["S1"]},
            }},
            "workflow_state": {"route_decision": route_decision,
                               "execution_status": "Success",
                               "current_node": "annotation_report"},
        }
    return fake_run


def _fake_conflict_check():
    """V4 fix: 让 Normalization 复检判定存在冲突 (B→C 触发源)。

    结构对齐 tools/assessment/statistical_conflict.py 的
    detect_conflicts_statistical 输出 (variances/anomalies/counts)。
    """
    def fake(data, threshold=0.20, use_advanced=True):
        return {
            "has_variance": True, "variance_count": 1,
            "variances": [{
                "entity_type": "FRB", "entity_name": "FRB 121102",
                "field_name": "dispersion_measure", "source_count": 2,
                "source_ids": ["S1", "S2"], "value_range": [100, 200],
                "max_cohens_d": 3.5,
                "source_stats": {
                    "S1": {"mean": 100.0, "std": 1.0, "n": 1,
                           "measurement_methods": [], "condition_tags": [],
                           "year": 2020, "unit": "pc"},
                    "S2": {"mean": 200.0, "std": 1.0, "n": 1,
                           "measurement_methods": [], "condition_tags": [],
                           "year": 2021, "unit": "pc"},
                },
                "unit_mismatch_detected": False, "cross_id_risk": False,
                "inferred_cause": "unknown", "cause_confidence": 0.3,
            }],
            "has_anomalies": True, "anomaly_count": 1,
            "anomalies": [{
                "anomaly_type": "statistical_outlier", "entity_type": "FRB",
                "entity_name": "FRB 121102", "field_name": "dispersion_measure",
                "source_id": "S1", "source_a": "S1", "source_b": "S2",
            }],
            "conflict_count": 1, "risk_level": "medium",
            "method": "multi_source_variance",
        }
    return fake


def _fake_aggregation():
    """控制 Conflict 子图 Stage 1 — 有 variance/anomaly, 防止快速出口跳过后续 Stage。"""
    def fake_run(self, state):
        return {
            "report_state": {"conflict": {"aggregation": {
                "trigger_path": "A→C",
                "total_variances": 1,
                "total_anomalies": 1,
                "variances": [{
                    "entity_type": "FRB", "entity_name": "FRB 121102",
                    "field_name": "dispersion_measure", "source_count": 2,
                    "source_ids": ["S1", "S2"], "value_range": [1, 2],
                    "max_cohens_d": 1.0, "inferred_cause": "unknown",
                    "cause_confidence": 0.3, "source_details": {},
                }],
                "anomalies": [{
                    "anomaly_type": "extraction_error", "entity_name": "X",
                    "field_name": "dispersion_measure", "source_id": "S1",
                }],
                "involved_sources": ["S1"],
            }}},
            "workflow_state": {"execution_status": "Success",
                               "current_node": "variance_aggregation"},
        }
    return fake_run


class TestMainGraphRouting(unittest.TestCase):

    def _invoke_until_terminal(self, app, state, max_steps=15):
        """用 stream(mode='values') 收集经过的节点 (单次 invoke 走完整图)。

        返回 (最终 state, 经过的节点列表 — 用 workflow_history 的 agent 名)。
        """
        path = []
        for _ in range(max_steps):
            for snapshot in app.stream(state, {"recursion_limit": 300}, stream_mode="values"):
                wf = snapshot.get("workflow_state", {})
                node = wf.get("current_node", "?")
                if node and node not in path:
                    path.append(node)
                state = snapshot
            wf = state.get("workflow_state", {})
            if wf.get("__human_review_needed__"):
                wf["__human_review_needed__"] = False
                wf["__human_review_decision__"] = {"decisions": {}, "route_decision": "Normalization"}
                wf["route_decision"] = "Normalization"
                wf["execution_status"] = "Success"
                state["workflow_state"] = wf
                continue  # 恢复后重新 stream
            break
        return state, path

    # ── 场景 1: A→B→D ──
    def test_1_a_b_d(self):
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        with patch.object(DecisionReasoningAgent, "run", _fake_decision({"S1": "Normalization"})):
            app = compile_quality_graph()
            state = make_initial_state(_base_data(["S1"]))
            state, path = self._invoke_until_terminal(app, state)
        self.assertIn("structured_export", path, f"未到达 Export: {path}")
        wf = state["workflow_state"]
        self.assertEqual(wf.get("pending_sources", {}).get("Normalization"), [],
                         "Normalization 队列应清空")

    # ── 场景 2: A→C→D ──
    def test_2_a_c_d(self):
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        from Data_Conflict_agentV1.agents.resolution_report_agent import AnnotationReportAgent
        with patch.object(DecisionReasoningAgent, "run", _fake_decision({"S1": "Conflict"})), \
             patch.object(AnnotationReportAgent, "run", _fake_annotation_report("Export")):
            app = compile_quality_graph()
            state = make_initial_state(_base_data(["S1"]))
            state, path = self._invoke_until_terminal(app, state)
        self.assertIn("structured_export", path, f"未到达 Export: {path}")

    # ── 场景 3: B→C→D — Normalization 复检发现冲突 → 进入 Conflict → Export ──
    def test_3_b_c_route(self):
        """V4 fix: B→C 路由激活 (此前是死代码 — gate 覆写 route_decision)。

        链路: Validation 复检 (patch detect_conflicts_statistical) 报 1 冲突 →
        route="Conflict" → ReportAgent 翻转 → gate 不再覆写 → LoopController
        B→C 分支 → Conflict 子图 (VarianceAggregationAgent 真实执行, 验证 B2
        桥接读取 validation.conflict_check) → AnnotationReport 判 Export。
        """
        import tools.assessment.statistical_conflict as sc
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        from Data_Conflict_agentV1.agents.resolution_report_agent import AnnotationReportAgent
        with patch.object(DecisionReasoningAgent, "run", _fake_decision({"S1": "Normalization", "S2": "Normalization"})), \
             patch.object(sc, "detect_conflicts_statistical", _fake_conflict_check()), \
             patch.object(AnnotationReportAgent, "run", _fake_annotation_report("Export")):
            app = compile_quality_graph()
            state = make_initial_state(_base_data(["S1", "S2"]))
            state, path = self._invoke_until_terminal(app, state)
        self.assertIn("structured_export", path, f"未到达 Export: {path}")
        # B2: Conflict 子图真实执行 (Aggregation 为子图内部节点, 主图流不展示,
        # 从 workflow_history 的 stage 断言)
        stages = [h.get("stage") for h in state["workflow_state"].get("workflow_history", [])]
        self.assertIn("Aggregation", stages, f"Conflict 子图未执行: {stages}")
        self.assertIn("Classification", stages, f"Conflict 子图未执行: {stages}")
        # B1: Normalization 后 LoopController 应决策 Conflict (B→C)
        loop_entries = [h for h in state["workflow_state"].get("workflow_history", [])
                        if h.get("stage") == "LoopCheck"]
        self.assertTrue(any("next=Conflict" in h.get("reason", "") for h in loop_entries),
                        f"LoopController 未决策 B→C: {[h.get('reason') for h in loop_entries]}")
        agg = (state["report_state"].get("conflict") or {}).get("aggregation", {})
        self.assertEqual(agg.get("trigger_path"), "B→C", "触发路径应为 B→C (Normalization 复检)")
        self.assertEqual(agg.get("total_variances"), 1, "应从 validation.conflict_check 读到方差")

    # ── 场景 4: A→C→E (Conflict 判 HumanReview) ──
    def test_4_a_c_e(self):
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        from Data_Conflict_agentV1.agents.conflict_identification_agent import VarianceAggregationAgent
        from Data_Conflict_agentV1.agents.resolution_report_agent import AnnotationReportAgent
        with patch.object(DecisionReasoningAgent, "run", _fake_decision({"S1": "Conflict"})), \
             patch.object(VarianceAggregationAgent, "run", _fake_aggregation()), \
             patch.object(AnnotationReportAgent, "run",
                          _fake_annotation_report("HumanReview", "Unresolved_Anomalies")):
            app = compile_quality_graph()
            state = make_initial_state(_base_data(["S1"]))
            state, path = self._invoke_until_terminal(app, state)
        self.assertIn("human_review", path, f"未进入 HumanReview: {path}")

    # ── 场景 5: E→A — HR 送回 Assessment, dispatch 重新初始化无残留 ──
    def test_5_e_a_clean(self):
        from routers import dispatch_node
        state = make_initial_state(_base_data(["S1"]))
        state["report_state"]["conflict"] = {"old": "data"}
        state["report_state"]["normalization"] = {"old": "data"}
        state["report_state"]["export"] = {"old": "data"}
        state["report_state"]["quality"] = {"per_source_routes": {"S1": "Export"}}
        r = dispatch_node(state)
        rs = r["report_state"]
        self.assertIsNone(rs.get("conflict"), "conflict 应被清除")
        self.assertIsNone(rs.get("normalization"), "normalization 应被清除")
        self.assertIsNone(rs.get("export"), "export 应被清除")
        self.assertIsNotNone(rs.get("quality"), "quality 应保留")
        self.assertEqual(r["workflow_state"]["pending_sources"]["Export"], ["S1"])
        self.assertEqual(r["workflow_state"]["phase"], "dispatch")

    # ── 场景 7: 混合 HumanReview + Normalization (HR 优先, 无人丢失) ──
    def test_7_mixed_human_normalization(self):
        from unittest.mock import patch as _patch
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        # V3.5: HR 现在会展示 Assessment 触发的质量审核项 (不再跳过),
        # 测试需 mock stdin 交互: 选项1(采用A) → 理由 → 下一步1(提交Normalization)
        with _patch.object(DecisionReasoningAgent, "run",
                           _fake_decision({"S_A": "HumanReview", "S_B": "Normalization"})), \
             _patch("builtins.input", side_effect=["1", "", "1"]):
            app = compile_quality_graph()
            state = make_initial_state(_base_data(["S_A", "S_B"]))
            state, path = self._invoke_until_terminal(app, state)
        self.assertIn("human_review", path, f"HumanReview 被跳过: {path}")
        self.assertIn("structured_export", path, f"未到达 Export: {path}")
        wf = state["workflow_state"]
        self.assertEqual(wf.get("pending_sources", {}).get("HumanReview"), [])
        self.assertEqual(wf.get("pending_sources", {}).get("Normalization"), [])

    # ── 场景 8: Retry 超限 → HumanReview ──
    def test_8_retry_exhausted(self):
        from routers import check_retry, MAX_RETRIES, NODE_HUMAN_REVIEW
        state = make_initial_state(_base_data(["S1"]))
        state["workflow_state"]["execution_status"] = "Retry"
        state["workflow_state"]["retry_by_node"] = {"assessment_graph": MAX_RETRIES}
        r = check_retry(state, "assessment_graph")
        self.assertEqual(r, NODE_HUMAN_REVIEW, "重试耗尽应去 HumanReview")

    # ── 场景 9: 循环超限强制 Export ──
    def test_9_loop_force_export(self):
        from routers import loop_controller_node, route_after_loop, NODE_EXPORT
        state = make_initial_state(_base_data(["S1"]))
        state["workflow_state"]["iteration_counter"] = 2  # +1 → 3 = MAX
        state["workflow_state"]["from_conflict"] = True
        state["workflow_state"]["loop_round"] = 1
        r = loop_controller_node(state)
        wf = r["workflow_state"]
        self.assertTrue(wf.get("force_export"), "应强制 Export")
        self.assertEqual(wf.get("next_route"), "Export")
        s2 = make_initial_state(_base_data(["S1"]))
        s2["workflow_state"].update(wf)
        self.assertEqual(route_after_loop(s2), NODE_EXPORT)

    # ── 场景 10: Gate 机制 — Retry 1 次成功重入, 超限 → HumanReview ──
    def test_10_gate_retry(self):
        from routers import _make_stage_gate, MAX_RETRIES
        gate = _make_stage_gate("assessment_graph")
        state = make_initial_state(_base_data(["S1"]))
        state["workflow_state"]["execution_status"] = "Retry"
        state["workflow_state"]["retry_by_node"] = {}
        r = gate(state)
        wf = r["workflow_state"]
        self.assertEqual(wf.get("route_decision"), "__retry__", "首次 Retry 应重入")
        self.assertEqual(wf.get("retry_by_node", {}).get("assessment_graph"), 1)
        self.assertEqual(wf.get("execution_status"), "Success", "Gate 清除 Retry 防重复")

        state2 = make_initial_state(_base_data(["S1"]))
        state2["workflow_state"]["execution_status"] = "Retry"
        state2["workflow_state"]["retry_by_node"] = {"assessment_graph": MAX_RETRIES}
        r2 = gate(state2)
        self.assertEqual(r2["workflow_state"].get("route_decision"), "HumanReview")


if __name__ == "__main__":
    unittest.main()
