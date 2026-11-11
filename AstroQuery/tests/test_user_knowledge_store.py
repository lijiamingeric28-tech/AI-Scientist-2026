"""
test_user_knowledge_store.py — Complete test suite for unified knowledge store,
user overlays, graph topology, REST API routes, and agent/insight integrations.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from astroquery_ai.agent_harness.tools import DomainTools
from astroquery_ai.api.http import create_app
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore
from astroquery_ai.science.property_insights import final_report


@pytest.fixture
def clean_store(tmp_path):
    """Fixture providing an isolated UserKnowledgeStore with temporary user overlay storage."""
    UserKnowledgeStore.reset_instance()
    storage_dir = tmp_path / "runtime-data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    store = UserKnowledgeStore(data_dir=storage_dir)
    return store


# ==============================================================================
# 1. Test loading and indexing of all knowledge bases
# ==============================================================================

def test_loading_and_indexing_all_knowledge_bases(clean_store):
    """Verify loading and indexing of all 5 knowledge sources totaling 1042 base items:
    - 294 YAML theories/laws
    - 149 concepts
    - 100 type profiles
    - 166 condition entries
    - 333 author entries
    """
    store = clean_store

    assert len(store.yaml_entries) == 294, f"Expected 294 YAML theories, got {len(store.yaml_entries)}"
    assert len(store.concept_entries) == 149, f"Expected 149 concepts, got {len(store.concept_entries)}"
    assert len(store.type_profile_entries) == 100, f"Expected 100 type profiles, got {len(store.type_profile_entries)}"
    assert len(store.research_entries) == 166, f"Expected 166 condition entries, got {len(store.research_entries)}"
    assert len(store.author_entries) == 333, f"Expected 333 author entries, got {len(store.author_entries)}"

    total_base = (
        len(store.yaml_entries)
        + len(store.concept_entries)
        + len(store.type_profile_entries)
        + len(store.research_entries)
        + len(store.author_entries)
    )
    assert total_base == 1042
    assert len(store.base_entries) == 1042

    # Check key theories exist in index dictionary
    assert "law.stefan_boltzmann" in store.base_entries_by_id
    assert "eddington_limit" in store.base_entries_by_id

    # Check category distribution
    categories = {e.get("category") for e in store.base_entries}
    assert "physical_laws" in categories
    assert "equations_of_state_and_models" in categories
    assert "measurement_and_extinction" in categories
    assert "observational_methodology" in categories
    assert "reference_limits" in categories
    assert "concepts_and_catalogs" in categories

    # Check that entries can be looked up
    entry = store.get_entry("law.stefan_boltzmann")
    assert entry is not None
    assert entry["id"] == "law.stefan_boltzmann"
    assert entry["category"] == "physical_laws"


# ==============================================================================
# 2. Test CRUD operations for user knowledge items
# ==============================================================================

def test_crud_operations_for_user_knowledge_items(clean_store, tmp_path):
    """Verify complete CRUD lifecycle, JSON persistence in runtime-data/user_knowledge.json,
    and fork-overriding / default restoration.
    """
    store = clean_store
    overlay_path = store.overlay_file

    # --- CREATE ---
    item_payload = {
        "title": "Magnetar Crustal Cooling Model",
        "category": "equations_of_state_and_models",
        "formula": r"T_{\text{crust}}(t) \propto t^{-\alpha}",
        "description": "考虑磁热耦合演化的磁星壳层热演化冷却方程",
        "properties": ["Crust Temperature", "Magnetic Field"],
        "tags": ["magnetar", "crust", "cooling"],
        "preferred": True,
        "weight_boost": 2.5,
    }
    created = store.create_user_entry(item_payload)
    cid = created["id"]
    assert cid.startswith("user_")
    assert created["is_user"] is True
    assert created["preferred"] is True
    assert created["weight_boost"] == 2.5

    # Verify written to disk file
    assert overlay_path.exists()
    with open(overlay_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert cid in disk_data["user_entries"]

    # --- READ ---
    read_entry = store.get_entry(cid)
    assert read_entry is not None
    assert read_entry["title"] == "Magnetar Crustal Cooling Model"

    # --- UPDATE ---
    updated = store.update_entry(cid, {
        "description": "更新：修正了相对论中微子冷却因数",
        "weight_boost": 3.0,
    })
    assert updated["description"] == "更新：修正了相对论中微子冷却因数"
    assert updated["weight_boost"] == 3.0

    # Verify update persisted
    with open(overlay_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["user_entries"][cid]["description"] == "更新：修正了相对论中微子冷却因数"

    # --- FORK-OVERRIDE a base entry ---
    base_id = "law.stefan_boltzmann"
    forked = store.update_entry(base_id, {
        "title": "User Calibrated Stefan-Boltzmann Law",
        "description": "针对强引力场致密星表面的校正形式",
        "weight_boost": 2.8,
    })
    assert forked["is_override"] is True
    assert forked["is_user"] is True
    assert store.get_entry(base_id)["title"] == "User Calibrated Stefan-Boltzmann Law"

    # --- RESTORE DEFAULT ---
    restore_res = store.restore_default(base_id)
    assert restore_res["success"] is True
    restored = store.get_entry(base_id)
    assert restored["is_override"] is False
    assert restored["title"] != "User Calibrated Stefan-Boltzmann Law"

    # --- DELETE USER ENTRY ---
    del_res = store.delete_entry(cid)
    assert del_res["success"] is True
    assert store.get_entry(cid) is None

    # Verify removed from disk
    with open(overlay_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert cid not in disk_data["user_entries"]


# ==============================================================================
# 3. Test user preference weighting & priority boost
# ==============================================================================

def test_user_preference_weighting_and_priority_boost(clean_store):
    """Verify preference state transitions (preferred, neutral, deprioritized)
    and that preferred items receive boosted rank in search.
    """
    store = clean_store
    target_id = "eddington_limit"

    # Set preferred with weight_boost
    res = store.set_preference(target_id, preference="preferred", weight_boost=3.5)
    assert res["preference"] == "preferred"
    assert res["weight_boost"] == 3.5

    entry = store.get_entry(target_id)
    assert entry["preferred"] is True
    assert entry["weight_boost"] == 3.5

    # Preferred IDs set includes target
    pref_ids = store.get_preferred_ids()
    assert target_id in pref_ids

    # Search ranking boost check:
    # A preferred entry should rank top when searching relevant properties
    cands = store.search(keywords=["eddington", "luminosity", "limit"], top_k=5)
    assert len(cands) > 0
    assert cands[0]["id"] == target_id

    # Switch to deprioritized
    store.set_preference(target_id, preference="deprioritized", weight_boost=0.1)
    dep_entry = store.get_entry(target_id)
    assert dep_entry["preferred"] is False
    assert dep_entry["preference"] == "deprioritized"
    assert target_id not in store.get_preferred_ids()

    # Reset to neutral
    store.set_preference(target_id, preference="neutral", weight_boost=1.0)
    neu_entry = store.get_entry(target_id)
    assert neu_entry["preferred"] is False
    assert neu_entry["preference"] == "neutral"


# ==============================================================================
# 4. Test graph topology derivation (nodes, edges)
# ==============================================================================

def test_graph_topology_derivation(clean_store):
    """Verify graph topology { nodes, edges, categories } generation:
    - Nodes contain id, label, category, formula, preferred flag, etc.
    - Edges connect entries with properties and concepts.
    - All 7 defined categories are present.
    - Property connector nodes exist and bind correctly.
    """
    store = clean_store
    graph = store.get_graph()

    assert "nodes" in graph
    assert "edges" in graph
    assert "categories" in graph

    nodes = graph["nodes"]
    edges = graph["edges"]
    categories = graph["categories"]

    assert len(nodes) > 100
    assert len(edges) > 100
    assert len(categories) == 7

    cat_ids = {c["id"] for c in categories}
    expected_cats = {
        "physical_laws",
        "equations_of_state_and_models",
        "measurement_and_extinction",
        "observational_methodology",
        "reference_limits",
        "concepts_and_catalogs",
        "user_private",
    }
    assert expected_cats.issubset(cat_ids)

    # Check node structure
    sample_node = nodes[0]
    assert "id" in sample_node
    assert "label" in sample_node
    assert "category" in sample_node

    # Check property connector nodes
    prop_nodes = [n for n in nodes if n.get("is_property")]
    assert len(prop_nodes) >= 3
    prop_node_ids = {p["id"] for p in prop_nodes}
    assert "prop_luminosity" in prop_node_ids
    assert "prop_teff" in prop_node_ids
    assert "prop_mass" in prop_node_ids

    # Check edge connections
    edge_targets = {e["target"] for e in edges}
    edge_sources = {e["source"] for e in edges}
    assert any(pid in edge_targets or pid in edge_sources for pid in prop_node_ids)


# ==============================================================================
# 5. Test REST API endpoints
# ==============================================================================

def test_rest_api_endpoints(tmp_path):
    """Verify FastAPI knowledge routes:
    - GET /api/knowledge (listing, filtering, pagination)
    - GET /api/knowledge/graph (graph topology)
    - GET /api/knowledge/{entry_id} (retrieval with alias fallback)
    - POST /api/knowledge (create user entry)
    - PUT /api/knowledge/{entry_id} (update user entry)
    - POST /api/knowledge/{entry_id}/preference (set preference)
    - DELETE /api/knowledge/{entry_id} (delete / restore)
    """
    app = create_app(root=tmp_path / "app_data", start_worker=False)
    client = TestClient(app)

    # 1. GET /api/knowledge with limit & pagination
    res = client.get("/api/knowledge?limit=20&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data and "total" in data
    assert len(data["items"]) == 20
    assert data["total"] > 900

    # 2. GET /api/knowledge with category filter
    res_cat = client.get("/api/knowledge?category=physical_laws&limit=10")
    assert res_cat.status_code == 200
    cat_items = res_cat.json()["items"]
    assert all(item["category"] == "physical_laws" for item in cat_items)

    # 3. GET /api/knowledge with keyword filter
    res_kw = client.get("/api/knowledge?keyword=光度&limit=10")
    assert res_kw.status_code == 200
    assert len(res_kw.json()["items"]) > 0

    # 4. GET /api/knowledge/graph
    res_graph = client.get("/api/knowledge/graph")
    assert res_graph.status_code == 200
    g = res_graph.json()
    assert "nodes" in g and "edges" in g and "categories" in g
    assert len(g["nodes"]) > 0

    # 5. GET /api/knowledge/{entry_id} (canonical & alias)
    res_item = client.get("/api/knowledge/law.stefan_boltzmann")
    assert res_item.status_code == 200
    assert res_item.json()["id"] == "law.stefan_boltzmann"

    res_alias = client.get("/api/knowledge/stefan_boltzmann_law")
    assert res_alias.status_code == 200
    assert res_alias.json()["id"] == "law.stefan_boltzmann"

    # 6. POST /api/knowledge (create user entry)
    new_doc = {
        "title": "Quantum Degeneracy Limit in White Dwarfs",
        "category": "physical_laws",
        "formula": r"P = K_1 \rho^{5/3}",
        "description": "简并电子气体状态方程简析",
        "properties": ["Pressure", "Density"],
        "preferred": True,
        "weight_boost": 2.0,
    }
    res_create = client.post("/api/knowledge", json=new_doc)
    assert res_create.status_code == 200
    created_item = res_create.json()
    eid = created_item["id"]
    assert eid.startswith("user_")
    assert created_item["title"] == new_doc["title"]

    # 7. PUT /api/knowledge/{entry_id} (update)
    res_update = client.put(f"/api/knowledge/{eid}", json={"description": "更新简并压力公式说明"})
    assert res_update.status_code == 200
    assert res_update.json()["description"] == "更新简并压力公式说明"

    # 8. POST /api/knowledge/{entry_id}/preference
    res_pref = client.post(f"/api/knowledge/{eid}/preference", json={"preference": "preferred", "weight_boost": 3.0})
    assert res_pref.status_code == 200
    assert res_pref.json()["preference"] == "preferred"

    # 9. DELETE /api/knowledge/{entry_id}
    res_delete = client.delete(f"/api/knowledge/{eid}")
    assert res_delete.status_code == 200
    assert res_delete.json()["success"] is True

    # 10. Verify 404
    res_gone = client.get(f"/api/knowledge/{eid}")
    assert res_gone.status_code == 404


# ==============================================================================
# 6. Test insights & agent tools incorporate user-preferred knowledge
# ==============================================================================

def test_insights_and_agent_tools_incorporate_user_preferred_knowledge(clean_store):
    """Verify that:
    1. Agent tool `get_scientific_theory` retrieves user-preferred knowledge,
       tags it with `★ [科研优先理论 (User Preferred)]`, and displays the core formula.
    2. Property insights cross-field relationships and knowledge blocks give priority
       weighting and boost to user-preferred theories.
    """
    store = clean_store

    # Mark a theory as preferred
    pref_target = "radius_temp_luminosity"
    store.set_preference(pref_target, preference="preferred", weight_boost=3.0)

    # 1. Test DomainTools
    mock_bundle = MagicMock()
    mock_bundle.theories = []
    mock_bundle.theories_by_prop = {}
    mock_bundle.definitions_by_id = {}
    mock_bundle.resolve_property_id.return_value = "effective_temperature"
    mock_bundle.index_theory = MagicMock()

    tools = DomainTools(mock_bundle)
    theory_out = tools.execute_tool("get_scientific_theory", {"property_name": "温度"})
    assert "[THEORY:" in theory_out
    assert "★ [科研优先理论 (User Preferred)]" in theory_out
    assert "核心公式:" in theory_out or "物理机制阐释:" in theory_out

    # 2. Test property_insights integration
    delivery = {
        "delivery_id": "deliv-verify-01",
        "measurements": [],
        "snapshot_ref": "snap-01",
        "task_id": "task-01",
        "target": "Betelgeuse",
        "materials_ref": "mat-01",
    }
    spec = {"properties": []}
    knowledge_ref = {"knowledge_id": "kref-01"}
    units = [
        {"property_id": "effective_temperature", "unit_id": "u-teff", "claims": [], "measurements": []},
        {"property_id": "luminosity", "unit_id": "u-lum", "claims": [], "measurements": []},
    ]
    checkpoints = {}

    report = final_report(delivery, spec, knowledge_ref, units, checkpoints)
    k_blocks = report.get("knowledge_blocks", [])
    assert len(k_blocks) > 0
    # User preferred block should be present and flagged
    preferred_blocks = [b for b in k_blocks if b.get("user_preferred") or b.get("preferred")]
    assert len(preferred_blocks) > 0
    assert preferred_blocks[0].get("weight_boost", 1.0) >= 2.0
