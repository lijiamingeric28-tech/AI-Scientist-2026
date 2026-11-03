"""Small delivery-pinned UI projections; no scientific conclusions added."""

def record_list(body):
    """List rows carry the displayed coordinates and navigation refs. Details stay on demand."""
    properties = {b['property_id']: b for b in body['definitions']}
    outputs = {d['measurement_id']: d for d in body['derived']}
    groups = {}
    for group in body.get('archive_groups', []):
        for member in group['member_refs']:
            groups.setdefault(member['id'], []).append(group)
    statuses = {}
    for check in body.get('dispositions', []):
        if check.get('report_only') and check.get('snapshot_ref') == body['snapshot_ref']:
            ref = check.get('measurement_ref') or {}
            statuses.setdefault((ref.get('id'), ref.get('version'), ref.get('content_sha256')), set()).add(check['status'])
    contexts = {c['context_id']: c for c in [*body['contexts'], *body.get('resolved_contexts', [])]}
    rows = []
    property_order = {pid: i for i, pid in enumerate(properties)}
    for record in sorted(body['measurements'], key=lambda r: property_order[r['property_ref']['id']]):
        mid = record['measurement_id']
        binding = properties[record['property_ref']['id']]
        derived = outputs.get(mid)
        states = statuses.get((mid, record['revision'], record['content_sha256']), ())
        source = {k: record.get(k) for k in ('task_id','measurement_id','source_ref','source_kind','target_ref',
            'raw_value','value','unit','representation','limit','evidence_refs')}
        declaration = record.get('unit_declaration') or {}
        source['unit_declaration'] = {k: declaration.get(k) for k in ('kind', 'canonical_symbol')}
        uncertainty = record.get('uncertainty') or {}
        source['uncertainty'] = {'state': uncertainty.get('state'), 'components': [
            {'raw_text': c.get('raw_text')} for c in uncertainty.get('components', [])]}
        rows.append({'source': source, 'target': {'main_id': body['target'].get('main_id')},
            'derived': {k: derived.get(k) for k in ('main_state','value_typed','status','limit')} if derived else None,
            'property_binding': {'property_id': binding['property_id'], 'definition': {'name_cn': binding['definition']['name_cn']},
                'output_profile': {k: binding['output_profile'][k] for k in ('unit','representation')}},
            'context': {'conditions': [{k: c.get(k) for k in ('key','value','state')} for c in
                contexts.get(record['context_ref']['id'], {}).get('conditions', [])]},
            'record_status': 'not_supported' if 'not_supported' in states else 'unresolved' if 'unresolved' in states else 'delivered',
            'archive_groups': groups.get(mid, []), 'details_loaded': False})
    return rows


def materials(body):
    records=body['measurements'];names={b['property_id']:b['definition']['name_cn'] for b in body['definitions']}
    result=[];by_work={}
    for source in body['sources']:
        associated=[r for r in records if r['source_ref']['id']==source['source_id']]
        work=source.get('work') or {};meta=(work.get('records') or [{}])[0]
        wid=work.get('work_id') or source.get('work_id')
        item={**source,'material_id':source['source_id'],'roles':['source'],
            'title':source.get('title') or meta.get('titles'),
            'authors':meta.get('authors',[]),'year':meta.get('year'),'abstract':meta.get('abstract'),
            'bibcode':meta.get('bibcode'),'dois':meta.get('dois',[]),
            'record_ids':[r['measurement_id'] for r in associated],
            'properties':[{'property_id':pid,'name':names.get(pid,pid),'count':sum(r['property_ref']['id']==pid for r in associated)}
                for pid in names if any(r['property_ref']['id']==pid for r in associated)],
            'figures':[f for f in body.get('figures',[]) if f.get('source_id')==source['source_id']],
            'availability':'原件已取得' if source.get('artifact') or source.get('schema_artifact') else '资料说明已保存'}
        result.append(item)
        if wid and source.get('kind')=='paper':by_work[wid]=item
    for item in result:
        if item.get('kind')=='official_attachment':
            parent=by_work.get(item.get('work_id'))
            item['parent_material_id']=parent['material_id'] if parent else None
    bundle=body.get('provenance_bundle',{})
    references=bundle.get('reported_references',[])
    for cited in bundle.get('cited_works',[]):
        links=[r for r in references if r.get('cited_work_id')==cited['cited_work_id']]
        existing=next((s for s in result if cited.get('bibcode') and s.get('bibcode')==cited['bibcode']),None)
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
