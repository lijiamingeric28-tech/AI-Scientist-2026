"""Resolve answer references against the immutable delivery, not model metadata."""

from __future__ import annotations

import hashlib
import re

from .data_loader import source_metadata

CITATION_PATTERN = re.compile(r"\[(REC|SOURCE|FIG|ARB|DEF|THEORY):([a-zA-Z0-9_.:/+&#-]+)\]")
MARKER = re.compile(r"(REC|SOURCE|FIG|ARB|DEF|THEORY):([a-zA-Z0-9_.:/+&#-]+)")
EMOJI_PATTERN = re.compile(r"[\U0001f300-\U0001faff\u2600-\u27bf]")
_TYPES = {
    "REC": "record", "SOURCE": "source", "FIG": "figure", "ARB": "conflict",
    "DEF": "definition", "THEORY": "theory",
}
_NAMES = {
    "REC": "测量", "SOURCE": "文献", "FIG": "图像", "ARB": "对照",
    "DEF": "物理量定义", "THEORY": "理论",
}


def artifact_id(artifact):
    return (artifact or {}).get("id") or (artifact or {}).get("artifact_id")


class GroundingVerifier:
    def __init__(self, bundle):
        self.bundle = bundle

    def resolve(self, marker):
        parsed = MARKER.fullmatch(marker.strip().strip("[]")) if isinstance(marker, str) else None
        if not parsed:
            return None
        tag, key = parsed.groups()
        b = self.bundle
        detail = {}
        if tag == "REC":
            record = b.measurements_by_id.get(key)
            if not record:
                return None
            pid = (record.get("property_ref") or {}).get("id")
            name = (b.definitions_by_id.get(pid, {}).get("definition") or {}).get("name_cn") or "测量"
            value = record.get("raw_value") or (record.get("value") or {}).get("value")
            label = f"{name} · {str(value)[:42]}" if value is not None else name
            source_id = (record.get("source_ref") or {}).get("id")
            detail = {"measurement_id": key, "property_id": pid, "source": b.source(source_id)}
        elif tag == "SOURCE":
            source_key, _, page_text = key.partition(":p.")
            source = b.source(source_key)
            if not source:
                return None
            key = source["source_id"]
            metadata = source_metadata(source)
            authors = metadata.get("authors") or []
            first = str(authors[0]).split(",")[0] if authors else None
            title = metadata.get("title") or "来源资料"
            label = f"{first} {metadata['year']}" if first and metadata.get("year") else title[:46]
            detail = {"source_id": key, "source": source}
            if page_text.isdecimal():
                page = int(page_text)
                points = b.paper_pages.get((key, page), [])
                if points:
                    view, point = max(points, key=lambda item: bool(item[1].get("bbox")))
                    original = artifact_id(view.get("artifact_ref"))
                    if original:
                        detail.update(page=page, artifact_id=original, point=point)
                else:
                    figure = next((f for f in b.figures if f.get("source_id") == key and
                                   f.get("page") == page and f.get("pdf_artifact_id")), None)
                    if figure:
                        detail.update(page=page, artifact_id=figure["pdf_artifact_id"])
                if detail.get("page"):
                    key += f":p.{page}"
                    label += f" · 第 {page} 页"
        elif tag == "FIG":
            figure = b.figures_by_id.get(key)
            if not figure:
                return None
            label = figure.get("label") or (f"第 {figure['page']} 页图像" if figure.get("page") else "研究图像")
            detail = {"figure": figure, "source": b.source(figure.get("source_id"))}
        elif tag == "ARB":
            group = b.comparisons_by_id.get(key)
            if not group:
                return None
            label = (b.definitions_by_id.get(group.get("property_id"), {}).get("definition") or {}).get("name_cn")
            label = f"{label}对照" if label else "测量对照"
            detail = {"group": group}
        elif tag == "DEF":
            binding = b.definitions_by_id.get(key)
            if not binding:
                return None
            label = (binding.get("definition") or {}).get("name_cn") or "性质定义"
            detail = {"binding": binding}
        else:
            block = b.theories_by_id.get(key)
            if not block:
                return None
            label = block.get("title") or (block.get("claim") or {}).get("title") or "科学知识"
            detail = {"block": block}
        normalized = f"{tag}:{key}"
        return {
            "citation_id": hashlib.sha256(normalized.encode()).hexdigest()[:24],
            "type": _TYPES[tag], "id": key, "marker": normalized, "label": label,
            "payload": detail,
        }

    def verify_and_clean(self, text):
        citations = {}

        def replace(match):
            citation = self.resolve(f"{match[1]}:{match[2]}")
            if citation:
                citations[citation["citation_id"]] = citation
                return f"[{citation['marker']}]"
            return f"{_NAMES[match[1]]} {match[2]}"

        return CITATION_PATTERN.sub(replace, EMOJI_PATTERN.sub("", text)), list(citations.values())
