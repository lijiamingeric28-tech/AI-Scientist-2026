"""Small delivery-pinned UI projections; no scientific conclusions added."""
from collections import Counter, defaultdict

def quality_modified_ids(quality):
    report = (quality or {}).get('quality_report', quality or {})
    modifications = report.get('report_state', {}).get('normalization', {}).get('modifications', [])
    if isinstance(modifications, dict):
        modifications = modifications.get('details', [])
        if isinstance(modifications, dict):
            modifications = [item for items in modifications.values() if isinstance(items, list) for item in items]
    modified = set()
    for item in modifications:
        modified.update(item.get('record_ids', []))
        if item.get('record_id'):
            modified.add(item['record_id'])
    for mid, trace in report.get('output_state', {}).get('traceability', {}).get('per_record_trace', {}).items():
        if trace.get('modifications'):
            modified.add(mid)
    return modified


def legacy_record_list(records, sources, quality):
    """Read original legacy flags without reinterpreting numeric data."""
    labels = {s['source_id']: s for s in sources}
    modified = quality_modified_ids(quality)
    report = (quality or {}).get('quality_report', quality or {})
    conflict = report.get('report_state', {}).get('conflict', {})
    groups = conflict.get('verification', {}).get('duplicate_groups') or conflict.get('resolution_report', {}).get('duplicate_groups') or []
    live = {r['record_id']: r for r in records}
    duplicates, seen = {}, set()
    for group in groups:
        key = '|'.join(str(group.get(k, '')) for k in ('entity_type', 'entity_name', 'field_name', 'field_value'))
        if key in seen:
            continue
        seen.add(key)
        ids = [mid for mid in group.get('record_ids', []) if mid in live]
        if len(ids) < 2:
            continue
        anchor = next((mid for mid in ids if live[mid].get('extraction_method') == 'database_query'), None)
        if anchor is None:
            scored = [mid for mid in ids if type(live[mid].get('extraction_confidence')) in {int, float}]
            anchor = max(scored, key=lambda mid: live[mid]['extraction_confidence']) if scored else min(ids)
        for mid in ids:
            duplicates.setdefault(mid, {'group_id': key, 'live_count': len(ids), 'anchor_id': anchor,
                'archive': False, 'reason': group.get('reason')})
    return [{**row, 'source_label': labels.get(row.get('source_id'), {}),
             'flags': {'excluded': row.get('record_status') == 'not_supported',
                       'modified': row['record_id'] in modified, 'duplicate': row['record_id'] in duplicates},
             'duplicate_group': duplicates.get(row['record_id'])} for row in records]




def report_dispositions(body):
    dispositions = defaultdict(list)
    for check in body.get('dispositions', []):
        if check.get('report_only') and check.get('snapshot_ref') == body['snapshot_ref']:
            ref = check.get('measurement_ref') or {}
            dispositions[ref.get('id'), ref.get('version'), ref.get('content_sha256')].append(check)
    return dispositions


def record_dispositions(record, dispositions):
    key = record['measurement_id'], record.get('revision'), record.get('content_sha256')
    return dispositions.get(key, [])


def record_status(record, dispositions):
    states = {check['status'] for check in record_dispositions(record, dispositions)}
    return 'not_supported' if 'not_supported' in states else 'unresolved' if 'unresolved' in states else 'delivered'


