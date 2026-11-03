"""Deterministic ADS queries, work identity, rank fusion and fair read quotas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from urllib.parse import unquote

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError


def literal(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
        raise DomainError("INVALID_SEARCH_LITERAL", "检索字面量无效", 422)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace('*', '\\*').replace('?', '\\?') + '"'


def clause(field: str, values: list[str], *, exact=False) -> str:
    if field not in {"abs", "object", "body", "bibcode", "doi", "identifier"} or not values:
        raise DomainError("INVALID_QUERY_AST", "检索条件不能为空或使用任意字段", 422)
    return ('=' if exact else '') + field + ":(" + " OR ".join(literal(v) for v in values) + ")"


def compile_queries(aliases: list[str], families: list[dict]) -> list[dict]:
    aliases = list(dict.fromkeys(aliases))[:16]
    if not aliases:
        raise DomainError("NO_VERIFIED_ALIASES", "查询没有已核验天体标识")
    plans = []
    # Retained for offline/legacy callers; production uses checked model
    # expressions. There is no name-only generation path.
    for layer in ("metadata", "body"):
        for family in families:
            concepts = sorted(set(family["search_concepts"]))[:16]
            if not concepts:
                raise DomainError("FAMILY_CONCEPTS_MISSING", "检索族没有审定检索概念")
            for ai in range(0, len(aliases), 8):
                for ci in range(0, len(concepts), 8):
                    a, c = aliases[ai : ai + 8], concepts[ci : ci + 8]
                    if layer == "metadata":
                        query = clause("abs", a, exact=True) + " AND " + clause("abs", c)
                    else:
                        query = (
                            "("
                            + clause("abs", a, exact=True)
                            + " OR "
                            + clause("body", a, exact=True)
                            + ") AND ("
                            + clause("abs", c)
                            + " OR "
                            + clause("body", c)
                            + ")"
                        )
                    query += " AND doctype:(article OR eprint)"
                    body = {
                        "family_id": family["family_id"],
                        "layer": layer,
                        "query": query,
                        "selected_property_ids": family["selected_property_ids"],
                        "phase": "direct",
                        "compiler_version": "ads-literal-identity-2",
                    }
                    plans.append({**body, "query_id": "query-" + digest(body)})
    return plans


def normalize_doi(raw: str) -> str:
    value = unquote(raw.strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value, flags=re.I):
        raise ValueError("invalid DOI")
    return value.casefold()


def normalize_arxiv(raw: str) -> tuple[str, int | None]:
    value = re.sub(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)", "", raw.strip(), flags=re.I)
    value = value.removesuffix(".pdf")
    match = re.fullmatch(r"((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7}))(?:v(\d+))?", value, flags=re.I)
    if not match:
        raise ValueError("invalid arXiv identifier")
    return match[1].casefold(), int(match[2]) if match[2] else None


def parse_record(document: dict) -> dict:
    bibcode = document.get("bibcode")
    if not isinstance(bibcode, str) or not bibcode:
        raise DomainError("PUBLICATION_ID_MISSING", "ADS记录没有可靠规范标识", 422)
    for field_name in (
        "title",
        "author",
        "doi",
        "identifier",
        "alternate_bibcode",
        "keyword",
        "esources",
    ):
        if field_name in document and (
            not isinstance(document[field_name], list)
            or any(not isinstance(v, str) for v in document[field_name])
        ):
            raise DomainError("PUBLICATION_SCHEMA", "ADS列表字段结构异常", 422, field=field_name)
    doctype = document.get("doctype")
    if doctype not in {"article", "eprint"}:
        raise DomainError("PUBLICATION_TYPE_EXCLUDED", "只允许研究论文和预印本", 422)
    flags = document.get("property", [])
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise DomainError("PUBLICATION_STATUS_SCHEMA", "来源资格标记结构异常", 422)
    if {flag.upper() for flag in flags} & {"RETRACTED", "WITHDRAWN"}:
        raise DomainError("PUBLICATION_DISQUALIFIED", "保存的元数据明确标为撤回或撤稿", 422)
    dois, arxivs, identifier_issues = [], [], []
    for raw in document.get("doi", []):
        try:
            dois.append(normalize_doi(raw))
        except ValueError:
            identifier_issues.append({"raw": raw, "reason": "invalid_doi"})
    for raw in document.get("identifier", []):
        try:
            arxivs.append(normalize_arxiv(raw))
        except ValueError:
            continue
    return {
        "bibcode": bibcode,
        "dois": sorted(set(dois)),
        "arxivs": sorted(set(arxivs), key=lambda x: (x[0], x[1] or 0)),
        "alternate_bibcodes": document.get("alternate_bibcode", []),
        "doctype": doctype,
        "titles": document.get("title", []),
        "authors": document.get("author", []),
        "abstract": document.get("abstract"),
        "year": document.get("year"),
        "esources": document.get("esources", []),
        "raw": document,
        "identifier_issues": identifier_issues,
    }


def deduplicate(records: list[dict]) -> tuple[list[dict], dict[str, str]]:
    parent = list(range(len(records)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    indexes = {}
    for i, record in enumerate(records):
        keys = [
            "bibcode:" + record["bibcode"],
            *["bibcode:" + b for b in record["alternate_bibcodes"]],
            *["doi:" + d for d in record["dois"]],
            *["arxiv:" + a[0] for a in record["arxivs"]],
        ]
        for key in keys:
            if key in indexes:
                other = indexes[key]
                # Two different published DOIs linked only by a shared arXiv ID
                # can represent a split preprint; do not close this ambiguity.
                first_dois, second_dois = set(record["dois"]), set(records[other]["dois"])
                if (
                    key.startswith("arxiv:")
                    and first_dois
                    and second_dois
                    and first_dois.isdisjoint(second_dois)
                ):
                    continue
                parent[root(i)] = root(other)
            else:
                indexes[key] = i
    components = {}
    for i, record in enumerate(records):
        components.setdefault(root(i), []).append(record)
    works, mapping = [], {}
    for component in components.values():
        keys = sorted({"doi:" + d for r in component for d in r["dois"]})
        if not keys:
            keys = sorted({"arxiv:" + a[0] for r in component for a in r["arxivs"]})
        canonical_key = keys[0] if keys else "bibcode:" + min(r["bibcode"] for r in component)
        work_id = "work-" + digest(canonical_key)
        work = {
            "work_id": work_id,
            "canonical_key": canonical_key,
            "records": sorted(component, key=lambda r: r["bibcode"]),
            "allowed_property_ids": [],
            "family_ids": [],
            "eligibility": "eligible_with_known_limits",
        }
        works.append(work)
        for record in component:
            mapping[record["bibcode"]] = work_id
    return sorted(works, key=lambda w: w["canonical_key"]), mapping


def ranked_queues(
    works: list[dict], mapping: dict[str, str], query_results: list[dict], family_order: list[str]
) -> dict[str, list[str]]:
    by_id = {work["work_id"]: work for work in works}
    best = {}
    from .ads_queries import query_memberships
    for physical in query_results:
      for membership in query_memberships(physical):
        query={**physical,**membership}
        seen = set()
        rank = 0
        for bibcode in query["bibcodes"]:
            wid = mapping.get(bibcode)
            if not wid or wid in seen:
                continue
            seen.add(wid)
            rank += 1
            key = (query["family_id"], query["layer"], wid)
            best[key] = min(best.get(key, rank), rank)
            work = by_id[wid]
            work["family_ids"] = sorted(set(work["family_ids"]) | {query["family_id"]})
            work["allowed_property_ids"] = sorted(
                set(work["allowed_property_ids"]) | set(query["selected_property_ids"])
            )
    result = {}
    for family in family_order:
        scored = []
        for work in works:
            score = sum(
                (
                    Fraction(weight, 60 + best[(family, layer, work["work_id"])])
                    for layer, weight in (("metadata", 3), ("body", 1))
                    if (family, layer, work["work_id"]) in best
                ),
                start=Fraction(0),
            )
            if score:
                scored.append((score, work["canonical_key"], work["work_id"]))
        result[family] = [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return result


def fair_candidate_order(queues, work_families, family_order, limit):
    """Metadata retention/root order only. This never grants semantic reading."""
    chosen, served, credited = [], set(), dict.fromkeys(family_order, 0)
    while len(chosen) < limit:
        available = {
            fid: [wid for wid in queues.get(fid, []) if wid not in chosen] for fid in family_order
        }
        eligible = [fid for fid in family_order if available[fid] and fid not in served]
        if not eligible:
            if not any(available.values()):
                break
            served.clear()
            eligible = [fid for fid in family_order if available[fid]]
        sponsor = min(eligible, key=lambda fid: (credited[fid], family_order.index(fid)))
        wid = available[sponsor][0]
        chosen.append(wid)
        for fid in work_families[wid]:
            served.add(fid)
            credited[fid] += 1
    return chosen






@dataclass
class FairReadLedger:
    """Serialize this whole state in the same transaction as a selection/grant."""

    family_order: list[str]
    queues: dict[str, list[str]]
    work_families: dict[str, list[str]]
    selections: dict[str, dict] = field(default_factory=dict)
    served: list[str] = field(default_factory=list)
    credited: dict[str, int] = field(default_factory=dict)
    round_id: int = 1
    maximum_works: int = 40
    # Old snapshots may retain their historical limit. Normal runs traverse the
    # finite candidate pool until forty actual reads have been consumed.
    maximum_attempts: int | None = None

    def select(self) -> dict | None:
        if (
            (self.maximum_attempts is not None and len(self.selections) >= self.maximum_attempts)
            or sum(
                s["state"] in {"reserved", "consumed", "unknown_outcome"}
                for s in self.selections.values()
            )
            >= self.maximum_works
        ):
            return None
        available = {
            family: [wid for wid in self.queues.get(family, []) if wid not in self.selections]
            for family in self.family_order
        }
        eligible = [
            family
            for family in self.family_order
            if available[family] and family not in self.served
        ]
        if not eligible:
            if not any(available.values()):
                return None
            self.round_id += 1
            self.served = []
            eligible = [family for family in self.family_order if available[family]]

        def opportunities(family):
            reserved = sum(
                s["state"] == "reserved" and family in s["families"]
                for s in self.selections.values()
            )
            return self.credited.get(family, 0) + reserved

        sponsor = min(
            eligible, key=lambda family: (opportunities(family), self.family_order.index(family))
        )
        wid = available[sponsor][0]
        families = [f for f in self.family_order if f in self.work_families[wid]]
        self.served = list(dict.fromkeys([*self.served, *families]))
        selection = {
            "work_id": wid,
            "selection_index": len(self.selections) + 1,
            "round_id": self.round_id,
            "sponsor": sponsor,
            "families": families,
            "state": "reserved",
        }
        self.selections[wid] = selection
        return selection

    def consume(self, work_id: str, *, unknown=False):
        selected = self.selections.get(work_id)
        if not selected or selected["state"] not in {"reserved", "consumed", "unknown_outcome"}:
            raise DomainError("READ_GRANT_MISSING", "作品没有合法阅读名额")
        if selected["state"] == "reserved":
            for family in selected["families"]:
                self.credited[family] = self.credited.get(family, 0) + 1
            selected["state"] = "unknown_outcome" if unknown else "consumed"

    def preflight_failed(self, work_id: str):
        selected = self.selections[work_id]
        if selected["state"] != "reserved":
            raise DomainError("READ_SLOT_CONSUMED", "实际阅读或未知调用已经占用名额，不能退回")
        selected["state"] = "released"
