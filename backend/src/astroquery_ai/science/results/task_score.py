"""Task completion/delivery accounting. Never measurement ranking or admission."""
from decimal import Decimal,ROUND_HALF_UP
from astroquery_ai.runtime.codec import digest,loads
from astroquery_ai.runtime.retrieval_preferences import readable_target


def freeze_scope(repo,c,tid,spec):
    existing=repo.objects(c,tid,'completion_scope')
    if existing:return existing[0]
    materials={}
    jobs=[{**dict(r),'payload':loads(r['payload'])} for r in c.execute('select job_id,kind,payload from jobs where task_id=?',(tid,))]
    for allocation in repo.objects(c,tid,'reading_allocation'):
        index=repo.object(c,tid,'document_index',allocation['work_id'])
        key='paper:'+allocation['work_id']
        materials[key]={'material_id':key,'kind':'paper','ranges':[
            {'property_id':pid,'page':page} for pid in allocation['property_ids'] for page in range(1,index['page_count']+1)]}
    for job in jobs:
        p=job['payload']
        if job['kind']=='paper_batch' and not p.get('quality_root_id'):
            key='paper:'+p['work_id'];m=materials.setdefault(key,{'material_id':key,'kind':'paper','ranges':[]})
            for pid in p['property_ids']:
                for page in p['core_pages']:
                    part={'property_id':pid,'page':page}
                    if part not in m['ranges']:m['ranges'].append(part)
        elif job['kind'] in {'catalog_extract','attachment_extract'}:
            key=job['kind']+':'+str(p.get('table_id') or p.get('attachment_id') or p.get('work_id') or job['job_id'])
            materials.setdefault(key,{'material_id':key,'kind':job['kind'],'ranges':[{'initial_job_id':job['job_id']}]})
    for pool in repo.objects(c,tid,'catalog_pool'):
        for table in pool['dispatched']:
            key='catalog_extract:'+table['node_id']
            materials.setdefault(key,{'material_id':key,'kind':'catalog_extract','ranges':[{'initial_job_id':None}]})
    from ..author_release import enabled
    scope={'schema_version':'TaskCompletionScope/1','requested_properties':[b['property_id'] for b in spec['properties']],
        'readable_target_per_property':readable_target(spec),'materials':list(materials.values()),'frozen_before_quality':True,
        'weight_total':100,'possible_points':100 if enabled(spec) else 95,
        'excluded_scope':[] if enabled(spec) else [{'scope':'insights','weight':5,'state':'deferred_by_scope'}]}
    repo.put_object(c,tid,'completion_scope',tid,1,scope)
    return scope


def _ratio(n,d):return Decimal(n)/Decimal(d) if d else Decimal(0)


def execution_fraction(scope,states,jobs):
    """Stable pages/properties; making more batches or retries adds no weight."""
    done=set()
    for s in states:
        if s.get('closed') and s.get('coverage') in {'complete','checked'}:
            for pid in s['property_ids']:
                done.update((s['work_id'],pid,p) for p in s['core_pages'])
    succeeded={j['job_id'] for j in jobs if j['status']=='succeeded'}
    results=[]
    for m in scope['materials']:
        if m['kind']=='paper':
            wid=m['material_id'][len('paper:'):]
            completed=sum((wid,x['property_id'],x['page']) in done for x in m['ranges'])
        else:completed=sum(x['initial_job_id'] in succeeded for x in m['ranges'])
        results.append({'material_id':m['material_id'],'completed_ranges':completed,'expected_ranges':len(m['ranges']),
            'fraction':str(_ratio(completed,len(m['ranges'])))})
    return sum((Decimal(r['fraction']) for r in results),Decimal(0))/len(results) if results else Decimal(0),results


