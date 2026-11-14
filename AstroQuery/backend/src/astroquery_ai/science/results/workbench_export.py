"""Preview and build a bundle of explicitly selected records and research images."""

from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from astroquery_ai.application.material_workbench import artifact_id, first_title
from astroquery_ai.runtime.codec import canonical, digest, loads
from astroquery_ai.runtime.errors import DomainError

from . import research_export


IMAGE_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                    "image/gif": "gif", "image/tiff": "tiff"}
ORIGINAL_EXTENSIONS = {**IMAGE_EXTENSIONS, "application/pdf": "pdf", "application/zip": "zip",
                       "application/fits": "fits", "application/x-fits": "fits", "text/csv": "csv",
                       "application/x-votable+xml": "vot", "application/xml": "xml", "text/plain": "txt",
                       "application/json": "json"}
OPTIONAL_FIELDS = {
    "uncertainty": ("error_minus", "error_plus", "error_unit", "error_kind", "error_role", "confidence_level",
                    "uncertainty_state", "uncertainty_component_count", "uncertainty_components_json"),
    "conditions": ("component", "method", "result_role", "context", *research_export.COORDINATE_FIELDS),
    "original": ("raw_value", "source_numeric_value", "source_unit", "source_representation"),
    "source": ("source_type", "source_title", "source_id", "physical_pages", "table", "row", "column",
               "figure", "evidence_ids", "original_url", "evidence_locations_json"),
    "processing": ("processing_status", "record_status", "review_status"),
}
FILE_METADATA = ("export_schema_version", "delivery_id", "delivery_revision", "snapshot_id", "snapshot_sha256", "selected_count")
TABLE_FIRST = ("target", "property_name", "value", "unit", "error_minus", "error_plus", "error_unit",
               "limit", "lower_bound", "upper_bound", "text_value")
PREVIEW_ROWS = 6


def _file_stem(value):
    return re.sub(r"[^\w.−-]+", "-", str(value or "未命名")).strip(".-_")[:36] or "文件"