def record_list(body, *, measurement_ids=None, quality=None, offset=0, limit=None):
    """List rows carry the displayed coordinates and navigation refs. Details stay on demand."""
    from astroquery_ai.science.results.native_coordinates import table_coordinates
    properties = {b['property_id']: b for b in body['definitions']}
    outputs = {d['measurement_id']: d for d in body['derived']}
    groups = {}
    for group in body.get('archive_groups', []):
        for member in group['member_refs']:
            groups.setdefault(member['id'], []).append(group)
    dispositions = report_dispositions(body)
    contexts = {c['context_id']: c for c in [*body['contexts'], *body.get('resolved_contexts', [])]}
    table_evidence = {e['evidence_id']: e for e in body.get('evidence_index', []) if e.get('text_origin') == 'original_cells'}
    rows = []
    labels = {s['source_id']: s for s in source_list(body)}
    modified = {mid for change in changes(body) for mid in change.get('measurement_ids', [])}
    modified.update(quality_modified_ids(quality))
    live = {m['measurement_id'] for m in body['measurements']}
    duplicates = {}
    for group in body.get('archive_groups', []):
        ids = [r['id'] for r in group['member_refs'] if r['id'] in live]
        if len(ids) >= 2:
            for mid in ids:
                duplicates[mid] = {'group_id': group['group_id'], 'live_count': len(ids),
                    'anchor_id': (group.get('display_anchor') or {}).get('id') or ids[0],
                    'archive': True, 'reason': group.get('reason')}
    property_order = {pid: i for i, pid in enumerate(properties)}
    selected = body['measurements'] if measurement_ids is None else (
        r for r in body['measurements'] if r['measurement_id'] in measurement_ids
    )
    ordered = sorted(selected, key=lambda r: property_order[r['property_ref']['id']])
    for record in ordered[offset:offset+limit if limit is not None else None]:
        mid = record['measurement_id']
        binding = properties[record['property_ref']['id']]
        derived = outputs.get(mid)
        source = {k: record.get(k) for k in ('task_id','measurement_id','source_ref','source_kind','target_ref',
            'raw_value','value','unit','representation','limit','evidence_refs')}
        declaration = record.get('unit_declaration') or {}
        source['unit_declaration'] = {k: declaration.get(k) for k in ('kind', 'canonical_symbol')}
        uncertainty = record.get('uncertainty') or {}
        source['uncertainty'] = {'state': uncertainty.get('state'), 'components': [
            {'raw_text': c.get('raw_text')} for c in uncertainty.get('components', [])]}
        coordinates = table_coordinates(record, table_evidence) if table_evidence else None
        rows.append({'source': source, 'target': {'main_id': body['target'].get('main_id')},
            'derived': {k: derived.get(k) for k in ('main_state','value_typed','status','limit')} if derived else None,
            'property_binding': {'property_id': binding['property_id'], 'definition': {'name_cn': binding['definition']['name_cn']},
                'output_profile': {k: binding['output_profile'][k] for k in ('unit','representation')}},
            'context': {'conditions': [{k: c.get(k) for k in ('key','value','state')} for c in
                contexts.get((record.get('context_ref') or {}).get('id'), {}).get('conditions', [])]},
            **({'native_coordinates': coordinates} if coordinates and any(coordinates.values()) else {}),
            'record_status': record_status(record, dispositions),
            'archive_groups': groups.get(mid, []), 'details_loaded': False,
            'source_label': labels.get(record['source_ref']['id'], {'source_id': record['source_ref']['id']}),
            'flags': {'modified': mid in modified, 'duplicate': mid in duplicates, 'excluded': record_status(record, dispositions) == 'not_supported'},
            'duplicate_group': duplicates.get(mid)})
    if 'archive_groups' not in body and quality:
        from astroquery_ai.application.result_filters import record_coordinates
        old_flags = legacy_record_list([record_coordinates(row) for row in rows], list(labels.values()), quality)
        for row, saved in zip(rows, old_flags):
            row['flags']['duplicate'] = saved['flags']['duplicate']
            row['duplicate_group'] = saved['duplicate_group']
    return rows


def analysis_list(body, quality=None, difference=None, *, rows=None):
    """Exact plot coordinates and saved error components, without evidence bodies."""
    if rows is None:
        rows = record_list(body, quality=quality)
    originals = {r['measurement_id']: r for r in body['measurements']}
    derived = {d['measurement_id']: d for d in body.get('derived', [])}
    groups = {}
    for group in (difference or {}).get('comparison_projection', {}).get('groups', []):
        compact = {k: group[k] for k in ('group_id', 'property_id', 'meaning') if k in group}
        for mid in group.get('measurement_ids', []):
            groups.setdefault(mid, []).append(compact)
    for row in rows:
        mid = row['source']['measurement_id']
        row['source'] = {**row['source'], 'uncertainty': originals[mid].get('uncertainty')}
        row['source'].pop('evidence_refs', None)
        if row['derived'] is not None:
            row['derived'] = {**row['derived'], **{k: derived[mid].get(k)
                for k in ('uncertainty_typed', 'coordinate_units')}}
        row.pop('context', None)
        row.pop('archive_groups', None)
        row['comparison_groups'] = groups.get(mid, [])
    return rows


