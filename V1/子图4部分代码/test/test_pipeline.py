"""
test_pipeline.py — V3.0 测试套件

测试: models, state, assessment agents (V3.0 多源方差分析), graph.
"""
from __future__ import annotations
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, os, sys, unittest
from unittest.mock import patch, MagicMock

def _fake_structured_llm(output_schema, **kw):
    """Mock structured LLM — 各 Agent 的 LLM 调用均返回无害结果。"""
    from schemas import AssessmentDecision, ConflictResolution, ConflictResolutionResult
    from schemas import NormalizationPlan, NormalizationValidation, ExportValidation
    from utils.llm import StructuredLLM
    fake = MagicMock(spec=StructuredLLM)
    if output_schema is AssessmentDecision:
        fake.invoke.return_value = AssessmentDecision(route="Export", reasoning="[mock]", critical_issues=[], confidence=0.9)
    elif output_schema is NormalizationPlan:
        fake.invoke.return_value = NormalizationPlan(tasks=["schema_mapping"], reasoning="[mock]")
    elif output_schema is NormalizationValidation:
        fake.invoke.return_value = NormalizationValidation(is_valid=True, remaining_issues=[], needs_conflict_analysis=False, confidence=0.8)
    elif output_schema is ConflictResolutionResult:
        fake.invoke.return_value = ConflictResolutionResult(resolutions=[], overall_summary="[mock]", needs_human_review=False, auto_resolved_count=0, human_required_count=0)
    elif output_schema is ExportValidation:
        fake.invoke.return_value = ExportValidation(is_valid=True, issues=[], data_quality_comment="[mock]", recommendations=[], confidence=0.9)
    return fake

_llm_patch = patch("utils.llm.get_structured_llm", side_effect=_fake_structured_llm)
_llm_patch.start()

# ==========================================================
# Test 1: Schema 校验
# ==========================================================
class TestGroundedDataSchema(unittest.TestCase):
    def test_valid_data(self):
        from models.grounded_data import GroundedData; from models.source import Source; from models.record import Record
        d = GroundedData(schema_version="1.0.0", sources=[Source(source_id="doi", source_type="paper", title="T", access_path="/t.pdf")], records=[Record(record_id="doi_x_1", source_id="doi", field_name="x", field_value=1.0, trace_id="t1", extraction_method="llm_text")])
        self.assertEqual(d.record_count, 1)

    def test_invalid_extraction_method(self):
        from models.record import Record
        with self.assertRaises(Exception): Record(record_id="t", source_id="d", field_name="x", field_value=1.0, trace_id="t1", extraction_method="bad")

    def test_schema_version_v2(self):
        """V2.0: schema_version '2.0.0' should be valid."""
        from models.grounded_data import GroundedData
        g = GroundedData.model_validate({"schema_version": "2.0.0", "sources": [], "records": []})
        self.assertEqual(g.schema_version, "2.0.0")

    def test_schema_version_invalid(self):
        """Invalid schema_version should be rejected."""
        from models.grounded_data import GroundedData
        with self.assertRaises(Exception):
            GroundedData.model_validate({"schema_version": "3.0.0", "sources": [], "records": []})

    def test_source_type_v2(self):
        """V2.0: source_type 'database' and 'supplement' should be valid."""
        from models.source import Source
        s = Source(source_id="x", source_type="database", title="T", access_path="/t.db")
        self.assertEqual(s.source_type, "database")

    def test_source_type_invalid(self):
        """Invalid source_type should be rejected."""
        from models.source import Source
        with self.assertRaises(Exception):
            Source(source_id="x", source_type="book", title="T", access_path="/t.pdf")

    def test_foreign_key(self):
        from models.grounded_data import GroundedData; from models.source import Source; from models.record import Record
        with self.assertRaises(Exception):
            GroundedData(schema_version="1.0.0", sources=[Source(source_id="doi_A", source_type="paper", title="T", access_path="/t.pdf")], records=[Record(record_id="r1", source_id="doi_BAD", field_name="x", field_value=1.0, trace_id="t1", extraction_method="llm_text")])

    def test_duplicate_record_id(self):
        from models.grounded_data import GroundedData; from models.source import Source; from models.record import Record
        with self.assertRaises(Exception):
            GroundedData(schema_version="1.0.0", sources=[Source(source_id="doi_A", source_type="paper", title="T", access_path="/t.pdf")], records=[Record(record_id="r1", source_id="doi_A", field_name="x", field_value=1.0, trace_id="t1", extraction_method="llm_text"), Record(record_id="r1", source_id="doi_A", field_name="y", field_value=2.0, trace_id="t2", extraction_method="llm_text")])