def _ids(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DomainError("INVALID_EXPORT_SELECTION", "导出选择无效", 422)
    if len(set(value)) != len(value):
        raise DomainError("INVALID_EXPORT_SELECTION", "导出 ID 不得重复", 422)
    return set(value)


def _request(task_id, request):
    fields = {"task_id", "delivery_id", "expected_delivery_revision", "export_schema_version", "selection", "options"}
    if (not isinstance(request, dict) or set(request) != fields | {"operation_id"}
            or request["task_id"] != task_id or type(request["export_schema_version"]) is not int
            or request["export_schema_version"] != 3 or type(request["expected_delivery_revision"]) is not int
            or not isinstance(request["operation_id"], str) or not request["operation_id"]
            or not isinstance(request["delivery_id"], str)):
        raise DomainError("INVALID_EXPORT_REQUEST", "导出请求协议无效", 422)
    selection, options = request["selection"], request["options"]
    if not isinstance(selection, dict) or set(selection) != {"measurement_ids", "figure_ids"}:
        raise DomainError("INVALID_EXPORT_SELECTION", "导出选择无效", 422)
    mids, fids = _ids(selection["measurement_ids"]), _ids(selection["figure_ids"])
    if not mids and not fids:
        raise DomainError("EMPTY_EXPORT_SELECTION", "请选择数据或图像", 422)
    required = {"data_format", "group_by", "container", "include_originals"}
    if (not isinstance(options, dict) or set(options) - {"fields"} != required
            or options["data_format"] not in ("csv", "json", "csv_wide")
            or options["group_by"] not in ("combined", "property", "material")
            or options["container"] not in ("direct", "zip", "separate") or type(options["include_originals"]) is not bool):
        raise DomainError("INVALID_EXPORT_REQUEST", "导出格式或分组无效", 422)
    if "fields" in options and _ids(options["fields"]) - OPTIONAL_FIELDS.keys():
        raise DomainError("INVALID_EXPORT_FIELDS", "请选择可导出的字段", 422)
    if options["container"] == "direct" and (
        options["include_originals"] or options["group_by"] != "combined"
        or fids and (mids or len(fids) != 1)
    ):
        raise DomainError("EXPORT_PACKAGE_REQUIRED", "此组合需要打包为 ZIP", 422)
    if options["include_originals"] and options["container"] != "zip":
        raise DomainError("EXPORT_PACKAGE_REQUIRED", "带出原件时请选择 ZIP", 422)
    return mids, fids, options


def _related_bundle(bundle, selected, seeds):
    """Follow explicit saved references from the selection, including independent error units."""
    lookup = defaultdict(list)
    id_fields = (
        "id", "statement_id", "interpretation_id", "unit_id", "unit_record_id", "unit_interpretation_id",
        "receipt_id", "processing_receipt_id", "answer_id", "reference_id", "cited_work_id",
        "candidate_id", "validation_id", "source_check_id", "root_id", "disposition_id",
        "application_id", "review_id", "context_id", "recheck_id", "qualification_id",
    )
    selected_positions = defaultdict(set)
    for field, items in bundle.items():
        if not isinstance(items, list):
            continue
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for key in id_fields:
                if isinstance(item.get(key), str):
                    lookup[item[key]].append((field, position))
            if (item.get("measurement_id") in selected
                    or (item.get("measurement_ref") or {}).get("id") in selected
                    or (item.get("input_ref") or {}).get("id") in selected):
                selected_positions[field].add(position)
                seeds.append(item)
    seen = set()
    while seeds:
        item = seeds.pop()
        if isinstance(item, dict):
            seeds.extend(item.values())
        elif isinstance(item, list):
            seeds.extend(item)
        elif isinstance(item, str) and item in lookup and item not in seen:
            seen.add(item)
            for field, position in lookup[item]:
                if position not in selected_positions[field]:
                    selected_positions[field].add(position)
                    seeds.append(bundle[field][position])
    return {field: [bundle[field][i] for i in sorted(positions)] for field, positions in selected_positions.items()}


def _scope(body, index, mids, fids, task_id, origin, *, full_provenance=True):
    measurements = [m for m in body["measurements"] if m["measurement_id"] in mids]
    figures = [f for f in body.get("figures", []) if f["figure_id"] in fids]
    source_ids = {m["source_ref"]["id"] for m in measurements} | {f.get("source_id") for f in figures}
    source_ids |= {index.source_group[s] for s in source_ids if s in index.source_group}
    sources = [s for s in body["sources"] if s["source_id"] in source_ids]
    pids = {m["property_ref"]["id"] for m in measurements}
    pids.update(pid for f in figures for pid in f.get("property_ids", []))
    evidence_ids = {r["id"] for m in measurements for r in m.get("evidence_refs", [])}
    evidence = [e for e in body["evidence_index"] if e["evidence_id"] in evidence_ids]
    contexts = {
        key: [r for r in body.get(key, []) if r["measurement_ref"]["id"] in mids]
        for key in ("contexts", "resolved_contexts")
    }
    derived = [r for r in body["derived"] if r["measurement_id"] in mids]
    dispositions = [r for r in body.get("dispositions", []) if (r.get("measurement_ref") or {}).get("id") in mids]
    selected = {
        key: body[key] for key in ("delivery_id", "snapshot_ref", "task_id", "target", "revision", "status")
    }
    selected.update(schema_version="ResearchSelection/3", measurements=measurements, figures=figures,
                    definitions=[d for d in body["definitions"] if d["property_id"] in pids],
                    sources=sources, evidence_index=evidence, derived=derived, dispositions=dispositions,
                    export_selection={"selected_ids": sorted(mids), "figure_ids": sorted(fids)},
                    export_metadata={"export_schema_version": 3, "resource_task_id": task_id,
                                     "origin": (origin or "").rstrip("/")}, **contexts)
    selected["joint_measurement_groups"] = [
        group for group in body.get("joint_measurement_groups", []) if mids.intersection(group.get("measurement_ids", []))
    ]
    provenance = body.get("provenance_bundle", {})
    if full_provenance:
        selected["provenance_bundle"] = _related_bundle(provenance, mids, [measurements, derived, evidence, sources,
                                                                         dispositions, *contexts.values()])
    else:
        # The selectable-field files need only the objects read by tables().
        interpretation_ids = {(m.get("interpretation_ref") or {}).get("id") for m in measurements}
        unit_ids = {(part.get("unit_ref") or {}).get("id") for m in measurements
                    for part in m["uncertainty"]["components"]}
        statement_ids = {ref["id"] for rows in contexts.values() for row in rows
                         for ref in row.get("source_statements", [])}
        selected["provenance_bundle"] = {
            "interpretations": [i for i in provenance.get("interpretations", []) if i["interpretation_id"] in interpretation_ids],
            "unit_records": [u for u in provenance.get("unit_records", []) if u["unit_id"] in unit_ids],
            "source_statements": [s for s in provenance.get("source_statements", []) if s["statement_id"] in statement_ids],
        }
    return selected


def _owned(conn, source_task, aid, store):
    if not aid:
        return None
    row = conn.execute("SELECT a.media_type, a.byte_size, a.relative_path FROM artifacts a "
                       "JOIN artifact_refs r USING(artifact_id) WHERE r.task_id=? AND a.artifact_id=? LIMIT 1",
                       (source_task, aid)).fetchone()
    if row is None:
        return None
    path = store.path(row["relative_path"])
    return {**dict(row), "available": path.is_file() and path.stat().st_size == row["byte_size"]}


def _source_originals(source):
    return {
        "primary": artifact_id(source.get("artifact")),
        "schema": artifact_id(source.get("schema_artifact")),
        "readme": artifact_id((source.get("readme") or {}).get("artifact")),
        "container": artifact_id((source.get("association") or {}).get("container_artifact_ref")),
    }


def _plan(service, conn, task_id, request, origin=None):
    mids, fids, options = _request(task_id, request)
    source, ref = service.delivery_reference(conn, task_id, request["delivery_id"])
    if request["expected_delivery_revision"] != ref["version"]:
        raise DomainError("DELIVERY_CHANGED", "交付版本已变化，请刷新后导出", 409)
    body = service.read_snapshot(conn, source, ref["id"], ref["version"])
    cutoff = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' "
                          "AND object_id=? AND version=?", (source, ref["id"], ref["version"])).fetchone()[0]
    index = service.material_index(conn, source, body, cutoff)
    if mids - index.records.keys() or fids - index.figures.keys():
        raise DomainError("EXPORT_ID_NOT_IN_DELIVERY", "选择含其他成果的数据或图像", 422)

    data = _scope(body, index, mids, fids, task_id, origin, full_provenance="fields" not in options)
    zip_mode = options["container"] == "zip"
    file_groups = defaultdict(list)
    group_by = options["group_by"]
    for measurement in data["measurements"]:
        if group_by == "property":
            key = measurement["property_ref"]["id"]
        elif group_by == "material":
            sid = measurement["source_ref"]["id"]
            key = index.source_group.get(sid, sid)
        else:
            key = "combined"
        file_groups[key].append(measurement["measurement_id"])
    files = []
    for key, ids in file_groups.items():
        label = index.names.get(key) if group_by == "property" else first_title(index.materials.get(key, {}))
        name = "测量" if key == "combined" else f"{_file_stem(label)}-{digest(key)[:8]}"
        prefix = "数据/" if zip_mode else ""
        ext = "json" if options["data_format"] == "json" else "csv"
        files.append({"path": f"{prefix}{name}.{ext}", "kind": "data", "measurement_ids": ids})
    for figure in data["figures"]:
        aid = artifact_id(figure.get("image_artifact"))
        meta = _owned(conn, source, aid, service.artifacts) or {}
        ext = IMAGE_EXTENSIONS.get(meta.get("media_type"))
        label = figure.get("label") or "图像"
        name = f"{_file_stem(research_export.text(figure.get('source_title')))}-{_file_stem(label)}-{figure['figure_id'][-8:]}"
        files.append({"path": f"{'图像/' if zip_mode else ''}{name}.{ext or 'bin'}",
                      "kind": "figure", "artifact_id": aid, "figure_id": figure["figure_id"],
                      "available": bool(ext and meta.get("available")), "bytes": meta.get("byte_size")})
    if options["container"] != "direct":
        data_dir, image_dir = ("数据/", "图像/") if zip_mode else ("", "")
        if data["measurements"] and options["data_format"] != "json" and _includes(options, "uncertainty"):
            files.append({"path": data_dir + "独立误差.json", "kind": "errors"})
        if fids:
            files.append({"path": image_dir + "图像说明.json", "kind": "figure_index"})
        if _includes(options, "source") or options["include_originals"]:
            files.append({"path": "来源与定位.json", "kind": "sources"})
        if "fields" not in options:
            files.append({"path": "资料总结.json", "kind": "summaries"})
        files.extend(({"path": "使用说明.md", "kind": "readme"}, {"path": "文件清单.json", "kind": "manifest"}))
    if options["include_originals"]:
        original_refs = {}
        for s in data["sources"]:
            for aid in _source_originals(s).values():
                if aid:
                    original_refs.setdefault(aid, s["source_id"])
        for f in data["figures"]:
            if aid := f.get("pdf_artifact_id"):
                original_refs.setdefault(aid, f.get("source_id"))
        for item in data["evidence_index"]:
            if aid := artifact_id(item.get("artifact_ref")):
                original_refs.setdefault(aid, item.get("source_id"))
        for aid, sid in original_refs.items():
            meta = _owned(conn, source, aid, service.artifacts) or {}
            stem = _file_stem(first_title(index.materials.get(sid, {})))
            ext = ORIGINAL_EXTENSIONS.get(meta.get("media_type"), "bin")
            files.append({"path": f"原件/{stem}-{aid[:12]}.{ext}", "kind": "original", "artifact_id": aid,
                          "available": bool(meta.get("available")), "bytes": meta.get("byte_size")})
    if "fields" not in options:
        groups = {(index.source_group.get(m["source_ref"]["id"], m["source_ref"]["id"]), m["property_ref"]["id"])
                  for m in data["measurements"]}
        groups.update((index.source_group.get(f.get("source_id"), f.get("source_id")), pid)
                      for f in data["figures"] for pid in (f.get("property_ids") or [None]))
        from ..material_summaries import stored_summary
        data["material_summaries"] = [
            summary for group, pid in sorted(groups, key=lambda item: (item[0] or "", item[1] or ""))
            if group and (summary := stored_summary(service.repository, conn, source, body, group, pid))
            and summary["state"] in {"ready", "bibliography"}
        ]
    return source, ref, data, files, options


