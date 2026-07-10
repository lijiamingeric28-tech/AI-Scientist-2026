"""
test_pipeline.py — V1 Clean 测试套件

只测试保留模块: models, state, assessment agents, graph.
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import patch, MagicMock

def _fake_structured_llm(output_schema, **kw):
    from schemas import (AssessmentDecision, ConflictResolution,
        ConflictResolutionResult, NormalizationPlan, NormalizationValidation, ExportValidation)
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

    def test_schema_version_literal(self):
        from models.grounded_data import GroundedData
        with self.assertRaises(Exception): GroundedData.model_validate({"schema_version": "2.0.0", "sources": [], "records": []})

    def test_source_type_literal(self):
        from models.source import Source
        with self.assertRaises(Exception): Source(source_id="x", source_type="database", title="T", access_path="/t.pdf")

    def test_foreign_key(self):
        from models.grounded_data import GroundedData; from models.source import Source; from models.record import Record
        with self.assertRaises(Exception):
            GroundedData(schema_version="1.0.0", sources=[Source(source_id="doi_A", source_type="paper", title="T", access_path="/t.pdf")], records=[Record(record_id="r1", source_id="doi_BAD", field_name="x", field_value=1.0, trace_id="t1", extraction_method="llm_text")])

    def test_duplicate_record_id(self):
        from models.grounded_data import GroundedData; from models.source import Source; from models.record import Record
        with self.assertRaises(Exception):
            GroundedData(schema_version="1.0.0", sources=[Source(source_id="doi_A", source_type="paper", title="T", access_path="/t.pdf")], records=[Record(record_id="r1", source_id="doi_A", field_name="x", field_value=1.0, trace_id="t1", extraction_method="llm_text"), Record(record_id="r1", source_id="doi_A", field_name="y", field_value=2.0, trace_id="t2", extraction_method="llm_text")])

# ==========================================================
# Test 2: State & Assessment Agents
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
        self.assertEqual(s["workflow_state"]["graph_version"], "V1.0")

    def test_profiling_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.profiling_agent import ProfilingAgent
        a = ProfilingAgent(); s = make_initial_state(get_mock_data_json())
        r = a.run(s)
        profile = r["report_state"]["quality"]["profile"]
        self.assertIn("dataset_summary", profile)
        self.assertEqual(profile["dataset_summary"]["record_count"], 8)

    def test_assessment_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        s = make_initial_state(get_mock_data_json())
        r = QualityAssessmentAgent().run(s)
        q = r["report_state"]["quality"]
        self.assertIn("completeness", q); self.assertIn("consistency", q)

    def test_scoring_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        r = QualityScoringAgent().run(s)
        self.assertIn("quality_scoring", r["report_state"]["quality"])

    def test_decision_agent(self):
        from mock_data import get_mock_data_json; from quality_state import make_initial_state
        from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
        from Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
        from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
        s = make_initial_state(get_mock_data_json())
        s = {**s, **QualityAssessmentAgent().run(s)}
        s = {**s, **QualityScoringAgent().run(s)}
        r = DecisionReasoningAgent().run(s)
        self.assertIn(r["workflow_state"]["route_decision"], ("Normalization", "Conflict", "Export", "HumanReview"))

# ==========================================================
# Test 3: End-to-end (mock LLM)
# ==========================================================
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.logger import setup_logging; setup_logging()

    def _run(self, data):
        from quality_state import make_initial_state
        from pipeline.quality.graph import compile_quality_graph
        from configs import load_yaml
        s = make_initial_state(data)
        s["context_state"].update({"quality_rules": load_yaml("quality_rules.yaml"), "target_schema": load_yaml("schema_mapping.yaml").get("target_schema", {})})
        app = compile_quality_graph()
        for _ in range(15):
            s = app.invoke(s)
            wf = s.get("workflow_state", {})
            if wf.get("__human_review_needed__"):
                wf["__human_review_needed__"] = False; wf["__human_review_decision__"] = []
                s["workflow_state"] = wf; continue
            break
        return s

    def test_mock_data(self):
        from mock_data import get_mock_data_json
        s = self._run(get_mock_data_json())
        self.assertEqual(s["workflow_state"]["execution_status"], "Success")

    def test_generated_data(self):
        from generate_test_data import generate_test_data
        s = self._run(generate_test_data(10))
        self.assertIn(s["workflow_state"]["execution_status"], ("Success", "Failed"))

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
    for tc in [TestGroundedDataSchema, TestAssessment, TestEndToEnd]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if r.wasSuccessful() else 1)
