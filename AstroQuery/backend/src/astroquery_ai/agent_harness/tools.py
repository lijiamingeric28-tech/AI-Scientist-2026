"""面向任务缓存的 7 大领域只读工具注册表 (Domain Tool Registry 2.0)
所有工具 100% 只读本地交付快照缓存，无外部网络依赖，返回天文学术高密度观测结构。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from .data_loader import TaskDataBundle, source_metadata


class DomainTools:
    """专精天体物理数据缓存调阅工具集。"""

    def __init__(self, bundle: TaskDataBundle, knowledge_store=None):
        self.bundle = bundle
        context = vars(bundle).get('knowledge_context')
        if context is not None:
            from astroquery_ai.science.task_knowledge import frozen_user_store
            knowledge_store = frozen_user_store(context)
        self.knowledge_store = knowledge_store

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """返回 OpenAI-Compatible Function Calling 工具定义。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "query_measurements",
                    "description": "从本次任务整理的结构化测定值列表中检索匹配记录，获取具体物理量数值、误差、单位、测定方法与文献出处。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "天体物理性质名称或物理量（例如 距离模数, 自转频率, 轨道周期, 色散量, 有效温度, 金属丰度, 视向速度 等）",
                            },
                            "source_id": {
                                "type": "string",
                                "description": "指定文献 Bibcode 或数据源标识符（可选）",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回记录最大条数，默认 6",
                            },
                        },
                        "required": ["property_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_measurement_provenance",
                    "description": "调阅指定测定记录的底层原文提取溯源链（原文摘录、所属文献物理页码、提取定位及单位换算与质检过程）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "measurement_id": {
                                "type": "string",
                                "description": "测定记录唯一标识符（例如从 query_measurements 获得的 measurement-... 标识符）",
                            }
                        },
                        "required": ["measurement_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_property_definition",
                    "description": "调阅天体物理量标准定义、国际天文量纲规范与本次任务的字段约定（标准化单位、有效物理范围及表示方式）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "天体物理量名称、符号或标识符（例如 自转频率, DM, orbital_period 等）",
                            }
                        },
                        "required": ["property_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_literature",
                    "description": "检索本次任务涵盖的核心 ADS 文献库与权威巡天星表，调阅论文题名、作者团队、发表年份、Bibcode 及所提取的物理量。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_terms": {
                                "type": "string",
                                "description": "检索关键词（例如作者名、年份、方法关键词或天体名称）",
                            },
                            "bibcode": {
                                "type": "string",
                                "description": "指定的 ADS 19位 Bibcode（可选）",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_differences_and_arbitration",
                    "description": "调阅多源测定分歧案卷、离群值核验与仲裁裁决依据（包含各源争议数值、仲裁采信依据及归一化对照组）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "目标物理性质名称（例如 色散量, 距离模数, 极大视星等 等，可选）",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_figure_evidence",
                    "description": "调阅从文献中自动抽取的科学图表切片元数据（如脉冲星轮廓、光变拟合、残差图、误差椭圆），获取图题与 PDF 原始坐标。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "figure_id": {
                                "type": "string",
                                "description": "指定的图证标识符（可选）",
                            },
                            "property_keyword": {
                                "type": "string",
                                "description": "与图表相关的物理量或特征词（如 dispersion, residual, profile, period 等，可选）",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_scientific_theory",
                    "description": "调阅天体物理理论底座与推演公式，获取经典天体物理方程（如色散延迟方程、双星质函数方程、光度距离关系等）及物理机制分析。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "物理量名称或机制关键词（例如 色散, 双星轨道, 磁偶极辐射, 视星等 等）",
                            },
                            "theory_id": {
                                "type": "string",
                                "description": "理论知识块标识符（可选）",
                            },
                        },
                    },
                },
            },
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """分发执行工具并格式化输出观测结果（绝不抛出未捕获异常）。"""
        try:
            if tool_name == "query_measurements":
                return self._query_measurements(
                    args.get("property_name", ""),
                    args.get("source_id"),
                    args.get("limit", 6),
                )
            elif tool_name == "get_measurement_provenance":
                return self._get_measurement_provenance(args.get("measurement_id", ""))
            elif tool_name == "get_property_definition":
                return self._get_property_definition(args.get("property_name", ""))
            elif tool_name == "search_literature":
                return self._search_literature(
                    args.get("query_terms", ""),
                    args.get("bibcode"),
                )
            elif tool_name == "inspect_differences_and_arbitration":
                return self._inspect_differences_and_arbitration(args.get("property_name", ""))
            elif tool_name == "get_figure_evidence":
                return self._get_figure_evidence(
                    args.get("figure_id"),
                    args.get("property_keyword", ""),
                )
            elif tool_name == "get_scientific_theory":
                return self._get_scientific_theory(
                    args.get("property_name", ""),
                    args.get("theory_id"),
                )
            else:
                return f"未知工具: {tool_name}"
        except Exception as e:
            return f"工具执行异常: {str(e)}"

    # ── 1. 测定记录检索 ──────────────────────────────────
    def _query_measurements(self, property_name: str, source_id: Optional[str], limit: int) -> str:
        pid = self.bundle.resolve_property_id(property_name)
        matched = []

        if pid and pid.lower() in self.bundle.measurements_by_prop:
            matched = list(self.bundle.measurements_by_prop[pid.lower()])
        else:
            # 关键词泛化搜索
            kw = property_name.strip().lower()
            for m in self.bundle.measurements:
                p_ref = (m.get("property_ref") or {}).get("id") or ""
                binding = self.bundle.definitions_by_id.get(p_ref, {})
                cname = str((binding.get("definition") or {}).get("name_cn") or "").lower()
                sym = str((binding.get("definition") or {}).get("symbol") or "").lower()
                if kw in cname or kw in sym or kw in p_ref.lower():
                    matched.append(m)

        if not matched and not property_name.strip():
            matched = self.bundle.measurements[:limit]

        if source_id:
            source = self.bundle.source(source_id)
            s_clean = (source["source_id"] if source else source_id).strip().lower()
            matched = [
                m for m in matched
                if s_clean in str((m.get("source_ref") or {}).get("id") or "").lower()
            ]

        sliced = matched[:min(40, max(1, limit))]
        if not sliced:
            return f"未在任务数据中检索到与「{property_name}」匹配的测定记录。"

        lines = [f"检索到 {len(sliced)} 项关于「{property_name}」的测定记录（已按天文学术规范提取）："]
        for idx, m in enumerate(sliced, 1):
            mid = m.get("measurement_id", "")
            raw_val = m.get("raw_value")
            val_dict = m.get("value") or {}
            val_str = str(val_dict.get("value") if isinstance(val_dict, dict) and "value" in val_dict else raw_val)
            unit_str = m.get("unit") or ""
            pref = (m.get("property_ref") or {}).get("id") or ""
            binding = self.bundle.definitions_by_id.get(pref, {})
            p_cn = (binding.get("definition") or {}).get("name_cn") or pref
            sref = (m.get("source_ref") or {}).get("id") or "未知文献"
            source_obj = self.bundle.sources_by_id.get(sref, {})
            bibcode = source_metadata(source_obj).get("bibcode") or sref
            context = self.bundle.contexts_by_id.get((m.get("context_ref") or {}).get("id"), {})
            conditions = "；".join(
                f"{c.get('key')}: {c['value']}" for c in context.get("conditions", []) if c.get("value") is not None
            )

            # 不确定度
            unc = m.get("uncertainty") or {}
            unc_str = ""
            comps = unc.get("components") or []
            if comps:
                unc_raw = " ± ".join(str(c.get("raw_text") or "") for c in comps if c.get("raw_text"))
                if unc_raw:
                    unc_str = f" ± {unc_raw}"

            # 衍生归一化
            derived = self.bundle.derived_by_mid.get(mid)
            norm_str = ""
            if derived:
                d_val = (derived.get("value_typed") or {}).get("value")
                d_unit = (derived.get("coordinate_units") or {}).get("target") or derived.get("unit")
                if d_val is not None and str(d_val) != val_str:
                    norm_str = f" [归一化值: {d_val} {d_unit}]"

            lines.append(
                f"{idx}. [{p_cn}] 原报: {raw_val or val_str}{unc_str} {unit_str}{norm_str} | [REC:{mid}] "
                f"| [SOURCE:{bibcode}] {source_metadata(source_obj).get('title') or ''}"
                + (f" | 条件: {conditions[:320]}" if conditions else "")
            )

        return "\n".join(lines)

    # ── 2. 底层溯源与证据链调阅 ──────────────────────────
    def _get_measurement_provenance(self, measurement_id: str) -> str:
        m = self.bundle.measurements_by_id.get(measurement_id)
        if not m:
            return f"未找到标识符为 {measurement_id} 的测定记录。"

        lines = [f"【测定记录底层溯源链: [REC:{measurement_id}]】"]
        pref = (m.get("property_ref") or {}).get("id") or ""
        binding = self.bundle.definitions_by_id.get(pref, {})
        p_cn = (binding.get("definition") or {}).get("name_cn") or pref
        lines.append(f"- 物理性质: {p_cn} ({pref})")
        lines.append(f"- 提取原始字面值: {m.get('raw_value')} {m.get('unit', '')}")

        # 出处
        sref = (m.get("source_ref") or {}).get("id") or ""
        source_obj = self.bundle.sources_by_id.get(sref, {})
        bibcode = source_metadata(source_obj).get("bibcode") or sref
        lines.append(f"- 出处文献/星表: [SOURCE:{bibcode}]《{source_obj.get('title', '未知论文')}》")

        # 原文证据摘录 (evidence_refs)
        evidence_refs = m.get("evidence_refs") or []
        if evidence_refs:
            lines.append("- 原文证据定位与切片:")
            for e_ref in evidence_refs:
                eid = e_ref.get("id") if isinstance(e_ref, dict) else str(e_ref)
                ev = self.bundle.evidence_by_id.get(eid, {})
                page = (ev.get("locator") or {}).get("page")
                raw_text = ev.get("raw_text") or "（无摘录文本）"
                locator = ev.get("locator") or {}
                page_info = f"文献物理第 {page} 页" if page else f"表格位置 {json.dumps(locator, ensure_ascii=False)}"
                lines.append(f"  * 位于 [SOURCE:{bibcode}{f':p.{page}' if page else ''}] {page_info}:")
                lines.append(f"    「{raw_text.strip()}」")

        # 观测上下文 (context)
        cref = (m.get("context_ref") or {}).get("id")
        ctx = self.bundle.contexts_by_id.get(cref, {})
        conds = ctx.get("conditions") or []
        if conds:
            cond_strs = [f"{c.get('key')}={c.get('value')}" for c in conds if c.get("key")]
            lines.append(f"- 提取观测条件/仪器状态: {', '.join(cond_strs)}")

        # 质检与清洗轨迹 (derived)
        derived = self.bundle.derived_by_mid.get(measurement_id)
        if derived:
            d_val = (derived.get("value_typed") or {}).get("value")
            d_unit = (derived.get("coordinate_units") or {}).get("target") or derived.get("unit")
            reason = derived.get("reason") or "遵循标准物理量纲转换规则"
            lines.append(f"- 质检清洗状态: {derived.get('main_state')} | 最终标准值: {d_val} {d_unit} (转换依据: {reason})")

        return "\n".join(lines)

    # ── 3. 物理定义与字段约定调阅 ──────────────────────────
    def _get_property_definition(self, property_name: str) -> str:
        pid = self.bundle.resolve_property_id(property_name)
        if not pid or pid not in self.bundle.definitions_by_id:
            return f"未在本次任务的字段约定中找到「{property_name}」的定义。"

        binding = self.bundle.definitions_by_id[pid]
        meta = binding.get("definition") or {}
        profile = binding.get("output_profile") or {}

        name_cn = meta.get("name_cn") or pid
        symbol = meta.get("symbol") or "无符号"
        unit = profile.get("unit") or meta.get("unit") or "无量纲"
        rep = profile.get("representation") or "linear"
        desc = meta.get("description") or meta.get("physical_meaning") or "天体物理量标准测定参量"

        lines = [
            f"【物理量约定与量纲定义: [DEF:{pid}]】",
            f"- 物理性质名称: {name_cn} (标识符: {pid})",
            f"- 国际标准物理符号: ${symbol}$",
            f"- 交付标准化单位: {unit}",
            f"- 数值表达形态: {rep}",
            f"- 天体物理内涵与约定: {desc}",
        ]
        return "\n".join(lines)

    # ── 4. 任务文献库检索 ──────────────────────────────────
    def _search_literature(self, query_terms: str, bibcode: Optional[str]) -> str:
        matched = []
        if bibcode:
            b_clean = bibcode.strip().lower()
            for s in self.bundle.sources:
                if b_clean == str(source_metadata(s).get("bibcode") or "").lower() or b_clean == str(s.get("source_id") or "").lower():
                    matched.append(s)
        else:
            q_clean = query_terms.strip().lower()
            for s in self.bundle.sources:
                meta = source_metadata(s)
                title = str(meta.get("title") or "").lower()
                authors = " ".join(str(a) for a in (meta.get("authors") or [])).lower()
                year = str(meta.get("year") or "")
                bib = str(meta.get("bibcode") or "").lower()
                if q_clean in title or q_clean in authors or q_clean in year or q_clean in bib:
                    matched.append(s)

        sliced = matched[:6]
        lines = [f"检索到 {len(sliced)} 篇涉及本次任务提取的文献出处："]
        for idx, s in enumerate(sliced, 1):
            meta = source_metadata(s)
            bib = meta.get("bibcode") or s.get("source_id")
            title = meta.get("title") or "未提供题名"
            year = meta.get("year") or "未知年份"
            authors = meta.get("authors") or []
            auth_str = ", ".join(map(str, authors[:3]))
            # 统计从该文献提取的测定数
            recs = self.bundle.measurements_by_source.get(str(s.get("source_id") or "").lower(), [])
            lines.append(
                f"{idx}. [SOURCE:{bib}] {auth_str} ({year}): 《{title}》 | 采纳测定数: {len(recs)} 项"
            )

        return "\n".join(lines)

    # ── 5. 分歧仲裁案卷调阅 ──────────────────────────────
    def _inspect_differences_and_arbitration(self, property_name: str) -> str:
        lines = ["【多源测定分歧案卷与质检仲裁记录】"]
        pid = self.bundle.resolve_property_id(property_name)
        all_groups = [group for group in self.bundle.comparisons_by_id.values()
                      if not pid or group.get("property_id") == pid]
        if not all_groups:
            return "本交付没有找到对应的对照或归档组。"

        for idx, g in enumerate(all_groups[:4], 1):
            gid = g["group_id"]
            pref = g.get("property_id") or "核心物理量"
            binding = self.bundle.definitions_by_id.get(pref, {})
            p_cn = (binding.get("definition") or {}).get("name_cn") or pref
            meaning = g.get("meaning") or g.get("reason") or g.get("question") or "已保存的对照组"
            mids = g.get("measurement_ids") or [r.get("id") for r in (g.get("member_refs") or [])]

            lines.append(f"\n[仲裁案卷: [ARB:{gid}]] - 涉及物理量: {p_cn}")
            lines.append(f"- 仲裁研判分析: {meaning}")
            lines.append(f"- 涉及测定记录数: {len(mids)} 条，关联记录 ID: {', '.join(f'[REC:{m}]' for m in mids[:4])}")

        return "\n".join(lines)

    # ── 6. 多模态科学图表切片调阅 ──────────────────────────
    def _get_figure_evidence(self, figure_id: Optional[str], property_keyword: str) -> str:
        matched = []
        if figure_id:
            fid_clean = figure_id.strip().lower()
            for f in self.bundle.figures:
                if fid_clean == str(f.get("figure_id") or "").lower():
                    matched.append(f)
        elif property_keyword:
            keywords = [word.strip().lower() for word in property_keyword.split("|") if word.strip()]
            properties = {self.bundle.resolve_property_id(word) for word in keywords}
            properties.discard(None)
            for f in self.bundle.figures:
                cap = str(f.get("caption") or "").lower()
                if any(word in cap for word in keywords) or properties.intersection(f.get("property_ids") or []):
                    matched.append(f)

        if not matched and not figure_id:
            matched = self.bundle.figures[:4]

        sliced = matched[:4]
        if not sliced:
            return "本次任务中未沉淀多模态图表切片数据。"

        lines = [f"调阅到 {len(sliced)} 幅科学图表切片元数据："]
        for idx, f in enumerate(sliced, 1):
            fid = f.get("figure_id")
            sref = f.get("source_id") or "未知文献"
            page = f.get("page")
            cap = f.get("caption") or "（无图题说明）"
            lines.append(
                f"{idx}. 图证标识: [FIG:{fid}] | 出处: [SOURCE:{sref}{f':p.{page}' if page else ''}] (第 {page} 页)"
            )
            lines.append(f"   图题说明: {cap.strip()[:180]}")

        return "\n".join(lines)

    # ── 7. 统一理论知识库与公式调阅 (集成用户优先理论与派生模型) ───────
    def _get_scientific_theory(self, property_name: str, theory_id: Optional[str]) -> str:
        matched = []
        user_store = self.knowledge_store
        cached = []
        for block in self.bundle.theories:
            active = user_store.resolve_cached_block(block) if user_store else block
            if active is not None:
                cached.append(active)

        if theory_id:
            tid_clean = theory_id.strip().lower()
            if vars(self.bundle).get('knowledge_scoped', False):
                exact = self.bundle.theories_by_id.get(theory_id)
                candidates = [b for b in cached if tid_clean in {
                    str(b.get('entry_id') or '').lower(), str(b.get('claim', {}).get('claim_id') or '').lower()}]
                if exact is not None:
                    matched.append(exact)
                elif len(candidates) > 1:
                    return '任务保存了该知识标识的多个版本，请按具体性质调阅。'
            if user_store:
                entry = user_store.get_entry(theory_id)
                if entry:
                    matched.append(user_store.to_knowledge_block(entry))
            for b in cached:
                claim = b.get("claim") or {}
                cid = str(claim.get("claim_id") or b.get("theory_id") or "").lower()
                if tid_clean in {cid, str(b.get("entry_id") or "").lower(), str(b.get("theory_id") or "").lower(), cid.removeprefix("kb-theory-").removeprefix("kb-")} and not any(m.get("entry_id") == b.get("entry_id", b.get("theory_id")) for m in matched):
                    matched.append(b)
        else:
            pid = self.bundle.resolve_property_id(property_name)
            if user_store:
                query_fields = [pid, property_name] if pid else [property_name]
                cands = user_store.search(
                    field_names=query_fields,
                    keywords=[property_name],
                    top_k=6,
                )
                for c in cands:
                    matched.append(user_store.to_knowledge_block(c))

            if pid and pid.lower() in self.bundle.theories_by_prop:
                for cached_block in self.bundle.theories_by_prop[pid.lower()]:
                    b = user_store.resolve_cached_block(cached_block) if user_store else cached_block
                    if b is None:
                        continue
                    if not any(m == b for m in matched):
                        matched.append(b)
            elif not vars(self.bundle).get('knowledge_scoped', False):
                kw = property_name.strip().lower()
                for b in cached:
                    claim = b.get("claim") or {}
                    title = str(claim.get("title") or b.get("title") or "").lower()
                    mech = str(b.get("physical_mechanism") or "").lower()
                    if kw in title or kw in mech:
                        if not any(m.get("entry_id") == b.get("theory_id") for m in matched):
                            matched.append(b)

        if not matched and not theory_id and not vars(self.bundle).get('knowledge_scoped', False):
            matched = cached[:3]

        if not matched and user_store and not theory_id and not vars(self.bundle).get('knowledge_scoped', False):
            pids = list(self.bundle.definitions_by_id.keys())
            cands = user_store.search(field_names=pids, top_k=3)
            matched = [user_store.to_knowledge_block(c) for c in cands]

        if not matched:
            return f"理论知识库中未查得关于「{property_name}」的特定天体物理公式。"

        def _rank(b):
            is_pref = 1 if (b.get("user_preferred") or b.get("preferred") or b.get("user_preference") == "preferred") else 0
            boost = b.get("weight_boost", 1.0)
            is_user = 1 if b.get("is_user") else 0
            return (is_pref, boost, is_user)

        matched.sort(key=_rank, reverse=True)

        lines = ["【天体物理学理论底座与推演公式调阅】"]
        for idx, b in enumerate(matched[:4], 1):
            runtime_id = self.bundle.index_theory(b)
            claim = b.get("claim") or {}
            cid = runtime_id if isinstance(runtime_id, str) else claim.get("claim_id") or b.get("theory_id") or f"THEORY-{idx}"
            title = claim.get("title") or b.get("title") or "经典天体物理规律"
            formula = b.get("formula") or {}
            latex = formula if isinstance(formula, str) else formula.get("latex") or formula.get("expression") or ""
            mech = b.get("physical_mechanism") or claim.get("text") or claim.get("statement") or ""

            pref_tag = ""
            if b.get("user_preferred") or b.get("preferred") or b.get("user_preference") == "preferred":
                pref_tag += " ★ [科研优先理论 (User Preferred)]"
            if b.get("is_user"):
                pref_tag += " [用户派生/私有模型]"

            lines.append(f"\n{idx}. 理论标识: [THEORY:{cid}] 《{title}》{pref_tag}")
            if latex:
                lines.append(f"   核心公式: $${latex}$$")
            if mech:
                lines.append(f"   物理机制阐释: {mech}")
            conds = b.get("conditions")
            if conds and isinstance(conds, list) and conds:
                lines.append(f"   适用条件: {', '.join(str(c) for c in conds[:2])}")

        return "\n".join(lines)
