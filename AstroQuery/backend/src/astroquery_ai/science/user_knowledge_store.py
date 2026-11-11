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


def _extract_formula(entry: dict[str, Any]) -> str:
    explicit = entry.get("formula")
    if explicit and isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    content = entry.get("content") or entry.get("description") or ""
    for line in str(content).split("\n"):
        line_clean = line.strip()
        if any(sym in line_clean for sym in ["=", r"\propto", "∝", r"\approx", "≈", r"\sim", "~"]):
            if len(line_clean) < 140 and not line_clean.startswith("#") and not line_clean.startswith("-"):
                res = line_clean.replace("`", "")
                if ":" in res and "=" in res:
                    res = res.split(":", 1)[1].strip()
                return res
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


class UserKnowledgeStore:
    """
    Unified knowledge store aggregating base astrophysics knowledge and user dynamic overlays.
    """

    _instance: Optional[UserKnowledgeStore] = None

    def __init__(self, resource_dir: Optional[Path] = None, data_dir: Optional[Path] = None):
        self.resource_dir = Path(resource_dir or resource_root())
        self.data_dir = Path(data_dir or data_root())
        self.overlay_file = self.data_dir / "user_knowledge.json"

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
                        item = {
                            "id": eid,
                            "title": entry.get("title", eid),
                            "category": norm_cat,
                            "formula": _extract_formula(entry),
                            "description": entry.get("content", "").strip(),
                            "conditions": [entry.get("confidence")] if entry.get("confidence") else [],
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

    # ── 2. Load & Save User Dynamic Overlay ───────────────────────────────────
    def _load_user_overlay(self) -> None:
        # Default seed preferences for benchmark theories
        seed_prefs = {
            "stefan_boltzmann_law": {"preference": "preferred", "weight_boost": 2.0},
            "eddington_luminosity_limit": {"preference": "preferred", "weight_boost": 2.0},
            "chandrasekhar_mass_limit": {"preference": "preferred", "weight_boost": 2.0},
            "gaia_astrometric_parallax": {"preference": "preferred", "weight_boost": 1.8},
        }

        if not self.overlay_file.is_file():
            self.preferences = seed_prefs
            return

        try:
            raw = json.loads(self.overlay_file.read_text(encoding="utf-8"))
            self.user_entries = raw.get("user_entries", {})
            self.user_overrides = raw.get("overrides", {})
            self.preferences = {**seed_prefs, **raw.get("preferences", {})}
            self.deleted_ids = set(raw.get("deleted_ids", []))
        except Exception as ex:
            logger.warning("Could not read user_knowledge.json: %s", ex)
            self.preferences = seed_prefs

    def _save_user_overlay(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "user_entries": self.user_entries,
            "overrides": self.user_overrides,
            "preferences": self.preferences,
            "deleted_ids": sorted(self.deleted_ids),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp = self.overlay_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if tmp.exists():
                tmp.replace(self.overlay_file)
        except Exception as ex:
            logger.error("Failed saving user overlay to %s: %s", self.overlay_file, ex)

    # ── 3. Internal Overlay Resolution ───────────────────────────────────────
    def _apply_overlay(self, item: dict[str, Any]) -> dict[str, Any]:
        """Apply user dynamic overlay (overrides, preferences, soft-delete) onto a base entry."""
        eid = item["id"]
        res = deepcopy(item)
        if eid in self.user_overrides:
            res.update(deepcopy(self.user_overrides[eid]))
            res["is_override"] = True
            res["is_user"] = True

        pref_info = self.preferences.get(eid)
        if pref_info:
            res["preference"] = pref_info.get("preference", "neutral")
            res["preferred"] = (res["preference"] == "preferred")
            res["weight_boost"] = float(pref_info.get("weight_boost", 2.0 if res["preferred"] else 1.0))
        return res

    # ── 4. Query & Search API ────────────────────────────────────────────────
    def get_entry(self, entry_id: str) -> Optional[dict[str, Any]]:
        """Retrieve entry by ID (user entries, overrides, or base entries)."""
        if not entry_id:
            return None
        eid = str(entry_id).strip()

        # Check pure user entries
        if eid in self.user_entries:
            res = deepcopy(self.user_entries[eid])
            pref_info = self.preferences.get(eid, {})
            if pref_info:
                res["preference"] = pref_info.get("preference", res.get("preference", "neutral"))
                res["preferred"] = (res["preference"] == "preferred")
                res["weight_boost"] = float(pref_info.get("weight_boost", res.get("weight_boost", 1.0)))
            return res

        # Check soft-deleted
        if eid in self.deleted_ids:
            return None

        # Check overrides or base entries
        cand = self.base_entries_by_id.get(eid)
        if not cand:
            alias_id = COMMON_ALIASES.get(eid.lower())
            if alias_id and alias_id in self.base_entries_by_id:
                cand = self.base_entries_by_id[alias_id]

        if not cand:
            # Fallback search by prefix
            for prefix in ("type_profile:", "research_entry:", "author:", "law."):
                if prefix + eid in self.base_entries_by_id:
                    cand = self.base_entries_by_id[prefix + eid]
                    break

        if not cand:
            # Case-insensitive search
            eid_lower = eid.lower()
            for k, item in self.base_entries_by_id.items():
                if k.lower() == eid_lower:
                    cand = item
                    break

        if cand:
            return self._apply_overlay(cand)
        return None

    def list_entries(
        self,
        category: Optional[str] = None,
        property_id: Optional[str] = None,
        user_only: bool = False,
        preferred_only: bool = False,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Query entries matching filters with pagination and preference weighting.
        """
        results: list[dict[str, Any]] = []

        norm_cat = normalize_category(category) if category and category.lower() != "all" else None
        target_prop = str(property_id).lower().strip() if property_id else None
        kw = str(keyword).lower().strip() if keyword else None

        # 1. User entries
        for u in self.user_entries.values():
            if u["id"] in self.deleted_ids:
                continue
            entry = self.get_entry(u["id"])
            if entry and self._matches_filter(entry, norm_cat, target_prop, user_only, preferred_only, kw):
                results.append(entry)

        # 2. Base entries with overlay
        if not user_only:
            seen_ids = {r["id"] for r in results}
            for b in self.base_entries:
                eid = b["id"]
                if eid in self.deleted_ids or eid in seen_ids:
                    continue
                entry = self._apply_overlay(b)
                if self._matches_filter(entry, norm_cat, target_prop, user_only, preferred_only, kw):
                    results.append(entry)
                    seen_ids.add(eid)

        # Sort: preferred first (highest weight boost), then user entries, then title
        def sort_key(item: dict[str, Any]):
            is_pref = 1 if (item.get("preference") == "preferred" or item.get("preferred")) else 0
            boost = item.get("weight_boost", 1.0)
            is_user = 1 if item.get("is_user") else 0
            return (is_pref, boost, is_user, -(item.get("title") or ""))

        results.sort(key=lambda x: (
            1 if (x.get("preference") == "preferred" or x.get("preferred")) else 0,
            x.get("weight_boost", 1.0),
            1 if x.get("is_user") else 0
        ), reverse=True)

        total = len(results)
        paged = results[offset: offset + limit] if limit > 0 else results
        return {"items": paged, "total": total}

    def _matches_filter(
        self,
        entry: dict[str, Any],
        norm_cat: Optional[str],
        target_prop: Optional[str],
        user_only: bool,
        preferred_only: bool,
        kw: Optional[str],
    ) -> bool:
        if user_only and not entry.get("is_user"):
            return False
        if preferred_only and not (entry.get("preference") == "preferred" or entry.get("preferred")):
            return False
        if norm_cat:
            entry_cat = entry.get("category")
            entry_raw_cat = entry.get("raw_category")
            if entry_cat != norm_cat and entry_raw_cat != norm_cat:
                cat_info = next((c for c in KNOWLEDGE_CATEGORIES if c["id"] == norm_cat), None)
                if not (cat_info and any(alt.lower() in [str(entry_cat).lower(), str(entry_raw_cat).lower()] for alt in cat_info.get("alt_names", []))):
                    return False
        if target_prop:
            props = [str(p).lower() for p in entry.get("properties", [])]
            tags = [str(t).lower() for t in entry.get("tags", [])]
            if not any(target_prop in p or p in target_prop for p in props + tags):
                return False
        if kw:
            text = " ".join([
                str(entry.get("title", "")),
                str(entry.get("description", "")),
                str(entry.get("formula", "")),
                " ".join(entry.get("tags", [])),
                " ".join(entry.get("properties", [])),
            ]).lower()
            if kw not in text:
                return False
        return True

    def search(
        self,
        field_names: Optional[Iterable[str]] = None,
        entity_types: Optional[Iterable[str]] = None,
        keywords: Optional[Iterable[str]] = None,
        categories: Optional[Iterable[str]] = None,
        top_k: int = 5,
        user_only: bool = False,
        preferred_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search entries with user-preference prioritization and property matching.
        """
        f_set = {str(f).lower() for f in (field_names or []) if f}
        e_set = {str(e).lower() for e in (entity_types or []) if e}
        c_set = {normalize_category(c) for c in (categories or []) if c}
        kw_list = [str(k).lower() for k in (keywords or []) if k]

        scores: list[tuple[float, dict[str, Any]]] = []

        all_entries = self.list_entries(user_only=user_only, preferred_only=preferred_only, limit=-1)["items"]

        for entry in all_entries:
            score = 0.0
            entry_fields = {str(f).lower() for f in entry.get("properties", [])}
            entry_entities = {str(e).lower() for e in entry.get("entity_types", [])}
            entry_tags = {str(t).lower() for t in entry.get("tags", [])}
            cat = entry.get("category", "")

            # Rule matching weights
            field_hits = len(f_set.intersection(entry_fields))
            if field_hits:
                score += 6.0 * field_hits
            else:
                for f in f_set:
                    if any(f in ef or ef in f for ef in entry_fields):
                        score += 3.5

            entity_hits = len(e_set.intersection(entry_entities))
            if entity_hits:
                score += 3.5 * entity_hits

            if cat in c_set:
                score += 2.5

            for kw in kw_list:
                if kw in entry_tags or kw in entry_fields or kw in entry["id"].lower():
                    score += 4.0
                elif kw in entry.get("title", "").lower():
                    score += 3.0
                elif kw in entry.get("description", "").lower():
                    score += 1.5

            # User preference boost
            pref = entry.get("preference", "neutral")
            weight_boost = entry.get("weight_boost", 1.0)
            if pref == "preferred" or entry.get("preferred"):
                score += 8.0 * max(1.0, weight_boost)
            elif pref == "deprioritized":
                score -= 8.0 * (1.0 / max(0.1, weight_boost))

            if entry.get("is_user"):
                score += 2.0

            if score > 0.5:
                scores.append((score, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scores[:top_k]]

    def get_preferred_ids(self) -> set[str]:
        """Return all entry IDs currently preferred by the user."""
        pref_ids = set()
        for eid, info in self.preferences.items():
            if info.get("preference") == "preferred":
                pref_ids.add(eid)
        for u in self.user_entries.values():
            if u.get("preference") == "preferred" or u.get("preferred"):
                pref_ids.add(u["id"])
        return pref_ids

    # ── 5. Dynamic Overlay CRUD & Fork ───────────────────────────────────────
    def create_user_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new user custom theoretical entry."""
        eid = str(data.get("id") or f"user_{int(time.time() * 1000)}").strip()
        pref = data.get("user_preference") or ("preferred" if data.get("preferred") else "neutral")
        weight = float(data.get("weight_boost", 2.0 if pref == "preferred" else 1.0))

        item = {
            "id": eid,
            "title": str(data.get("title") or eid).strip(),
            "category": normalize_category(data.get("category") or "user_private"),
            "formula": str(data.get("formula") or "").strip(),
            "description": str(data.get("description") or data.get("content") or "").strip(),
            "conditions": list(data.get("conditions") or []),
            "parameters": list(data.get("parameters") or []),
            "properties": list(data.get("properties") or []),
            "entity_types": list(data.get("entity_types") or []),
            "tags": list(data.get("tags") or []),
            "sources": str(data.get("sources") or "User Private Theory").strip(),
            "origin": "user",
            "is_user": True,
            "is_override": False,
            "is_deleted": False,
            "preference": pref,
            "preferred": (pref == "preferred"),
            "weight_boost": weight,
            "base_id": data.get("base_id"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.user_entries[eid] = item
        self.preferences[eid] = {"preference": pref, "weight_boost": weight}
        self._save_user_overlay()
        return item

    def update_entry(self, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a user entry, or fork-override a base entry."""
        eid = str(entry_id).strip()

        if eid in self.user_entries:
            target = self.user_entries[eid]
            for key in ("title", "category", "formula", "description", "conditions", "parameters", "properties", "entity_types", "tags", "sources"):
                if key in data:
                    target[key] = data[key]
            if "category" in target:
                target["category"] = normalize_category(target["category"])
            if "user_preference" in data or "preferred" in data:
                pref = data.get("user_preference") or ("preferred" if data.get("preferred") else "neutral")
                target["preference"] = pref
                target["preferred"] = (pref == "preferred")
                target["weight_boost"] = float(data.get("weight_boost", target.get("weight_boost", 1.0)))
                self.preferences[eid] = {"preference": pref, "weight_boost": target["weight_boost"]}
            elif "weight_boost" in data:
                target["weight_boost"] = float(data["weight_boost"])
                if eid in self.preferences:
                    self.preferences[eid]["weight_boost"] = target["weight_boost"]
            target["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._save_user_overlay()
            return target

        # Base entry fork-override
        base = self.get_entry(eid)
        if not base:
            raise DomainError("KNOWLEDGE_ENTRY_NOT_FOUND", f"未找到理论条目 {eid}", 404)

        override = deepcopy(base)
        for key in ("title", "category", "formula", "description", "conditions", "parameters", "properties", "entity_types", "tags", "sources"):
            if key in data:
                override[key] = data[key]
        if "category" in override:
            override["category"] = normalize_category(override["category"])
        override["is_override"] = True
        override["is_user"] = True
        override["base_id"] = eid
        override["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if "user_preference" in data or "preferred" in data:
            pref = data.get("user_preference") or ("preferred" if data.get("preferred") else "neutral")
            override["preference"] = pref
            override["preferred"] = (pref == "preferred")
            override["weight_boost"] = float(data.get("weight_boost", override.get("weight_boost", 1.0)))
            self.preferences[eid] = {"preference": pref, "weight_boost": override["weight_boost"]}
        elif "weight_boost" in data:
            override["weight_boost"] = float(data["weight_boost"])
            if eid in self.preferences:
                self.preferences[eid]["weight_boost"] = override["weight_boost"]

        self.user_overrides[eid] = override
        self._save_user_overlay()
        return override

    def delete_entry(self, entry_id: str) -> dict[str, Any]:
        """Delete user entry or soft-delete base entry."""
        eid = str(entry_id).strip()
        action = "deleted"

        if eid in self.user_entries:
            del self.user_entries[eid]
            self.preferences.pop(eid, None)
        elif eid in self.user_overrides:
            del self.user_overrides[eid]
            action = "restored"
        elif eid in self.base_entries_by_id:
            self.deleted_ids.add(eid)
        else:
            raise DomainError("KNOWLEDGE_ENTRY_NOT_FOUND", f"未找到理论知识条目 {eid}", 404)

        self._save_user_overlay()
        return {"success": True, "id": eid, "action": action}

    def restore_default(self, entry_id: str) -> dict[str, Any]:
        """Restore a base entry by clearing overrides, soft-delete, and preferences."""
        eid = str(entry_id).strip()
        self.user_overrides.pop(eid, None)
        self.deleted_ids.discard(eid)
        self.preferences.pop(eid, None)
        self._save_user_overlay()

        restored = self.get_entry(eid)
        if not restored:
            raise DomainError("KNOWLEDGE_ENTRY_NOT_FOUND", f"条目 {eid} 无法恢复默认", 404)
        return {"success": True, "id": eid, "action": "restored", "entry": restored}

    def set_preference(
        self,
        entry_id: str,
        preference: str,
        weight_boost: Optional[float] = None,
    ) -> dict[str, Any]:
        """Toggle preferred/neutral/deprioritized state with weight boost."""
        eid = str(entry_id).strip()
        pref = str(preference).lower().strip()
        if pref not in {"preferred", "neutral", "deprioritized"}:
            if pref in {"true", "1"}:
                pref = "preferred"
            elif pref in {"false", "0"}:
                pref = "neutral"
            else:
                pref = "neutral"

        if weight_boost is None:
            weight_boost = 2.0 if pref == "preferred" else 0.2 if pref == "deprioritized" else 1.0
        else:
            weight_boost = float(weight_boost)

        self.preferences[eid] = {"preference": pref, "weight_boost": weight_boost}

        # Update in-memory user entries/overrides
        if eid in self.user_entries:
            self.user_entries[eid]["preference"] = pref
            self.user_entries[eid]["preferred"] = (pref == "preferred")
            self.user_entries[eid]["weight_boost"] = weight_boost
        elif eid in self.user_overrides:
            self.user_overrides[eid]["preference"] = pref
            self.user_overrides[eid]["preferred"] = (pref == "preferred")
            self.user_overrides[eid]["weight_boost"] = weight_boost

        self._save_user_overlay()
        return {"success": True, "id": eid, "preference": pref, "weight_boost": weight_boost}

    # ── 6. Graph Topology Generation ─────────────────────────────────────────
    def get_graph(
        self,
        category: Optional[str] = None,
        property_id: Optional[str] = None,
        user_only: bool = False,
        preferred_only: bool = False,
        keyword: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate network graph topology { nodes, edges, categories } linking properties,
        laws, models, and concepts with LaTeX formulas.
        """
        entries_resp = self.list_entries(
            category=category,
            property_id=property_id,
            user_only=user_only,
            preferred_only=preferred_only,
            keyword=keyword,
            limit=120,
        )
        active_entries = entries_resp["items"]

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: set[str] = set()

        # 1. Theory & Knowledge Nodes
        for e in active_entries:
            nid = e["id"]
            node_ids.add(nid)
            nodes.append({
                "id": nid,
                "label": e.get("title", nid),
                "category": e.get("category", "physical_laws"),
                "formula": e.get("formula", ""),
                "description": e.get("description", ""),
                "preferred": e.get("preferred", False),
                "user_preference": e.get("preference", "neutral"),
                "is_user": e.get("is_user", False),
                "properties": e.get("properties", []),
                "tags": e.get("tags", []),
            })

        # 2. Property Connector Nodes
        prop_nodes_added: set[str] = set()
        for pnode in CONNECTOR_PROPERTIES:
            pid = pnode["id"]
            p_aliases = [p.lower() for p in pnode["properties"]]
            # Connect theory nodes to matching property connector
            connected = False
            for e in active_entries:
                e_props = [p.lower() for p in e.get("properties", [])]
                e_tags = [t.lower() for t in e.get("tags", [])]
                if any(alias in p or p in alias for alias in p_aliases for p in e_props + e_tags):
                    edges.append({
                        "source": e["id"],
                        "target": pid,
                        "label": f"关联{pnode['properties'][0]}",
                    })
                    connected = True

            if connected or not category or category == "all":
                nodes.append(pnode)
                prop_nodes_added.add(pid)
                node_ids.add(pid)

        # 3. Inter-theory Coupling Edges
        # Predefined classical physical couplings
        classical_couplings = [
            ("stefan_boltzmann_law", "wien_displacement_law", "黑体热辐射联立分析"),
            ("lane_emden_equation", "chandrasekhar_mass_limit", "多方球状态方程与相对论极限"),
            ("eddington_luminosity_limit", "stefan_boltzmann_law", "极限辐射压与光球光度平衡"),
            ("cardelli_ccm89_extinction", "gaia_astrometric_parallax", "消光修正与视差几何测距"),
        ]
        for src, tgt, label in classical_couplings:
            if src in node_ids and tgt in node_ids:
                edges.append({"source": src, "target": tgt, "label": label})

        # User fork relations
        for e in active_entries:
            if e.get("base_id") and e["base_id"] in node_ids:
                edges.append({"source": e["id"], "target": e["base_id"], "label": "派生自基准理论"})

        # Collect all active categories including dynamic user-defined categories
        all_cats = list(KNOWLEDGE_CATEGORIES)
        existing_cat_ids = {c["id"] for c in all_cats}
        for n in nodes:
            c = n.get("category")
            if c and c not in existing_cat_ids and not n.get("is_property"):
                existing_cat_ids.add(c)
                all_cats.append({
                    "id": c,
                    "label": c,
                    "color": "#0ea5e9",
                    "is_custom": True,
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "categories": all_cats,
        }

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