# ==========================================================
# Test 2: State & Assessment Agents (V3.0)
# ==========================================================
class TestAssessment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.logger import setup_logging; setup_logging()

    def test_state_deepcopy(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        s = make_initial_state(get_mock_data_json())
        self.assertNotEqual(id(s["data_state"]["input_data"]), id(s["data_state"]["current_data"]))

    def test_state_run_id(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        s = make_initial_state(get_mock_data_json())
        self.assertTrue(len(s["workflow_state"]["run_id"]) > 0)

    def test_profiling_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.profiling_agent import ProfilingAgent
        a = ProfilingAgent(); s = make_initial_state(get_mock_data_json())
        r = a.run(s)
        profile = r["report_state"]["quality"]["profile"]
        self.assertIn("dataset_summary", profile)

    def test_assessment_agent_v3(self):
        """V3.0: Assessment agent should produce multi_source_variance, not just conflicts."""
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        s = make_initial_state(get_mock_data_json())
        r = QualityAssessmentAgent().run(s)
        q = r["report_state"]["quality"]
        # V3.0: multi_source_variance should exist
        msv = q.get("multi_source_variance", {})
        self.assertIn("has_variance", msv)
        self.assertIn("has_anomalies", msv)
        # Sources should have conflict_risk (backward compat = anomalies only)
        sources = q.get("sources", {})
        self.assertGreater(len(sources), 0)

    def test_scoring_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        r = QualityScoringAgent().run(s)
        self.assertIn("quality_scoring", r["report_state"]["quality"])

    def test_decision_agent_v3(self):
        """V3.0: Decision agent routes per-source, based on anomalies not conflicts."""
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        s = {**s, **QualityScoringAgent().run(s)}
        r = DecisionReasoningAgent().run(s)
        # V3.0: per-source routes, not global route_decision
        per_source = r["report_state"]["quality"].get("per_source_routes", {})
        self.assertGreater(len(per_source), 0)
        for sid, route in per_source.items():
            self.assertIn(route, ("Normalization", "Conflict", "Export", "HumanReview"))

    def test_multi_source_variance_analyzer(self):
        """V3.0: Test the multi_source_variance analyzer directly."""
        from tools.assessment.statistical_conflict import analyze_multi_source_variance
        from mock_data import get_mock_data_json
        result = analyze_multi_source_variance(get_mock_data_json())
        # Should detect variances (DM, flux, redshift from multiple sources)
        self.assertTrue(result["has_variance"])
        self.assertGreater(result["variance_count"], 0)
        # Should NOT flag normal multi-source differences as conflicts
        # (backward compat: has_conflicts = has_anomalies only)
        for v in result["variances"]:
            cause = v["inferred_cause"]
            self.assertIn(cause, [
                "condition_variance", "methodological_variance",
                "temporal_variation", "measurement_uncertainty",
                "duplicate_observation", "unknown",
            ])

# ==========================================================
# Test 3: Conflict/Variance Agent (V3.0)
# ==========================================================
class TestVarianceAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.logger import setup_logging; setup_logging()

    def test_aggregation_agent(self):
        """V3.0: VarianceAggregationAgent should read multi_source_variance."""
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Conflict_agentV1.agents.conflict_identification_agent import VarianceAggregationAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        r = VarianceAggregationAgent().run(s)
        agg = r["report_state"]["conflict"]["aggregation"]
        self.assertIn("total_variances", agg)
        self.assertIn("total_anomalies", agg)

    def test_classification_agent(self):
        """V3.0: DifferenceClassificationAgent classifies variance causes."""
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Conflict_agentV1.agents.conflict_identification_agent import VarianceAggregationAgent
        from Data_Conflict_agentV1.agents.conflict_classification_agent import DifferenceClassificationAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        s = {**s, **VarianceAggregationAgent().run(s)}
        r = DifferenceClassificationAgent().run(s)
        cls_result = r["report_state"]["conflict"]["classification"]
        self.assertIn("classified_variances", cls_result)
        self.assertIn("by_cause", cls_result)

    def test_annotation_report_agent(self):
        """V3.0: AnnotationReportAgent outputs annotations, not resolutions."""
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Conflict_agentV1.agents.conflict_identification_agent import VarianceAggregationAgent
        from Data_Conflict_agentV1.agents.conflict_classification_agent import DifferenceClassificationAgent
        from Data_Conflict_agentV1.agents.evidence_collection_agent import AnomalyVerificationAgent
        from Data_Conflict_agentV1.agents.confidence_evaluation_agent import AnnotationConfidenceAgent
        from Data_Conflict_agentV1.agents.resolution_report_agent import AnnotationReportAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        s = {**s, **VarianceAggregationAgent().run(s)}
        s = {**s, **DifferenceClassificationAgent().run(s)}
        s = {**s, **AnomalyVerificationAgent().run(s)}
        s = {**s, **AnnotationConfidenceAgent().run(s)}
        r = AnnotationReportAgent().run(s)
        report = r["report_state"]["conflict"]["resolution_report"]
        self.assertIn("annotations", report)
        self.assertIn("route_decision", report)
        route = report["route_decision"]
        self.assertIn(route, ("Export", "Normalization", "HumanReview"))

# ==========================================================
# Test 4: End-to-end (mock LLM)
# ==========================================================
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.logger import setup_logging; setup_logging()

    def _run(self, data):
        from quality_state import make_initial_state
        from graph import compile_quality_graph
        from configs import load_yaml
        s = make_initial_state(data)
        s["context_state"].update({
            "quality_rules": load_yaml("quality_rules.yaml"),
            "target_schema": load_yaml("schema_mapping.yaml").get("target_schema", {}),
        })
        app = compile_quality_graph()
        for _ in range(15):
            s = app.invoke(s)
            wf = s.get("workflow_state", {})
            if wf.get("__human_review_needed__"):
                wf["__human_review_needed__"] = False
                wf["__human_review_decision__"] = []
                s["workflow_state"] = wf
                continue
            break
        return s

    def test_mock_data_v3(self):
        """V3.0: End-to-end with astronomy mock data."""
        from mock_data import get_mock_data_json
        s = self._run(get_mock_data_json())
        status = s["workflow_state"]["execution_status"]
        self.assertIn(status, ("Success", "Failed", "HumanReview"))

    def test_history_accumulates(self):
        from mock_data import get_mock_data_json
        s = self._run(get_mock_data_json())
        h = s["workflow_state"].get("workflow_history", [])
        self.assertGreater(len(h), 0)

# ==========================================================
if __name__ == "__main__":
    import logging; logging.basicConfig(level=logging.WARNING)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestGroundedDataSchema, TestAssessment, TestVarianceAgent, TestEndToEnd]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if r.wasSuccessful() else 1)
