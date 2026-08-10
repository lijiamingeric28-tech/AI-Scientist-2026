#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb_coverage_report.py — P1-5 知识库覆盖率报告 (纯标准库 + 项目自带 yaml 加载)

三级覆盖率:
  L1 字段级: KB 条目 applies_to.fields 覆盖的字段 vs 领域字段全集
             (优先 rag_properties 的属性全集; 无 rag_properties 时退化为 KB 自身字段并集)
  L2 实体级: KB 条目 applies_to.entities vs rag_properties 文件类型名 (otype)
  L3 gap 清单: 领域字段/实体未被 KB 覆盖的缺口 (含 insights 输出中的字段/实体缺口)

用法:
  python scripts/kb_coverage_report.py                # 读 KB + rag_properties
  python scripts/kb_coverage_report.py --insights out/xxx.json   # 附加 insights 输出缺口分析
  python scripts/kb_coverage_report.py --json report.json        # 同时输出 JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK 无法输出 ⚠/═ 等字符 — 显式 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# 项目根目录 (本文件在 astroquery_final/scripts/ 下)
ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "quality_pipeline" / "data" / "insight_knowledge" / "astrophysics"
RAG_DIR = ROOT / "rag_properties"

# 脚本直跑时项目根不在 sys.path — 引导后 import quality_pipeline 才可用
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_entries() -> list[dict]:
    """加载 KB 条目 (YAML → dict)。"""
    from quality_pipeline.configs import load_yaml
    entries: list[dict] = []
    for yf in sorted(KB_DIR.glob("*.yaml")):
        data = load_yaml(str(yf)) or {}
        for e in (data.get("entries") or []):
            entries.append(e)
    return entries


