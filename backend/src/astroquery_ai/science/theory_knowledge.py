"""
theory_knowledge.py — Curated Astrophysical Theory Knowledge Base and Cross-Field Relations.

Loads curated astrophysical theory models, physical laws, measurement principles,
and reference ranges from the application resources.
Provides hybrid rule + TF-IDF lexical search and cross-field physical network generation.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional
import yaml

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.paths import resource_root

# Fold Unicode sub/superscripts & special astro glyphs for tokenization
_UNIT_FOLDS = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
    "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁻": "", "₋": "",
    "µ": "u", "μ": "u",
    "☉": "sun", "☾": "moon",
})
_TOKEN_RE = re.compile(r"[a-z0-9_]+")

def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase tokens with unit/symbol normalization."""
    if not text:
        return []
    t = str(text).lower().translate(_UNIT_FOLDS)
    return _TOKEN_RE.findall(t)


class LexicalEmbedder:
    """TF-IDF lexical search over knowledge entries with cached vectors."""

    def __init__(self, entries: list[dict]):
        self._entries = list(entries or [])
        self._vectors: dict[str, dict[str, float]] = {}
        self._norms: dict[str, float] = {}
        self._idf: dict[str, float] = {}
        self._n = len(self._entries)
        if self._n:
            self._build()

    @staticmethod
    def _entry_text(entry: dict) -> str:
        applies = entry.get("applies_to") or {}
        parts = [
            entry.get("title", ""),
            entry.get("content", ""),
            " ".join(entry.get("tags", []) or []),
            " ".join(entry.get("hypothetical_queries", []) or []),
            " ".join(applies.get("fields", []) or []),
            " ".join(applies.get("entities", []) or []),
            entry.get("category", ""),
        ]
        return " ".join(str(p) for p in parts if p)

    def _build(self) -> None:
        docs: dict[str, Counter] = {}
        for e in self._entries:
            eid = e.get("id") or str(id(e))
            docs[eid] = Counter(tokenize(self._entry_text(e)))

        df: Counter = Counter()
        for toks in docs.values():
            df.update(set(toks))
        n = self._n
        self._idf = {tok: math.log((n + 1) / (d + 1)) + 1.0 for tok, d in df.items()}

        for eid, toks in docs.items():
            vec: dict[str, float] = {}
            norm2 = 0.0
            for tok, c in toks.items():
                w = (1.0 + math.log(c)) * self._idf.get(tok, 1.0)
                vec[tok] = w
                norm2 += w * w
            self._vectors[eid] = vec
            self._norms[eid] = math.sqrt(norm2) if norm2 > 0 else 1.0

    def cosine_similarity(self, query_tokens: list[str], entry_id: str) -> float:
        if not query_tokens or entry_id not in self._vectors:
            return 0.0
        q_counts = Counter(query_tokens)
        q_vec = {t: (1.0 + math.log(c)) * self._idf.get(t, 1.0) for t, c in q_counts.items() if t in self._idf}
        q_norm2 = sum(w * w for w in q_vec.values())
        if q_norm2 <= 0:
            return 0.0
        q_norm = math.sqrt(q_norm2)

        doc_vec = self._vectors[entry_id]
        doc_norm = self._norms[entry_id]

        dot = sum(w * doc_vec[t] for t, w in q_vec.items() if t in doc_vec)
        return dot / (q_norm * doc_norm)


