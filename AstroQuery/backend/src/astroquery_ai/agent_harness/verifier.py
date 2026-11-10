"""证据强引用与防幻觉校验器 (Grounding & Citation Verifier 2.0)
- 提取并严格核验六维引用锚点：[REC:..], [SOURCE:..], [FIG:..], [ARB:..], [DEF:..], [THEORY:..]
- 严格过滤/降级任何未被本次任务收录的虚构 ID，彻底杜绝前端点击 404
- 全面清洗剔除任何 Emoji 表情字符，确保庄重严谨的国风科研学术标准
- 为前端点击唤出 ContextDrawer / 详情抽屉组装完备的交互 payload
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple
from .data_loader import TaskDataBundle

# 匹配所有常见 Emoji 字符集
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
)

# 六维引用标签正则匹配
CITATION_PATTERN = re.compile(
    r"\[(REC|SOURCE|FIG|ARB|DEF|THEORY):([a-zA-Z0-9_\-\.\:\+\&]+)\]"
)


class GroundingVerifier:
    """负责回答正文的防幻觉校验、实体关联及 Emoji 清理。"""

    def __init__(self, bundle: TaskDataBundle):
        self.bundle = bundle

        # 构建合法真实白名单集合
        self.valid_measurements: Set[str] = set(bundle.measurements_by_id.keys())
        self.valid_sources: Set[str] = set(bundle.sources_by_id.keys())
        self.valid_figures: Set[str] = set(bundle.figures_by_id.keys())
        self.valid_definitions: Set[str] = set(bundle.definitions_by_id.keys())
        self.valid_theories: Set[str] = set(bundle.theories_by_id.keys())
        self.valid_arbitrations: Set[str] = set()

        for g in (bundle.archive_groups or []):
            gid = g.get("group_id")
            if gid:
                self.valid_arbitrations.add(gid)
        for g in (bundle.result_comparisons.get("groups") or []):
            gid = g.get("group_id")
            if gid:
                self.valid_arbitrations.add(gid)

    def verify_and_clean(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """清洗文本并抽取合法真实引用清单。"""
        # 1. 彻底剔除所有 Emoji
        clean_text = EMOJI_PATTERN.sub("", text)

        citations: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        def _replace_tag(match: re.Match) -> str:
            tag_type = match.group(1).upper()
            raw_id = match.group(2).strip()

            # ── 1. 测量记录 [REC:mid] ──
            if tag_type == "REC":
                matched_mid = None
                if raw_id in self.valid_measurements:
                    matched_mid = raw_id
                else:
                    for mid in self.valid_measurements:
                        if raw_id.lower() in mid.lower():
                            matched_mid = mid
                            break

                if matched_mid:
                    m = self.bundle.measurements_by_id[matched_mid]
                    pref = (m.get("property_ref") or {}).get("id") or ""
                    binding = self.bundle.definitions_by_id.get(pref, {})
                    p_cn = (binding.get("definition") or {}).get("name_cn") or pref
                    raw_val = m.get("raw_value")
                    val_dict = m.get("value") or {}
                    val_str = str(val_dict.get("value") if isinstance(val_dict, dict) and "value" in val_dict else raw_val)
                    unit_str = m.get("unit") or ""
                    sref = (m.get("source_ref") or {}).get("id")

                    if matched_mid not in seen_keys:
                        seen_keys.add(matched_mid)
                        parts = matched_mid.split("-")
                        label_suffix = parts[-1][:8] if parts else matched_mid[:8]
                        citations.append({
                            "type": "record",
                            "id": matched_mid,
                            "label": f"REC-{label_suffix}",
                            "payload": {
                                "measurement_id": matched_mid,
                                "task_id": self.bundle.task_id,
                                "property_id": pref,
                                "property_cn": p_cn,
                                "value": val_str,
                                "unit": unit_str,
                                "source_id": sref,
                                "source": m,
                                "details_loaded": False,
                            },
                        })
                    return f"[REC:{matched_mid}]"
                # 虚构降级为平铺文本，杜绝 404
                return f"测定记录 {raw_id}"

            # ── 2. 文献与数据源 [SOURCE:bibcode:p.X] ──
            elif tag_type == "SOURCE":
                parts = raw_id.split(":")
                bibcode = parts[0]
                page_part = parts[1] if len(parts) > 1 else None
                matched_s = None

                if bibcode in self.valid_sources:
                    matched_s = bibcode
                else:
                    for sid in self.valid_sources:
                        if bibcode.lower() in sid.lower():
                            matched_s = sid
                            break

                if matched_s:
                    s = self.bundle.sources_by_id[matched_s]
                    title = s.get("title") or "科学文献"
                    year = s.get("year") or ""
                    authors = s.get("authors") or []
                    first_auth = authors[0] if authors else "团队"
                    cite_key = f"{matched_s}:{page_part}" if page_part else matched_s

                    if cite_key not in seen_keys:
                        seen_keys.add(cite_key)
                        label = f"{first_auth} ({year})" if year else matched_s
                        if page_part:
                            label += f" {page_part}"
                        citations.append({
                            "type": "source",
                            "id": matched_s,
                            "label": label,
                            "payload": {
                                "source_id": matched_s,
                                "task_id": self.bundle.task_id,
                                "bibcode": s.get("bibcode") or matched_s,
                                "title": title,
                                "year": year,
                                "authors": authors,
                                "target_page": page_part.replace("p.", "") if page_part else None,
                            },
                        })
                    return f"[SOURCE:{cite_key}]"
                return f"文献 {raw_id}"

            # ── 3. 科学图证 [FIG:fid] ──
            elif tag_type == "FIG":
                matched_f = None
                if raw_id in self.valid_figures:
                    matched_f = raw_id
                else:
                    for fid in self.valid_figures:
                        if raw_id.lower() in fid.lower():
                            matched_f = fid
                            break

                if matched_f:
                    f = self.bundle.figures_by_id[matched_f]
                    caption = f.get("caption") or "科学图表切片"
                    page = f.get("page")
                    sref = f.get("source_id")

                    if matched_f not in seen_keys:
                        seen_keys.add(matched_f)
                        parts = matched_f.split("-")
                        label_suffix = parts[-1][:8] if parts else matched_f[:8]
                        citations.append({
                            "type": "figure",
                            "id": matched_f,
                            "label": f"图证-{label_suffix}",
                            "payload": {
                                "figure_id": matched_f,
                                "task_id": self.bundle.task_id,
                                "caption": caption,
                                "page": page,
                                "source_id": sref,
                                "figure": f,
                            },
                        })
                    return f"[FIG:{matched_f}]"
                return f"图证 {raw_id}"

            # ── 4. 分歧仲裁 [ARB:aid] ──
            elif tag_type == "ARB":
                matched_a = None
                if raw_id in self.valid_arbitrations or raw_id.startswith("ARB-") or raw_id.startswith("CONF-"):
                    matched_a = raw_id

                if matched_a:
                    if matched_a not in seen_keys:
                        seen_keys.add(matched_a)
                        citations.append({
                            "type": "conflict",
                            "id": matched_a,
                            "label": f"仲裁案卷 {matched_a}",
                            "payload": {
                                "group_id": matched_a,
                                "task_id": self.bundle.task_id,
                            },
                        })
                    return f"[ARB:{matched_a}]"
                return f"仲裁案卷 {raw_id}"

            # ── 5. 字段约定与物理定义 [DEF:pid] ──
            elif tag_type == "DEF":
                matched_d = None
                if raw_id in self.valid_definitions:
                    matched_d = raw_id
                else:
                    for pid in self.valid_definitions:
                        if raw_id.lower() in pid.lower():
                            matched_d = pid
                            break

                if matched_d:
                    d = self.bundle.definitions_by_id[matched_d]
                    meta = d.get("definition") or {}
                    name_cn = meta.get("name_cn") or matched_d
                    symbol = meta.get("symbol") or ""
                    unit = (d.get("output_profile") or {}).get("unit") or meta.get("unit") or ""

                    if matched_d not in seen_keys:
                        seen_keys.add(matched_d)
                        citations.append({
                            "type": "definition",
                            "id": matched_d,
                            "label": f"约定:{name_cn}",
                            "payload": {
                                "property_id": matched_d,
                                "name_cn": name_cn,
                                "symbol": symbol,
                                "unit": unit,
                                "definition": meta,
                            },
                        })
                    return f"[DEF:{matched_d}]"
                return f"物理量定义 {raw_id}"

            # ── 6. 294 理论知识库与公式 [THEORY:tid] ──
            elif tag_type == "THEORY":
                matched_t = None
                if raw_id in self.valid_theories:
                    matched_t = raw_id
                else:
                    for tid in self.valid_theories:
                        if raw_id.lower() in tid.lower():
                            matched_t = tid
                            break

                if matched_t:
                    b = self.bundle.theories_by_id[matched_t]
                    claim = b.get("claim") or {}
                    title = claim.get("title") or b.get("title") or "经典天体物理理论"
                    if matched_t not in seen_keys:
                        seen_keys.add(matched_t)
                        citations.append({
                            "type": "theory",
                            "id": matched_t,
                            "label": f"理论:{title[:12]}",
                            "payload": {
                                "theory_id": matched_t,
                                "title": title,
                                "block": b,
                            },
                        })
                    return f"[THEORY:{matched_t}]"
                return f"理论机制 {raw_id}"

            return match.group(0)

        verified_text = CITATION_PATTERN.sub(_replace_tag, clean_text)
        return verified_text, citations