def _includes(options, field):
    return "fields" not in options or field in options["fields"]


def _table_projection(data, files):
    rows, errors, locations = research_export.tables(data) if data["measurements"] else ([], [], [])
    by_id = {r["measurement_id"]: r for r in rows}
    figure_paths = {f["figure_id"]: f["path"] for f in files if f["kind"] == "figure"}
    originals = {f["artifact_id"]: f["path"] for f in files if f["kind"] == "original"}
    sources = research_export.source_rows(data)
    for source in sources:
        paths = {role: originals[aid] for role, aid in _source_originals(source).items() if aid in originals}
        source.update(original_in_package="primary" in paths, original_paths=paths)
    if originals:
        evidence_paths = {
            evidence["evidence_id"]: originals.get(artifact_id(evidence.get("artifact_ref")))
            for evidence in data["evidence_index"]
        }
        for entry in locations:
            for locator in entry["locations"]:
                if path := evidence_paths.get(locator["evidence_id"]):
                    locator["original_path"] = path
                container_id = artifact_id((locator.get("attachment_location") or {}).get("container_artifact_ref"))
                if path := originals.get(container_id):
                    locator["container_path"] = path
            by_id[entry["measurement_id"]]["evidence_locations_json"] = canonical(entry["locations"]).decode()
    index = {
        "figure_files": [{**f, "path": figure_paths[f["figure_id"]],
                          "original_path": originals.get(f.get("pdf_artifact_id"))} for f in data["figures"]],
        "sources": sources, "locations": locations, "original_files": originals,
    }
    return by_id, errors, index


