"""
test_insights_graph.py — DataInsights 子图测试 (V3.4)

覆盖:
  1. Pydantic 模型校验
  2. 知识库加载 + 检索 (关键词匹配)
  3. 4 节点独立测试 (mock LLM)
  4. 子图集成 (build_insights_graph 走通)
  5. 无知识库回退 (纯 LLM 模式不崩溃)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import unittest
from unittest.mock import patch, MagicMock

import utils.llm as llm_mod

_orig_get_llm = llm_mod.get_llm


def _fake_llm(*args, **kwargs):
    m = MagicMock()
    m.content = '{"insights": [], "relationships": [], "overall_grade": "good", "suitable_use_cases": [], "limitations": [], "recommended_caveats": []}'
    return m


llm_mod.get_llm = _fake_llm

from quality_state import make_initial_state


def _mock_state():
    """构造含 paper + database 混合数据的 state (直接注入, 不跑 Assessment)。"""
    data = {
        "schema_version": "2.0.0",
        "research_domain": "astrophysics",
        "sources": [
            {"source_id": "P1", "source_type": "paper", "title": "FRB Paper",
             "abstract": "We observed FRB 121102 with FAST L-band."},
            {"source_id": "DB1", "source_type": "database", "title": "Gaia DR3",
             "description": "ESA Gaia astrometry catalog.",
             "research_content": "Parallax and photometry for 1.8B stars.",
             "research_methodology": "Space-based optical astrometry.",
             "waveband": "Optical G/BP/RP",
             "reference_paper": "Gaia Collaboration 2023",
             "vizier_table_id": "I/355/gaiadr3"},
        ],
        "records": [
            {"record_id": "P1_frb_dm", "source_id": "P1", "entity_type": "FRB",
             "entity_name": "FRB 121102", "field_name": "dispersion_measure",
             "field_value": "560", "field_unit": "cm^-3 pc",
             "extraction_method": "vlm_text", "extraction_confidence": 0.95,
             "context_snippet": "FAST L-band observation. DM=560 pc cm^-3.",
             "measurement_method": "radio interferometry",
             "condition_tags": ["L-band"], "trace_id": "t1",
             "provenance": {"page": 1, "bbox": [0, 0, 1, 1]}},
            {"record_id": "DB1_plx", "source_id": "DB1", "entity_type": "Star",
             "entity_name": "Gaia DR3 123", "field_name": "Plx",
             "field_value": "1.3421", "field_unit": "mas",
             "extraction_method": "database_query",
             "provenance": {"db_table": "I/355/gaiadr3", "key_column": "Source",
                            "key_value": "123", "raw_column": "Plx"}},
        ],
    }
    state = make_initial_state(data)
    state["context_state"].update({
        "research_domain": "astrophysics",
        "target_schema": {"fields": [{"name": "parallax", "aliases": ["Plx", "plx"],
                                      "standard_unit": "mas"}]},
    })
    # 注入 export 输出目录 (供 Synthesis 文件写入)
    state["output_state"]["output_dir"] = os.path.join(os.path.dirname(__file__), "..", "output", "test_insights")
    os.makedirs(state["output_state"]["output_dir"], exist_ok=True)
    return state


class TestInsightsModels(unittest.TestCase):
    def test_models(self):
        from models.insights import (DataInsightsReport, FieldInsight,
                                     CrossFieldRelationship, DataUsageRecommendation)
        report = DataInsightsReport(
            research_domain="astrophysics",
            generated_at="2026-08-01T00:00:00",
            field_insights=[FieldInsight(field_name="dispersion_measure",
                                         observation="2 records",
                                         interpretation="DM consistent with L-band")],
            cross_field_relationships=[CrossFieldRelationship(field_a="DM", field_b="z",
                                                              relationship_type="physical_law",
                                                              description="Macquart")],
            usage_recommendations=DataUsageRecommendation(overall_grade="good"),
            overall_narrative="Summary",
        )
        self.assertEqual(report.research_domain, "astrophysics")
        self.assertEqual(len(report.field_insights), 1)
        print("[OK] Pydantic models validate")


class TestKnowledgeStore(unittest.TestCase):
    def test_load_and_search(self):
        from tools.insight.knowledge_store import KnowledgeStore
        ks = KnowledgeStore("astrophysics")
        self.assertGreater(ks.entry_count, 0, "知识库应加载条目")
        hits = ks.search(field_names=["dispersion_measure"], entity_types=["FRB"])
        self.assertGreater(len(hits), 0, "DM/FRB 检索应有结果")
        ids = [h["id"] for h in hits]
        self.assertTrue(any("DM" in i or "dm" in i for i in ids), f"应命中 DM 相关: {ids}")
        print(f"[OK] KB: {ks.entry_count} entries, search hits={len(hits)}")

    def test_degrade_empty(self):
        from tools.insight.knowledge_store import KnowledgeStore
        ks = KnowledgeStore("nonexistent_domain")
        self.assertEqual(ks.entry_count, 0, "不存在领域 → 空 (可降级)")
        self.assertEqual(ks.search(field_names=["x"]), [], "空库检索 → []")
        print("[OK] KB degrade: empty domain returns []")


class TestEntityTypes(unittest.TestCase):
    """V4: Simbad 对象类型配置消费 (entity_types_astrophysics)。"""

    @classmethod
    def setUpClass(cls):
        from configs import set_research_domain
        set_research_domain("astrophysics")

    def test_config_loaded(self):
        from configs import load_domain_config
        et = load_domain_config("entity_types")
        self.assertEqual(len(et.get("types", {})), 153, "otypes.list 全量 153 类型")
        print(f"[OK] entity_types: {len(et['types'])} types, "
              f"{len(et.get('typical_ranges', {}))} typical_ranges")

    def test_unknown_inference(self):
        from tools.insight.entity_types import normalize_entity_type
        self.assertEqual(normalize_entity_type("Unknown", "distance"), "galaxy")
        self.assertEqual(normalize_entity_type("", "effective_temperature"), "star")
        # 非 Simbad 类型原样返回 (兼容)
        self.assertEqual(normalize_entity_type("FRB", ""), "frb")
        print("[OK] Unknown 推断: distance→galaxy, teff→star, FRB 原样")

    def test_catalog_inference(self):
        from tools.insight.entity_types import infer_entity_type
        self.assertEqual(infer_entity_type("radial_velocity", {"vizier_table_id": "III/135A/catalog"}), "star")
        self.assertEqual(infer_entity_type("J.K20e", {"vizier_table_id": "VII/233/xsc"}), "galaxy")
        print("[OK] 目录推断: HD→star, 2MASS→galaxy")

    def test_ancestors(self):
        from tools.insight.entity_types import entity_ancestors
        self.assertEqual(entity_ancestors("quasar"), ["quasar", "agn", "galaxy"])
        self.assertEqual(entity_ancestors("FRB"), ["frb"], "未知类型 → [自身]")
        print("[OK] 祖先链: quasar→[quasar,agn,galaxy]")

    def test_typical_range(self):
        from tools.insight.entity_types import get_typical_range
        r = get_typical_range("galaxy", "distance")
        self.assertIsNotNone(r)
        self.assertIn("pc", r)
        self.assertIsNone(get_typical_range("FRB", "dispersion_measure"), "无配置 → None")
        print(f"[OK] typical_range: galaxy/distance → {r}")

    def test_parent_matching(self):
        from tools.insight.knowledge_store import KnowledgeStore
        ks = KnowledgeStore("astrophysics")
        # seyfert_2_galaxy 无直接条目, 经祖先链 (agn/galaxy) 命中星系条目
        hits = ks.search(entity_types=["seyfert_2_galaxy"], top_k=5)
        ids = [h["id"] for h in hits]
        self.assertTrue(any("galactic" in i or "galaxy" in i or "sersic" in i for i in ids),
                        f"父类匹配应命中星系条目: {ids}")
        print(f"[OK] 父类匹配: seyfert_2_galaxy → {ids[:3]}")


class TestAgents(unittest.TestCase):
    def _run_agents(self, state):
        from Data_Insights_agentV1.agents.field_insight_agent import FieldInsightAgent
        from Data_Insights_agentV1.agents.relationship_agent import RelationshipAgent
        from Data_Insights_agentV1.agents.recommendation_agent import RecommendationAgent
        from Data_Insights_agentV1.agents.synthesis_agent import SynthesisAgent

        state = {**state, **FieldInsightAgent().run(state)}
        self.assertIn("field_insights", state["report_state"]["insights"])
        state = {**state, **RelationshipAgent().run(state)}
        state = {**state, **RecommendationAgent().run(state)}
        state = {**state, **SynthesisAgent().run(state)}
        return state

    def test_full_pipeline(self):
        state = _mock_state()
        state = self._run_agents(state)
        insights = state["output_state"]["insights"]
        self.assertIsNotNone(insights, "output_state.insights 应为报告")
        self.assertEqual(insights["research_domain"], "astrophysics")
        self.assertIn("overall_narrative", insights)
        # 混合数据: paper (DM) + database (Plx) 都应产生洞察
        field_names = [f["field_name"] for f in insights["field_insights"]]
        print(f"[OK] field insights: {field_names}")
        print(f"[OK] narrative: {insights['overall_narrative'][:60]}...")

    def test_database_field_insight(self):
        """DB 字段 (Plx) 应产生 source_type=database 的洞察。"""
        from Data_Insights_agentV1.agents.field_insight_agent import FieldInsightAgent
        state = _mock_state()
        r = FieldInsightAgent().run(state)
        insights = r["report_state"]["insights"]["field_insights"]
        db_insights = [i for i in insights if i["source_type"] == "database"]
        self.assertGreater(len(db_insights), 0, "DB 字段应有洞察")
        plx = [i for i in db_insights if i["field_name"] == "Plx"]
        self.assertGreater(len(plx), 0, "Plx 字段应有洞察")
        print(f"[OK] DB insight: {db_insights[0]['field_name']} src={db_insights[0]['source_type']}")


class TestSubGraph(unittest.TestCase):
    def test_build_and_invoke(self):
        from Data_Insights_agentV1.insights_graph import build_insights_graph
        graph = build_insights_graph()
        app = graph.compile()
        state = _mock_state()
        state = app.invoke(state, {"recursion_limit": 100})
        self.assertIsNotNone(state["output_state"]["insights"])
        print("[OK] SubGraph invoke completes, insights written")


if __name__ == "__main__":
    unittest.main()