def source_list(body):
    """Only the citation identity needed to label, filter and sort measurements."""
    from astroquery_ai.application.result_filters import source_year
    result = []
    keys = ('source_id', 'kind', 'source_type', 'title', 'journal', 'year',
            'bibcode', 'canonical_key', 'table_id', 'catalog_id', 'official_supplement')
    for source in body['sources']:
        item = {key: source[key] for key in keys if key in source}
        work = source.get('work') or {}
        if work:
            record = (work.get('records') or [{}])[0]
            item['work'] = {key: work[key] for key in ('work_id', 'canonical_key') if key in work}
            item['work']['records'] = [{key: record[key] for key in ('titles', 'year') if key in record}]
        if (source.get('metadata') or {}).get('catalog_id'):
            item['metadata'] = {'catalog_id': source['metadata']['catalog_id']}
        year = source_year(source)
        if year is not None:
            item['year'] = year
        if source.get('kind') == 'official_attachment' and (source.get('association') or {}).get('source_table_id'):
            item['association'] = {'source_table_id': source['association']['source_table_id']}
        result.append(item)
    return result


def materials(body):
    names={b['property_id']:b['definition']['name_cn'] for b in body['definitions']}
    records = defaultdict(list)
    figures = defaultdict(list)
    table_originals = defaultdict(dict)
    for evidence in body.get('evidence_index', []):
        if evidence.get('text_origin') != 'original_cells':
            continue
        sid = evidence.get('source_id') or (evidence.get('source_ref') or {}).get('id')
        ref = evidence.get('artifact_ref') or {}
        aid = ref.get('id') or ref.get('artifact_id')
        if sid and aid:
            table_originals[sid][aid] = {'artifact_id': aid,
                'sha256': ref.get('content_sha256') or ref.get('sha256')}
    for record in body['measurements']:
        records[record['source_ref']['id']].append(record)
    for figure in body.get('figures', []):
        figures[figure.get('source_id')].append(figure)
    result=[];by_work={}
    for source in body['sources']:
        associated=records[source['source_id']]
        counts = Counter(r['property_ref']['id'] for r in associated)
        work=source.get('work') or {};meta=(work.get('records') or [{}])[0]
        wid=work.get('work_id') or source.get('work_id')
        item={**source,'material_id':source['source_id'],'roles':['source'],
            'title':source.get('title') or meta.get('titles'),
            'authors':meta.get('authors',[]),'year':meta.get('year'),'abstract':meta.get('abstract'),
            'bibcode':meta.get('bibcode'),'dois':meta.get('dois',[]),
            'record_ids':[r['measurement_id'] for r in associated],
            'properties':[{'property_id':pid,'name':name,'count':counts[pid]}
                for pid,name in names.items() if counts[pid]],
            'figures':figures[source['source_id']],
            'availability':'原件已取得' if source.get('artifact') or source.get('schema_artifact') else '资料说明已保存'}
        if source.get('kind') == 'catalog' and table_originals[source['source_id']]:
            # The metadata VOTable may contain no rows. Open an actual saved
            # response from this delivery; retain schema and all other responses.
            item['data_artifacts'] = list(table_originals[source['source_id']].values())
            item['artifact'] = source.get('artifact') or item['data_artifacts'][0]
        result.append(item)
        if wid and source.get('kind')=='paper':by_work[wid]=item
    for item in result:
        if item.get('kind')=='official_attachment':
            parent=by_work.get(item.get('work_id'))
            item['parent_material_id']=parent['material_id'] if parent else None
    bundle=body.get('provenance_bundle',{})
    references=bundle.get('reported_references',[])
    by_cited_work = defaultdict(list)
    for ref in references:
        by_cited_work[ref.get('cited_work_id')].append(ref)
    by_bibcode = {s['bibcode']:s for s in reversed(result) if s.get('bibcode')}
    for cited in bundle.get('cited_works',[]):
        links=by_cited_work[cited['cited_work_id']]
        existing=by_bibcode.get(cited.get('bibcode'))
        if existing:existing['roles'].append('cited');existing['citations']=links;continue
        result.append({'material_id':cited['cited_work_id'],'source_id':cited['cited_work_id'],
            'kind':'cited','roles':['cited'],'title':cited.get('title'),'authors':cited.get('authors',[]),
            'bibcode':cited.get('bibcode'),'abstract':cited.get('abstract'),'year':cited.get('year'),
            'dois':cited.get('dois',[]),'citations':links,'record_ids':[],
            'availability':'仅摘要' if cited.get('abstract') else '仅题录'})
    for ref in references:
        if ref.get('cited_work_id'):continue
        result.append({'material_id':ref['reference_id'],'source_id':ref['reference_id'],'kind':'cited',
            'roles':['cited'],'title':ref.get('raw_code') or '未解析引文','citations':[ref],
            'availability':'引文未解析','record_ids':[]})
    return result