def _legacy_json(data, record_rows, ids):
    subset = {**data, "measurements": record_rows}
    if len(ids) == len(data["measurements"]):
        return subset
    for field in ("derived", "contexts", "resolved_contexts", "dispositions"):
        subset[field] = [r for r in data[field] if (r.get("measurement_id") or (r.get("measurement_ref") or {}).get("id")) in ids]
    ev_ids = {ref["id"] for m in record_rows for ref in m.get("evidence_refs", [])}
    subset["evidence_index"] = [e for e in data["evidence_index"] if e["evidence_id"] in ev_ids]
    subset["export_selection"] = {"selected_ids": sorted(ids), "figure_ids": []}
    subset["figures"] = []
    subset["provenance_bundle"] = _related_bundle(
        data["provenance_bundle"], ids, [record_rows, subset["evidence_index"], subset["contexts"],
        subset["resolved_contexts"], subset["derived"], subset["dispositions"]])
    return subset


def _selected_json(data, record_rows, rows, errors, index, options):
    from .native_coordinates import table_coordinates
    derived = {row["measurement_id"]: row for row in data["derived"]}
    evidence = {row["evidence_id"]: row for row in data["evidence_index"]}
    locations = {row["measurement_id"]: row["locations"] for row in index["locations"]}
    errors_by_id = defaultdict(list)
    for error in errors:
        errors_by_id[error["measurement_id"]].append(error)
    conditions = {row["measurement_ref"]["id"]: row.get("conditions", [])
                  for row in [*data["contexts"], *data["resolved_contexts"]]}
    measurements = []
    for record, row in zip(record_rows, rows, strict=True):
        mid = record["measurement_id"]
        output = derived.get(mid, {})
        item = {key: row[key] for key in ("measurement_id", "target", "property_name", "property_id",
                                         "unit", "representation", "limit", "value_origin")}
        item["value"] = output["value_typed"] if row["value_origin"] == "processed" else record["value"]
        if _includes(options, "original"):
            item["original"] = {**{key: record.get(key) for key in ("raw_value", "value", "unit", "representation", "limit")},
                                "unit_declaration": record.get("unit_declaration")}
        if _includes(options, "uncertainty"):
            item["uncertainty"] = {"state": record["uncertainty"]["state"], "components": errors_by_id[mid]}
        if _includes(options, "conditions"):
            item["conditions"] = conditions.get(mid, [])
            item["method"] = row["method"] or None
            item["result_role"] = row["result_role"] or None
            item["native_coordinates"] = table_coordinates(record, evidence)
        if _includes(options, "source"):
            item["source"] = {"id": row["source_id"], "title": row["source_title"], "kind": row["source_type"],
                              "locations": locations[mid]}
        if _includes(options, "processing"):
            item["processing"] = {key: row[key] for key in ("processing_status", "record_status", "review_status")}
        measurements.append(item)
    return {"schema_version": "ResearchSelection/3", "delivery_id": data["delivery_id"],
            "revision": data["revision"], "snapshot_ref": data["snapshot_ref"], "fields": options["fields"],
            "measurements": measurements}


