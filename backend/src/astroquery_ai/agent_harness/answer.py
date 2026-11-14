"""Typed answer blocks and their projection from a pinned scientific delivery."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic_core import from_json

from .data_loader import source_metadata
from .verifier import artifact_id


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Block(Spec):
    title: str = ""
    refs: list[str] = Field(default_factory=list, max_length=24)


class Text(Block):
    type: Literal["text"]
    markdown: str


class Variable(Spec):
    symbol: str
    description: str
    unit: str = ""
    value: str = ""


class Formula(Block):
    type: Literal["formula"]
    latex: str
    variables: list[Variable] = Field(default_factory=list, max_length=16)


Column = Literal["property", "original", "value", "unit", "error", "method", "conditions", "source", "year"]


class Table(Block):
    type: Literal["table"]
    record_ids: list[str] = Field(min_length=1, max_length=100)
    columns: list[Column] = Field(default_factory=list, max_length=9)


class Chart(Block):
    type: Literal["chart"]
    record_ids: list[str] = Field(min_length=1, max_length=100)
    chart_type: Literal["dot", "interval", "scatter", "line", "bar"] = "interval"
    x: Literal["source", "year", "index"] = "source"


class CompareItem(Block):
    markdown: str
    record_ids: list[str] = Field(default_factory=list, max_length=8)


class Compare(Block):
    type: Literal["compare"]
    items: list[CompareItem] = Field(min_length=2, max_length=6)


class Gallery(Block):
    type: Literal["gallery"]
    figure_ids: list[str] = Field(default_factory=list, max_length=12)


class Node(Spec):
    id: str
    label: str
    description: str = ""
    latex: str = ""
    refs: list[str] = Field(default_factory=list, max_length=5)


class Edge(Spec):
    source: str
    target: str
    label: str = ""


class Relation(Block):
    type: Literal["relation"]
    nodes: list[Node] = Field(min_length=2, max_length=14)
    edges: list[Edge] = Field(max_length=24)
    layout: Literal["flow", "network"] = "flow"


class Parameter(Spec):
    name: str
    label: str
    unit: str = ""
    min: float
    max: float
    step: float
    value: float
    choices: list[float] = Field(default_factory=list, max_length=12)


class Explore(Block):
    type: Literal["explore"]
    latex: str
    expression: str = Field(max_length=350)
    parameters: list[Parameter] = Field(min_length=1, max_length=6)
    x: str
    y_label: str
    y_unit: str = ""


BlockSpec = Text | Formula | Table | Chart | Compare | Gallery | Relation | Explore
BLOCK_SPEC = TypeAdapter(BlockSpec)


class AnswerSpec(Spec):
    blocks: list[BlockSpec] = Field(min_length=1, max_length=20)


def provider_format():
    schema = AnswerSpec.model_json_schema()

    def make_required(node):
        if isinstance(node, list):
            for part in node:
                make_required(part)
        elif isinstance(node, dict):
            if "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            node.pop("default", None)
            if "const" in node:
                node["enum"] = [node.pop("const")]
            for part in node.values():
                make_required(part)

    make_required(schema)
    return {"type": "json_schema", "json_schema": {
        "name": "research_answer", "strict": True, "schema": schema,
    }}


def _value_text(value, limit=None):
    if value.get("kind") == "interval":
        return f"[{value.get('lower', '…')}, {value.get('upper', '…')}]"
    raw = value.get("value")
    if raw is None:
        return ""
    return {"upper": "≤ ", "lower": "≥ "}.get(limit, "") + str(raw)


def _plain_value(value):
    if isinstance(value, dict):
        return value.get("text") or value.get("value") or value.get("raw_text") or ""
    return value


def measurement_row(bundle, record):
    mid = record["measurement_id"]
    pid = (record.get("property_ref") or {}).get("id")
    binding = bundle.definitions_by_id.get(pid, {})
    definition = binding.get("definition") or {}
    profile = binding.get("output_profile") or {}
    derived = bundle.derived_by_mid.get(mid) or {}
    converted = derived.get("main_state") == "ready" and bool(derived.get("value_typed"))
    value = (derived["value_typed"] if converted else record.get("value")) or {}
    limit = derived.get("limit") if converted else record.get("limit")
    limit = limit or record.get("limit")
    unit_decl = profile.get("unit") or {}
    unit = unit_decl.get("canonical_symbol") if converted and isinstance(unit_decl, dict) else record.get("unit")
    unit = unit or record.get("unit") or ""
    raw_unc = (record.get("uncertainty") or {}).get("components") or []
    plot_unc = raw_unc
    if converted:
        plot_unc = [c["output_component"] for c in (derived.get("uncertainty_typed") or {}).get("components", [])
                    if c.get("output_component") and c.get("status") in {"identity", "exact", "approximate"}]
    context = bundle.contexts_by_id.get((record.get("context_ref") or {}).get("id"), {})
    conditions = [(str(c.get("key") or ""), str(_plain_value(c["value"]))) for c in context.get("conditions", [])
                  if c.get("value") is not None and _plain_value(c["value"]) not in ("", None)]
    source_id = (record.get("source_ref") or {}).get("id")
    source = bundle.source(source_id) or {}
    meta = source_metadata(source)
    authors = meta.get("authors") or []
    first = str(authors[0]).split(",")[0] if authors else None
    source_label = f"{first} {meta['year']}" if first and meta.get("year") else meta.get("title")
    representation = (profile.get("representation") or {}).get("kind") if converted else record.get("representation")
    errors = []
    for part in raw_unc:
        if part.get("raw_text"):
            errors.append(part["raw_text"])
    return {
        "id": mid, "property_id": pid, "property": definition.get("name_cn") or pid,
        "original": record.get("raw_value") or _value_text(record.get("value") or {}, record.get("limit")),
        "original_unit": record.get("unit") or "", "value": _value_text(value, limit),
        "typed": value, "limit": limit, "unit": unit, "representation": representation,
        "error": "；".join(errors), "error_components": [
            {k: part.get(k) for k in ("kind", "role", "values", "raw_text", "level")}
            for part in plot_unc if part.get("values")
        ],
        "method": "；".join(val for key, val in conditions if "method" in key.lower() or "方法" in key),
        "conditions": "；".join(val for _, val in conditions),
        "source": source_label or "来源资料", "source_id": source_id,
        "source_title": meta.get("title"), "year": meta.get("year"),
        "target_id": (record.get("target_ref") or {}).get("id"),
    }


class AnswerProjection:
    """Build UI payloads with the same citation resolver used by answer prose."""

    def __init__(self, bundle, verifier):
        self.bundle = bundle
        self.verifier = verifier

    def block(self, raw, index):
        block_id = f"b{index + 1}"
        try:
            spec = BLOCK_SPEC.validate_python(raw)
        except ValidationError:
            return self.missing(block_id, raw)
        block = spec.model_dump()
        citations = {}

        def attach(citation):
            if citation:
                citations[citation["citation_id"]] = citation
                return citation["citation_id"]
            return None

        def refs(markers):
            return list(dict.fromkeys(cid for marker in markers if (cid := attach(self.verifier.resolve(marker)))))

        def prose(text):
            text, found = self.verifier.verify_and_clean(text)
            for citation in found:
                attach(citation)
            return text

        def rows(ids):
            output = []
            for mid in dict.fromkeys(ids):
                record = self.bundle.measurements_by_id.get(mid)
                if record:
                    row = measurement_row(self.bundle, record)
                    row["citation_id"] = attach(self.verifier.resolve(f"REC:{mid}"))
                    row["source_citation_id"] = attach(self.verifier.resolve(f"SOURCE:{row['source_id']}"))
                    output.append(row)
            return output

        block["id"] = block_id
        block["refs"] = refs(spec.refs)
        if isinstance(spec, Text):
            block["markdown"] = prose(spec.markdown)
        elif isinstance(spec, (Table, Chart)):
            block["rows"] = rows(spec.record_ids)
            if not block["rows"]:
                return self.missing(block_id, raw)
        elif isinstance(spec, Compare):
            for item in block["items"]:
                item["markdown"] = prose(item["markdown"])
                item["refs"] = refs(item["refs"])
                item["rows"] = rows(item["record_ids"])
        elif isinstance(spec, Gallery):
            items = []
            for fid in dict.fromkeys(spec.figure_ids):
                citation = self.verifier.resolve(f"FIG:{fid}")
                if citation:
                    figure = citation["payload"]["figure"]
                    cid = attach(citation)
                    items.append({
                        "id": fid, "label": citation["label"], "caption": figure.get("caption"),
                        "source": figure.get("source_title"), "page": figure.get("page"),
                        "image_artifact_id": artifact_id(figure.get("image_artifact")),
                        "citation_id": cid,
                    })
            block["items"] = items
            if not items and not block["refs"]:
                return self.missing(block_id, raw)
        elif isinstance(spec, Relation):
            nodes = {n.id for n in spec.nodes}
            if len(nodes) != len(spec.nodes) or any(e.source not in nodes or e.target not in nodes for e in spec.edges):
                return self.missing(block_id, raw)
            for node in block["nodes"]:
                node["refs"] = refs(node["refs"])
        elif isinstance(spec, Explore):
            names = {p.name for p in spec.parameters}
            if len(names) != len(spec.parameters) or spec.x not in names or any(
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", p.name) or not p.min <= p.value <= p.max
                or p.min >= p.max or p.step <= 0 or any(not p.min <= c <= p.max for c in p.choices)
                for p in spec.parameters
            ):
                return self.missing(block_id, raw)
        return block, list(citations.values())

    @staticmethod
    def missing(block_id, raw):
        kind = raw.get("type", "") if isinstance(raw, dict) else ""
        title = raw.get("title", "") if isinstance(raw, dict) else ""
        return {
            "id": block_id,
            "type": "unavailable",
            "kind": kind if isinstance(kind, str) else "",
            "title": title if isinstance(title, str) else "",
        }, []


def answer_text(blocks):
    """Plain Markdown for older clients and subsequent model turns."""
    parts = []
    for block in blocks:
        if block.get("title"):
            parts.append("### " + block["title"])
        kind = block["type"]
        if kind == "text":
            parts.append(block["markdown"])
        elif kind in {"formula", "explore"}:
            parts.append("$$\n" + block["latex"] + "\n$$")
        elif kind in {"table", "chart"}:
            for row in block["rows"][:40]:
                parts.append(f"- {row['property']}：{row['original']} {row['original_unit']} [REC:{row['id']}]")
        elif kind == "compare":
            parts.extend(item["markdown"] for item in block["items"])
        elif kind == "gallery":
            parts.extend(f"- {item['label']} [FIG:{item['id']}]" for item in block["items"])
        elif kind == "relation":
            parts.extend(f"- {node['label']}：{node['description']}" for node in block["nodes"])
    return "\n\n".join(parts)


_BLOCKS_OPEN = re.compile(r'"blocks"\s*:\s*\[')
_JSON = json.JSONDecoder()


def stream_specs(raw):
    """Complete blocks, followed by the growing Markdown of a text block."""
    start = _BLOCKS_OPEN.search(raw)
    if not start:
        return [], None
    index = start.end()
    complete = []
    while index < len(raw):
        while index < len(raw) and raw[index] in " \r\n\t,":
            index += 1
        if index >= len(raw) or raw[index] == "]":
            return complete, None
        try:
            item, index = _JSON.raw_decode(raw, index)
        except json.JSONDecodeError:
            try:
                item = from_json(raw[index:], allow_partial="trailing-strings")
            except ValueError:
                return complete, None
            return complete, item if isinstance(item, dict) and item.get("type") == "text" else None
        complete.append(item)
    return complete, None