def calculate(repo,c,tid,spec,snapshot,*,delivery_verified,insight_report=None):
    from ..archive_comparison import current_reports
    scope=freeze_scope(repo,c,tid,spec);pids=scope['requested_properties'];records=snapshot['measurements']
    allocations=repo.objects(c,tid,'reading_allocation')
    readable={pid:len({a['work_id'] for a in allocations if pid in a['property_ids']}) for pid in pids}
    covered={r['property_ref']['id'] for r in records}
    coverage=Decimal(15)*_ratio(len(covered),len(pids))+Decimal(15)*sum(
        (min(Decimal(1),_ratio(readable[p],scope.get('readable_target_per_property',readable_target(spec)))) for p in pids),Decimal(0))/max(1,len(pids))
    jobs=[dict(r) for r in c.execute('select job_id,kind,status from jobs where task_id=?',(tid,))]
    execution,execution_details=execution_fraction(scope,repo.objects(c,tid,'reading_batch_state'),jobs)
    roots=repo.objects(c,tid,'quality_candidate_root')
    decisions=[loads(r[0]) for r in c.execute(
        "select payload from objects where task_id=? and kind='quality_decision' order by created_at,rowid",(tid,))]
    reextractions=repo.objects(c,tid,'quality_reextraction_result')
    reviews=[{**dict(r),'application':loads(r['application']) if r['application'] else None,
              'payload':loads(r['payload'])} for r in c.execute('select status,application,payload from reviews where task_id=?',(tid,))]
    conclusions=0;links=repo.objects(c,tid,'quality_candidate_link')
    closed_states={'supported','not_applicable','not_passed','raw_retained'}
    for root in roots:
        own=[d for d in decisions if d['root_id']==root['root_id']]
        own_links=[l for l in links if l['root_id']==root['root_id']]
        parents={l['parent_ref']['id'] for l in own_links if l.get('parent_ref')}
        leaves=[l['candidate_ref']['id'] for l in own_links if l['candidate_ref']['id'] not in parents]
        groups=[[d for d in own if d.get('candidate_ref',{}).get('id')==cid] for cid in leaves] if own_links else [own]
        def concluded(group):
            if not group:return False
            latest=group[-1]
            if latest['state'] in closed_states:return True
            ids={latest.get('review_candidate_id')}-{None}
            if latest['state']=='needs_human':
                return any(ids.intersection(r['payload']['scope'].get('candidate_ids',[])) and r['application'] and
                    r['application']['status']=='applied' and r['status'] not in {'pending','accepted','application_failed'} for r in reviews)
            return latest['state']=='reextraction_requested' and any(
                x['root_id']==root['root_id'] and x.get('complete') and x.get('outcome')=='no_target_result' for x in reextractions)
        complete=bool(groups) and all(concluded(g) for g in groups)
        conclusions+=bool(complete)
    processing=snapshot.get('processing_receipts',[])
    processed=0;retained=[]
    for record in records:
        output=next((d for d in snapshot['derived'] if d['measurement_id']==record['measurement_id']),None)
        receipt=next((r for r in processing if r.get('input_ref',{}).get('content_sha256')==record['content_sha256']
            and r.get('output_ref',{}).get('id')==(output or {}).get('derived_id')),None)
        okay=output and output.get('main_state')=='ready' and receipt and any(
            x.get('target')=='main_value' and x.get('status')=='passed' for x in receipt.get('checks',[]))
        processed+=bool(okay)
        if not okay:retained.append({'measurement_id':record['measurement_id'],'state':(output or {}).get('status','not_run'),
            'reason':(output or {}).get('reason')})
    quality=Decimal(15)*_ratio(conclusions,len(roots))+Decimal(10)*_ratio(processed,len(records))
    checks=current_reports(repo,c,tid,records);by_property={r['property_id']:r for r in checks}
    checked=sum(by_property.get(p,{}).get('state')=='checked' for p in covered)
    applicable=[r for r in reviews if r['payload'].get('issue_kind')=='comparison_contradiction']
    applied=sum(bool(r['application'] and r['application']['status']=='applied' and r['status'] not in {'pending','accepted','application_failed'}) for r in applicable)
    all_checks=bool(covered) and checked==len(covered)
    review_fraction=_ratio(applied,len(applicable)) if applicable else Decimal(1) if all_checks else Decimal(0)
    comparison=Decimal(10)*_ratio(checked,len(covered))+Decimal(5)*review_fraction
    from ..author_release import enabled
    author_enabled=enabled(spec);possible=100 if author_enabled else 95
    qualified=set((insight_report or {}).get('qualified_property_ids',[]))&covered&set(pids)
    insight_component={'key':'insights','weight':5,
        'earned':float(Decimal(5)*_ratio(len(qualified),len(pids))),
        'state':'pending' if insight_report is None else (insight_report or {})['status'],
        'qualified_properties':sorted(qualified),'requested_properties':len(pids)} if author_enabled else {
        'key':'insights','weight':5,'earned':None,'state':'deferred_by_scope'}
    from ..material_summaries import enabled as summaries_enabled
    if summaries_enabled(spec):
        counts = (insight_report or {}).get('counts', {})
        requested = sum(c['requested'] for c in counts.values())
        ready = sum(c['ready'] for c in counts.values())
        insight_component = {'key': 'material_summaries', 'weight': 5,
            'earned': float(5*_ratio(ready, requested)) if requested else
                5 if insight_report and insight_report['status'] == 'generated' else 0,
            'state': (insight_report or {}).get('status', 'pending'),
            'ready': ready, 'requested': requested,
            'bibliography': sum(c['bibliography'] for c in counts.values())}
    from ..insight_bundle import enabled as bundle_enabled
    if bundle_enabled(spec):
        material = (insight_report or {}).get('material_report', {})
        prop = (insight_report or {}).get('property_report', {})
        counts = material.get('counts', {})
        requested = sum(c.get('requested', 0) for c in counts.values())
        ready = sum(c.get('ready', 0) for c in counts.values())
        qualified = set(prop.get('qualified_property_ids', [])) & covered & set(pids)
        material_points = float(Decimal('2.5') * _ratio(ready, requested)) if requested else 0
        property_points = float(Decimal('2.5') * _ratio(len(qualified), len(pids)))
        insight_component = {'key':'insights', 'weight':5, 'earned':material_points + property_points,
            'state':(insight_report or {}).get('status', 'pending'),
            'qualified_properties':sorted(qualified), 'requested_properties':len(pids),
            'components':{'material':{'weight':2.5, 'earned':material_points,
                'state':material.get('status','pending'), 'ready':ready, 'requested':requested},
                'property':{'weight':2.5, 'earned':property_points,
                'state':prop.get('status','pending'), 'qualified_properties':sorted(qualified)}}}
    components=[{'key':'request_materials','weight':30,'earned':float(coverage),
        'property_coverage':{'covered':len(covered),'requested':len(pids)},'readable_per_property':readable},
        {'key':'extraction','weight':20,'earned':float(20*execution),'materials':execution_details,
         'state':'completed' if execution==1 else 'partial' if scope['materials'] else 'no_materials'},
        {'key':'quality_cleaning','weight':25,'earned':float(quality),'candidate_roots':len(roots),
         'concluded_roots':conclusions,'eligible_records':len(records),'processed_or_no_change_verified':processed,
         'raw_retained':retained,'state':'no_materials' if not roots else 'assessed'},
        {'key':'comparison_review','weight':15,'earned':float(comparison),'properties_checked':checked,
         'properties_with_data':len(covered),'necessary_reviews':len(applicable),'answers_applied_rechecked':applied,
         'review_state':'not_applicable_checked' if not applicable and all_checks else 'assessed' if applicable else 'not_checked'},
        {'key':'delivery','weight':5,'earned':5 if delivery_verified else 0,'same_snapshot_exports_verified':bool(delivery_verified)},
        insight_component]
    earned=sum(Decimal(str(x['earned'])) for x in components if x['earned'] is not None) if records else Decimal(0)
    score=int((earned*100/possible).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    pending=author_enabled and insight_report is None
    report={'schema_version':'TaskCompletionScore/1','report_id':'task-score-'+digest([tid,snapshot['query']['spec_hash']]),
        'status':'pending' if pending else 'available' if records else 'no_usable_results','score':None if pending else score,'earned_points':float(earned),
        'possible_points':possible,'excluded_scope':scope['excluded_scope'],'components':components,
        'scope_ref':{'id':tid,'version':1,'content_sha256':digest(scope)},'readable_per_property':readable,
        'readable_target_per_property':scope.get('readable_target_per_property',readable_target(spec)),
        'property_coverage':{'covered':len(covered),'requested':len(pids)},
        'meaning':'任务流程完成度，含资料总结' if summaries_enabled(spec) else
            '任务覆盖与闭环完成度；不是科学正确率；含新洞察覆盖' if author_enabled else '任务覆盖与闭环完成度；不是科学正确率；本轮不含洞察',
        'measurement_scores':[],'incomplete':[x for x in components if x['earned'] is not None and x['earned']<x['weight']]}
    return report