def _data_file(data, file, options, projection):
    by_id, errors, index = projection
    ids = file["measurement_ids"]
    rows = [by_id[mid] for mid in ids]
    if options["data_format"] == "json":
        wanted = set(ids)
        records = [record for record in data["measurements"] if record["measurement_id"] in wanted]
        if "fields" not in options:
            return "json", _legacy_json(data, records, wanted), None
        return "json", _selected_json(data, records, rows, errors, index, options), None
    columns = research_export.FIELDS + research_export.COORDINATE_FIELDS
    if "fields" in options:
        excluded = {key for group, keys in OPTIONAL_FIELDS.items() if group not in options["fields"] for key in keys}
        columns = tuple(key for key in dict.fromkeys((*TABLE_FIRST, *columns)) if key not in excluded)
    if options["data_format"] == "csv_wide":
        coordinates = None
        if "fields" in options:
            coordinates = tuple(key for key in columns if key not in FILE_METADATA and key not in {"target", "property_id"})
        wide, fields = research_export.wide_rows(data, rows, coordinates)
        if coordinates is not None:
            fields = ["target", *fields[9:], "group_id", "group_basis", *fields[3:9]]
        return "csv", wide, fields
    return "csv", rows, columns


def preview(service, task_id, request, *, origin=None, path=None):
    from .exporting import csv_display

    with service.repository.read() as conn:
        _, ref, data, files, options = _plan(service, conn, task_id, request, origin)
    data_files = [file for file in files if file["kind"] == "data"]
    data_preview = None
    if data_files:
        file = next((file for file in data_files if file["path"] == path), data_files[0])
        kind, value, columns = _data_file(data, file, options, _table_projection(data, files))
        if kind == "csv":
            def cell(row, key):
                displayed = csv_display(row.get(key, ""))[0]
                return "" if displayed is None else str(displayed)

            data_preview = {"columns": columns, "rows": [[cell(row, key) for key in columns] for row in value[:PREVIEW_ROWS]],
                            "total": len(value)}
        else:
            shown = {key: rows[:PREVIEW_ROWS] if isinstance(rows, list) else rows for key, rows in value.items()}
            data_preview = {"value": shown, "total": len(value["measurements"]),
                            "array_totals": {key: len(rows) for key, rows in value.items() if isinstance(rows, list)}}
        data_preview.update(path=file["path"], format=kind)
    figures = {figure["figure_id"]: figure for figure in data["figures"]}
    return {"delivery_id": ref["id"], "delivery_revision": ref["version"], "snapshot_ref": data["snapshot_ref"],
            "record_count": len(data["measurements"]), "figure_count": len(figures),
            "container": options["container"], "data_preview": data_preview,
            "images": [{"figure_id": file["figure_id"], "path": file["path"],
                        "label": figures[file["figure_id"]].get("label"),
                        "caption": figures[file["figure_id"]].get("caption"),
                        "page": figures[file["figure_id"]].get("page"),
                        "source_title": research_export.text(figures[file["figure_id"]].get("source_title")),
                        "image_url": research_export.artifact_url(data, file["artifact_id"]) if file["available"] else None}
                       for file in files if file["kind"] == "figure"],
            "files": [{k: v for k, v in item.items() if k != "measurement_ids"} for item in files]}