def changes(body):
    result=[];native={m['measurement_id']:m for m in body['measurements']}
    bundle=body.get('provenance_bundle',{})
    normalized={x['after_ref']['id']:x for x in bundle.get('normalization_changes',[])}
    for d in body.get('derived',[]):
        m=native.get(d['measurement_id'])
        event=normalized.get(d['derived_id'])
        if not m or d.get('main_state')!='ready' or not event:continue
        result.append({'id':d['derived_id'],'kind':'representation','operation':'主值表示处理',
            'measurement_ids':[m['measurement_id']],'property_id':m['property_ref']['id'],
            'before':{'raw':m['raw_value'],'value':m['value'],'unit':m.get('unit'),'representation':m.get('representation')},
            'after':{'value':d.get('value_typed'),'coordinate_units':d.get('coordinate_units')},
            'at':event.get('timestamp'),'field_diff':event.get('field_diff'),
            'status':d.get('status'),'basis_ref':d.get('validation_receipt_ref'),
            'notice':'仅展示已保存的主值处理；独立误差在记录详情分别列出。'})
    for g in body.get('archive_groups',[]):
        result.append({'id':g['group_id'],'kind':'archive','operation':'有据重复归档',
            'measurement_ids':[r['id'] for r in g.get('member_refs',[])],
            'property_id':g.get('property_id'),'reason':g.get('reason'),
            'notice':'关系变化，所有原报保留；不表示重新计算了主值。'})
    candidates={c['candidate_id']:c for c in bundle.get('candidate',[])}
    for action in bundle.get('quality_reextraction_action',[]):
        root=action['root_id'];before=candidates.get(action['parent_candidate_ref']['id'],{}).get('proposal',{})
        decisions=[d for d in bundle.get('quality_decision',[]) if d.get('root_id')==root]
        ids=list(dict.fromkeys(d['measurement_ref']['id'] for d in decisions if d.get('measurement_ref') and d['measurement_ref']['id'] in native))
        result.append({'id':'reextract-'+root,'kind':'reextraction','operation':'原文局部重提与复检',
            'measurement_ids':ids,'property_id':action['property_id'],
            'before':{'raw':before.get('raw_value'),'unit':before.get('unit')},
            'after':{'records':[{'raw':native[mid]['raw_value'],'unit':native[mid].get('unit')} for mid in ids]},
            'status':list(dict.fromkeys(d.get('state') for d in decisions)),
            'notice':f"记录了{len(decisions)}项复检结论、{len(ids)}条交付原报；重提不等于一定修改数值，未保存的对应关系不补造。"})
    interpretations={x['interpretation_id']:x for x in bundle.get('interpretations',[])}
    for a in bundle.get('human_answers',[]):
        ids=[m['measurement_id'] for m in native.values() if (interpretations.get(m['interpretation_ref']['id'],{}).get('human_answer_ref') or {}).get('id')==a['answer_id']]
        receipt=next((x for x in bundle.get('review_applications',[]) if x.get('answer_id')==a['answer_id']),{})
        for x in receipt.get('results',[]):
            mid=x.get('measurement_id')
            if mid in native and mid not in ids:ids.append(mid)
        result.append({'id':a['answer_id'],'kind':'human','operation':'人工判断',
            'measurement_ids':ids,'property_id':native[ids[0]]['property_ref']['id'] if ids else None,
            'reason':a.get('reason'),'at':a.get('received_at'),'postcheck':receipt.get('postcheck'),
            'simulation':a.get('simulation',False),'outcome':a.get('comparison_outcome') or a.get('action'),
            'notice':'答案的实际应用及复检以审核回执为准，不将关系变化当作主值修改。'})
    return result
