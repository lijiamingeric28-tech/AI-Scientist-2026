"""Load the frozen delivery and index the evidence available to follow-up tools."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from astroquery_ai.runtime.errors import DomainError

logger = logging.getLogger("agent_harness.data_loader")

def source_metadata(source):
    """Bibliography of the edition actually saved with this delivery."""
    work = source.get("work") or {}
    records = work.get("records") or []
    identity = source.get("identity") or {}
    record = next((item for item in records if item.get("bibcode") == identity.get("bibcode")),
                  records[0] if records else {})
    metadata = {key: source.get(key) or record.get(key) or identity.get(key)
                for key in ("title", "authors", "year", "bibcode")}
    if isinstance(metadata["title"], list):
        metadata["title"] = next((title for title in metadata["title"] if isinstance(title, str) and title.strip()), None)
    if isinstance(metadata["authors"], str):
        metadata["authors"] = [metadata["authors"]]
    return metadata


class TaskDataBundle:
    """封装单一任务的全部沉淀资产与极速检索索引。"""

    def __init__(self, task_id: str, delivery_body: Dict[str, Any], raw_task: Optional[Dict[str, Any]] = None):
        self.task_id = task_id
        self.raw_task = raw_task or {}
        self.body = delivery_body
        self.scope = {
            "delivery_id": delivery_body.get("delivery_id"),
            "delivery_revision": delivery_body.get("revision"),
            "snapshot_ref": delivery_body.get("snapshot_ref"),
        }

        # 1. 目标天体信息
        target = delivery_body.get("target") or {}
        self.target = target
        self.target_name = (
            target.get("main_id")
            or (target.get("user_mentions") or [""])[0]
            or (self.raw_task.get("title") or "").split(" ")[-1]
            or "目标天体"
        )
        self.aliases: List[str] = target.get("aliases") or []
        self.coordinates = target.get("coordinates") or {}
        self.primary_otype = target.get("primary_otype") or ""

        # 2. 字段约定与物理量定义 (definitions)
        self.definitions_list: List[Dict[str, Any]] = delivery_body.get("definitions") or []
        self.definitions_by_id: Dict[str, Dict[str, Any]] = {}
        self.property_name_map: Dict[str, str] = {}  # 中文名/符号/别名 -> property_id

        # 常见天文学术物理量同义词映射
        SYNONYMS = {
            "色散量": ["dm", "dispersion", "柱密度", "自由电子", "色散"],
            "自转频率": ["f0", "自转", "频率", "spin", "frequency", "旋转频率"],
            "自转周期": ["p0", "自转周期", "自转", "spin_period"],
            "轨道周期": ["orbital_period", "porb", "周期", "轨道"],
            "距离模数": ["distance_modulus", "模数", "距离", "distance"],
            "视差": ["parallax", "plx"],
            "有效温度": ["teff", "温度", "temperature"],
            "金属丰度": ["feh", "fe_h", "metallicity", "丰度"],
            "极大视星等": ["v_max", "max_mag", "星等", "极大", "视星等", "magnitude"],
            "视向速度": ["radial_velocity", "rv", "视向速度"],
            "自转速度": ["vsini", "投影自转速度"],
        }

        for d in self.definitions_list:
            pid = d.get("property_id") or ""
            if not pid:
                continue
            self.definitions_by_id[pid] = d
            definition_meta = d.get("definition") or {}
            cn_name = str(definition_meta.get("name_cn") or "").strip().lower()
            symbol = str(definition_meta.get("symbol") or "").strip().lower()
            if cn_name:
                self.property_name_map[cn_name] = pid
            if symbol:
                self.property_name_map[symbol] = pid
            self.property_name_map[pid.lower()] = pid

            # 括号内的缩写（如 DM, F0）
            in_brackets = re.findall(r"[\(（]([a-zA-Z0-9_\-]+)[\)）]", cn_name)
            for b in in_brackets:
                self.property_name_map[b.lower()] = pid

            # 同义词双向关联
            for term, syns in SYNONYMS.items():
                if any(s in cn_name or s in pid.lower() for s in syns) or term in cn_name:
                    self.property_name_map[term.lower()] = pid
                    for s in syns:
                        self.property_name_map[s.lower()] = pid

        # 3. 测量数据 (measurements) 与 衍生数据 (derived)
        self.measurements: List[Dict[str, Any]] = delivery_body.get("measurements") or []
        self.derived_by_mid: Dict[str, Dict[str, Any]] = {
            d.get("measurement_id"): d for d in (delivery_body.get("derived") or []) if d.get("measurement_id")
        }

        # 4. 文献与数据源 (sources)
        self.sources: List[Dict[str, Any]] = delivery_body.get("sources") or []

        # 5. 多模态图表证据 (figures)
        self.figures: List[Dict[str, Any]] = delivery_body.get("figures") or []

        # 6. 底层原文证据与观测上下文 (evidence_index, contexts)
        self.evidence_by_id: Dict[str, Dict[str, Any]] = {
            e.get("evidence_id"): e for e in (delivery_body.get("evidence_index") or []) if e.get("evidence_id")
        }
        self.evidence_views = {item["evidence_id"]: item for item in delivery_body.get("evidence_views", [])}
        self.paper_pages = {}
        for eid, view in self.evidence_views.items():
            source_id = self.evidence_by_id.get(eid, {}).get("source_id")
            if view.get("kind") == "pdf":
                for point in view.get("points", []):
                    if source_id and type(point.get("page")) is int:
                        self.paper_pages.setdefault((source_id, point["page"]), []).append((view, point))
        self.provenance = delivery_body.get("provenance_bundle") or {}
        self.interpretations = {
            i["interpretation_id"]: i for i in self.provenance.get("interpretations", [])
            if i.get("interpretation_id")
        }
        self.contexts_by_id: Dict[str, Dict[str, Any]] = {
            c.get("context_id"): c for c in (delivery_body.get("contexts") or []) if c.get("context_id")
        }
        for c in (delivery_body.get("resolved_contexts") or []):
            if c.get("context_id"):
                self.contexts_by_id[c["context_id"]] = c

        # 7. 质量、分歧与仲裁
        self.difference = delivery_body.get("difference") or {}
        self.quality = delivery_body.get("quality") or {}
        self.dispositions: List[Dict[str, Any]] = delivery_body.get("dispositions") or []
        self.archive_groups: List[Dict[str, Any]] = delivery_body.get("archive_groups") or []
        self.result_comparisons = delivery_body.get("result_comparisons") or {}
        report = delivery_body.get("difference_report") or {}
        self.comparisons_by_id = {
            g["group_id"]: g for g in [*self.archive_groups, *self.result_comparisons.get("groups", []),
                                       *report.get("groups", []), *report.get("suspicions", [])]
            if g.get("group_id")
        }
        record_properties = {m["measurement_id"]: (m.get("property_ref") or {}).get("id") for m in self.measurements}
        for group_id, group in self.comparisons_by_id.items():
            if not group.get("property_id"):
                ids = group.get("measurement_ids") or [ref["id"] for ref in group.get("member_refs", [])]
                property_ids = {record_properties[mid] for mid in ids if record_properties.get(mid)}
                if len(property_ids) == 1:
                    self.comparisons_by_id[group_id] = {**group, "property_id": next(iter(property_ids))}

        # 8. 科学洞察与理论知识底座 (insights & theories)
        insight_obj = delivery_body.get("insight_report") or delivery_body.get("insight") or {}
        if isinstance(insight_obj, dict):
            self.insight_report = insight_obj
            self.theories: List[Dict[str, Any]] = list(insight_obj.get("knowledge_blocks") or [])
            self.insight_cards: List[Dict[str, Any]] = insight_obj.get("cards") or []
            self.cross_field_relationships: List[Dict[str, Any]] = insight_obj.get("cross_field_relationships") or []
        else:
            self.insight_report = {}
            self.theories = []
            self.insight_cards = []
            self.cross_field_relationships = []

        # 构建高密度极速索引
        self._build_indexes()

    def _build_indexes(self) -> None:
        # A. 测量记录索引
        self.measurements_by_id: Dict[str, Dict[str, Any]] = {}
        self.measurements_by_prop: Dict[str, List[Dict[str, Any]]] = {}
        self.measurements_by_source: Dict[str, List[Dict[str, Any]]] = {}

        for m in self.measurements:
            mid = str(m.get("measurement_id") or "")
            if mid:
                self.measurements_by_id[mid] = m
            pref = (m.get("property_ref") or {}).get("id") or ""
            if pref:
                self.measurements_by_prop.setdefault(pref.lower(), []).append(m)
            sref = (m.get("source_ref") or {}).get("id") or ""
            if sref:
                self.measurements_by_source.setdefault(sref.lower(), []).append(m)

        # B. 文献源索引 (按 source_id、bibcode、work_id)
        self.sources_by_id: Dict[str, Dict[str, Any]] = {}
        self.sources_by_bibcode: Dict[str, Dict[str, Any]] = {}

        for s in self.sources:
            sid = str(s.get("source_id") or "")
            if sid:
                self.sources_by_id[sid] = s
            bib = str(source_metadata(s).get("bibcode") or "")
            if bib:
                self.sources_by_bibcode[bib] = s

        # C. 图表证据索引
        self.figures_by_id: Dict[str, Dict[str, Any]] = {}
        self.figures_by_prop: Dict[str, List[Dict[str, Any]]] = {}

        for f in self.figures:
            fid = str(f.get("figure_id") or "")
            if fid:
                self.figures_by_id[fid] = f
            caption = str(f.get("caption") or "").lower()
            for pid, binding in self.definitions_by_id.items():
                cname = str((binding.get("definition") or {}).get("name_cn") or "").lower()
                sym = str((binding.get("definition") or {}).get("symbol") or "").lower()
                if (cname and cname in caption) or (sym and sym in caption) or (pid.lower() in caption):
                    self.figures_by_prop.setdefault(pid.lower(), []).append(f)

        # D. 理论知识块索引
        self.theories_by_prop: Dict[str, List[Dict[str, Any]]] = {}
        self.theories_by_id: Dict[str, Dict[str, Any]] = {}

        for block in self.theories:
            self.index_theory(block)

    def index_theory(self, block):
        claim = block.get("claim") or {}
        cid = claim.get("claim_id") or block.get("theory_id")
        if cid and cid not in self.theories_by_id:
            self.theories_by_id[cid] = block
            pids = {claim.get("property_id"), block.get("property_id"),
                    *((mapping.get("definition_ref") or {}).get("id") for mapping in block.get("applicable_mappings", []))}
            for pid in pids - {None, ""}:
                self.theories_by_prop.setdefault(pid.lower(), []).append(block)

    def source(self, key):
        return self.sources_by_id.get(key) or self.sources_by_bibcode.get(key)

    def resolve_property_id(self, query: str) -> Optional[str]:
        """将用户输入的属性名（如'周期'、'轨道周期'、'P_orb'）泛化解析为标准 property_id。"""
        q = query.strip().lower()
        if not q:
            return None
        if q in self.property_name_map:
            return self.property_name_map[q]
        matches = {pid for alias, pid in self.property_name_map.items()
                   if len(alias) >= 2 and (alias in q or q in alias)}
        return next(iter(matches)) if len(matches) == 1 else None

    def get_grounded_summary(self) -> str:
        """为智能体生成极简任务基底事实文本（Tier 1 Grounded Context）。"""
        prop_labels = []
        for d in self.definitions_list:
            meta = d.get("definition") or {}
            pid = d["property_id"]
            name = meta.get("name_cn") or pid
            unit = ((d.get("output_profile") or {}).get("unit") or {}).get("canonical_symbol")
            suffix = f"，单位 {unit}" if unit else ""
            prop_labels.append(f"{name} [DEF:{pid}]（{len(self.measurements_by_prop.get(pid.lower(), []))} 条{suffix}）")

        props_str = "、".join(prop_labels) if prop_labels else "多项天体物理量"

        lines = [
            f"【当前任务事实基底 (Grounded Task Facts)】",
            f"- 目标天体: {self.target_name} (常用别名: {', '.join(self.aliases[:4]) if self.aliases else '无'})",
            f"- 天体类型: {self.primary_otype or '未明确指定'}",
            f"- 检索物理量约定: {props_str}",
            f"- 已交付科学测定记录: 共 {len(self.measurements)} 条有效记录",
            f"- 涉及科学文献/星表: 共 {len(self.sources)} 篇 (ADS 核心论著与权威巡天表)",
            f"- 多模态科研图表切片: 共 {len(self.figures)} 幅 (包含光变曲线、拟合图、残差图等)",
            f"- 保存的归档与对照组: {len(self.comparisons_by_id)} 组",
        ]
        return "\n".join(lines)


def load_task_bundle(task_id: str, application, delivery_id=None, revision=None, snapshot_ref=None) -> TaskDataBundle:
    """Pin this turn to one published delivery, including its reports."""
    with application.repository.read() as conn:
        task = application.repository.task(conn, task_id)
        if task["kind"] == "replay":
            raise DomainError("REPLAY_READ_ONLY", "退出回放后即可追问", 409)
        body = dict(application.delivery.read_for_display(conn, task_id, delivery_id, revision))
        if snapshot_ref is not None and body.get("snapshot_ref") != snapshot_ref:
            raise DomainError("DELIVERY_CHANGED", "交付版本已变化，请刷新后再问", 409)
        source_task = application.history.source(conn, task_id)
        for kind in ("insight", "difference", "quality"):
            ref = (body.get(kind) or {}).get("report_ref")
            if ref:
                body[kind + "_report"] = application.repository.object(
                    conn, source_task, kind, ref["id"], ref["version"]
                )
        return TaskDataBundle(task_id, body, raw_task=task)