def _file_contents(service, owner, data, files, options):
    unavailable = [f["path"] for f in files if f.get("available") is False]
    if unavailable:
        raise DomainError("EXPORT_FILE_UNAVAILABLE", "原件或图像暂不可读：" + "、".join(unavailable), 409)
    projection = _table_projection(data, files)
    _, errors, index = projection
    description = index
    if not _includes(options, "source"):
        description = {"original_files": description["original_files"]}
    manifest = {"schema_version": "ResearchFileIndex/3", "delivery_id": data["delivery_id"],
                "delivery_revision": data["revision"], "snapshot_ref": data["snapshot_ref"],
                "selection": data["export_selection"], "files": {}}

    def content(file):
        kind = file["kind"]
        if kind in {"figure", "original"}:
            lease = service.artifacts.lease(owner, file["artifact_id"])
            try:
                meta, path = service.artifacts.read_owned(owner, file["artifact_id"])
                return path.read_bytes(), meta["media_type"]
            finally:
                service.artifacts.release(lease)
        if kind == "data":
            format, rows, fields = _data_file(data, file, options, projection)
            return (canonical(rows), "application/json") if format == "json" else (research_export.csv_bytes(rows, fields), "text/csv")
        if kind == "readme":
            text = "# AstroQuery 研究数据包\n\n文件清单记录所选对象、交付快照与文件校验值。\n"
            if _includes(options, "source"):
                text += "\n来源与定位索引保留论文物理页和表格行列。\n"
            if data["figures"]:
                text += "\n图像说明保存图注、原页与裁切精度。\n"
            return text.encode("utf-8"), "text/markdown"
        value = {"errors": errors, "figure_index": index["figure_files"], "sources": description,
                 "summaries": data.get("material_summaries"), "manifest": manifest}[kind]
        return canonical(value), "application/json"

    for item in sorted(files, key=lambda file: file["kind"] == "manifest"):
        payload, media = content(item)
        if item["kind"] != "manifest":
            manifest["files"][item["path"]] = {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
        yield item["path"], payload, media


def _build(service, owner, data, files, options):
    contents = _file_contents(service, owner, data, files, options)
    if options["container"] == "direct":
        _, payload, media = next(contents)
        return payload, media
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for path, payload, _ in contents:
            entry = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, payload)
    return output.getvalue(), "application/zip"


