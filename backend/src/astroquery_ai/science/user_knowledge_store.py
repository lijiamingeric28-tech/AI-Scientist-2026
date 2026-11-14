"""
user_knowledge_store.py — Unified incremental and user-preference knowledge base system in AstroQuery.

Aggregates:
1. 294 YAML theories/laws from `resources/insight_knowledge/astrophysics/*.yaml`
2. 149 concepts from `resources/insight_kb/content/concepts.json`
3. 100 type profiles from `resources/insight_kb/content/type-profiles.json`
4. 166 research entries from `resources/insight_kb/content/entries.json`
5. 333 author entries from `resources/insight_kb/dot-author-20261030/output/entries.jsonl`
6. User dynamic overlay in `runtime-data/user_knowledge.json` (supports CRUD, fork-override,
   delete, restore, and user preferences: preferred, neutral, deprioritized, weight_boost).

Generates graph topology `{ nodes, edges, categories }` linking properties, laws, models,
and concepts with LaTeX formulas.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.paths import data_root, resource_root
from .knowledge_workbench import KnowledgeWorkbenchMixin, overlay_lock

logger = logging.getLogger("astroquery_ai.user_knowledge_store")

# Category definitions aligned with frontend and astrophysics taxonomy
KNOWLEDGE_CATEGORIES = [
    {"id": "physical_laws", "label": "物理定律", "color": "#3b82f6", "alt_names": ["物理定律", "physical_law", "physical_laws", "law", "physics"]},
    {"id": "equations_of_state_and_models", "label": "状态方程与模型", "color": "#8b5cf6", "alt_names": ["状态方程与模型", "equations_of_state_and_models", "equation_of_state", "model", "astrophysical_models", "galactic_model", "cosmological_model", "empirical_relation", "cosmological_relation"]},
    {"id": "measurement_and_extinction", "label": "测量与消光", "color": "#f59e0b", "alt_names": ["测量与消光", "measurement_and_extinction", "extinction", "measurement", "reddening", "measurement_principle"]},
    {"id": "observational_methodology", "label": "观测方法学", "color": "#10b981", "alt_names": ["观测方法学", "observational_methodology", "methodology", "observation_method", "telescope", "astrometry", "method_comparison", "best_practice", "measurement_method", "author_entry"]},
    {"id": "reference_limits", "label": "参考界限", "color": "#f43f5e", "alt_names": ["参考界限", "reference_limits", "limit", "boundary", "criterion", "reference_range", "usage_limitation"]},
    {"id": "concepts_and_catalogs", "label": "概念星表", "color": "#06b6d4", "alt_names": ["概念星表", "concepts_and_catalogs", "concept", "catalog", "concepts", "catalogs", "profile", "type_profile"]},
    {"id": "user_private", "label": "用户私有", "color": "#eab308", "alt_names": ["用户私有", "user_private", "user", "custom", "private"]},
]

_CATEGORY_MAP: dict[str, str] = {}
for _cat in KNOWLEDGE_CATEGORIES:
    _cid = _cat["id"]
    _CATEGORY_MAP[_cid.lower()] = _cid
    for _alt in _cat.get("alt_names", []):
        _CATEGORY_MAP[_alt.lower()] = _cid


# Common aliases mapping frontend IDs and classical names to backend entry IDs
COMMON_ALIASES: dict[str, str] = {
    "stefan_boltzmann_law": "law.stefan_boltzmann",
    "stefan_boltzmann": "law.stefan_boltzmann",
    "eddington_luminosity_limit": "eddington_limit",
    "eddington_luminosity": "eddington_limit",
    "chandrasekhar_mass_limit": "chandrasekhar_limit",
    "chandrasekhar_mass": "chandrasekhar_limit",
    "wien_displacement_law": "rayleigh_jeans_wien",
    "wien_law": "rayleigh_jeans_wien",
    "gaia_astrometric_parallax": "gaia_dr3_astrophysical_params",
    "gaia_parallax": "gaia_dr3_astrophysical_params",
    "cardelli_ccm89_extinction": "interstellar_extinction_av",
    "ccm89_extinction": "interstellar_extinction_av",
    "lane_emden_equation": "stellar_structure_equations",
    "simbad_ned_concept_catalog": "type.star",
}


def normalize_category(cat: Optional[str]) -> str:
    if not cat:
        return "physical_laws"
    c_clean = str(cat).strip()
    c_lower = c_clean.lower()
    if c_lower in _CATEGORY_MAP:
        return _CATEGORY_MAP[c_lower]
    # 保留用户自由定义的分类名称（清洗换行和制表符）
    import re
    safe_cat = re.sub(r'[\r\n\t]+', ' ', c_clean).strip()
    return safe_cat or "user_custom"


CONFIDENCE_LABELS = {
    "established": "学界公认",
    "consensus": "广泛共识",
    "empirical": "经验模型",
    "provisional": "前沿假说",
}


def _clean_formula(s: str) -> str:
    import re
    s = s.strip().lstrip("→").strip()
    chinese_match = re.search(r'[\u4e00-\u9fa5]', s)
    if chinese_match:
        idx = chinese_match.start()
        left = s[:idx].strip()
        if len(left) >= 4 and any(sym in left for sym in ["=", "∝", "≈", "~"]):
            return left
    return s


def _extract_formula(entry: dict[str, Any]) -> str:
    explicit = entry.get("formula")
    if explicit and isinstance(explicit, str) and explicit.strip():
        return _clean_formula(explicit)
    content = entry.get("content") or entry.get("description") or ""
    import re
    for line in str(content).split("\n"):
        line_clean = line.strip().replace("`", "")
        if ":" in line_clean:
            left_part = line_clean.split(":", 1)[0].strip()
            if any(sym in left_part for sym in ["=", r"\propto", "∝", r"\approx", "≈"]):
                chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', left_part))
                if chinese_chars <= 6:
                    return _clean_formula(left_part)
        if any(sym in line_clean for sym in ["=", r"\propto", "∝", r"\approx", "≈"]):
            if not line_clean.startswith("#") and not line_clean.startswith("-") and not line_clean.startswith("•"):
                chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', line_clean))
                if chinese_chars <= 6 and len(line_clean) < 100:
                    return _clean_formula(line_clean)
    return ""


# Standard property connector nodes for the global knowledge graph
CONNECTOR_PROPERTIES = [
    {"id": "prop_luminosity", "label": "光度 (Luminosity)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Luminosity", "光度", "luminosity"]},
    {"id": "prop_teff", "label": "有效温度 (Teff)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Effective Temperature", "有效温度", "temperature", "teff", "温度"]},
    {"id": "prop_mass", "label": "天体质量 (Mass)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Mass", "质量", "stellar_mass", "pl_mass", "mass"]},
    {"id": "prop_radius", "label": "天体半径 (Radius)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Radius", "半径", "stellar_radius", "pl_radius", "radius"]},
    {"id": "prop_distance", "label": "天体距离 (Distance)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Distance", "距离", "distance_modulus", "distance"]},
    {"id": "prop_extinction", "label": "星际消光 (Extinction)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Extinction", "消光", "a_v", "av", "extinction"]},
    {"id": "prop_reddening", "label": "色余红化 (Reddening)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Color Excess", "色余", "红化", "e(b-v)", "reddening"]},
    {"id": "prop_parallax", "label": "天体测量视差 (Parallax)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Parallax", "视差", "plx", "parallax"]},
    {"id": "prop_period", "label": "轨道周期 (Period)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Orbital Period", "周期", "orbital_period", "period"]},
    {"id": "prop_metallicity", "label": "金属丰度 (Metallicity)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Metallicity", "金属丰度", "fe/h", "metallicity"]},
    {"id": "prop_surface_gravity", "label": "表面重力 (Surface Gravity)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Surface Gravity", "表面重力", "logg", "surface_gravity"]},
    {"id": "prop_density", "label": "物质密度 (Density)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Density", "密度", "density", "central_density"]},
    {"id": "prop_dispersion", "label": "色散量 (Dispersion Measure)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Dispersion Measure", "色散量", "dm", "dispersion_measure"]},
    {"id": "prop_radial_velocity", "label": "视向速度 (Radial Velocity)", "category": "concepts_and_catalogs", "is_property": True, "preferred": False, "properties": ["Radial Velocity", "视向速度", "rv", "radial_velocity"]},
]


class UserKnowledgeStore(KnowledgeWorkbenchMixin):
    """
    Unified knowledge store aggregating base astrophysics knowledge and user dynamic overlays.
    """

    _instance: Optional[UserKnowledgeStore] = None

    def __init__(self, resource_dir: Optional[Path] = None, data_dir: Optional[Path] = None):
        self.resource_dir = Path(resource_dir or resource_root())
        self.data_dir = Path(data_dir or data_root())
        self.overlay_file = self.data_dir / "user_knowledge.json"
        self._lock = overlay_lock(self.overlay_file)
        self._overlay_signature = None
        self.revision = 0
        self.entry_revisions: dict[str, int] = {}
        self.cleared_preferences: set[str] = set()

        # Raw collections
        self.yaml_entries: list[dict[str, Any]] = []
        self.concept_entries: list[dict[str, Any]] = []
        self.type_profile_entries: list[dict[str, Any]] = []
        self.research_entries: list[dict[str, Any]] = []
        self.author_entries: list[dict[str, Any]] = []

        # Combined base storage
        self.base_entries: list[dict[str, Any]] = []
        self.base_entries_by_id: dict[str, dict[str, Any]] = {}

        # User dynamic overlay
        self.user_entries: dict[str, dict[str, Any]] = {}
        self.user_overrides: dict[str, dict[str, Any]] = {}
        self.preferences: dict[str, dict[str, Any]] = {}
        self.deleted_ids: set[str] = set()

        self._load_base_knowledge()
        self.property_labels: dict[str, dict[str, str]] = {}
        for concept in self.concept_entries:
            label = {'label': concept['title'], 'label_provenance': 'concept:' + concept['id']}
            for key in (concept['id'], *concept.get('properties', [])):
                self.property_labels[str(key).casefold()] = label
        with self._lock:
            self._load_user_overlay()

    @classmethod
    def get_instance(cls) -> UserKnowledgeStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ── 1. Load Base Scientific Knowledge Corpus ─────────────────────────────
    def _load_base_knowledge(self) -> None:
        # 1. 294 YAML theories/laws
        yaml_dir = self.resource_dir / "insight_knowledge" / "astrophysics"
        if yaml_dir.is_dir():
            for yf in sorted(yaml_dir.glob("*.yaml")):
                try:
                    with open(yf, "r", encoding="utf-8") as fp:
                        data = yaml.safe_load(fp) or {}
                    for entry in data.get("entries", []):
                        eid = entry.get("id")
                        if not eid:
                            continue
                        applies = entry.get("applies_to") or {}
                        norm_cat = normalize_category(entry.get("category"))
                        conf = entry.get("confidence")
                        raw_cond = entry.get("assumptions") or entry.get("conditions") or []
                        if isinstance(raw_cond, str):
                            cond_list = [raw_cond]
                        elif isinstance(raw_cond, list):
                            cond_list = [c for c in raw_cond if isinstance(c, str) and c.strip()]
                        else:
                            cond_list = []
                        item = {
                            "id": eid,
                            "title": entry.get("title", eid),
                            "category": norm_cat,
                            "formula": _extract_formula(entry),
                            "description": entry.get("content", "").strip(),
                            "conditions": cond_list,
                            "confidence": conf,
                            "confidence_label": CONFIDENCE_LABELS.get(conf, conf or ""),
                            "parameters": entry.get("parameters", []),
                            "properties": applies.get("fields", []),
                            "entity_types": applies.get("entities", []),
                            "tags": entry.get("tags", []),
                            "sources": entry.get("source", "Standard Astrophysics"),
                            "origin": "yaml_theory",
                            "raw_category": entry.get("category", "physical_law"),
                            "is_user": False,
                            "is_override": False,
                            "is_deleted": False,
                            "preference": "neutral",
                            "preferred": False,
                            "weight_boost": 1.0,
                        }
                        self.yaml_entries.append(item)
                        self.base_entries.append(item)
                        self.base_entries_by_id[eid] = item
                except Exception as ex:
                    logger.debug("Failed reading YAML theory %s: %s", yf, ex)

        # 2. 149 concepts
        concepts_file = self.resource_dir / "insight_kb" / "content" / "concepts.json"
        if concepts_file.is_file():
            try:
                c_data = json.loads(concepts_file.read_text(encoding="utf-8"))
                for c in c_data:
                    cid = c.get("concept_id")
                    if not cid:
                        continue
                    item = {
                        "id": cid,
                        "title": c.get("label_zh", cid),
                        "category": "concepts_and_catalogs",
                        "formula": "",
                        "description": c.get("definition_zh", "").strip(),
                        "conditions": [c.get("binding_rule")] if c.get("binding_rule") else [],
                        "parameters": [],
                        "properties": [c.get("property_id")] if c.get("property_id") else [],
                        "entity_types": c.get("entry_ids", []),
                        "tags": [c.get("kind", "concept")],
                        "sources": f"AstroQuery Concept ({c.get('binding_status', '')})",
                        "origin": "concept",
                        "raw_category": "concept",
                        "is_user": False,
                        "is_override": False,
                        "is_deleted": False,
                        "preference": "neutral",
                        "preferred": False,
                        "weight_boost": 1.0,
                    }
                    self.concept_entries.append(item)
                    self.base_entries.append(item)
                    self.base_entries_by_id[cid] = item
            except Exception as ex:
                logger.debug("Failed reading concepts.json: %s", ex)

        # 3. 100 type profiles
        types_file = self.resource_dir / "insight_kb" / "content" / "type-profiles.json"
        if types_file.is_file():
            try:
                t_data = json.loads(types_file.read_text(encoding="utf-8"))
                for t in t_data:
                    tid = t.get("profile_id") or t.get("entry_id")
                    if not tid:
                        continue
                    desc_parts = [t.get("identity_zh", ""), t.get("property_interpretation_zh", ""), t.get("methods_and_limits_zh", "")]
                    item = {
                        "id": tid,
                        "title": f"{t.get('otype', '')} {t.get('title', '')}".strip() or tid,
                        "category": "concepts_and_catalogs",
                        "formula": "",
                        "description": "\n\n".join(p for p in desc_parts if p).strip(),
                        "conditions": [t.get("exclusions_zh")] if t.get("exclusions_zh") else [],
                        "parameters": [],
                        "properties": t.get("concept_ids", []),
                        "entity_types": [t.get("otype", ""), t.get("subject_class", "")],
                        "tags": ["type_profile", t.get("subject_class", "")],
                        "sources": t.get("authoring_basis", "author_knowledge"),
                        "origin": "type_profile",
                        "raw_category": "type_profile",
                        "is_user": False,
                        "is_override": False,
                        "is_deleted": False,
                        "preference": "neutral",
                        "preferred": False,
                        "weight_boost": 1.0,
                    }
                    self.type_profile_entries.append(item)
                    self.base_entries.append(item)
                    # Index with prefix and standard id
                    self.base_entries_by_id[f"type_profile:{tid}"] = item
                    if tid not in self.base_entries_by_id:
                        self.base_entries_by_id[tid] = item
            except Exception as ex:
                logger.debug("Failed reading type-profiles.json: %s", ex)

        # 4. 166 research entries
        entries_file = self.resource_dir / "insight_kb" / "content" / "entries.json"
        if entries_file.is_file():
            try:
                e_data = json.loads(entries_file.read_text(encoding="utf-8"))
                for e in e_data:
                    eid = e.get("entry_id")
                    if not eid:
                        continue
                    kind = e.get("kind", "observational_methodology")
                    norm_cat = normalize_category(kind)
                    claims_text = "\n\n".join(c.get("statement_zh", "") for c in e.get("claims", []))
                    if not claims_text:
                        claims_text = e.get("retrieval", {}).get("short_explanation_zh", "")
                    conditions = [c.get("description_zh", "") for c in e.get("conditions", [])] or ([e.get("conditions_zh")] if e.get("conditions_zh") else [])
                    item = {
                        "id": eid,
                        "title": e.get("title", eid),
                        "category": norm_cat,
                        "formula": e.get("formula") or "",
                        "description": claims_text.strip(),
                        "conditions": [c for c in conditions if c],
                        "parameters": [],
                        "properties": e.get("concept_ids", []),
                        "entity_types": e.get("otype_scope", []),
                        "tags": e.get("concept_ids", []) + [kind],
                        "sources": f"AstroQuery Curated Entry ({e.get('binding_status', '')})",
                        "origin": "research_entry",
                        "raw_category": kind,
                        "is_user": False,
                        "is_override": False,
                        "is_deleted": False,
                        "preference": "neutral",
                        "preferred": False,
                        "weight_boost": 1.0,
                    }
                    self.research_entries.append(item)
                    self.base_entries.append(item)
                    self.base_entries_by_id[f"research_entry:{eid}"] = item
                    if eid not in self.base_entries_by_id:
                        self.base_entries_by_id[eid] = item
            except Exception as ex:
                logger.debug("Failed reading entries.json: %s", ex)

        # 5. 333 author entries
        author_file = self.resource_dir / "insight_kb" / "dot-author-20261030" / "output" / "entries.jsonl"
        if author_file.is_file():
            try:
                with open(author_file, "r", encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        a = json.loads(line)
                        aid = a.get("entry_id")
                        if not aid:
                            continue
                        desc = "\n\n".join(b.get("text", "") for b in a.get("blocks", []))
                        item = {
                            "id": aid,
                            "title": a.get("title", aid),
                            "category": "observational_methodology",
                            "formula": "",
                            "description": desc.strip(),
                            "conditions": a.get("conditions", []),
                            "parameters": [],
                            "properties": a.get("property_topics", []),
                            "entity_types": a.get("otypes", []),
                            "tags": a.get("property_topics", []),
                            "sources": "Dot Author Reviewed 20261030",
                            "origin": "author_entry",
                            "raw_category": "author_entry",
                            "is_user": False,
                            "is_override": False,
                            "is_deleted": False,
                            "preference": "neutral",
                            "preferred": False,
                            "weight_boost": 1.0,
                        }
                        self.author_entries.append(item)
                        self.base_entries.append(item)
                        self.base_entries_by_id[f"author:{aid}"] = item
                        if aid not in self.base_entries_by_id:
                            self.base_entries_by_id[aid] = item
            except Exception as ex:
                logger.debug("Failed reading entries.jsonl: %s", ex)

    # ── 7. Transform to AstroQuery Standard Knowledge Block ───────────────────
    def to_knowledge_block(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Convert entry into an AstroQuery standard knowledge_block dict."""
        eid = entry.get("id", "unknown")
        bid = f"kb-{eid}"
        formula_str = entry.get("formula", "")

        conditions = list(entry.get("conditions") or [])
        if entry.get("properties"):
            conditions.append(f"适用物理性质: {', '.join(entry.get('properties', []))}")
        if entry.get("entity_types"):
            conditions.append(f"适用天体分类: {', '.join(entry.get('entity_types', []))}")

        return {
            "claim": {
                "claim_id": bid,
                "text": entry.get("description", "").strip(),
                "role": "theory_law",
                "formula": formula_str,
            },
            "entry_id": eid,
            "title": entry.get("title", eid),
            "category": entry.get("category", "physical_laws"),
            "category_label": entry.get("category_label", self._category_label(entry.get("category", "physical_laws"))),
            "conditions": conditions,
            "formula": formula_str,
            "authoring_basis": "user_overlay" if entry.get("is_user") else "standard_theory",
            "sources": [
                {
                    "source_id": f"src-{eid}",
                    "title": entry.get("sources", "Astrophysical Knowledge Base"),
                    "url": None,
                    "locator": "user_preferred" if entry.get("preferred") else "consensus",
                    "support_note": f"天体物理理论底座条目 {eid}",
                }
            ],
            "tags": entry.get("tags", []),
            "user_preferred": entry.get("preferred", False),
            "user_preference": entry.get("preference", "neutral"),
            "weight_boost": entry.get("weight_boost", 1.0),
            "is_user": entry.get("is_user", False),
            "parameters": entry.get("parameters", []),
            "properties": entry.get("properties", []),
        }
