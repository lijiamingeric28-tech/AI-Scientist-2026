"""Index of source contributions within one published scientific snapshot."""

from collections import Counter, defaultdict

from astroquery_ai.application.result_views import materials
from astroquery_ai.runtime.errors import DomainError


def first_title(material):
    title = material.get("title")
    return next(iter(title), "") if isinstance(title, list) else title or ""


def artifact_id(reference):
    if isinstance(reference, str):
        return reference
    return (reference or {}).get("artifact_id") or (reference or {}).get("id")


def figure_view(task_id, figure):
    route = f"/api/tasks/{task_id}/artifacts"
    image = artifact_id(figure.get("image_artifact"))
    page = artifact_id(figure.get("page_artifact"))
    pdf = figure.get("pdf_artifact_id")
    return {
        **figure,
        "image_url": f"{route}/{image}" if image else None,
        "page_url": f"{route}/{page}" if page else None,
        "pdf_url": f"{route}/{pdf}#page={figure['page']}" if pdf else None,
    }


def _table_identity(material):
    table = (material.get("association") or {}).get("source_table_id") or material.get("table_id")
    data = artifact_id(material.get("artifact"))
    return (table, data) if table and data else None


def has_material_content(group):
    root = group["root"]
    return bool(root.get("abstract") or root.get("readme") or root.get("metadata") or group["attachment_ids"]
                or any(p["records"] or p["figures"] for p in group["by_property"].values()))


def material_overview(body, index=None):
    """Count substantive material/property entries in the pinned delivery."""
    report = body.get("insight_report") or {}
    if report.get('schema_version') == 'InsightBundle/1':
        report = report.get('material_report') or {}
    counts = report.get("counts") if report.get("schema_version") == "MaterialSummaryReport/1" else None
    bindings = body.get("definitions", [])
    if bindings and not counts and index is None:
        return None
    coverage = Counter()
    if not counts and index is not None:
        coverage.update(entry["property_id"] for entry in index.entries
                        if entry["property_id"] and has_material_content(index.groups[entry["group_id"]]))
    properties = []
    for binding in bindings:
        pid = binding["property_id"]
        row = counts.get(pid, {}) if counts else {}
        properties.append({
            "property_id": pid, "name": binding["definition"]["name_cn"],
            "total": row.get("requested", 0) if counts else coverage[pid],
            "ready": row.get("ready", 0) if counts or report.get("status") == "pending" else None,
            "failed": row.get("failed", 0) if counts or report.get("status") == "pending" else None,
        })
    return {"total": sum(row["total"] for row in properties),
            "state": report.get("status") if report.get("schema_version") == "MaterialSummaryReport/1" else "not_recorded",
            "properties": properties}