def export(service, task_id, request, *, origin=None):
    _request(task_id, request)
    repo = service.repository
    with repo.read() as conn:
        replay = repo.replay_operation(conn, task_id, request["operation_id"], request)
        if replay is not None:
            return replay
        owner, ref, data, files, options = _plan(service, conn, task_id, request, origin)
    container = options["container"]
    if container == "separate":
        artifacts = [{**service.artifacts.write(payload, media), "filename": path}
                     for path, payload, media in _file_contents(service, owner, data, files, options)]
        checksum = [a["sha256"] for a in artifacts]
        filename, output_format = "分开交付", "separate"
    else:
        payload, media = _build(service, owner, data, files, options)
        artifacts = [service.artifacts.write(payload, media)]
        checksum = artifacts[0]["sha256"]
        filename = _file_stem(data["target"].get("main_id")) + "-研究包.zip" if container == "zip" else files[0]["path"]
        output_format = ("package" if container == "zip" else
                         filename.rsplit(".", 1)[-1] if files[0]["kind"] == "figure" else options["data_format"])
    key = [ref, data["export_selection"], options, checksum]
    export_id = "export-" + digest(key)
    with repo.transaction() as conn:
        replay = repo.replay_operation(conn, task_id, request["operation_id"], request)
        if replay is not None:
            return replay
        _, current = service.delivery_reference(conn, task_id, ref["id"])
        if current != ref:
            raise DomainError("DELIVERY_CHANGED", "导出期间交付版本已变化，请刷新后重试", 409)
        existing = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='export' AND object_id=?",
                                (task_id, export_id)).fetchone()
        if existing:
            manifest = loads(existing[0])
        else:
            for artifact in artifacts:
                service.artifacts.register(conn, task_id, export_id, artifact)
            manifest = {"schema_version": "ExportManifest/3", "export_schema_version": 3, "export_id": export_id,
                        "task_id": task_id, "delivery_id": ref["id"], "delivery_revision": ref["version"],
                        "snapshot_ref": data["snapshot_ref"], "selection": data["export_selection"],
                        "selected_count": len(data["measurements"]), "figure_count": len(data["figures"]),
                        "format": output_format, "filename": filename, "status": "ready", "artifacts": artifacts,
                        "files": [f["path"] for f in files]}
            repo.put_object(conn, task_id, "export", export_id, 1, manifest)
            repo.event(conn, task_id, "export_updated", {"export_id": export_id, "status": "ready"})
        repo.save_operation(conn, task_id, request["operation_id"], request, manifest)
        return manifest