def load_rag_properties() -> dict[str, list[str]]:
    """rag_properties/*.json → {otype: [property_id, ...]} (目录不存在则空)。"""
    out: dict[str, list[str]] = {}
    if not RAG_DIR.exists():
        return out
    for jf in sorted(RAG_DIR.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        props = [p.get("property_id", "") for p in (data.get("properties") or []) if p.get("property_id")]
        out[jf.stem] = sorted(set(props))
    return out


# rag 原始列 → 语义组的本地迷你映射 (纯标准库, 与 context_builder._semantic_group 口径对齐)
_SEMANTIC_PREFIX = [
    (("fnu_", "fcor_", "snu_", "f_"), "flux_density"),
    (("cc_", "b_v", "u_b"), "color_index"),
    (("e_", "ses", "erro"), "measurement_error"),
    (("q_",), "quality_flag"),
    (("cirr",), "cirrus_flag"),
    (("h.", "j.", "k.", "r."), "2mass_photometry"),
    (("logd", "logr"), "galaxy_size"),
    (("majaxis", "minaxis", "pa", "posang"), "galaxy_morphology"),
    (("hubble", "mtype", "otype"), "morphological_type"),
    (("ra", "de", "_ra", "_de"), "sky_position"),
    (("pm",), "proper_motion"),
    (("tsnr_", "snr", "noise"), "signal_to_noise"),
    (("mag",), "apparent_magnitude"),
    (("z", "redshift"), "redshift"),
]


def _semantic_group(raw: str) -> str:
    """rag 原始列 → 语义组 (本地迷你映射; 未命中保留原列名)。"""
    col = str(raw).lower()
    for prefixes, group in _SEMANTIC_PREFIX:
        if any(col.startswith(p) for p in prefixes):
            return group
    return col


# Simbad otype 码 → 知识库实体家族 (本地迷你映射, 纯标准库)
_OTYPE_FAMILY = {
    "agn": "agn", "sy1": "seyfert_galaxy", "sy2": "seyfert_galaxy", "syg": "seyfert_galaxy",
    "qso": "quasar", "bll": "blazar", "bla": "blazar",
    "g": "galaxy", "bcg": "galaxy", "cgg": "galaxy_group", "grg": "galaxy_group",
    "clg": "galaxy_cluster", "gic": "galaxy_cluster", "glc": "galaxy_cluster",
    "emg": "emission_line_galaxy", "lin": "liner",
    "h2g": "hii_region", "hii": "hii_region", "sbr": "star_forming_region",
    "wd": "white_dwarf", "ns": "neutron_star", "psr": "pulsar", "snr": "supernova_remnant",
    "sn": "supernova", "bh": "black_hole", "xb": "xray_binary",
    "yso": "young_stellar_object", "tts": "t_tauri_star", "pr": "pre_star",
    "cstar": "evolved_star", "rg*": "red_giant_star", "rgs": "red_supergiant",
    "sg*": "supergiant", "hrg": "high_redshift_quasar",
    "radio": "radio_source", "irs": "infrared_source", "fir": "far_infrared_source",
    "x": "xray_source", "*": "star",
    # 第二轮扩展: 23 个 rag_properties 文件型 → KB 实体家族 (对齐 quality_rules.yaml entity_types 名)
    "bic": "brightest_cluster_galaxy", "gig": "galaxy_in_group", "gip": "galaxy_in_pair",
    "hh": "herbig_haro_object", "hxb": "high_mass_xray_binary", "ig": "interacting_galaxies",
    "lsb": "low_surface_brightness_galaxy", "lxb": "low_mass_xray_binary", "mgr": "moving_group",
    "opc": "open_cluster", "pcg": "protocluster", "pn": "planetary_nebula",
    "pag": "galaxy_pair", "pl": "exoplanet", "sbg": "starburst_galaxy",
    "scg": "supercluster", "y_staro": "young_stellar_object", "out": "outflow",
    "rg": "radio_galaxy", "s_starb": "blue_supergiant", "s_starr": "red_supergiant",
    "s_stary": "yellow_supergiant", "vid": "underdense_region",
}


def _entity_family(otype: str) -> str | None:
    """rag otype 文件名 → KB 实体家族 (无映射/非星族返回 None)。"""
    o = str(otype).lower()
    if o in _OTYPE_FAMILY:
        return _OTYPE_FAMILY[o]
    if o.endswith("_star"):
        return "star"   # 光谱型星族 (A2_star/Be_star/...) 归入恒星家族
    return None


def analyze(entries: list[dict], rag: dict[str, list[str]]) -> dict:
    """三级覆盖率统计。"""
    # L1/L2: KB 侧字段/实体全集
    kb_fields: set[str] = set()
    kb_entities: set[str] = set()
    per_entry_fields: dict[str, list[str]] = {}
    per_entry_entities: dict[str, list[str]] = {}
    for e in entries:
        applies = e.get("applies_to") or {}
        fields = [str(f).lower() for f in (applies.get("fields") or [])]
        ents = [str(x).lower() for x in (applies.get("entities") or [])]
        per_entry_fields[e.get("id", "?")] = fields
        per_entry_entities[e.get("id", "?")] = ents
        kb_fields.update(fields)
        kb_entities.update(ents)

    # 领域字段全集: rag 属性全集 (存在时); 否则 KB 自身并集
    rag_fields: set[str] = set()
    rag_semantic: set[str] = set()
    for props in rag.values():
        for p in props:
            pl = p.lower()
            rag_fields.add(pl)
            rag_semantic.add(_semantic_group(pl))
    domain_fields = rag_fields or kb_fields
    domain_semantic = rag_semantic or kb_fields
    domain_entities = set(rag.keys()) or kb_entities

    # L1 字段覆盖率 (raw): 领域原始列中被 KB 语义字段覆盖的比例
    covered_fields = domain_fields & kb_fields
    field_cov = len(covered_fields) / len(domain_fields) if domain_fields else 0.0
    # L1' 字段覆盖率 (语义): rag 列映射到语义组后与 KB 字段的覆盖
    covered_semantic = domain_semantic & kb_fields
    semantic_cov = len(covered_semantic) / len(domain_semantic) if domain_semantic else 0.0
    # L2 实体覆盖率: rag otype (大小写不敏感精确匹配 + Simbad 码家族映射) 中被 KB entities 覆盖的比例
    covered_entities = sorted({o for o in domain_entities if o.lower() in kb_entities})
    rag_families: dict[str, str] = {}                  # otype → 家族
    for o in domain_entities:
        fam = _entity_family(o)
        if fam:
            rag_families[o] = fam
    covered_families = sorted({f for f in rag_families.values() if f in kb_entities})
    entity_cov = len(covered_entities) / len(domain_entities) if domain_entities else 0.0
    family_cov = len(covered_families) / len(set(rag_families.values())) if rag_families else 0.0
    family_gaps = sorted(set(rag_families.values()) - kb_entities)
    unmapped_otypes = sorted(o for o in domain_entities if o not in rag_families)

    # L3 gap 清单: 未被覆盖的领域字段/实体 + 无实体挂靠的条目 (检索时只能靠字段/标签命中)
    field_gaps = sorted(domain_fields - kb_fields)
    semantic_gaps = sorted(domain_semantic - kb_fields)
    entity_gaps = sorted({o for o in domain_entities if o.lower() not in kb_entities})
    entries_no_entity = sorted(eid for eid, ents in per_entry_entities.items() if not ents)

    return {
        "kb_dir": str(KB_DIR),
        "rag_dir": str(RAG_DIR) if RAG_DIR.exists() else None,
        "entry_count": len(entries),
        "field_level": {
            "domain_field_count": len(domain_fields),
            "covered_field_count": len(covered_fields),
            "coverage": round(field_cov, 4),
            "semantic_group_count": len(domain_semantic),
            "covered_semantic_count": len(covered_semantic),
            "semantic_coverage": round(semantic_cov, 4),
            "uncovered_fields": field_gaps[:50],
            "uncovered_field_count": len(field_gaps),
            "uncovered_semantic": semantic_gaps[:50],
        },
        "entity_level": {
            "domain_entity_count": len(domain_entities),
            "covered_entity_count": len(covered_entities),
            "coverage": round(entity_cov, 4),
            "family_count": len(set(rag_families.values())),
            "covered_family_count": len(covered_families),
            "family_coverage": round(family_cov, 4),
            "covered_families": covered_families,
            "unmapped_otype_count": len(unmapped_otypes),
            "unmapped_otypes": unmapped_otypes[:50],
            "uncovered_entities": entity_gaps[:50],
            "uncovered_entity_count": len(entity_gaps),
            "uncovered_families": family_gaps,
        },
        "gaps": {
            "field_gaps": field_gaps,
            "semantic_gaps": semantic_gaps,
            "entity_gaps": entity_gaps,
            "entity_family_gaps": family_gaps,
            "entries_without_entity": entries_no_entity,
        },
    }


def analyze_insights(insights_path: Path, kb_fields: set[str], kb_entities: set[str]) -> dict:
    """insights 输出 (report_state.insights) 中的字段/实体 vs KB 覆盖 → 检索缺口。"""
    data = json.loads(insights_path.read_text(encoding="utf-8"))
    insights = data.get("report_state", {}).get("insights", data)
    fields: set[str] = set()
    entities: set[str] = set()
    for f in (insights.get("field_insights") or []):
        if f.get("field_name"):
            fields.add(str(f["field_name"]).lower())
        if f.get("entity_type"):
            entities.add(str(f["entity_type"]).lower())
    return {
        "insights_path": str(insights_path),
        "data_fields": sorted(fields),
        "data_entities": sorted(entities),
        "uncovered_fields": sorted(fields - kb_fields),
        "uncovered_entities": sorted(entities - kb_entities),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库三级覆盖率报告 (P1-5)")
    ap.add_argument("--insights", type=Path, default=None, help="insights 输出 JSON (可选)")
    ap.add_argument("--json", type=Path, default=None, dest="json_out", help="同时写出 JSON 报告")
    args = ap.parse_args()

    entries = load_entries()
    rag = load_rag_properties()
    report = analyze(entries, rag)

    print("═" * 60)
    print("知识库覆盖率报告 (P1-5)")
    print("═" * 60)
    print(f"知识库: {KB_DIR}  ({report['entry_count']} 条)")
    print(f"rag_properties: {RAG_DIR if RAG_DIR.exists() else '不存在 (实体级退化为 KB 自身并集)'}")
    print()
    fl = report["field_level"]
    print(f"[L1 字段级] 领域字段 {fl['domain_field_count']} 个 (rag 原始列), "
          f"KB 覆盖 {fl['covered_field_count']} 个 → 覆盖率 {fl['coverage']:.1%}")
    print(f"           语义组 {fl['semantic_group_count']} 个, "
          f"KB 覆盖 {fl['covered_semantic_count']} 个 → 语义覆盖率 {fl['semantic_coverage']:.1%}")
    if fl["uncovered_fields"]:
        print(f"  ⚠ 未覆盖字段 ({fl['uncovered_field_count']}): {', '.join(fl['uncovered_fields'][:15])}")
    if fl["uncovered_semantic"]:
        print(f"  ⚠ 未覆盖语义组: {', '.join(fl['uncovered_semantic'][:15])}")
    el = report["entity_level"]
    print(f"[L2 实体级] 领域实体 {el['domain_entity_count']} 个, "
          f"KB 精确覆盖 {el['covered_entity_count']} 个 → 覆盖率 {el['coverage']:.1%}")
    print(f"           家族映射 {el['family_count']} 个 (Simbad 码→家族), "
          f"KB 覆盖 {el['covered_family_count']} 个 → 家族覆盖率 {el['family_coverage']:.1%}")
    if el["covered_families"]:
        print(f"  已覆盖家族: {', '.join(el['covered_families'])}")
    if el["unmapped_otype_count"]:
        print(f"  ⚠ 未映射 otype ({el['unmapped_otype_count']}): "
              f"{', '.join(el['unmapped_otypes'][:15])}")
    print("[L3 gap 清单]")
    g = report["gaps"]
    print(f"  - 未覆盖字段: {len(g['field_gaps'])} 个 (见上方抽样)")
    print(f"  - 未覆盖实体家族: {len(g['entity_family_gaps'])} 个")
    print(f"  - 未覆盖实体: {len(g['entity_gaps'])} 个")
    if g["entries_without_entity"]:
        print(f"  - 无实体挂靠的条目: {', '.join(g['entries_without_entity'][:10])}")
    if not entries:
        print("  - 知识库为空! (检索将降级为纯 LLM 模式)")

    if args.insights is not None:
        print()
        print("── insights 输出缺口分析 ──")
        try:
            kb_fields = {f for e in entries for f in ((e.get("applies_to") or {}).get("fields") or [])}
            kb_entities = {x.lower() for e in entries
                           for x in ((e.get("applies_to") or {}).get("entities") or [])}
            ia = analyze_insights(args.insights, kb_fields, kb_entities)
            print(f"数据字段 {len(ia['data_fields'])} 个, KB 未覆盖 {len(ia['uncovered_fields'])} 个: "
                  f"{', '.join(ia['uncovered_fields'][:15])}")
            print(f"数据实体 {len(ia['data_entities'])} 个, KB 未覆盖 {len(ia['uncovered_entities'])} 个: "
                  f"{', '.join(ia['uncovered_entities'][:15])}")
            report["insights_gap_analysis"] = ia
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            print(f"  ✗ 无法解析 insights 输出: {exc}")

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写出: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
