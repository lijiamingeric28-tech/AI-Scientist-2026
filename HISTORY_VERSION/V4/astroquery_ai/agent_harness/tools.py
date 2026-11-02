"""面向任务缓存的 6 大领域只读工具注册表 (Domain Tool Registry)
所有工具 100% 只读本地缓存，无外部网络依赖，返回学术精炼结构。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from .data_loader import TaskDataBundle


class DomainTools:
    """专精天体物理数据缓存调阅工具集。"""

    def __init__(self, bundle: TaskDataBundle):
        self.bundle = bundle

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """返回 OpenAI-Compatible Function Calling 工具定义。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "query_records",
                    "description": "从本次任务整理的结构化测定值列表中检索匹配记录，获取具体物理量数值、误差、单位、测定方法与置信度。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "天体物理性质名称（如 距离, 视差, distance, 年龄, age, 金属丰度, fe_h, 有效温度, 质量, 半径, 视向速度 等）"
                            },
                            "source_id": {
                                "type": "string",
                                "description": "指定文献 Bibcode 或数据源名称（可选）"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回记录最大条数，默认 5"
                            }
                        },
                        "required": ["property_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_record_provenance",
                    "description": "查询指定记录 ID 的底层提取溯源链（原文摘录、所属文献页码、提取方法及数据质检转换过程）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "record_id": {
                                "type": "string",
                                "description": "记录唯一标识符（例如从 query_records 获得的 ID）"
                            }
                        },
                        "required": ["record_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_literature",
                    "description": "检索本次任务涵盖的核心 ADS 文献库，调阅论文标题、作者团队、发表年份及学术摘要。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_terms": {
                                "type": "string",
                                "description": "检索关键词（例如天体名称与目标物理量：Betelgeuse radius, Sgr A* mass, distance controversy 等）"
                            },
                            "bibcode": {
                                "type": "string",
                                "description": "指定的论文 ADS Bibcode（可选）"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_conflicts_and_anomalies",
                    "description": "调阅质量管线针对多源测量分歧所生成的冲突仲裁案卷（包含争议数值、仲裁裁定采信值及裁决物理依据）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "property_name": {
                                "type": "string",
                                "description": "目标物理性质名称（如 distance, metallicity, age 等，可选）"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_figure_evidence",
                    "description": "调阅从文献中自动抽取的科学图表切片元数据（如赫罗图拟合、光谱图、误差残差图），获取图题与 PDF 原始坐标。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "figure_id": {
                                "type": "string",
                                "description": "指定的图证标识符（可选）"
                            },
                            "property_keyword": {
                                "type": "string",
                                "description": "与图表相关的物理量或特征词（如 isochrone, parallax, spectrum 等，可选）"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_domain_insights",
                    "description": "调阅本次任务生成的天体物理前沿洞察报告，获取物理机制总结、相关性分析与后续观测建议。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "section": {
                                "type": "string",
                                "enum": ["overall_narrative", "field_insights", "relationships", "recommendations", "all"],
                                "description": "想要调阅的洞察模块，默认为 all"
                            }
                        }
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """分发执行工具并格式化返回观测字符串（Observation）。"""
        try:
            if tool_name == "query_records":
                return self._query_records(
                    args.get("property_name", ""),
                    args.get("source_id"),
                    args.get("limit", 5)
                )
            elif tool_name == "get_record_provenance":
                return self._get_record_provenance(args.get("record_id", ""))
            elif tool_name == "search_literature":
                return self._search_literature(
                    args.get("query_terms", ""),
                    args.get("bibcode")
                )
            elif tool_name == "inspect_conflicts_and_anomalies":
                return self._inspect_conflicts(args.get("property_name", ""))
            elif tool_name == "get_figure_evidence":
                return self._get_figure_evidence(
                    args.get("figure_id"),
                    args.get("property_keyword", "")
                )
            elif tool_name == "get_domain_insights":
                return self._get_domain_insights(args.get("section", "all"))
            else:
                return f"未知工具: {tool_name}"
        except Exception as e:
            return f"工具执行异常: {str(e)}"

    def _query_records(self, prop: str, source_id: Optional[str], limit: int) -> str:
        matched = []
        prop_lower = prop.strip().lower()
        # 同义词映射
        alias_map = {
            "距离": ["dist", "distance", "parallax", "模数"],
            "视差": ["parallax", "plx"],
            "年龄": ["age", "cluster_age"],
            "金属丰度": ["fe_h", "feh", "metallicity"],
            "有效温度": ["teff", "temp", "temperature"],
            "视向速度": ["rv", "radial_velocity", "velocity"],
            "自转速度": ["vsini", "rotation"],
        }
        search_terms = [prop_lower] if prop_lower else []
        for k, v in alias_map.items():
            if k in prop_lower or prop_lower in k:
                search_terms.extend(v)

        for r in self.bundle.records:
            rp = str(r.get("field_name") or r.get("property_name") or "").lower()
            hit = not search_terms or any(term in rp for term in search_terms)
            if hit:
                if source_id:
                    sid = str(r.get("source_id") or "")
                    if source_id.lower() not in sid.lower():
                        continue
                matched.append(r)

        if not matched:
            matched = self.bundle.records[:limit]

        matched = matched[:limit]
        if not matched:
            return "未检索到匹配的记录。"

        lines = [f"共检索到 {len(matched)} 条相关记录:"]
        for r in matched:
            rid = r.get("record_id") or "REC-UNKNOWN"
            p = r.get("field_name") or r.get("property_name") or ""
            val = r.get("field_value") if r.get("field_value") is not None else r.get("value")
            unit = r.get("field_unit") or r.get("unit") or ""
            ep = r.get("error_plus")
            em = r.get("error_minus")
            err_str = f" +{ep}/-{em}" if ep is not None and em is not None else ""
            src = r.get("source_id") or ""
            method = r.get("measurement_method") or r.get("extraction_method") or r.get("method") or "未标明"
            conf = r.get("extraction_confidence") if r.get("extraction_confidence") is not None else r.get("confidence")
            conf_str = f" (置信度: {conf})" if conf is not None else ""
            lines.append(f"- 记录 [{rid}]: {p} = {val}{err_str} {unit} | 来源: {src} | 方法: {method}{conf_str}")
        return "\n".join(lines)

    def _get_record_provenance(self, record_id: str) -> str:
        rec = self.bundle.records_by_id.get(record_id)
        traces = self.bundle.trace_by_record_id.get(record_id, [])

        if not rec and not traces:
            for rid, r in self.bundle.records_by_id.items():
                if record_id.lower() in rid.lower():
                    rec = r
                    traces = self.bundle.trace_by_record_id.get(rid, [])
                    record_id = rid
                    break

        if not rec and not traces:
            return f"未找到记录 ID 为 {record_id} 的溯源链条。"

        lines = [f"【记录 {record_id} 溯源链详情】"]
        if rec:
            prov = rec.get("provenance") or {}
            val = rec.get("field_value") if rec.get("field_value") is not None else rec.get("value")
            unit = rec.get("field_unit") or rec.get("unit") or ""
            p = rec.get("field_name") or rec.get("property_name")
            lines.append(f"- 物理性质: {p} = {val} {unit}")
            lines.append(f"- 来源文献: {rec.get('source_id')}")
            if prov.get("page"):
                lines.append(f"- 所属页码: Page {prov.get('page')}")
            if prov.get("bbox"):
                lines.append(f"- 坐标定位: BBox {prov.get('bbox')}")
            ctx = rec.get("context_snippet") or prov.get("extracted_text")
            if ctx:
                lines.append(f"- 原文切片: \"{ctx}\"")

        for t in traces:
            lines.append(f"- 字段级提取: 原始值={t.get('raw_value')}, 规范化={t.get('normalized_value')}, 提取方式={t.get('method')}")

        return "\n".join(lines)

    def _search_literature(self, query: str, bibcode: Optional[str]) -> str:
        matched = []
        if bibcode:
            s = self.bundle.sources_by_bibcode.get(bibcode)
            if s:
                matched.append(s)

        if not matched:
            q_terms = [t.lower() for t in re.split(r"\s+", query) if len(t) > 2]
            for s in self.bundle.sources:
                title = str(s.get("title") or "").lower()
                abstract = str(s.get("abstract") or "").lower()
                authors = " ".join([str(a) for a in (s.get("authors") or [])]).lower()
                b = str(s.get("bibcode") or "").lower()

                score = 0
                for term in q_terms:
                    if term in title:
                        score += 3
                    if term in abstract:
                        score += 1
                    if term in authors or term in b:
                        score += 2
                if score > 0 or not q_terms:
                    matched.append((score, s))

            matched.sort(key=lambda x: x[0] if isinstance(x, tuple) else 0, reverse=True)
            matched = [item[1] if isinstance(item, tuple) else item for item in matched]

        matched = matched[:3]
        if not matched:
            return "文献库中未找到强相关的论文。"

        lines = [f"匹配到 {len(matched)} 篇相关文献:"]
        for s in matched:
            b = s.get("source_id") or s.get("bibcode") or "未知Bibcode"
            t = s.get("title") or "无标题"
            y = s.get("year") or ""
            auths = s.get("authors") or []
            auth_str = (auths[0] + " et al.") if auths else "未知作者"
            ab = s.get("abstract") or "未提供摘要"
            if len(ab) > 280:
                ab = ab[:280] + "..."
            lines.append(f"- [{b}] ({y}) {auth_str}: {t}\n  摘要: {ab}")
        return "\n".join(lines)

    def _inspect_conflicts(self, prop: str) -> str:
        conflicts = self.bundle.conflict_items
        if not conflicts:
            return "本次任务的质量研判报告中未发现显著的多源跨表冲突。"

        matched = []
        p_lower = prop.strip().lower()
        alias = {"距离": "distance", "视差": "parallax", "年龄": "age", "金属丰度": "fe_h"}
        check_p = alias.get(p_lower, p_lower)

        for c in conflicts:
            fld = str(c.get("field_name") or c.get("field") or "").lower()
            if not check_p or check_p in fld or fld in check_p:
                matched.append(c)

        if not matched:
            matched = conflicts[:3]

        lines = [f"调阅到 {len(matched)} 项多源冲突/异常仲裁案卷:"]
        for c in matched:
            fld = c.get("field_name") or c.get("field") or "未知字段"
            cid = c.get("conflict_id") or c.get("id") or f"CONF-{fld.upper()}"
            cause = c.get("inferred_cause") or c.get("arbitration_reason") or c.get("reason") or "观测方法或数据源系统差异"
            v_range = c.get("value_range") or []
            src_count = c.get("source_count") or len(c.get("source_ids") or [])
            src_details = c.get("source_details") or {}
            detail_str = ""
            if src_details:
                top_items = list(src_details.items())[:3]
                detail_str = " | 样本: " + ", ".join([f"{k}: {v.get('mean')}" for k, v in top_items if isinstance(v, dict)])
            lines.append(f"- 案卷 [{cid}] (物理量: {fld}): 覆盖 {src_count} 个数据源, 数值区间={v_range}\n  判定成因: {cause}{detail_str}")
        return "\n".join(lines)

    def _get_figure_evidence(self, fig_id: Optional[str], keyword: str) -> str:
        figs = self.bundle.figures
        if not figs:
            return "本次任务未提取到多模态图证切片。"

        matched = []
        if fig_id:
            f = self.bundle.figures_by_id.get(fig_id)
            if f:
                matched.append(f)

        if not matched:
            kw = keyword.strip().lower()
            for f in figs:
                cap = str(f.get("caption") or "").lower()
                if not kw or kw in cap:
                    matched.append(f)

        matched = (matched or figs)[:3]
        lines = [f"调阅到 {len(matched)} 幅科学图证切片:"]
        for f in matched:
            fid = f.get("figure_id") or f.get("id") or (Path(f.get("image_path", "")).stem if f.get("image_path") else "FIG-UNKNOWN")
            sid = f.get("source_id") or ""
            page = f.get("page") or ""
            cap = f.get("caption") or "科学图表切片"
            bbox = f.get("bbox_2d") or f.get("bbox") or []
            lines.append(f"- 图证 [{fid}]: 来自文献 {sid} 第 {page} 页 | BBox {bbox}\n  图题说明: {cap}")
        return "\n".join(lines)

    def _get_domain_insights(self, section: str) -> str:
        ins = self.bundle.insights
        if not ins or not isinstance(ins, dict):
            return "当前任务未生成专门的天体物理洞察报告。"

        out = []
        if section in ("overall_narrative", "all") and ins.get("overall_narrative"):
            out.append(f"【总体宏观物理叙述】\n{ins.get('overall_narrative')}")

        if section in ("field_insights", "all") and ins.get("field_insights"):
            fi = ins.get("field_insights")
            out.append("【各物理量深度见解】")
            if isinstance(fi, dict):
                for k, v in list(fi.items())[:3]:
                    out.append(f"- {k}: {v}")
            elif isinstance(fi, list):
                for item in fi[:3]:
                    out.append(f"- {item}")

        if section in ("relationships", "all") and ins.get("relationships"):
            rel = ins.get("relationships")
            out.append(f"【物理性质跨度关联】\n{json.dumps(rel, ensure_ascii=False) if isinstance(rel, (dict, list)) else str(rel)}")

        if section in ("recommendations", "all") and ins.get("recommendations"):
            rec = ins.get("recommendations")
            out.append(f"【后续观测与科研建议】\n{json.dumps(rec, ensure_ascii=False) if isinstance(rec, (dict, list)) else str(rec)}")

        return "\n\n".join(out) if out else "指定洞察板块内容为空。"
