"""Existing results HTTP routes; business services retain authority."""

from __future__ import annotations

from fastapi import Query, Request

from fastapi.responses import FileResponse
from fastapi.responses import Response

from starlette.background import BackgroundTask

from astroquery_ai.runtime.errors import DomainError


def register(app, application, scheduler):

    @app.get("/api/tasks/{task_id}/preview")
    def preview(
        task_id: str, offset: int = 0, limit: int = 100, expected_preview_id: str | None = None, view: str | None = None,
        preview_protocol: int = 1,
    ):
        with application.repository.read() as conn:
            result = application.delivery.preview(
                conn, task_id, offset=offset, limit=limit, expected_preview_id=expected_preview_id,
                preview_protocol=preview_protocol,
            )
            if view == 'ui':
                from astroquery_ai.application.preview_views import enrich_preview_page
                enrich_preview_page(application.repository, conn, task_id, result['items'])
            return result

    @app.get("/api/tasks/{task_id}/delivery")
    def delivery(task_id: str, delivery_revision: int | None = None, delivery_id: str | None = None):
        with application.repository.read() as conn:
            legacy = application.legacy.get(conn, task_id)
            if legacy:
                return {
                    "delivery_id": legacy["result_id"],
                    "legacy_version": 1,
                    "status": "historical_read_only",
                    "scientific_validation": False,
                }
            body = application.delivery.read_header(conn, task_id, delivery_id, delivery_revision)
            source_task = application.history.source(conn, task_id)
            revision_ceiling = publication_cutoff = None
            if source_task != task_id:
                _, captured = application.delivery.delivery_reference(conn, task_id)
                if body['delivery_id'] == captured['id']:
                    revision_ceiling = captured['version']
                horizon = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' "
                    "AND object_id=? AND version=?", (source_task, captured['id'], captured['version'])).fetchone()
                publication_cutoff = horizon[0]
            return {
                "delivery_id": body["delivery_id"],
                "revision": body["revision"],
                "snapshot_ref": body["snapshot_ref"],
                "status": body["status"],
                "counts": body["counts"],
                "display_counts": body["display_counts"],
                "export_schema_versions": [1, 2, 3],
                "available_revisions": [row[0] for row in conn.execute(
                    "SELECT version FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? "
                    "AND (? IS NULL OR version<=?) AND (? IS NULL OR created_at<=?) ORDER BY version",
                    (source_task, body['delivery_id'], revision_ceiling, revision_ceiling,
                     publication_cutoff, publication_cutoff))],
            }

    @app.get("/api/tasks/{task_id}/deliveries/{delivery_id}/{resource}")
    def resource(request: Request, task_id: str, delivery_id: str, resource: str, offset: int = 0, limit: int = 100, expected_delivery_revision: int | None = None,
                 delivery_revision: int | None = None, view: str | None = None, record_id: str | None = None,
                 material_id: str | None = None, source_id: str | None = None, figure_id: str | None = None,
                 q: str = '', quick: str = 'all', field: str = 'all', year_sort: str = 'none',
                 fields: str | None = None, source_group: str = 'all', collapse_duplicates: bool = False,
                 property_id: str | None = None, output: str | None = None,
                 material_type: str | None = None, search: str | None = None,
                 candidates_only: bool = False, record_section: str | None = None, at_seq: int | None = None,
                 sealed_only: bool = False, projection: str | None = None,
                 analysis_scope: str = Query('material', alias='scope'), report_version: int | None = None,
                 group_by: str | None = None, entry_id: str | None = None, claim_id: str | None = None,
                 entry_hash: str | None = None, action: str = 'all', activity_kind: str | None = None,
                 activity_start: str | None = None, activity_end: str | None = None, effect: str = 'all'):
        from astroquery_ai.application.result_filters import normalize_filters
        filters = {'q': q, 'quick': quick, 'field': field, 'source_id': source_id,
                   'year_sort': year_sort, 'record_id': record_id, 'source_group': source_group}
        if fields is not None:
            import json
            try:
                filters['fields'] = json.loads(fields)
            except ValueError:
                raise DomainError('INVALID_RESULT_FILTER', '性质筛选必须为JSON文本数组', 422)
        filters = normalize_filters(filters)
        with application.repository.read() as conn:
            if resource == 'material-analysis':
                if property_id is None or analysis_scope != 'property_comparison' and material_id is None:
                    raise DomainError('MATERIAL_ANALYSIS_SCOPE', '请选择资料与性质', 422)
                selected = application.delivery.display_scope(conn, task_id, delivery_id, delivery_revision,
                    expected_revision=expected_delivery_revision, at_seq=at_seq, sealed_only=sealed_only)
                return application.material_analysis.read(task_id, delivery_id, selected['revision'], material_id,
                    property_id, analysis_scope, report_version=report_version, at_seq=at_seq,
                    sealed_only=sealed_only, projection=projection)
            legacy = application.legacy.get(conn, task_id)
            if legacy:
                if resource in {'materials','changes'}:
                    sources=application.legacy.resource(conn,task_id,delivery_id,'sources')
                    rows=([{**s,'material_id':s.get('source_id'),'kind':{'database':'catalog','supplementary':'official_attachment'}.get(s.get('source_type'),'paper'),
                            'availability':'旧历史归档；原件可用性按既有链接','record_ids':[]} for s in sources] if resource=='materials' else [])
                    return {'delivery_id':delivery_id,'legacy_version':1,'items':rows[max(0,offset):max(0,offset)+min(max(1,limit),500)],'total':len(rows),
                            'notice':'历史未保存新格式数据变更日志；已有处理轨迹保留在原报告中。'}
                if resource in {'records', 'sources'} and (view == 'list' or resource == 'records' and view == 'analysis'):
                    if delivery_id != legacy['result_id']:
                        raise DomainError('LEGACY_RESULT_MISMATCH', '历史结果身份不一致', 409)
                    if delivery_revision not in {None, 1} or expected_delivery_revision not in {None, 1}:
                        raise DomainError('DELIVERY_CHANGED', '历史交付修订不可用', 409)
                    from astroquery_ai.application.result_views import legacy_record_list
                    from astroquery_ai.api.read_caching import conditional_json
                    def legacy_build():
                        sources = application.legacy.resource(conn, task_id, delivery_id, 'sources')
                        rows = sources
                        if resource == 'records':
                            rows = legacy_record_list(application.legacy.resource(conn, task_id, delivery_id, 'records'),
                                sources, application.legacy.resource(conn, task_id, delivery_id, 'quality'))
                        return rows, {'resource': resource, 'delivery_id': delivery_id, 'legacy_version': 1,
                                      'source_labels': {s['source_id']: s for s in sources}}
                    result = application.delivery._read_index.read((application.history.source(conn, task_id),
                        delivery_id, 1, legacy['state_sha256'], resource, 'legacy'), legacy_build,
                        filters=filters, offset=offset, limit=limit, collapse_duplicates=collapse_duplicates)
                    return conditional_json(request, result, namespace='legacy-delivery-list/1')
                rows = application.legacy.resource(conn, task_id, delivery_id, resource)
                if isinstance(rows, dict):
                    return {"delivery_id": delivery_id, "legacy_version": 1, "body": rows}
                if resource == 'records' and record_id is not None:
                    rows = [row for row in rows if row.get('record_id') == record_id]
                if resource == 'sources' and source_id is not None:
                    rows = [row for row in rows if row.get('source_id') == source_id]
                if resource == 'figures' and figure_id is not None:
                    rows = [row for row in rows if row.get('figure_id') == figure_id]
                return {
                    "delivery_id": delivery_id,
                    "legacy_version": 1,
                    "items": rows[max(0, offset) : max(0, offset) + min(max(1, limit), 500)],
                    "total": len(rows),
                    'offset': max(0, offset), 'limit': min(max(1, limit), 500),
                }
            if resource == 'knowledge_context':
                from astroquery_ai.application.insight_views import read_knowledge_context
                from astroquery_ai.api.read_caching import conditional_json
                payload, scope = read_knowledge_context(application, conn, task_id, delivery_id, delivery_revision,
                    expected_revision=expected_delivery_revision, at_seq=at_seq, sealed_only=sealed_only)
                if view == 'reference':
                    if not entry_id or not claim_id or not entry_hash:
                        raise DomainError('KNOWLEDGE_REFERENCE_REQUIRED', '请选择准确的知识引用与版本', 422)
                    from astroquery_ai.application.insight_views import knowledge_reference_view
                    reference = knowledge_reference_view(application, payload['context'], entry_id, claim_id, entry_hash)
                    payload = {key: payload[key] for key in ('delivery_id', 'delivery_revision', 'snapshot_ref')} | {'reference': reference}
                return conditional_json(request, payload, namespace='task-knowledge-context/1',
                    identity=[scope['source'], delivery_id, scope['revision'], scope['sha'], scope['summary_before']])
            if resource in {'records', 'sources'} and (view == 'list' or resource == 'records' and view == 'analysis'):
                from astroquery_ai.api.read_caching import conditional_json
                result = application.delivery.read_page(conn, task_id, delivery_id, resource,
                    revision=delivery_revision, expected_revision=expected_delivery_revision,
                    filters=filters, offset=offset, limit=limit, collapse_duplicates=collapse_duplicates, projection=view,
                    at_seq=at_seq, sealed_only=sealed_only)
                return conditional_json(request, result, namespace='delivery-list/1')
            workbench = resource == 'materials' and view == 'workbench' or resource in {'material_records', 'material_figures'}
            if resource == 'materials' and view == 'workbench' and projection == 'summary' and material_id is not None:
                from astroquery_ai.api.read_caching import conditional_json
                payload, scope = application.delivery.read_material_summary(conn, task_id, delivery_id, material_id,
                    property_id, delivery_revision, expected_revision=expected_delivery_revision,
                    at_seq=at_seq, sealed_only=sealed_only)
                return conditional_json(request, payload, namespace='material-summary/1',
                    identity=[scope['source'], delivery_id, scope['revision'], scope['sha'], scope['summary_before']])
            if workbench:
                body, index, scope = application.delivery.read_workbench(conn, task_id, delivery_id, delivery_revision,
                    expected_revision=expected_delivery_revision, at_seq=at_seq, sealed_only=sealed_only)
            else:
                audit = application.delivery.read_audit_resource(conn, task_id, delivery_id, resource,
                    revision=delivery_revision, expected_revision=expected_delivery_revision,
                    offset=offset, limit=limit, view=view, at_seq=at_seq, sealed_only=sealed_only,
                    projection=projection, property_id=property_id, source_id=source_id,
                    action=action, activity_kind=activity_kind, activity_start=activity_start, activity_end=activity_end, effect=effect)
                if audit is not None:
                    return audit
                identifier = {'records': record_id, 'sources': source_id, 'figures': figure_id}.get(resource)
                indexed = application.delivery.read_detail_resource(conn, task_id, delivery_id, resource,
                    revision=delivery_revision, expected_revision=expected_delivery_revision, identifier=identifier,
                    offset=offset, limit=limit, view=view, at_seq=at_seq, sealed_only=sealed_only)
                if indexed is not None:
                    return indexed
                if resource == 'insights':
                    scope = application.delivery.display_scope(conn, task_id, delivery_id, delivery_revision,
                        expected_revision=expected_delivery_revision, at_seq=at_seq, sealed_only=sealed_only)
                body = application.delivery.read_for_display(conn, task_id, delivery_id, delivery_revision,
                                                             allow_published=True)
            if expected_delivery_revision is not None and body['revision']!=expected_delivery_revision:
                raise DomainError('DELIVERY_CHANGED','交付报告已修订，请刷新后读取')
            source_task = application.history.source(conn, task_id)
            from astroquery_ai.application import research_views
            sealed = conn.execute(
                "SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                (source_task, delivery_id, body['revision'])).fetchone()
            cutoff = sealed[0] if sealed else None
            if resource == 'insights' and scope['summary_before'] is not None:
                cutoff = scope['summary_before']
            start, size = max(0, offset), min(max(1, limit), 500)
            if workbench:
                from astroquery_ai.application.material_workbench import figure_view
                result = {'delivery_id': delivery_id, 'delivery_revision': body['revision'],
                          'snapshot_ref': body['snapshot_ref'], 'offset': start, 'limit': size}
                if resource == 'materials' and material_id is None:
                    if group_by not in {None, 'material'}:
                        raise DomainError('MATERIAL_GROUPING', '不支持的资料分组方式', 422)
                    selected = property_id
                    if candidates_only and group_by is None and selected not in index.names:
                        selected = next(iter(index.names), None)
                    entries = (index.grouped_listing if group_by == 'material' else index.listing)(
                        property_id=selected, output=output, kind=material_type, search=search)
                    if candidates_only and group_by is None and selected is None:
                        entries = []
                    page = entries[start:start+size]
                    if group_by == 'material' and selected in index.names:
                        from astroquery_ai.application.material_reading import profile_for
                        for item in page:
                            profile = profile_for(application.delivery, conn, task_id, delivery_id, body['revision'],
                                item['group_id'], selected, at_seq=at_seq, sealed_only=sealed_only) or {}
                            item['coordinates'] = {key: profile.get(key, []) for key in ('units', 'representations', 'bands', 'epochs')}
                    return {**result, 'items': page, 'total': len(entries),
                            **({'group_by': 'material'} if group_by == 'material' else {}),
                            'selected_property_id': selected,
                            'material_count': len({entry['group_id'] for entry in entries}),
                            'properties': [{'property_id': pid, 'name': name} for pid, name in index.names.items()]}
                if material_id is None:
                    raise DomainError('MATERIAL_REQUIRED', '请选择资料', 422)
                group, pid = index.resolve(material_id, property_id)
                items = group['by_property'][pid]
                if resource == 'material_records':
                    ids = index.record_ids(group, pid, record_section)
                    rows = application.delivery.read_material_records(conn, task_id, delivery_id, body['revision'],
                                                                     ids[start:start+size])
                    return {**result, 'items': rows, 'total': len(ids), 'ids': ids}
                if resource == 'material_figures':
                    ids = items['figures']
                    return {**result, 'items': [figure_view(task_id, index.figures[fid]) for fid in ids[start:start+size]],
                            'total': len(ids), 'ids': ids}
                from astroquery_ai.science.material_summaries import read_summary
                root = group['root']
                related = [{key: index.materials[mid].get(key) for key in
                            ('material_id', 'source_id', 'title', 'kind', 'association', 'table_id', 'artifact',
                             'schema_artifact', 'origin_url', 'readme', 'metadata', 'parent_material_id')}
                           for mid in group['member_ids'] if mid != group['group_id']]
                before = scope['summary_before']
                summary = read_summary(application.repository, conn, source_task, body, group, pid,
                                       before=before)
                row = {**index._entry(group, pid),
                       'material': {key: value for key, value in root.items() if key not in {'record_ids', 'figures'}},
                       'related_materials': related, 'summary': summary}
                from astroquery_ai.application.material_reading import profile_for
                row['available_properties'] = [
                    {'property_id': own, 'name': index.names[own],
                     'record_count': len(group['by_property'][own]['records']),
                     'figure_count': len(group['by_property'][own]['figures'])}
                    for own in index.names if own in group['properties']]
                row['profile'] = profile_for(application.delivery, conn, task_id, delivery_id, body['revision'],
                    group['group_id'], pid, at_seq=at_seq, sealed_only=sealed_only)
                return {**result, 'items': [row], 'total': 1}
            def pinned_report(name):
                reference = (body.get(name) or {}).get('report_ref')
                if reference:
                    if resource == 'insights' and scope['summary_before'] is not None:
                        meta = conn.execute('SELECT created_at FROM objects WHERE task_id=? AND kind=? AND object_id=? AND version=?',
                            (source_task, name, reference['id'], reference['version'])).fetchone()
                        if not meta or meta[0] > scope['summary_before']:
                            return None
                    return application.repository.object(conn, source_task, name, reference['id'], reference['version'])
                return None
            def _enrich_theory(report):
                if not isinstance(report, dict):
                    return report
                if report.get('schema_version') == 'InsightBundle/1':
                    return report
                try:
                    from astroquery_ai.science.theory_knowledge import TheoryKnowledgeStore
                    store = TheoryKnowledgeStore.get_instance()
                    pids = [p['property_id'] for p in body.get('definitions', [])]
                    if not pids and 'cards' in report:
                        pids = [c['property_id'] for c in report['cards']]
                    if not report.get('cross_field_relationships'):
                        report['cross_field_relationships'] = store.derive_network_relationships(pids)
                    existing_bids = {b.get('claim', {}).get('claim_id') for b in report.get('knowledge_blocks', [])}
                    blocks = list(report.get('knowledge_blocks', []))
                    for rel in report.get('cross_field_relationships', []):
                        tid = rel.get('theory_id')
                        if tid and tid in store.by_id:
                            tblk = store.to_knowledge_block(store.by_id[tid])
                            if tblk['claim']['claim_id'] not in existing_bids:
                                existing_bids.add(tblk['claim']['claim_id'])
                                blocks.append(tblk)
                    report['knowledge_blocks'] = blocks
                except Exception:
                    pass
                return report

            def insight_report():
                report = pinned_report('insight')
                if report is not None:
                    return _enrich_theory(report)
                rep = next(iter(research_views.historical_insights(conn, source_task, body, cutoff)), None)
                return _enrich_theory(rep) if rep is not None else None
            if resource == "records" and view == "list":
                from astroquery_ai.application.result_views import record_list
                return {"delivery_id": delivery_id, "delivery_revision": body['revision'],
                        "snapshot_ref": body["snapshot_ref"], "items": record_list(body, offset=start, limit=size),
                        "total": len(body["measurements"])}
            elif resource == "records":
                records = body["measurements"]
                if record_id is not None:
                    records=[r for r in records if r['measurement_id']==record_id]
                    if not records:raise DomainError('RECORD_NOT_FOUND','当前交付版本没有此记录',404)
                outputs = {d["measurement_id"]: d for d in body["derived"]}
                properties = {b["property_id"]: b for b in body["definitions"]}
                report = application.repository.object(
                    conn, source_task, "difference", body["difference"]["report_ref"]["id"], body["difference"]["report_ref"]["version"]
                )
                projection = report.get('comparison_projection',{'groups':[],'limitations':[]})
                evidence = {e["evidence_id"]: e for e in body["evidence_index"]}
                views=body.get('evidence_views')
                if view=='summary':views=[]
                elif views is None:
                    from astroquery_ai.science.evidence_views import build_views
                    # Additive read-only display for historical snapshots. No
                    # old evidence/hash or admission state is rewritten.
                    needed_ids = {ref['id'] for row in records for ref in row['evidence_refs']}
                    views=build_views(application.repository,conn,source_task,
                        [e for e in body['evidence_index'] if e['evidence_id'] in needed_ids],body['sources'],snapshot=body,cutoff=cutoff)
                contexts = {c["context_id"]: c for c in body["contexts"]}
                resolved_contexts = {c["context_id"]: c for c in body.get("resolved_contexts", [])}
                interpretations = {
                    i["interpretation_id"]: i for i in body["provenance_bundle"]["interpretations"]
                }
                answers = {a["answer_id"]: a for a in body["provenance_bundle"]["human_answers"]}
                reported_references = {
                    item["reference_id"]: item
                    for item in body["provenance_bundle"].get("reported_references", [])
                }
                cited_works = {c['cited_work_id']:c for c in body['provenance_bundle'].get('cited_works',[])}
                alias_to = {(m.get('original_measurement_ref') or {}).get('id'):m['measurement_id']
                            for m in body['provenance_bundle'].get('source_mentions',[])}
                def citations_for(record):
                    ids = {r['id'] for r in record.get('lineage_refs',[])}
                    return [{**r,'cited_work':cited_works.get(r.get('cited_work_id'))}
                        for r in reported_references.values() if r['reference_id'] in ids or
                        alias_to.get(r['measurement_id']) == record['measurement_id']]
                source_statements = {
                    item["statement_id"]: item
                    for item in body["provenance_bundle"].get("source_statements", [])
                }
                source_metadata={s['source_id']:s for s in body['sources']}
                from astroquery_ai.application.result_views import record_dispositions, report_dispositions, record_status
                dispositions = report_dispositions(body)
                rows = [
                    {
                        "source": record,
                        'source_title':source_metadata.get(record['source_ref']['id'],{}).get('title'),
                        'source_version_grade':source_metadata.get(record['source_ref']['id'],{}).get('version_grade'),
                        'report_checks':record_dispositions(record, dispositions),'record_status':record_status(record, dispositions),
                        'uncertainty_units':{part['component_id']:next((u.get('unit_text') or u.get('unit_declaration',{}).get('canonical_symbol')
                            for u in body['provenance_bundle'].get('unit_records',[]) if u['unit_id']==(part.get('unit_ref') or {}).get('id')),None)
                            for part in record['uncertainty']['components']},
                        'workflow_contract':body.get('workflow_contract'),
                        'archive_groups':[g for g in body.get('archive_groups',[]) if record['measurement_id'] in {r['id'] for r in g['member_refs']}],
                        "derived": outputs.get(record["measurement_id"]),
                        "property_binding": properties[record["property_ref"]["id"]],
                        "target": body["target"],
                        "interpretation": interpretations[record["interpretation_ref"]["id"]],
                        "human_answer": answers.get(
                            (
                                interpretations[record["interpretation_ref"]["id"]].get(
                                    "human_answer_ref"
                                )
                                or {}
                            ).get("id")
                        ),
                        "context": resolved_contexts.get(
                            record["context_ref"]["id"], contexts[record["context_ref"]["id"]]
                        ),
                        "source_context": contexts[record["context_ref"]["id"]],
                        "reported_references": citations_for(record),
                        "source_statements": [
                            source_statements[reference["id"]]
                            for reference in contexts[record["context_ref"]["id"]].get(
                                "source_statements", []
                            )
                            if reference["id"] in source_statements
                        ],
                        "evidence": [evidence[ref["id"]] for ref in record["evidence_refs"]],
                        "evidence_views": [view for view in views
                            if view['evidence_id'] in {ref['id'] for ref in record['evidence_refs']}],
                        "comparison_groups": [
                            g
                            for g in projection["groups"]
                            if record["measurement_id"] in g["measurement_ids"]
                        ],
                        "comparison_limitations": [
                            l
                            for l in projection["limitations"]
                            if record["measurement_id"] in l["measurement_ids"]
                        ],
                        "result_comparison_refs": [
                            {
                                "group_id": group["group_id"],
                                "property_id": group["property_id"],
                                "meaning": group["meaning"],
                            }
                            for group in report.get("result_comparisons", {}).get("groups", [])
                            if record["measurement_id"] in group["measurement_ids"]
                        ],
                    }
                    for record in records
                ]
                if view=='summary':
                    for item in rows:
                        binding=item['property_binding']
                        item['property_binding']={'property_id':binding['property_id'],
                            'definition':{'name_cn':binding['definition']['name_cn']},
                            'output_profile':{'unit':binding['output_profile']['unit'],
                                              'representation':binding['output_profile']['representation']}}
                        for name in ('evidence','evidence_views','source_statements','reported_references','interpretation'):
                            item.pop(name,None)
                        item['details_loaded']=False
                elif record_id is not None:
                    activity = research_views.activities(body, report, research_views.review_details(conn, source_task, body))
                    for item in rows:
                        mid = item['source']['measurement_id']
                        from astroquery_ai.science.evidence_views import focus_record_views
                        item['evidence_views'] = focus_record_views(conn, source_task, cutoff,
                            source_metadata.get(item['source']['source_ref']['id'], {}), item['source'], item['evidence_views'])
                        item['activity'] = [a for a in activity if mid in a['measurement_ids']]
                        item['processing_receipt'] = next((r for r in body['provenance_bundle'].get('processing_receipts', [])
                            if (r.get('input_ref') or {}).get('id') == mid), None)
            elif resource in {'materials','changes'}:
                from astroquery_ai.application.result_views import materials,changes
                rows=(research_views.activities(body, pinned_report('difference'), research_views.review_details(conn, source_task, body))
                      if resource=='changes' and view=='activity' else (materials if resource=='materials' else changes)(body))
                if resource=='materials':
                    research_views.enrich_materials(rows, body, research_views.process_facts(conn, source_task, cutoff), pinned_report('quality'))
                    for item in rows:
                        if item.get('kind')!='paper' or not sealed:continue
                        sha=(item.get('artifact') or {}).get('sha256')
                        index=conn.execute("SELECT json_extract(CAST(payload AS TEXT),'$.page_count') FROM objects WHERE task_id=? AND kind='document_index' AND object_id=? AND created_at<=? AND json_extract(CAST(payload AS TEXT),'$.sha256')=? ORDER BY version DESC LIMIT 1",(source_task,(item.get('work') or {}).get('work_id'),sealed[0],sha)).fetchone()
                        if index:item['page_count']=index[0]
                    if material_id is not None:
                        rows = [row for row in rows if row['material_id'] == material_id or
                                any(ref.get('cited_work_id') == material_id for ref in row.get('citations', []))]
                        if not rows:
                            raise DomainError('MATERIAL_NOT_FOUND', '当前交付修订没有此资料', 404)
                        from astroquery_ai.science.evidence_views import build_views
                        views = body.get('evidence_views')
                        evidence_sources = {e['evidence_id']: e.get('source_id') or (e.get('source_ref') or {}).get('id')
                                            for e in body['evidence_index']}
                        if views is None:
                            source_ids = {item['source_id'] for item in rows}
                            ev = [e for e in body['evidence_index'] if e.get('text_origin') == 'original_cells'
                                  and evidence_sources.get(e['evidence_id']) in source_ids]
                            views = build_views(application.repository, conn, source_task, ev, body['sources'], snapshot=body, cutoff=cutoff)
                        for item in rows:
                            ids = {e['id'] for m in body['measurements'] if m['source_ref']['id'] == item['source_id'] for e in m.get('evidence_refs', [])}
                            item['table_views'] = [v for v in views if v.get('kind') == 'table' and (v['evidence_id'] in ids or evidence_sources.get(v['evidence_id']) == item['source_id'])]
            elif resource in {"quality", "differences"}:
                report = body["quality" if resource == "quality" else "difference"]
                kind = "quality" if resource == "quality" else "difference"
                reference = report["report_ref"]
                return {
                    "delivery_id": delivery_id,
                    'delivery_revision':body['revision'],
                    "snapshot_ref": body["snapshot_ref"],
                    "body": application.repository.object(
                        conn, source_task, kind, reference["id"], reference["version"]
                    ),
                }
            elif resource == "figures":
                from astroquery_ai.application.material_workbench import figure_view
                rows = [figure_view(task_id, figure) for figure in body.get("figures", [])]
            elif resource == 'coverage' and view == 'matrix':
                rows = research_views.coverage_matrix(body, pinned_report('quality'), pinned_report('difference'), insight_report(),
                    research_views.process_facts(conn, source_task, cutoff))
            elif resource == 'sources' and view == 'list':
                from astroquery_ai.application.result_views import source_list
                rows = source_list(body)
            elif resource in {"sources", "coverage", "contexts"}:
                rows = body[resource]
            elif resource == "insights":
                report = insight_report()
                rows = [report] if report else []
            else:
                raise DomainError("RESOURCE_NOT_FOUND", "交付资源不存在", 404)
            if resource == 'sources' and source_id is not None:
                rows = [row for row in rows if row['source_id'] == source_id]
                if not rows:
                    raise DomainError('SOURCE_NOT_FOUND', '当前交付修订没有此来源', 404)
            if resource == 'figures' and figure_id is not None:
                rows = [row for row in rows if row['figure_id'] == figure_id]
                if not rows:
                    raise DomainError('FIGURE_NOT_FOUND', '当前交付修订没有此图像', 404)
            return {
                "delivery_id": delivery_id,
                'delivery_revision':body['revision'],
                "snapshot_ref": body["snapshot_ref"],
                "items": rows[max(0, offset) : max(0, offset) + min(max(1, limit), 500)],
                "total": len(rows),
                'offset': max(0, offset), 'limit': min(max(1, limit), 500),
                **({"coverage": body.get("figure_coverage", [])} if resource == "figures" else {}),
            }

    @app.post("/api/tasks/{task_id}/exports")
    async def export(task_id: str, request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(application.delivery.export, task_id, await request.json(),
                                       origin=str(request.base_url))

    @app.post("/api/tasks/{task_id}/exports/preview")
    async def export_preview(task_id: str, request: Request, path: str | None = None):
        from starlette.concurrency import run_in_threadpool
        from astroquery_ai.science.results.workbench_export import preview
        return await run_in_threadpool(preview, application.delivery, task_id, await request.json(),
                                       origin=str(request.base_url), path=path)

    @app.post('/api/tasks/{task_id}/deliveries/{delivery_id}/material-analysis', status_code=202)
    async def generate_material_analysis(task_id: str, delivery_id: str, request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(application.material_analysis.submit, task_id, delivery_id, await request.json())

    @app.get('/api/tasks/{task_id}/material-analysis-runs/{run_id}')
    def material_analysis_status(task_id: str, run_id: str, at_seq: int | None = None, sealed_only: bool = False):
        return application.material_analysis.status(task_id, run_id, at_seq=at_seq, sealed_only=sealed_only)

    @app.post('/api/tasks/{task_id}/material-analysis-runs/{run_id}/stop')
    def stop_material_analysis(task_id: str, run_id: str):
        return application.material_analysis.stop(task_id, run_id)

    @app.post("/api/tasks/{task_id}/deliveries/{delivery_id}/material-summary")
    async def generate_material_summary(task_id: str, delivery_id: str, request: Request):
        from astroquery_ai.science.material_summaries import request_summary
        body = await request.json()
        if (not isinstance(body, dict) or set(body) != {'delivery_revision', 'material_id', 'property_id'}
                or type(body['delivery_revision']) is not int or not isinstance(body['material_id'], str)
                or (body['property_id'] is not None and not isinstance(body['property_id'], str))):
            raise DomainError('INVALID_MATERIAL_SUMMARY', '资料总结请求无效', 422)
        return await request_summary(application, task_id, delivery_id, body['delivery_revision'],
                                     body['material_id'], body['property_id'])

    @app.get("/api/tasks/{task_id}/exports")
    def exports(task_id: str):
        with application.repository.read() as conn:
            source=application.history.source(conn,task_id)
            return [{**application.repository.object(conn,source,'export',row['object_id'],row['version']),
                     'created_at':row['created_at']} for row in conn.execute(
                "SELECT object_id,version,created_at FROM objects WHERE task_id=? AND kind='export' ORDER BY created_at",(source,))]

    @app.get('/api/tasks/{task_id}/artifacts/{artifact_id}/pages/{page}')
    async def page_preview(task_id: str, artifact_id: str, page: int):
        if page<1:raise DomainError('PDF_PAGE_INVALID','物理页从1开始',422)
        with application.repository.read() as conn:
            source=task_id if conn.execute('SELECT 1 FROM artifact_refs WHERE task_id=? AND artifact_id=?',(task_id,artifact_id)).fetchone() else application.history.source(conn,task_id)
        lease=application.artifacts.lease(source,artifact_id)
        try:
            item,path=application.artifacts.read_owned(source,artifact_id)
            if item['media_type']!='application/pdf':raise DomainError('PDF_REQUIRED','只有归档PDF可渲染原页',422)
            cache=application.root/'cache'/'ui-pages'/f'{item["sha256"]}-{page}-150.png'
            if cache.is_file():content=cache.read_bytes()
            else:
                content=await application.parsers.run('page_image',path,page=page,dpi=150,display_only=True,timeout=45)
                cache.parent.mkdir(parents=True,exist_ok=True)
                from uuid import uuid4
                temporary=cache.with_suffix('.'+uuid4().hex+'.tmp')
                temporary.write_bytes(content);temporary.replace(cache)
            return Response(content,media_type='image/png',headers={'Cache-Control':'private, max-age=86400'})
        finally:application.artifacts.release(lease)

    @app.get("/api/tasks/{task_id}/artifacts/{artifact_id}")
    def artifact(task_id: str, artifact_id: str):
        with application.repository.read() as conn:
            source_task = (
                task_id
                if conn.execute(
                    "SELECT 1 FROM artifact_refs WHERE task_id=? AND artifact_id=?",
                    (task_id, artifact_id),
                ).fetchone()
                else application.history.source(conn, task_id)
            )
        lease = application.artifacts.lease(source_task, artifact_id)
        try:
            item, path = application.artifacts.read_owned(source_task, artifact_id)
        except BaseException:
            application.artifacts.release(lease)
            raise
        return FileResponse(
            path,
            media_type=item["media_type"],
            filename=artifact_id,
            content_disposition_type="inline" if item["media_type"] in {
                "application/pdf", "image/png", "image/jpeg", "image/webp"
            } else "attachment",
            background=BackgroundTask(application.artifacts.release, lease),
        )