class TheoryKnowledgeStore:
    """Manages the 294 curated astrophysical theoretical models, laws, and relations."""

    _instance: Optional[TheoryKnowledgeStore] = None

    def __init__(self, kb_dir: Optional[Path] = None):
        self.kb_dir = Path(kb_dir) if kb_dir is not None else resource_root() / "insight_knowledge" / "astrophysics"
        self.entries: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_field: dict[str, list[dict[str, Any]]] = {}
        self.by_category: dict[str, list[dict[str, Any]]] = {}
        self._embedder: Optional[LexicalEmbedder] = None
        self._load()

    @classmethod
    def get_instance(cls) -> TheoryKnowledgeStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if not self.kb_dir.is_dir():
            return
        for yf in sorted(self.kb_dir.glob("*.yaml")):
            try:
                with open(yf, "r", encoding="utf-8") as fp:
                    data = yaml.safe_load(fp) or {}
                for entry in data.get("entries", []):
                    eid = entry.get("id")
                    if not eid or eid in self.by_id:
                        continue
                    entry["_file"] = yf.name
                    self.entries.append(entry)
                    self.by_id[eid] = entry
                    cat = entry.get("category", "general")
                    self.by_category.setdefault(cat, []).append(entry)

                    applies = entry.get("applies_to") or {}
                    for f in applies.get("fields", []) or []:
                        self.by_field.setdefault(f.lower(), []).append(entry)
            except Exception:
                continue

        if self.entries:
            self._embedder = LexicalEmbedder(self.entries)

    def search(
        self,
        field_names: Optional[Iterable[str]] = None,
        entity_types: Optional[Iterable[str]] = None,
        keywords: Optional[Iterable[str]] = None,
        categories: Optional[Iterable[str]] = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not self.entries:
            return []

        f_set = {str(f).lower() for f in (field_names or []) if f}
        e_set = {str(e).lower() for e in (entity_types or []) if e}
        c_set = {str(c).lower() for c in (categories or []) if c}
        kw_list = [str(k).lower() for k in (keywords or []) if k]
        kw_tokens = tokenize(" ".join(kw_list))

        scores: list[tuple[float, dict[str, Any]]] = []

        for entry in self.entries:
            score = 0.0
            applies = entry.get("applies_to") or {}
            entry_fields = {str(f).lower() for f in applies.get("fields", [])}
            entry_entities = {str(e).lower() for e in applies.get("entities", [])}
            entry_tags = {str(t).lower() for t in entry.get("tags", [])}
            cat = str(entry.get("category", "")).lower()

            # Rule matching weights
            field_hits = len(f_set.intersection(entry_fields))
            if field_hits:
                score += 6.0 * field_hits

            entity_hits = len(e_set.intersection(entry_entities))
            if entity_hits:
                score += 3.5 * entity_hits

            if cat in c_set:
                score += 2.5

            for kw in kw_list:
                if kw in entry_tags or kw in entry_fields or kw in entry.get("id", "").lower():
                    score += 3.0
                elif kw in entry.get("title", "").lower():
                    score += 2.0

            # Lexical TF-IDF cosine similarity boost
            if self._embedder and kw_tokens:
                sim = self._embedder.cosine_similarity(kw_tokens, entry["id"])
                score += 4.0 * sim

            if score > 0.5:
                scores.append((score, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scores[:top_k]]

    def to_knowledge_block(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Convert a theory entry into an AstroQuery standard knowledge_block."""
        eid = entry.get("id", "unknown")
        bid = f"kb-theory-{eid}"
        source_title = entry.get("source") or "Astrophysics Standard Theory"
        fields = entry.get("applies_to", {}).get("fields", [])
        entities = entry.get("applies_to", {}).get("entities", [])

        conditions = []
        if fields:
            conditions.append(f"适用物理性质: {', '.join(fields)}")
        if entities:
            conditions.append(f"适用天体分类: {', '.join(entities)}")
        if entry.get("confidence"):
            conditions.append(f"置信体系: {entry.get('confidence')}")

        return {
            "claim": {
                "claim_id": bid,
                "text": entry.get("content", "").strip(),
                "role": "theory_law",
            },
            "entry_id": eid,
            "title": entry.get("title", eid),
            "category": entry.get("category", "physical_law"),
            "conditions": conditions,
            "authoring_basis": "standard_theory",
            "sources": [
                {
                    "source_id": f"src-{eid}",
                    "title": source_title,
                    "url": None,
                    "locator": entry.get("confidence", "consensus"),
                    "support_note": f"《天体物理基础模型与观测定律库》条目 {eid}",
                }
            ],
            "tags": entry.get("tags", []),
            "related_entries": entry.get("related_entries", []),
        }

    def derive_network_relationships(
        self,
        field_names: list[str],
        top_relations: int = 12,
    ) -> list[dict[str, Any]]:
        """
        Derive cross-property physical relationships (nodes & edges) from theoretical laws
        and empirical relations matching the requested fields.
        """
        fields_clean = [f.strip() for f in field_names if f and f.strip()]
        if len(fields_clean) < 2:
            return []

        relations: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        # Check if the query is for an exoplanet
        is_exoplanet = any("行星" in f or "planet" in f.lower() or "pl_" in f.lower() for f in fields_clean)
        is_supernova = any("超新星" in f or "sn" in f.lower() or "消光" in f or "红化" in f or "等效宽度" in f for f in fields_clean)

        # 1. Search for entries whose applies_to.fields maps to at least two distinct requested fields
        def resolve_user_field(raw_field: str) -> Optional[str]:
            c_raw = canonical_property(raw_field)
            rf_l = str(raw_field).lower()
            for req in fields_clean:
                req_l = req.lower()
                c_req = canonical_property(req)
                if c_raw and c_req and c_raw == c_req:
                    return req
                if rf_l == req_l or rf_l in req_l or req_l in rf_l:
                    return req
            return None

        for entry in self.entries:
            applies = entry.get("applies_to") or {}
            ef = applies.get("fields", [])
            ee = applies.get("entities", [])

            # Filter out galactic halo models when querying exoplanets
            if is_exoplanet and ee:
                if any(x in ee for x in ["galaxy_cluster", "galaxy_halo", "dark_matter_halo"]) and not any("planet" in x for x in ee):
                    continue

            matched_user_fields = list(dict.fromkeys(filter(None, (resolve_user_field(f) for f in ef))))
            if len(matched_user_fields) >= 2:
                for i in range(len(matched_user_fields)):
                    for j in range(i + 1, len(matched_user_fields)):
                        fa, fb = matched_user_fields[i], matched_user_fields[j]
                        pair = tuple(sorted([fa, fb]))
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            formula_str = _extract_formula_or_latex(entry)
                            relations.append({
                                "field_a": fa,
                                "field_b": fb,
                                "relation_type": entry.get("category", "physical_law"),
                                "description": entry.get("title", "") + ": " + entry.get("content", "").split("\n\n")[0],
                                "formula": formula_str,
                                "confidence": entry.get("confidence", "established"),
                                "source": entry.get("source", "Standard Astrophysics"),
                                "claim_id": f"kb-theory-{entry['id']}",
                                "theory_id": entry["id"],
                            })

        # 2. Domain-known couplings fallback if fewer than desired relations
        domain_couplings = [
            ("effective_temperature", "surface_gravity", "斯特藩-玻尔兹曼与表面引力联立标度", r"L = 4\pi R^2 \sigma T_{\text{eff}}^4, \quad g = \frac{GM}{R^2}"),
            ("mass", "radius", "质径关系与简并物态方程" if is_exoplanet else "恒星质径关系与主序结构模型", r"\bar{\rho}_p = \frac{3 M_p}{4\pi R_p^3}, \quad R_p \propto M_p^{-1/3}" if is_exoplanet else r"R \propto M^\xi \quad (\xi \approx 0.8 \text{ for MS stars})"),
            ("mass", "inclination", "开普勒视向速度质量下限与轨道倾角解耦", r"M_p \sin i = K_* \left(\frac{P M_*^2}{2\pi G}\right)^{1/3} \sqrt{1 - e^2}"),
            ("radius", "inclination", "凌星几何接触角与冲击参数视线投影", r"b = \frac{a \cos i}{R_*} \left(\frac{1 - e^2}{1 + e \sin \omega}\right) \le 1 + \frac{R_p}{R_*}"),
            ("orbital_period", "radial_velocity_semi_amplitude", "开普勒视向速度半振幅方程", r"K = \left(\frac{2\pi G}{P}\right)^{1/3} \frac{M_p \sin i}{(M_* + M_p)^{2/3}}"),
            ("transit_depth", "radius", "系外行星凌星光变几何投影深度", r"\delta = \left(\frac{R_p}{R_*}\right)^2"),
            ("dispersion_measure", "redshift", "Macquart 脉冲星/FRB 色散量-红移演化关系", r"\text{DM}_{\text{IGM}}(z) \approx 800\text{--}1200 \, \text{pc}\,\text{cm}^{-3} \cdot z"),
            ("distance", "parallax", "三角几何视差与距离模数方程", r"d = \frac{1000}{\varpi} \, \text{pc}, \quad \mu = 5\log_{10}d - 5"),
            ("extinction", "reddening", "超新星视星等星际色余与消光定律方程", r"A_V = R_V \cdot E(B-V), \quad m_{\text{obs}} = m_{\text{true}} + A_V"),
            ("apparent_magnitude", "reddening", "视星等消光色余校正方程", r"m_{\lambda,\text{obs}} = m_{\lambda,\text{true}} + R_\lambda \cdot E(B-V)"),
            ("apparent_magnitude", "extinction", "视星等消光校正方程", r"m_{\lambda,\text{obs}} = m_{\lambda,\text{true}} + A_\lambda"),
            ("extinction", "equivalent_width", "星际介质钠双线等效宽度与消光反演方程", r"W_\lambda(\text{Na I D}) \propto A_V \approx 3.1 \cdot E(B-V)"),
            ("reddening", "equivalent_width", "星际介质钠双线视线吸收等效宽度与色余比例", r"W_\lambda(\text{Na I D}) \propto N(\text{Na I}) \cdot f \cdot \lambda^2 \propto E(B-V)"),
            ("apparent_magnitude", "equivalent_width", "视线吸收等效宽度与视星等消光反演", r"A_V \approx 3.1 \cdot E(B-V) \sim \beta \cdot W(\text{Na I D})"),
            ("metallicity", "effective_temperature", "恒星大气模型谱线生长曲线标定", r"[\text{Fe/H}] = \log_{10}(N_{\text{Fe}}/N_H)_* - \log_{10}(N_{\text{Fe}}/N_H)_\odot"),
            ("microturbulent_velocity", "surface_gravity", "恒星大气非热速度场展宽方程", r"v_{\text{tot}}^2 = \frac{2kT}{\mu m_H} + \xi^2"),
            ("age", "distance", "星团等时线拟合与绝对年龄测定", r"\tau = \tau(M_{\text{TO}}, [\text{Fe/H}]), \quad (m - M)_0 = 5\log_{10} d - 5"),
            ("age", "metallicity", "银河系化学动力学演化年龄-金属丰度关系 (AMR)", r"[\text{Fe/H}](t) = [\text{Fe/H}]_0 - \gamma \cdot t"),
        ]

        for fa_key, fb_key, desc, form in domain_couplings:
            match_a = next((f for f in fields_clean if canonical_property(f) == fa_key or fa_key in f.lower()), None)
            match_b = next((f for f in fields_clean if canonical_property(f) == fb_key or fb_key in f.lower()), None)
            if match_a and match_b and match_a != match_b:
                pair = tuple(sorted([match_a, match_b]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    relations.append({
                        "field_a": match_a,
                        "field_b": match_b,
                        "relation_type": "empirical_coupling",
                        "description": desc,
                        "formula": form,
                        "confidence": "consensus",
                        "source": "Standard Astrophysical Relations",
                        "claim_id": f"kb-coupling-{fa_key}-{fb_key}",
                        "theory_id": f"coupling_{fa_key}_{fb_key}",
                    })

        return relations[:top_relations]


FIELD_ALIASES: dict[str, list[str]] = {
    "effective_temperature": ["温度", "teff", "temp", "effective_temperature", "teff_gspphot"],
    "surface_gravity": ["重力", "logg", "grav", "surface_gravity", "logg_gspphot"],
    "mass": ["质量", "mass", "msun", "mjup", "m_p", "pl_mass", "pl_msini", "stellar_mass"],
    "radius": ["半径", "radius", "rsun", "rjup", "r_p", "pl_radius", "scale_radius"],
    "orbital_period": ["周期", "period", "orbital_period", "pl_orbper"],
    "inclination": ["倾角", "orbit_inc", "inclination", "inc", "orbital_inclination", "pl_orbincl"],
    "transit_depth": ["凌星深度", "transit_depth", "depth"],
    "radial_velocity_semi_amplitude": ["半振幅", "rv_semi_amplitude", "semi_amplitude", "velocity_semi_amplitude"],
    "dispersion_measure": ["色散", "dm", "dispersion", "dispersion_measure"],
    "redshift": ["红移", "redshift", "z"],
    "distance": ["距离", "dist", "modulus", "distance", "distance_modulus", "adopted_distance"],
    "parallax": ["视差", "plx", "parallax", "parallax_distance"],
    "apparent_magnitude": ["星等", "magnitude", "mag", "app_mag", "peak_magnitude", "peak_mag_obs", "apparent_magnitude"],
    "extinction": ["消光", "extinction", "a_v", "av", "galactic_extinction"],
    "reddening": ["红化", "色余", "e(b-v)", "e_bv", "ebv", "reddening"],
    "equivalent_width": ["等效宽度", "ew", "equivalent_width", "naid", "na_i", "line_width"],
    "metallicity": ["丰度", "fe/h", "fe_h", "metallicity", "mh_gspphot"],
    "microturbulent_velocity": ["微湍流", "vmic", "turbulent", "microturbulent_velocity"],
    "age": ["年龄", "age", "isochrone_age", "cluster_age"],
}


def canonical_property(name: str) -> Optional[str]:
    t = str(name).lower()
    for canon, aliases in FIELD_ALIASES.items():
        if canon == t or any(a in t for a in aliases):
            return canon
    return None


def _extract_formula_or_latex(entry: dict[str, Any]) -> str:
    explicit = entry.get("formula")
    if explicit and isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    content = entry.get("content", "")
    lines = content.split("\n")
    for line in lines:
        line_clean = line.strip()
        if any(sym in line_clean for sym in ["=", r"\propto", "∝", r"\approx", "≈", r"\sim", "~"]):
            if len(line_clean) < 120 and not line_clean.startswith("#") and not line_clean.startswith("-"):
                res = line_clean.replace("`", "")
                if ":" in res and "=" in res:
                    res = res.split(":", 1)[1].strip()
                return res
    return ""