class MaterialIndex:
    def __init__(self, body, preparation=None):
        self.names = {d["property_id"]: d["definition"]["name_cn"] for d in body.get("definitions", [])}
        self.materials = {m["material_id"]: m for m in materials(body)}
        self.records = {m["measurement_id"]: m for m in body["measurements"]}
        self.figures = {f["figure_id"]: f for f in body.get("figures", [])}
        self.works = {}
        by_bibcode = defaultdict(set)
        for mid, material in self.materials.items():
            if material.get("kind") != "paper":
                continue
            work_id = (material.get("work") or {}).get("work_id") or material.get("work_id")
            if work_id:
                self.works[work_id] = mid
            if bibcode := material.get("bibcode"):
                by_bibcode[bibcode].add(mid)

        self.source_group = {}
        attached_tables = defaultdict(list)
        for mid, material in self.materials.items():
            if material.get("kind") != "official_attachment":
                continue
            association = material.get("association") or {}
            parent = material.get("parent_material_id")
            if not parent:
                matching = set().union(*(by_bibcode[b] for b in association.get("parent_bibcodes", [])))
                parent = next(iter(matching)) if len(matching) == 1 else None
            self.source_group[mid] = parent if parent in self.materials else mid
            if key := _table_identity(material):
                attached_tables[key].append(mid)

        self.attachment_aliases = {}
        members = defaultdict(list)
        for mid, material in self.materials.items():
            group_id = self.source_group.get(mid)
            if group_id is None and material.get("kind") == "catalog":
                attachments = attached_tables.get(_table_identity(material), [])
                if len(attachments) == 1:
                    self.attachment_aliases[mid] = attachments[0]
                    group_id = self.source_group[attachments[0]]
            self.source_group[mid] = group_id or mid
            members[group_id or mid].append(mid)

        read = defaultdict(set)
        bundle = body.get("provenance_bundle") or {}
        for scope in bundle.get("completion_scope", []):
            for material in scope.get("materials", []):
                key = material["material_id"]
                if key.startswith("paper:"):
                    key = self.works.get(key.removeprefix("paper:"), key)
                read[key].update(r.get("property_id") for r in material.get("ranges", []))
        for pid, pool in (preparation or {}).get("pools", {}).items():
            for work_id in pool.get("acquired", []):
                if work_id in self.works:
                    read[self.works[work_id]].add(pid)
        for row in body.get("coverage", []):
            source = row.get("source_id")
            if source in self.materials and row.get("property_id"):
                read[source].add(row["property_id"])

        self.groups = {}
        self.entries = []
        for group_id, ids in members.items():
            self.groups[group_id] = self._group(group_id, ids, read)
        for pid in (*self.names, None):
            self.entries.extend(
                self._entry(group, pid) for group in self.groups.values() if pid in group["properties"]
            )

    def _group(self, group_id, ids, read):
        root = self.materials[group_id]
        properties = set()
        by_property = defaultdict(lambda: {"records": [], "figures": []})
        cited_properties = set()
        for mid in ids:
            material = self.materials[mid]
            work = material.get("work") or {}
            properties.update(read[mid])
            properties.update(work.get("allowed_property_ids", []))
            for record_id in material.get("record_ids", []):
                pid = self.records[record_id]["property_ref"]["id"]
                properties.add(pid)
                by_property[pid]["records"].append(record_id)
            for figure in material.get("figures", []):
                figure_properties = set(figure.get("property_ids") or []) & self.names.keys()
                if not figure_properties:
                    figure_properties = {None}
                for pid in figure_properties:
                    properties.add(pid)
                    by_property[pid]["figures"].append(figure["figure_id"])
            for citation in material.get("citations", []):
                record = self.records.get(citation.get("measurement_id")) or {}
                pid = (record.get("property_ref") or {}).get("id") or citation.get("property_id")
                if pid in self.names:
                    cited_properties.add(pid)
        properties.update(cited_properties)
        properties.intersection_update({*self.names, None})
        if not properties:
            properties.add(None)
        attachments = [mid for mid in ids if self.materials[mid].get("kind") == "official_attachment"]
        return {
            "group_id": group_id, "root": root, "member_ids": ids, "properties": properties,
            "by_property": by_property, "attachment_ids": attachments,
            "cited_properties": cited_properties,
        }

    def _entry(self, group, pid):
        root = group["root"]
        records = group["by_property"][pid]["records"]
        figures = group["by_property"][pid]["figures"]
        counts = Counter(self.record_section(group, mid) for mid in records)
        attachments = [
            {
                "material_id": mid,
                "title": first_title(self.materials[mid]),
                "table_id": (self.materials[mid].get("association") or {}).get("source_table_id")
                    or self.materials[mid].get("table_id"),
                "record_count": counts[mid],
            }
            for mid in group["attachment_ids"]
            if mid != group["group_id"]
        ]
        kinds = [root.get("kind") or "paper"]
        if attachments and "official_attachment" not in kinds:
            kinds.append("official_attachment")
        if pid in group["cited_properties"] and "cited" not in kinds:
            kinds.append("cited")
        roles = root.get("roles", [])
        if "cited" in roles and not group["cited_properties"] and "cited" not in kinds:
            kinds.append("cited")
        return {
            "group_id": group["group_id"], "property_id": pid,
            "property_name": self.names.get(pid, "其他资料"),
            "title": first_title(root), "authors": root.get("authors") or [],
            "year": root.get("year"), "kind": kinds[0], "types": kinds,
            "roles": roles, "availability": root.get("availability"),
            "record_count": len(records), "figure_count": len(figures),
            "body_record_count": counts["main"],
            "attachments": attachments,
            "output": "both" if records and figures else "data" if records else "figures" if figures else "none",
        }

    def resolve(self, group_id, property_id=None):
        group_id = self.source_group.get(group_id) or self.works.get(group_id) or group_id
        group = self.groups.get(group_id)
        if group is None:
            raise DomainError("MATERIAL_NOT_FOUND", "当前结果没有此资料", 404)
        if property_id == "other":
            property_id = None
            if None not in group["properties"]:
                raise DomainError("MATERIAL_PROPERTY_NOT_FOUND", "此资料没有该性质的归属", 404)
        elif property_id is None:
            property_id = next((p for p in self.names if p in group["properties"]), None)
        elif property_id not in group["properties"]:
            raise DomainError("MATERIAL_PROPERTY_NOT_FOUND", "此资料没有该性质的归属", 404)
        return group, property_id

    def record_section(self, group, measurement_id):
        source = self.records[measurement_id]["source_ref"]["id"]
        attachment = self.attachment_aliases.get(source, source)
        return attachment if attachment in group["attachment_ids"] and attachment != group["group_id"] else "main"

    def record_ids(self, group, pid, section=None):
        records = group["by_property"][pid]["records"]
        if section is None:
            return records
        if section != "main" and section not in group["attachment_ids"]:
            raise DomainError("MATERIAL_SECTION_NOT_FOUND", "该资料没有这个附表", 404)
        return [mid for mid in records if self.record_section(group, mid) == section]

    def listing(self, *, property_id=None, output=None, kind=None, search=None):
        if property_id and property_id not in {*self.names, "other"}:
            raise DomainError("MATERIAL_PROPERTY_NOT_FOUND", "当前结果没有该性质", 404)
        term = (search or "").strip().casefold()
        rows = [
            entry for entry in self.entries
            if (not property_id or property_id == (entry["property_id"] or "other"))
            and (not output or entry["output"] == output)
            and (not kind or kind in entry["types"])
            and (not term or term in " ".join(
                (entry["title"], *map(str, entry["authors"]),
                 *(attachment["title"] for attachment in entry["attachments"]))
            ).casefold())
        ]
        if property_id and property_id != "other":
            rows.sort(key=lambda row: (
                -(row["record_count"] + row["figure_count"]), -row["record_count"], -row["figure_count"],
                row["title"].casefold(), row["group_id"]))
        return rows

    def grouped_listing(self, *, property_id=None, output=None, kind=None, search=None):
        """One card per existing source group; figures shared by properties count once."""
        entries = self.listing(property_id=property_id, kind=kind, search=search)
        selected = dict.fromkeys(entry['group_id'] for entry in entries)
        result = []
        for gid in selected:
            group = self.groups[gid]
            # Unresolved bibliography mentions are separate leads, not another
            # copy of a retrieved paper. Keep their original identities readable.
            if kind is None and group['root'].get('kind') == 'cited':
                continue
            pids = [pid for pid in self.names if pid in group['properties']]
            chosen = property_id if property_id in pids else pids[0] if pids else None
            own = [pid for pid in group['properties'] if not property_id or (pid or 'other') == property_id]
            records = {mid for pid in own for mid in group['by_property'][pid]['records']}
            figures = {fid for pid in own for fid in group['by_property'][pid]['figures']}
            row = self._entry(group, chosen)
            counts = Counter(self.record_section(group, mid) for mid in records)
            row.update(record_count=len(records), figure_count=len(figures), body_record_count=counts['main'],
                group_by='material', count_scope='material_property' if property_id else 'material_all_properties',
                source_count=len({self.records[mid]['source_ref']['id'] for mid in records}),
                output='both' if records and figures else 'data' if records else 'figures' if figures else 'none',
                available_properties=[{'property_id': pid, 'name': self.names[pid],
                    'record_count': len(set(group['by_property'][pid]['records'])),
                    'figure_count': len(set(group['by_property'][pid]['figures']))} for pid in pids])
            row['attachments'] = [{**file, 'record_count': counts[file['material_id']]} for file in row['attachments']]
            if not output or row['output'] == output:
                result.append(row)
        return sorted(result, key=lambda row: (row['title'].casefold(), row['group_id']))
