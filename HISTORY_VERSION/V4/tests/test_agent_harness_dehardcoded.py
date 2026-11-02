"""自动化回归测试：验证科研问答智能体 (Agent Harness) 全链路 100% 数据驱动与去硬编码特性。
测试覆盖：
1. 多天体泛化支持 (Betelgeuse, Arcturus, M45)
2. 真实观测数据提取与动态溯源标签解析
3. 杜绝硬编码特定数值与特设分支
"""

import asyncio
import pytest
from pathlib import Path

from astroquery_ai.agent_harness import (
    AgentController,
    AgentMemory,
    DomainTools,
    GroundingVerifier,
    load_task_bundle,
)

CATALOG_DB = "AstroQuery_AI/sample_pack/catalog.db"
EXPORTS_DIR = "AstroQuery_AI/sample_pack/exports"

BETELGEUSE_TASK_ID = "e2f0e2a2-61e9-4d40-b42d-1f5d655821ec"
ARCTURUS_TASK_ID = "ead8444c-0a68-466e-bc59-e02c0a400c14"
M45_TASK_ID = "4873c876-d3d4-483e-9bd7-d3c4ab8df197"


def test_bundle_loader_multi_target():
    """验证数据加载器对不同天体任务的通用装载能力与字段保全。"""
    # 1. 参宿四
    b_betel = load_task_bundle(BETELGEUSE_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
    assert b_betel.target_entity == "Betelgeuse"
    assert len(b_betel.records) > 0
    assert len(b_betel.sources) > 0

    # 2. 大角星
    b_arc = load_task_bundle(ARCTURUS_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
    assert b_arc.target_entity == "Arcturus"
    assert len(b_arc.records) > 0

    # 3. M45
    b_m45 = load_task_bundle(M45_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
    assert b_m45.target_entity == "M45"
    assert len(b_m45.records) > 0


def test_domain_tools_universal_search():
    """验证领域工具在非特设分支下根据属性泛化检索的能力。"""
    b_betel = load_task_bundle(BETELGEUSE_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
    tools = DomainTools(b_betel)

    # 检索有效温度相关记录
    res = tools.execute_tool("query_records", {"property_name": "teff", "limit": 5})
    assert "teff" in res.lower()
    assert "2007A&A" in res or "2009A&A" in res

    # 检索文献
    lit_res = tools.execute_tool("search_literature", {"query_terms": "Betelgeuse"})
    assert "Dupree" in lit_res or "A&A" in lit_res or "ApJ" in lit_res


def test_grounding_verifier_tag_extraction():
    """验证学术引用校验器对多模态与文献图表标签的精准反向提取与清洗。"""
    b_betel = load_task_bundle(BETELGEUSE_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
    verifier = GroundingVerifier(b_betel)

    sample_rec_id = b_betel.records[0].get("record_id")
    sample_src_id = b_betel.sources[0].get("source_id") or b_betel.sources[0].get("bibcode")

    text = f"根据测定 [REC:{sample_rec_id}] 与文献 [SOURCE:{sample_src_id}] 的结论分析。"
    clean_text, citations = verifier.verify_and_clean(text)
    assert len(citations) >= 1
    found_types = {c["type"] for c in citations}
    assert "record" in found_types or "source" in found_types


def test_controller_dehardcoded_synthesis():
    """验证控制器在纯离线兜底模式下，针对参宿四严格生成真实观测事实，绝不泄漏 M45 硬编码。"""
    async def _run():
        b_betel = load_task_bundle(BETELGEUSE_TASK_ID, db_path=CATALOG_DB, output_dir=EXPORTS_DIR)
        ctrl = AgentController(b_betel)

        events = []
        async for ev in ctrl.run_react_stream([], "参宿四的有效温度测定结果与主要文献？"):
            events.append(ev)

        done_ev = next(e for e in events if e.get("event") == "agent_done")
        content = done_ev["data"]["content"]
        citations = done_ev["data"]["citations"]

        # 严格断言：不能包含昴星团或特设硬编码数值
        assert "Pleiades" not in content
        assert "120.2" not in content
        assert "136.2" not in content
        assert "0.075" not in content

        # 肯定断言：必须包含真实观测事实与引用
        assert "Betelgeuse" in content
        assert len(citations) > 0

    asyncio.run(_run())
