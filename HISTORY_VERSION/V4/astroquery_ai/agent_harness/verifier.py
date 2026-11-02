"""证据强引用与防幻觉校验器 (Grounding & Citation Verifier)
- 提取并校验四维引用锚点：[REC:..], [SOURCE:..], [FIG:..], [ARB:..]
- 严格过滤/降级虚构 ID，防点击 404
- 全面清洗剔除任何 Emoji 字符，确保符合国风严谨科研标准
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple
from .data_loader import TaskDataBundle

# 匹配所有常见 Emoji 范围
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
)

# 引用标签提取正则
CITATION_PATTERN = re.compile(
    r"\[(REC|SOURCE|FIG|ARB):([a-zA-Z0-9_\-\.\:\+\&]+)\]"
)


class GroundingVerifier:
    """负责回答正文的防幻觉校验、实体关联及 Emoji 清理。"""

    def __init__(self, bundle: TaskDataBundle):
        self.bundle = bundle
        self.valid_record_ids: Set[str] = set(bundle.records_by_id.keys())
        self.valid_bibcodes: Set[str] = set(bundle.sources_by_bibcode.keys())
        self.valid_figure_ids: Set[str] = set(bundle.figures_by_id.keys())
        self.valid_conflict_ids: Set[str] = set()

        for c in bundle.conflict_items:
            fld = (c.get("field_name") or c.get("field") or "UNKNOWN").upper()
            cid = c.get("conflict_id") or c.get("id") or f"CONF-{fld}"
            self.valid_conflict_ids.add(cid)
            self.valid_conflict_ids.add(f"CONF-{fld}")

    def verify_and_clean(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """清洗文本并抽取合法引用清单。"""
        # 1. 彻底剔除所有 Emoji
        clean_text = EMOJI_PATTERN.sub("", text)

        citations: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        def _replace_tag(match: re.Match) -> str:
            tag_type = match.group(1).upper()
            raw_id = match.group(2).strip()

            if tag_type == "REC":
                matched_id = None
                if raw_id in self.valid_record_ids:
                    matched_id = raw_id
                else:
                    for rid in self.valid_record_ids:
                        if raw_id.lower() in rid.lower():
                            matched_id = rid
                            break
                if matched_id:
                    rec = self.bundle.records_by_id[matched_id]
                    p = rec.get("field_name") or rec.get("property_name") or ""
                    v = rec.get("field_value") if rec.get("field_value") is not None else rec.get("value")
                    u = rec.get("field_unit") or rec.get("unit") or ""
                    conf = rec.get("extraction_confidence") if rec.get("extraction_confidence") is not None else rec.get("confidence")
                    if matched_id not in seen_keys:
                        seen_keys.add(matched_id)
                        parts = matched_id.split('_')
                        label_suffix = f"{parts[-2]}_{parts[-1]}" if len(parts) >= 2 else matched_id
                        citations.append({
                            "type": "record",
                            "id": matched_id,
                            "label": f"REC-{label_suffix}",
                            "payload": {
                                "property": p,
                                "value": v,
                                "unit": u,
                                "source_id": rec.get("source_id"),
                                "confidence": conf,
                            }
                        })
                    return f"[REC:{matched_id}]"
                return f"测定记录 {raw_id}"

            elif tag_type == "SOURCE":
                parts = raw_id.split(":")
                bibcode = parts[0]
                page_info = f":{parts[1]}" if len(parts) > 1 else ""
                matched_b = None
                if bibcode in self.valid_bibcodes:
                    matched_b = bibcode
                else:
                    for b in self.valid_bibcodes:
                        if bibcode.lower() in b.lower():
                            matched_b = b
                            break
                if matched_b:
                    src = self.bundle.sources_by_bibcode[matched_b]
                    auths = src.get("authors") or []
                    first_auth = auths[0] if auths else "et al."
                    if matched_b not in seen_keys:
                        seen_keys.add(matched_b)
                        citations.append({
                            "type": "source",
                            "id": matched_b,
                            "label": f"{matched_b[:19]}{page_info}",
                            "payload": {
                                "title": src.get("title"),
                                "year": src.get("year"),
                                "first_author": first_auth,
                                "abstract": src.get("abstract"),
                            }
                        })
                    return f"[SOURCE:{matched_b}{page_info}]"
                return f"文献 {bibcode}"

            elif tag_type == "FIG":
                matched_fid = None
                if raw_id in self.valid_figure_ids:
                    matched_fid = raw_id
                else:
                    for fid in self.valid_figure_ids:
                        if raw_id.lower() in fid.lower():
                            matched_fid = fid
                            break
                if matched_fid:
                    fig = self.bundle.figures_by_id[matched_fid]
                    if matched_fid not in seen_keys:
                        seen_keys.add(matched_fid)
                        citations.append({
                            "type": "figure",
                            "id": matched_fid,
                            "label": f"图证 {matched_fid}",
                            "payload": {
                                "source_id": fig.get("source_id"),
                                "page": fig.get("page"),
                                "caption": fig.get("caption"),
                                "bbox": fig.get("bbox_2d") or fig.get("bbox"),
                            }
                        })
                    return f"[FIG:{matched_fid}]"
                return f"科学图表 {raw_id}"

            elif tag_type == "ARB":
                matched_cid = None
                if raw_id in self.valid_conflict_ids:
                    matched_cid = raw_id
                else:
                    for cid in self.valid_conflict_ids:
                        if raw_id.lower() in cid.lower():
                            matched_cid = cid
                            break
                if matched_cid:
                    if matched_cid not in seen_keys:
                        seen_keys.add(matched_cid)
                        citations.append({
                            "type": "conflict",
                            "id": matched_cid,
                            "label": f"仲裁 {matched_cid}",
                            "payload": {"conflict_id": matched_cid}
                        })
                    return f"[ARB:{matched_cid}]"
                return f"仲裁案卷 {raw_id}"

            return match.group(0)

        verified_text = CITATION_PATTERN.sub(_replace_tag, clean_text)
        return verified_text, citations
