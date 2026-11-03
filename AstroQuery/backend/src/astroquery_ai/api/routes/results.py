"""Existing results HTTP routes; business services retain authority."""

from __future__ import annotations

from fastapi import Request

from fastapi.responses import FileResponse
from fastapi.responses import Response

from starlette.background import BackgroundTask

from astroquery_ai.runtime.errors import DomainError


def register(app, application, scheduler):

    @app.get("/api/tasks/{task_id}/preview")
    def preview(
        task_id: str, offset: int = 0, limit: int = 100, expected_preview_id: str | None = None, view: str | None = None
    ):
        with application.repository.read() as conn:
            result = application.delivery.preview(
                conn, task_id, offset=offset, limit=limit, expected_preview_id=expected_preview_id
            )
            if view == 'ui':
                from astroquery_ai.science.evidence_views import build_views
                rows = result['items']
                evidence = {e['evidence_id']:e for r in rows for e in r['evidence']}
                sources = {r['source_document']['source_id']:r['source_document'] for r in rows}
                views = build_views(application.repository, conn, task_id, list(evidence.values()), list(sources.values()))
                derived = {d['measurement_id']:d for d in application.repository.objects(conn,task_id,'derived')}
                for row in rows:
                    ids = {e['evidence_id'] for e in row['evidence']}
                    row['evidence_views'] = [v for v in views if v['evidence_id'] in ids]
                    row['saved_processing'] = derived.get(row['source']['measurement_id'])
            return result

    @app.get("/api/tasks/{task_id}/delivery")
    def delivery(task_id: str, delivery_revision: int | None = None):
        with application.repository.read() as conn:
            legacy = application.legacy.get(conn, task_id)
            if legacy:
                return {
                    "delivery_id": legacy["result_id"],
                    "legacy_version": 1,
                    "status": "historical_read_only",
                    "scientific_validation": False,
                }
            body = application.delivery.read_for_display(conn, task_id, revision=delivery_revision)
            return {
                "delivery_id": body["delivery_id"],
                "revision": body["revision"],
                "snapshot_ref": body["snapshot_ref"],
                "status": body["status"],
                "counts": body["counts"],
                "display_counts": {key: len(body.get(field, [])) for key, field in
                                   [('records', 'measurements'), ('sources', 'sources'), ('figures', 'figures')]},
                "export_schema_versions": [1, 2],
                "available_revisions": [row[0] for row in conn.execute(
                    "SELECT version FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? ORDER BY version",
                    (application.history.source(conn, task_id), body['delivery_id']))],
            }

    @app.get("/api/tasks/{task_id}/deliveries/{delivery_id}/{resource}")
    def resource(task_id: str, delivery_id: str, resource: str, offset: int = 0, limit: int = 100, expected_delivery_revision: int | None = None,
                 delivery_revision: int | None = None, view: str | None = None, record_id: str | None = None,
                 material_id: str | None = None):
        with application.repository.read() as conn:
            legacy = application.legacy.get(conn, task_id)
            if legacy:
                if resource in {'materials','changes'}:
                    sources=application.legacy.resource(conn,task_id,delivery_id,'sources')
                    rows=([{**s,'material_id':s.get('source_id'),'kind':{'database':'catalog','supplementary':'official_attachment'}.get(s.get('source_type'),'paper'),
                            'availability':'旧历史归档；原件可用性按既有链接','record_ids':[]} for s in sources] if resource=='materials' else [])
                    return {'delivery_id':delivery_id,'legacy_version':1,'items':rows[max(0,offset):max(0,offset)+min(max(1,limit),500)],'total':len(rows),
                            'notice':'历史未保存新格式数据变更日志；已有处理轨迹保留在原报告中。'}
                rows = application.legacy.resource(conn, task_id, delivery_id, resource)
                if isinstance(rows, dict):
                    return {"delivery_id": delivery_id, "legacy_version": 1, "body": rows}
                return {
                    "delivery_id": delivery_id,
                    "legacy_version": 1,
                    "items": rows[max(0, offset) : max(0, offset) + min(max(1, limit), 500)],
                    "total": len(rows),
                }
            body = application.delivery.read_for_display(conn, task_id, delivery_id, delivery_revision)
            if expected_delivery_revision is not None and body['revision']!=expected_delivery_revision:
                raise DomainError('DELIVERY_CHANGED','交付报告已修订，请刷新后读取')
            source_task = application.history.source(conn, task_id)
            from astroquery_ai.application import research_views
            sealed = conn.execute(
                "SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                (source_task, delivery_id, body['revision'])).fetchone()
            cutoff = sealed[0] if sealed else None
            def pinned_report(name):
                reference = (body.get(name) or {}).get('report_ref')
                if reference:
                    return application.repository.object(conn, source_task, name, reference['id'], reference['version'])
                return None
            def insight_report():
                report = pinned_report('insight')
                if report is not None:
                    return report
                return next(iter(research_views.historical_insights(conn, source_task, body, cutoff)), None)
            if resource == "records" and view == "list":
                from astroquery_ai.application.result_views import record_list
                rows = record_list(body)
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
                def report_checks(record):
                    reference={'id':record['measurement_id'],'version':record['revision'],'content_sha256':record['content_sha256']}
                    return [d for d in body.get('dispositions',[]) if d.get('report_only') is True
                        and d.get('measurement_ref')==reference and d.get('snapshot_ref')==body['snapshot_ref']]
                def report_status(record):
                    statuses={d['status'] for d in report_checks(record)}
                    return 'not_supported' if 'not_supported' in statuses else 'unresolved' if 'unresolved' in statuses else 'delivered'
                rows = [
                    {
                        "source": record,
                        'source_title':source_metadata.get(record['source_ref']['id'],{}).get('title'),
                        'source_version_grade':source_metadata.get(record['source_ref']['id'],{}).get('version_grade'),
                        'report_checks':report_checks(record),'record_status':report_status(record),
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
                # Never read incidental current objects into an old delivery.
                rows = [{**figure,
                         "image_url": f"/api/tasks/{task_id}/artifacts/{figure['image_artifact']['artifact_id']}",
                         "page_url": f"/api/tasks/{task_id}/artifacts/{figure['page_artifact']['artifact_id']}",
                         "pdf_url": f"/api/tasks/{task_id}/artifacts/{figure['pdf_artifact_id']}#page={figure['page']}"}
                        for figure in body.get("figures", [])]
            elif resource == 'coverage' and view == 'matrix':
                rows = research_views.coverage_matrix(body, pinned_report('quality'), pinned_report('difference'), insight_report(),
                    research_views.process_facts(conn, source_task, cutoff))
            elif resource in {"sources", "coverage", "contexts"}:
                rows = body[resource]
            elif resource == "insights":
                report = insight_report()
                rows = [report] if report else []
            else:
                raise DomainError("RESOURCE_NOT_FOUND", "交付资源不存在", 404)
            return {
                "delivery_id": delivery_id,
                'delivery_revision':body['revision'],
                "snapshot_ref": body["snapshot_ref"],
                "items": rows[max(0, offset) : max(0, offset) + min(max(1, limit), 500)],
                "total": len(rows),
                **({"coverage": body.get("figure_coverage", [])} if resource == "figures" else {}),
            }

    @app.post("/api/tasks/{task_id}/exports")
    async def export(task_id: str, request: Request):
        return application.delivery.export(task_id, await request.json(), origin=str(request.base_url))

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
