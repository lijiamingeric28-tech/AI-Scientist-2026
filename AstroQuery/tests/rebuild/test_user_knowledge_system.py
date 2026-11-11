"""
test_user_knowledge_system.py — Comprehensive tests for UserKnowledgeStore, Knowledge API routes,
and integration with Property Insights and Agent Harness tools.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.agent_harness.tools import DomainTools
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore


@pytest.fixture
def store(tmp_path):
    UserKnowledgeStore.reset_instance()
    instance = UserKnowledgeStore(data_dir=tmp_path / "runtime-data")
    return instance


def test_base_knowledge_aggregation_counts(store):
    """Verify exact counts of aggregated base knowledge sources."""
    assert len(store.yaml_entries) == 294, f"Expected 294 YAML entries, got {len(store.yaml_entries)}"
    assert len(store.concept_entries) == 149, f"Expected 149 concepts, got {len(store.concept_entries)}"
    assert len(store.type_profile_entries) == 100, f"Expected 100 type profiles, got {len(store.type_profile_entries)}"
    assert len(store.research_entries) == 166, f"Expected 166 research entries, got {len(store.research_entries)}"
    assert len(store.author_entries) == 333, f"Expected 333 author entries, got {len(store.author_entries)}"
    assert len(store.base_entries) == 1042, f"Expected 1042 total base entries, got {len(store.base_entries)}"


def test_user_dynamic_overlay_crud_and_fork(store):
    """Verify user overlay CRUD, fork-override, delete, restore, and preferences."""
    # 1. Create user entry
    user_item = {
        "title": "Custom Relativistic Jet Precession Model",
        "category": "user_private",
        "formula": r"\Omega_{\text{prec}} = \frac{2 G J}{c^2 r^3}",
        "description": "Lense-Thirring 效应引起的喷流进动模型",
        "properties": ["Jet Precession", "Black Hole Spin"],
        "tags": ["AGN", "Jet", "Lense-Thirring"],
        "preferred": True,
        "weight_boost": 2.5,
    }
    created = store.create_user_entry(user_item)
    cid = created["id"]
    assert cid.startswith("user_")
    assert created["is_user"] is True
    assert created["preferred"] is True
    assert created["weight_boost"] == 2.5

    # 2. Retrieve entry
    retrieved = store.get_entry(cid)
    assert retrieved is not None
    assert retrieved["title"] == user_item["title"]
    assert retrieved["preferred"] is True

    # 3. Update user entry
    updated = store.update_entry(cid, {"description": "更新后的进动模型释义", "weight_boost": 3.0})
    assert updated["description"] == "更新后的进动模型释义"
    assert updated["weight_boost"] == 3.0

    # 4. Fork-override a base entry
    base_eid = "law.stefan_boltzmann"
    base_entry = store.get_entry(base_eid)
    assert base_entry is not None
    assert base_entry["is_override"] is False

    forked = store.update_entry(base_eid, {
        "title": "Modified Stefan-Boltzmann Law (Forked)",
        "description": "考虑非理想灰体因子修正的光度计算",
        "weight_boost": 2.2,
    })
    assert forked["is_override"] is True
    assert forked["is_user"] is True
    assert forked["title"] == "Modified Stefan-Boltzmann Law (Forked)"

    # Verify fork is active
    active = store.get_entry(base_eid)
    assert active["title"] == "Modified Stefan-Boltzmann Law (Forked)"

    # 5. Restore default
    restored = store.restore_default(base_eid)
    assert restored["success"] is True
    assert restored["entry"]["is_override"] is False
    assert restored["entry"]["title"] != "Modified Stefan-Boltzmann Law (Forked)"

    # 6. Preference toggle
    pref_res = store.set_preference("eddington_limit", "preferred", 2.0)
    assert pref_res["preference"] == "preferred"
    edd_entry = store.get_entry("eddington_limit")
    assert edd_entry["preferred"] is True

    pref_res2 = store.set_preference("eddington_limit", "deprioritized", 0.1)
    assert pref_res2["preference"] == "deprioritized"
    edd_entry2 = store.get_entry("eddington_limit")
    assert edd_entry2["preference"] == "deprioritized"
    assert edd_entry2["preferred"] is False

    # 7. Delete user entry
    del_res = store.delete_entry(cid)
    assert del_res["success"] is True
    assert store.get_entry(cid) is None


def test_graph_topology_generation(store):
    """Verify graph topology { nodes, edges, categories } generation."""
    graph = store.get_graph()
    assert "nodes" in graph
    assert "edges" in graph
    assert "categories" in graph
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0
    assert len(graph["categories"]) == 7

    # Check property connector nodes
    prop_nodes = [n for n in graph["nodes"] if n.get("is_property")]
    assert len(prop_nodes) > 0
    prop_ids = {n["id"] for n in prop_nodes}
    assert "prop_luminosity" in prop_ids
    assert "prop_teff" in prop_ids

    # Check edges link to property nodes
    edges = graph["edges"]
    assert any(e["target"] in prop_ids or e["source"] in prop_ids for e in edges)


def test_api_routes(tmp_path):
    """Verify all FastAPI routes under /api/knowledge."""
    app = create_app(root=tmp_path / "app_data", start_worker=False)
    client = TestClient(app)

    # GET /api/knowledge
    res = client.get("/api/knowledge?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data and "total" in data
    assert len(data["items"]) == 10
    assert data["total"] > 900

    # GET /api/knowledge with filters
    res_pref = client.get("/api/knowledge?preferred_only=true")
    assert res_pref.status_code == 200
    assert all(item.get("preferred") or item.get("preference") == "preferred" for item in res_pref.json()["items"])

    res_kw = client.get("/api/knowledge?keyword=辐射")
    assert res_kw.status_code == 200
    assert len(res_kw.json()["items"]) > 0

    # GET /api/knowledge/graph
    res_graph = client.get("/api/knowledge/graph")
    assert res_graph.status_code == 200
    g = res_graph.json()
    assert "nodes" in g and "edges" in g and "categories" in g

    # GET /api/knowledge/{entry_id}
    res_item = client.get("/api/knowledge/law.stefan_boltzmann")
    assert res_item.status_code == 200
    assert "id" in res_item.json()

    # Alias lookup
    res_alias = client.get("/api/knowledge/stefan_boltzmann_law")
    assert res_alias.status_code == 200

    # POST /api/knowledge (create)
    new_doc = {
        "title": "API Test Theory",
        "category": "physical_laws",
        "formula": "F = G M m / r^2",
        "description": "万有引力定律测试条目",
        "preferred": True,
    }
    res_post = client.post("/api/knowledge", json=new_doc)
    assert res_post.status_code == 200
    posted = res_post.json()
    created_id = posted["id"]

    # PUT /api/knowledge/{entry_id} (update)
    res_put = client.put(f"/api/knowledge/{created_id}", json={"description": "更新万有引力描述"})
    assert res_put.status_code == 200
    assert res_put.json()["description"] == "更新万有引力描述"

    # POST preference
    res_pref_toggle = client.post(f"/api/knowledge/{created_id}/preference", json={"preference": "deprioritized", "weight_boost": 0.3})
    assert res_pref_toggle.status_code == 200
    assert res_pref_toggle.json()["preference"] == "deprioritized"

    # DELETE /api/knowledge/{entry_id}
    res_del = client.delete(f"/api/knowledge/{created_id}")
    assert res_del.status_code == 200

    # Verify 404 after deletion
    res_404 = client.get(f"/api/knowledge/{created_id}")
    assert res_404.status_code == 404


def test_agent_harness_integration():
    """Verify agent harness get_scientific_theory marks and prioritizes user preferred theories."""
    store = UserKnowledgeStore.get_instance()
    store.set_preference("radius_temp_luminosity", "preferred", 3.0)

    bundle = MagicMock()
    bundle.theories = []
    bundle.theories_by_prop = {}
    bundle.definitions_by_id = {}
    bundle.resolve_property_id.return_value = "effective_temperature"
    bundle.index_theory = MagicMock()

    tools = DomainTools(bundle)
    ans = tools.execute_tool("get_scientific_theory", {"property_name": "温度"})
    assert "★ [科研优先理论 (User Preferred)]" in ans
    assert "[THEORY:" in ans
    assert "核心公式:" in ans or "物理机制阐释:" in ans
